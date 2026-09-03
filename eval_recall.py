"""Recall@4 du retrieval, sur des questions annotées à la main.

Protocole : prendre des questions d'un vrai contrôle (pas écrites par moi, pour ne
pas biaiser vers ce que le moteur sait faire), noter à la main où se trouve la
réponse dans mes cours (document + page), avant de lancer quoi que ce soit. Puis
vérifier si ce passage figure dans les 4 que le moteur retourne. Aucun appel LLM :
on mesure la recherche seule, pas la réponse rédigée.

Les questions ne sont pas dans ce fichier (propriété de l'enseignant, non
versionnées). Il faut un eval_questions.json à côté, au format :

{
  "subject": "crypto",
  "questions": {
    "1": "texte de la question 1 ...",
    "2": "texte de la question 2 ..."
  },
  "gold": {
    "1": {"document": "signature-m1.pdf", "pages": [17, 18, 19]},
    "2": null
  }
}

"gold": null signifie que la réponse n'est pas couverte par le corpus (mesure de
couverture) ou qu'elle demande un raisonnement plutôt qu'un passage précis.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
from sentence_transformers import SentenceTransformer

import chatbot
from rag_engine import RagEngine, RERANK_CANDIDATES

QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")
TOP_K = 4


def load_dataset(path=QUESTIONS_PATH):
    if not path.exists():
        sys.exit(
            f"Fichier absent : {path}\n"
            "Ce fichier contient les questions et leur annotation, il n'est pas "
            "versionné (voir le docstring de ce script pour le format attendu)."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = {int(k): v for k, v in data["questions"].items()}
    gold = {
        int(k): (v["document"], v["pages"]) if v else None
        for k, v in data["gold"].items()
    }
    return data["subject"], questions, gold


def retrieve(engine, question, subject, mode):
    allowed = engine._scoped_sources(None, subject)
    idx = [i for i, c in enumerate(engine._chunks) if c.source in allowed]
    if mode == "vecteurs":
        qv = engine._model.encode([question], normalize_embeddings=True)[0]
        order = np.argsort(engine._embeddings[idx] @ qv)[::-1][:TOP_K]
        return [engine._chunks[idx[i]] for i in order]
    fused = engine._fuse_candidates(question, idx)
    if mode == "rrf":
        return [engine._chunks[i] for i in fused[:TOP_K]]
    return [engine._chunks[i] for i in engine._rerank(question, fused[:RERANK_CANDIDATES])]


def main():
    subject, questions, gold = load_dataset()
    model = SentenceTransformer(chatbot.EMBEDDING_MODEL)
    engine = RagEngine(None, model, reranker=chatbot.load_reranker())
    engine.rebuild()

    modes = ["vecteurs", "rrf", "complet"]
    labels = {"vecteurs": "vecteurs seuls", "rrf": "+ BM25 (RRF)", "complet": "+ re-ranker"}
    scored = [q for q in questions if gold[q]]
    results = {m: {} for m in modes}

    for m in modes:
        for q in scored:
            doc, pages = gold[q]
            got = retrieve(engine, questions[q], subject, m)
            results[m][q] = any(c.source == doc and c.page in pages for c in got)

    print(f"\nCouverture : {len(scored)}/{len(questions)} questions ont leur réponse dans le corpus")
    absent = [q for q in questions if not gold[q]]
    if absent:
        print(f"(sans réponse dans le corpus : {', '.join('Q%d' % q for q in absent)})")
    print()
    for m in modes:
        hits = sum(results[m][q] for q in scored)
        print(f"  recall@4 {labels[m]:<16} : {hits}/{len(scored)}")


if __name__ == "__main__":
    main()
