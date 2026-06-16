import hashlib
import json
import os
import pickle
import sys
from dataclasses import dataclass
from glob import glob

import numpy as np
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

DOCS_DIR = "docs"
PDF_PATH = "signature-m1.pdf"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
GROQ_MODEL = "llama-3.3-70b-versatile"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
TOP_K = 4
CACHE_PATH = "index_cache.pkl"


@dataclass
class Chunk:
    text: str
    source: str
    page: int

    def label(self):
        return f"{self.source} p.{self.page}"


def discover_pdfs(docs_dir=DOCS_DIR, fallback=PDF_PATH):
    if os.path.isdir(docs_dir):
        paths = sorted(glob(os.path.join(docs_dir, "*.pdf")))
        if paths:
            return paths
    return [fallback] if os.path.exists(fallback) else []


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    pieces = []
    step = chunk_size - overlap
    for start in range(0, len(words), step):
        piece = " ".join(words[start:start + chunk_size])
        if piece.strip():
            pieces.append(piece)
    return pieces


def load_chunks(paths):
    chunks = []
    for path in paths:
        source = os.path.basename(path)
        reader = PdfReader(path)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for piece in chunk_text(text):
                chunks.append(Chunk(piece, source, page_number))
    return chunks


def build_index(chunks, model):
    texts = [chunk.text for chunk in chunks]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(embeddings)


def file_signature(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8192), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cache(cache_path=CACHE_PATH):
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as handle:
            return pickle.load(handle)
    return {}


def save_cache(cache, cache_path=CACHE_PATH):
    with open(cache_path, "wb") as handle:
        pickle.dump(cache, handle)


def build_index_cached(paths, model, cache_path=CACHE_PATH):
    cache = load_cache(cache_path)
    fresh_cache = {}
    all_chunks = []
    embedding_parts = []
    reused = 0
    encoded = 0
    for path in paths:
        source = os.path.basename(path)
        signature = file_signature(path)
        cached = cache.get(source)
        if cached and cached["signature"] == signature:
            entry = cached
            reused += 1
        else:
            chunks = load_chunks([path])
            entry = {
                "signature": signature,
                "chunks": chunks,
                "embeddings": build_index(chunks, model),
            }
            encoded += 1
        fresh_cache[source] = entry
        all_chunks.extend(entry["chunks"])
        if len(entry["chunks"]):
            embedding_parts.append(entry["embeddings"])
    save_cache(fresh_cache, cache_path)
    embeddings = np.vstack(embedding_parts) if embedding_parts else None
    print(f"Index : {reused} document(s) depuis le cache, {encoded} (ré)encodé(s).")
    return all_chunks, embeddings


def retrieve(question, chunks, embeddings, model, top_k=TOP_K):
    query_vec = model.encode([question], normalize_embeddings=True)[0]
    scores = embeddings @ query_vec
    best = np.argsort(scores)[::-1][:top_k]
    return [chunks[i] for i in best]


