"""Qualité de la réponse rédigée, notée par un LLM-juge.

eval_recall.py mesure la recherche (le bon passage remonte-t-il ?). Ce script mesure
l'étape suivante : la réponse que le LLM écrit à partir des passages retournés.
Pour chaque question de eval_questions.json (même fichier, mêmes limites : non
versionné), on génère la réponse comme l'application, puis un second appel LLM la note :

- fidélité : part des affirmations de la réponse que les passages soutiennent
  (1.0 = rien d'inventé). Mesure l'invention.
- pertinence : 0 à 5, la réponse traite-t-elle la question posée ? Mesure le hors-sujet.
- refus : le modèle a-t-il dit que la réponse n'est pas dans les passages ?

On croise ensuite avec l'annotation "gold" : refuser alors que la réponse est dans le
corpus est un raté ; répondre alors qu'elle n'y est pas est à relire à la main.

Limite : le juge est le même modèle que le générateur, il peut être indulgent avec
son propre style. Les scores sont un signal, à confirmer en relisant les cas faibles.
Appels Groq : 3 par question.
"""
import json
import os
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer

import chatbot
from eval_recall import load_dataset
from rag_engine import RagEngine

JUDGE_MODEL = os.getenv("JUDGE_MODEL", chatbot.GROQ_MODEL)
RELEVANCE_MAX = 5


def _judge(client, system, prompt):
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _format_passages(chunks):
    return "\n\n---\n\n".join(f"[{n}] {c.text}" for n, c in enumerate(chunks, start=1))


def judge_faithfulness(client, answer_text, chunks):
    """Découpe la réponse en affirmations et vérifie chacune contre les passages."""
    data = _judge(
        client,
        "Tu es un vérificateur strict. Tu réponds uniquement en JSON.",
        "Découpe la réponse en affirmations factuelles simples (ignore les marqueurs [n] "
        "et les formules de politesse). Pour chacune, indique si elle est soutenue par les "
        "passages fournis. Une affirmation vraie en général mais absente des passages "
        "compte comme NON soutenue.\n"
        'Format : {"claims": [{"claim": "<texte>", "supported": true|false}]}\n\n'
        f"Passages :\n{_format_passages(chunks)}\n\nRéponse :\n{answer_text}",
    )
    claims = data.get("claims", [])
    if not claims:
        return None, []
    supported = sum(1 for c in claims if c.get("supported") is True)
    unsupported = [c["claim"] for c in claims if c.get("supported") is not True]
    return supported / len(claims), unsupported


def judge_relevance(client, question, answer_text):
    data = _judge(
        client,
        "Tu es un correcteur exigeant. Tu réponds uniquement en JSON.",
        "La réponse traite-t-elle directement la question posée ? Note de 0 à 5 "
        "(0 = hors sujet, 3 = répond partiellement, 5 = répond complètement). "
        "Ne juge pas l'exactitude, seulement si la question est traitée.\n"
        'Format : {"score": <0-5>}\n\n'
        f"Question : {question}\n\nRéponse :\n{answer_text}",
    )
    return max(0, min(RELEVANCE_MAX, int(data.get("score", 0))))


def judge_refusal(client, answer_text):
    data = _judge(
        client,
        "Tu classes des réponses. Tu réponds uniquement en JSON.",
        "Cette réponse dit-elle que l'information demandée est absente des passages "
        "(refus de répondre) ?\n"
        'Format : {"refusal": true|false}\n\n'
        f"Réponse :\n{answer_text}",
    )
    return data.get("refusal") is True


def main():
    load_dotenv()
    subject, questions, gold = load_dataset()
    client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=chatbot.GROQ_MAX_RETRIES)
    model = SentenceTransformer(chatbot.EMBEDDING_MODEL)
    engine = RagEngine(client, model, reranker=chatbot.load_reranker())
    engine.rebuild()

    rows = []
    for q in sorted(questions):
        chunks = engine._retrieve(questions[q], subject=subject)
        text = chatbot.answer(client, questions[q], chunks)
        refusal = judge_refusal(client, text)
        row = {"q": q, "has_gold": bool(gold[q]), "refusal": refusal}
        if not refusal:
            row["faithfulness"], row["unsupported"] = judge_faithfulness(client, text, chunks)
            row["relevance"] = judge_relevance(client, questions[q], text)
        rows.append(row)
        print(f"Q{q} ... {'refus' if refusal else 'réponse'}")

    answered = [r for r in rows if not r["refusal"]]
    faith = [r["faithfulness"] for r in answered if r.get("faithfulness") is not None]
    print(f"\n{len(answered)}/{len(rows)} questions répondues, {len(rows) - len(answered)} refusées")
    if faith:
        print(f"Fidélité moyenne (réponses données) : {sum(faith) / len(faith):.2f}")
        print(f"Pertinence moyenne                  : {sum(r['relevance'] for r in answered) / len(answered):.1f}/{RELEVANCE_MAX}")

    groups = defaultdict(list)
    for r in rows:
        groups[(r["has_gold"], r["refusal"])].append(f"Q{r['q']}")
    print("\nCroisement avec l'annotation :")
    print(f"  réponse dans le corpus, répondu   : {', '.join(groups[(True, False)]) or '-'}")
    print(f"  réponse dans le corpus, REFUSÉ    : {', '.join(groups[(True, True)]) or '-'}  (raté)")
    print(f"  absente du corpus, refusé         : {', '.join(groups[(False, True)]) or '-'}  (bon réflexe)")
    print(f"  absente du corpus, répondu        : {', '.join(groups[(False, False)]) or '-'}  (à relire)")

    weak = [r for r in answered if r.get("unsupported")]
    if weak:
        print("\nAffirmations non soutenues par les passages :")
        for r in weak:
            for claim in r["unsupported"]:
                print(f"  Q{r['q']} : {claim}")


if __name__ == "__main__":
    main()
