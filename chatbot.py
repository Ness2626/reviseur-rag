import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass
from glob import glob

import numpy as np
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

DOCS_DIR = "docs"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MAX_RETRIES = 5
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
TOP_K = 4
CACHE_PATH = "index_cache"
CACHE_KEY_PATH = ".cache_key"
CACHE_KEY_SIZE_BYTES = 32


@dataclass
class Chunk:
    text: str
    source: str
    page: int

    def label(self):
        return f"{self.source} p.{self.page}"


def discover_pdfs(docs_dir=DOCS_DIR):
    if os.path.isdir(docs_dir):
        paths = sorted(glob(os.path.join(docs_dir, "*.pdf")))
        if paths:
            return paths
    return sorted(glob("*.pdf"))


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
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8192), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_files(cache_path=CACHE_PATH):
    return f"{cache_path}.json", f"{cache_path}.npz", f"{cache_path}.hmac"


def _load_or_create_cache_key(key_path=CACHE_KEY_PATH):
    if os.path.exists(key_path):
        with open(key_path, "rb") as handle:
            key = handle.read()
        if len(key) == CACHE_KEY_SIZE_BYTES:
            return key
    key = secrets.token_bytes(CACHE_KEY_SIZE_BYTES)
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


def _compute_cache_hmac(key, meta_bytes, embeddings_bytes):
    mac = hmac.new(key, digestmod=hashlib.sha256)
    mac.update(len(meta_bytes).to_bytes(8, "big"))
    mac.update(meta_bytes)
    mac.update(embeddings_bytes)
    return mac.hexdigest()


def load_cache(cache_path=CACHE_PATH, key_path=CACHE_KEY_PATH):
    meta_path, embeddings_path, hmac_path = _cache_files(cache_path)
    if not all(os.path.exists(p) for p in (meta_path, embeddings_path, hmac_path, key_path)):
        return {}
    with open(key_path, "rb") as handle:
        key = handle.read()
    with open(meta_path, "rb") as handle:
        meta_bytes = handle.read()
    with open(embeddings_path, "rb") as handle:
        embeddings_bytes = handle.read()
    with open(hmac_path, encoding="ascii") as handle:
        stored_hmac = handle.read().strip()
    expected_hmac = _compute_cache_hmac(key, meta_bytes, embeddings_bytes)
    if not hmac.compare_digest(stored_hmac, expected_hmac):
        print("Cache d'index rejeté : signature HMAC invalide. Reconstruction depuis les PDF.", file=sys.stderr)
        return {}
    return _decode_cache(meta_bytes, embeddings_path)


def _decode_cache(meta_bytes, embeddings_path):
    meta = json.loads(meta_bytes)
    cache = {}
    with np.load(embeddings_path, allow_pickle=False) as arrays:
        for source, entry in meta.items():
            chunks = [Chunk(c["text"], c["source"], c["page"]) for c in entry["chunks"]]
            cache[source] = {
                "signature": entry["signature"],
                "chunks": chunks,
                "embeddings": arrays[entry["array"]],
            }
    return cache