def answer(client, question, chunks):
    context = "\n\n---\n\n".join(f"[{chunk.label()}]\n{chunk.text}" for chunk in chunks)
    prompt = (
        "Réponds à la question en te basant uniquement sur le contexte ci-dessous. "
        "Chaque passage est précédé de sa source entre crochets [fichier p.X]. "
        "Cite la ou les sources utilisées entre crochets à la fin de ta réponse. "
        "Si la réponse ne s'y trouve pas, dis-le clairement.\n\n"
        f"Contexte :\n{context}\n\nQuestion : {question}"
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu es un assistant qui répond en français de façon précise et concise."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


def summarize_fiche(client, chunks, scope_label):
    context = "\n\n---\n\n".join(f"[{chunk.label()}]\n{chunk.text}" for chunk in chunks)
    prompt = (
        "À partir du contexte de cours ci-dessous, rédige une fiche de révision claire et structurée "
        f"sur « {scope_label} ». Utilise du Markdown avec ces sections :\n"
        "## Idées clés (liste de 4 à 8 points essentiels)\n"
        "## Définitions (terme — définition courte, pour les notions importantes)\n"
        "## À retenir (l'essentiel à mémoriser pour un examen)\n"
        "## Pour t'auto-tester (3 questions ouvertes sans les réponses)\n"
        "Reste fidèle au contenu, n'invente rien. Si le contexte est insuffisant, dis-le.\n\n"
        f"Contexte :\n{context}"
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu es un assistant pédagogique qui rédige des fiches de révision en français."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content


def generate_cards(client, chunks, count, scope_label):
    context = "\n\n---\n\n".join(f"[{chunk.label()}]\n{chunk.text}" for chunk in chunks)
    prompt = (
        f"À partir du contexte de cours ci-dessous, génère {count} questions de révision sur "
        f"« {scope_label} ». Chaque question doit tester la compréhension d'une notion précise et "
        "appeler une réponse courte. Reste strictement fidèle au contenu, n'invente rien.\n"
        'Réponds UNIQUEMENT avec un objet JSON de la forme : '
        '{"cards": [{"question": "...", "answer": "..."}]}.\n\n'
        f"Contexte :\n{context}"
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu génères des questions de révision en français au format JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    cards = data.get("cards", [])
    return [c for c in cards if c.get("question") and c.get("answer")]


def generate_quiz(client, chunks, count, scope_label):
    context = "\n\n---\n\n".join(f"[{chunk.label()}]\n{chunk.text}" for chunk in chunks)
    prompt = (
        f"À partir du contexte de cours ci-dessous, génère {count} questions à choix multiples sur "
        f"« {scope_label} ». Chaque question a exactement 4 propositions dont UNE seule correcte. "
        "Les distracteurs doivent être plausibles mais faux. Reste strictement fidèle au contenu, "
        "n'invente rien.\n"
        'Réponds UNIQUEMENT avec un objet JSON de la forme : '
        '{"cards": [{"question": "...", "answer": "...", "options": ["...", "...", "...", "..."]}]}. '
        "Le champ answer doit être identique, au caractère près, à l'une des options.\n\n"
        f"Contexte :\n{context}"
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu génères des QCM de révision en français au format JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    cards = []
    for card in data.get("cards", []):
        question = card.get("question")
        answer = card.get("answer")
        options = card.get("options")
        if question and answer and isinstance(options, list) and len(options) >= 2 and answer in options:
            cards.append({"question": question, "answer": answer, "options": options})
    return cards


def grade_answer(client, question, reference, user_answer):
    prompt = (
        "Évalue la réponse d'un étudiant à une question de révision. Compare-la à la réponse de "
        "référence. Note de 0 à 5 (0 = totalement faux, 3 = correct dans l'ensemble, 5 = parfait). "
        "Sois juste mais exigeant.\n"
        'Réponds UNIQUEMENT avec un objet JSON : {"score": <0-5>, "feedback": "<une à deux phrases>"}.\n\n'
        f"Question : {question}\n"
        f"Réponse de référence : {reference}\n"
        f"Réponse de l'étudiant : {user_answer}"
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu es un correcteur pédagogique qui évalue des réponses en français au format JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    score = int(data.get("score", 0))
    score = max(0, min(5, score))
    return {"score": score, "feedback": data.get("feedback", "")}


def main():
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Erreur : GROQ_API_KEY introuvable dans le fichier .env", file=sys.stderr)
        sys.exit(1)

    paths = discover_pdfs()
    if not paths:
        print(f"Erreur : aucun PDF trouvé dans '{DOCS_DIR}/' ni '{PDF_PATH}'", file=sys.stderr)
        sys.exit(1)

    print(f"Lecture de {len(paths)} document(s) : {', '.join(os.path.basename(p) for p in paths)}")
    print(f"Chargement du modèle d'embeddings ({EMBEDDING_MODEL})...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    chunks, embeddings = build_index_cached(paths, model)
    print(f"{len(chunks)} chunks indexés.")

    client = Groq(api_key=api_key)

    print("\nChatbot prêt. Posez vos questions (tapez 'quit' ou Ctrl+C pour quitter).\n")
    while True:
        try:
            question = input("Question > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir.")
            break
        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            print("Au revoir.")
            break
        retrieved = retrieve(question, chunks, embeddings, model)
        print("\n" + answer(client, question, retrieved))
        sources = sorted({chunk.label() for chunk in retrieved})
        print("Sources : " + ", ".join(sources) + "\n")


if __name__ == "__main__":
    main()
