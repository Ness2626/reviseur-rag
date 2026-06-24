import os
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from groq import Groq
from sentence_transformers import SentenceTransformer
from werkzeug.utils import secure_filename

import chatbot
import store
from rag_engine import RagEngine

app = Flask(__name__)

load_dotenv()
_api_key = os.getenv("GROQ_API_KEY")
if not _api_key:
    print("Erreur : GROQ_API_KEY introuvable dans le fichier .env", file=sys.stderr)
    sys.exit(1)

print(f"Chargement du modèle d'embeddings ({chatbot.EMBEDDING_MODEL})...")
_model = SentenceTransformer(chatbot.EMBEDDING_MODEL)
os.makedirs(chatbot.DOCS_DIR, exist_ok=True)

store.init_db()
_engine = RagEngine(Groq(api_key=_api_key), _model)
_engine.rebuild()
print(f"Index prêt : {len(_engine.documents())} document(s).")


@app.route("/")
def index():
    return render_template("index.html", documents=_engine.documents())


@app.route("/api/documents")
def api_documents():
    return jsonify({"documents": _engine.documents()})


@app.route("/api/stats", methods=["POST"])
def api_stats():
    data = request.get_json(silent=True) or {}
    document = data.get("document") or None
    stats = _engine.progress(document)
    stats["documents"] = len(_engine.documents())
    return jsonify(stats)


@app.route("/api/dashboard", methods=["POST"])
def api_dashboard():
    data = request.get_json(silent=True) or {}
    document = data.get("document") or None
    return jsonify(_engine.dashboard(document))


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    document = data.get("document") or None
    if not question:
        return jsonify({"error": "Question vide."}), 400
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    return jsonify(_engine.ask(question, document))


@app.route("/api/fiche", methods=["POST"])
def api_fiche():
    data = request.get_json(silent=True) or {}
    document = data.get("document") or None
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_fiche(document)
    status = 400 if "error" in result else 200
    return jsonify(result), status


@app.route("/api/cards/generate", methods=["POST"])
def api_cards_generate():
    data = request.get_json(silent=True) or {}
    document = data.get("document") or None
    count = data.get("count", 8)
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_cards(document, count)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/study/next", methods=["POST"])
def api_study_next():
    data = request.get_json(silent=True) or {}
    return jsonify(_engine.next_card(data.get("document") or None))


@app.route("/api/study/answer", methods=["POST"])
def api_study_answer():
    data = request.get_json(silent=True) or {}
    card_id = data.get("card_id")
    answer = (data.get("answer") or "").strip()
    if card_id is None or not answer:
        return jsonify({"error": "Réponse vide."}), 400
    result = _engine.submit_answer(card_id, answer, data.get("document") or None)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/flashcards/next", methods=["POST"])
def api_flashcards_next():
    data = request.get_json(silent=True) or {}
    return jsonify(_engine.next_flashcard(data.get("document") or None))


@app.route("/api/flashcards/answer", methods=["POST"])
def api_flashcards_answer():
    data = request.get_json(silent=True) or {}
    card_id = data.get("card_id")
    quality = data.get("quality")
    if card_id is None or quality is None:
        return jsonify({"error": "Note manquante."}), 400
    try:
        quality = int(quality)
    except (TypeError, ValueError):
        return jsonify({"error": "Note invalide."}), 400
    if not 0 <= quality <= 5:
        return jsonify({"error": "Note invalide."}), 400
    result = _engine.submit_flashcard(card_id, quality, data.get("document") or None)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/quiz/generate", methods=["POST"])
def api_quiz_generate():
    data = request.get_json(silent=True) or {}
    document = data.get("document") or None
    count = data.get("count", 8)
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_quiz(document, count)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/quiz/next", methods=["POST"])
def api_quiz_next():
    data = request.get_json(silent=True) or {}
    return jsonify(_engine.next_quiz(data.get("document") or None))


@app.route("/api/quiz/answer", methods=["POST"])
def api_quiz_answer():
    data = request.get_json(silent=True) or {}
    card_id = data.get("card_id")
    selected = data.get("selected")
    if card_id is None or selected is None:
        return jsonify({"error": "Réponse manquante."}), 400
    result = _engine.submit_quiz(card_id, selected, data.get("document") or None)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("pdf")
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier sélectionné."}), 400
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Seuls les fichiers PDF sont acceptés."}), 400
    file.save(os.path.join(chatbot.DOCS_DIR, filename))
    _engine.rebuild()
    return jsonify({"message": f"« {filename} » ajouté et indexé.", "documents": _engine.documents()})


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False)