def save_cache(cache, cache_path=CACHE_PATH, key_path=CACHE_KEY_PATH):
    meta_path, embeddings_path, hmac_path = _cache_files(cache_path)
    meta = {}
    arrays = {}
    for index, (source, entry) in enumerate(cache.items()):
        array_key = f"emb_{index}"
        meta[source] = {
            "signature": entry["signature"],
            "array": array_key,
            "chunks": [{"text": c.text, "source": c.source, "page": c.page} for c in entry["chunks"]],
        }
        arrays[array_key] = np.asarray(entry["embeddings"])
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    with open(meta_path, "wb") as handle:
        handle.write(meta_bytes)
    np.savez(embeddings_path, **arrays)
    with open(embeddings_path, "rb") as handle:
        embeddings_bytes = handle.read()
    digest = _compute_cache_hmac(_load_or_create_cache_key(key_path), meta_bytes, embeddings_bytes)
    with open(hmac_path, "w", encoding="ascii") as handle:
        handle.write(digest)


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
    context = "\n\n---\n\n".join(
        f"[{number}] ({chunk.label()})\n{chunk.text}"
        for number, chunk in enumerate(chunks, start=1)
    )
    prompt = (
        "Réponds à la question en te basant uniquement sur les passages numérotés ci-dessous. "
        "Après chaque affirmation tirée d'un passage, cite son numéro entre crochets, "
        "par exemple [1] ou [2][3]. Ne cite que les passages réellement utilisés, "
        "et n'ajoute pas de liste de sources à la fin. "
        "Si la réponse ne se trouve pas dans les passages, dis-le clairement.\n\n"
        f"Passages :\n{context}\n\nQuestion : {question}"
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


def feynman_feedback(client, concept, explanation, chunks):
    context = "\n\n---\n\n".join(f"[{chunk.label()}]\n{chunk.text}" for chunk in chunks)
    prompt = (
        "Tu appliques la technique Feynman : pour vérifier qu'on maîtrise vraiment un concept, "
        "on doit pouvoir l'expliquer simplement, comme à un débutant. Rester vague, employer du "
        "jargon sans le définir ou sauter des étapes sont des signes qu'on ne le maîtrise pas "
        "encore. L'étudiant t'explique un concept ci-dessous.\n\n"
        f"Concept : {concept}\n\n"
        f"Explication de l'étudiant :\n{explanation}\n\n"
        f"Extraits du cours :\n{context}\n\n"
        "Évalue son explication en te basant STRICTEMENT sur le cours fourni, pas sur tes "
        "connaissances générales. Réponds en français, en Markdown, avec ces trois sections :\n"
        "## Ce que tu expliques bien\n(ce qui est correct ET clairement formulé)\n"
        "## Là où ça coince\n(les points faux, vagues, jargonneux ou survolés ; nomme la notion "
        "exacte du cours concernée. Si l'explication est juste et claire, dis-le franchement et "
        "n'invente aucun défaut.)\n"
        "## Pour aller plus loin\n(si l'explication est solide : 2 à 3 questions ou notions pour "
        "approfondir ; sinon : les notions précises à revoir en priorité)\n\n"
        "Tutoie l'étudiant, sois encourageant mais exigeant. Ne réécris pas l'explication à sa "
        "place. Si l'explication se limite à citer des termes ou reste très superficielle, ne "
        "demande pas de tout définir : choisis LA notion la plus importante ou la plus subtile, "
        "et demande-lui de te la définir précisément, avec un exemple si possible — concentre ton "
        "retour sur celle-là. Si l'explication est vide, dis-le. N'invente rien."
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Tu es un binôme de révision exigeant et encourageant qui aide à tester sa compréhension par l'explication, en français."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
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
        f"« {scope_label} ». Chaque question a exactement 4 propositions, dont UNE OU PLUSIEURS "
        "correctes (au moins une). Les distracteurs doivent être plausibles mais faux. Reste "
        "strictement fidèle au contenu, n'invente rien.\n"
        'Réponds UNIQUEMENT avec un objet JSON de la forme : '
        '{"cards": [{"question": "...", "options": ["...", "...", "...", "..."], "correct": ["...", "..."], "explanation": "..."}]}. '
        "Le champ correct est la liste des propositions exactes (au caractère près) qui sont vraies. "
        "Le champ explanation (2 à 3 phrases max) explique la réponse comme le ferait un bon prof, "
        "en variant l'angle d'une question à l'autre : tantôt développer pourquoi la bonne réponse "
        "est vraie, tantôt illustrer par un exemple concret du cours, tantôt démonter seulement le "
        "distracteur le plus piégeux. Ne passe pas systématiquement chaque proposition en revue et "
        "bannis les formules mécaniques du type « les autres options sont incorrectes car ».\n\n"
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
        options = card.get("options")
        correct = card.get("correct")
        if not (question and isinstance(options, list) and len(options) >= 2):
            continue
        if not (isinstance(correct, list) and correct and all(c in options for c in correct)):
            continue
        cards.append({
            "question": question,
            "answer": json.dumps(correct, ensure_ascii=False),
            "options": options,
            "explanation": card.get("explanation"),
        })
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
        print(f"Erreur : aucun PDF trouvé dans '{DOCS_DIR}/'", file=sys.stderr)
        sys.exit(1)

    print(f"Lecture de {len(paths)} document(s) : {', '.join(os.path.basename(p) for p in paths)}")
    print(f"Chargement du modèle d'embeddings ({EMBEDDING_MODEL})...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    chunks, embeddings = build_index_cached(paths, model)
    print(f"{len(chunks)} chunks indexés.")

    client = Groq(api_key=api_key, max_retries=GROQ_MAX_RETRIES)

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
        sources = [f"[{number}] {chunk.label()}" for number, chunk in enumerate(retrieved, start=1)]
        print("Sources : " + ", ".join(sources) + "\n")


if __name__ == "__main__":
    main()
