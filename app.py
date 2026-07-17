import csv
import hashlib
import io
import json
import os
import sys
from glob import glob

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory
from groq import Groq
from sentence_transformers import SentenceTransformer
from werkzeug.utils import secure_filename

import chatbot
import exercises
import store
from rag_engine import RagEngine

MAX_UPLOAD_MB = 50
PDF_MAGIC = b"%PDF"
CSV_DELIMITER = ";"
CSV_BOM = chr(0xFEFF)
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


@app.after_request
def set_security_headers(response):
    response.headers["Content-Security-Policy"] = CSP_POLICY
    return response

load_dotenv()
_api_key = os.getenv("GROQ_API_KEY")
if not _api_key:
    print("Erreur : GROQ_API_KEY introuvable dans le fichier .env", file=sys.stderr)
    sys.exit(1)

print(f"Chargement du modèle d'embeddings ({chatbot.EMBEDDING_MODEL})...")
_model = SentenceTransformer(chatbot.EMBEDDING_MODEL)
print(f"Chargement du re-ranker ({chatbot.RERANKER_MODEL})...")
_reranker = chatbot.load_reranker()
os.makedirs(chatbot.DOCS_DIR, exist_ok=True)

store.init_db()
store.ensure_skills(exercises.KINDS)
EXERCISE_CORRECT_GRADE = 5
EXERCISE_WRONG_GRADE = 1
_engine = RagEngine(Groq(api_key=_api_key, max_retries=chatbot.GROQ_MAX_RETRIES), _model, reranker=_reranker)
_engine.rebuild()
print(f"Index prêt : {len(_engine.documents())} document(s).")


def _scope(data):
    return data.get("document") or None, data.get("subject") or None


def _documents_payload(message=None):
    payload = {
        "documents": _engine.documents(),
        "subjects": _engine.subjects(),
        "document_subjects": _engine.document_subjects(),
    }
    if message:
        payload["message"] = message
    return payload


def _find_duplicate_document(digest):
    for path in glob(os.path.join(chatbot.DOCS_DIR, "*.pdf")):
        if chatbot.file_signature(path) == digest:
            return os.path.basename(path)
    return None


@app.route("/")
def index():
    return render_template(
        "index.html",
        documents=_engine.documents(),
        subjects=_engine.subjects(),
        document_subjects=_engine.document_subjects(),
    )


@app.route("/api/documents")
def api_documents():
    return jsonify(_documents_payload())


@app.route("/docs/<name>")
def serve_document(name):
    if not name.lower().endswith(".pdf"):
        abort(404)
    return send_from_directory(os.path.abspath(chatbot.DOCS_DIR), name)


@app.route("/api/stats", methods=["POST"])
def api_stats():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    stats = _engine.progress(document, subject=subject)
    stats["documents"] = len(_engine.documents())
    return jsonify(stats)


@app.route("/api/dashboard", methods=["POST"])
def api_dashboard():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    return jsonify(_engine.dashboard(document, subject=subject))


def _card_answer_for_export(card):
    if card["options"]:
        return " / ".join(RagEngine._decode_correct(card["answer"]))
    return card["answer"]


@app.route("/api/export/csv")
def api_export_csv():
    document = request.args.get("document") or None
    subject = request.args.get("subject") or None
    cards = store.all_cards(document, subject=subject)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER)
    writer.writerow(["question", "reponse", "source"])
    for card in cards:
        writer.writerow([card["question"], _card_answer_for_export(card), card["document"]])
    body = (CSV_BOM + buffer.getvalue()).encode("utf-8")
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=cartes.csv"},
    )


@app.route("/api/exercise/new", methods=["POST"])
def api_exercise_new():
    data = request.get_json(silent=True) or {}
    return jsonify(exercises.new_exercise(data.get("kind") or None))


@app.route("/api/exercise/next", methods=["POST"])
def api_exercise_next():
    kind = store.next_due_skill()
    progress = store.skills_progress()
    exercise = exercises.new_exercise(kind) if kind else None
    return jsonify({"exercise": exercise, "progress": progress})


@app.route("/api/exercise/grade", methods=["POST"])
def api_exercise_grade():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    params = data.get("params")
    if not kind or not isinstance(params, dict):
        return jsonify({"error": "Exercice invalide."}), 400
    result = exercises.grade(kind, params, data.get("answer"))
    if "error" in result:
        return jsonify(result), 400
    grade_value = EXERCISE_CORRECT_GRADE if result["correct"] else EXERCISE_WRONG_GRADE
    schedule = store.record_skill_review(kind, grade_value)
    result["next_due_in_days"] = schedule["interval"] if schedule else None
    result["progress"] = store.skills_progress()
    return jsonify(result)


def _sse_event(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    document, subject = _scope(data)
    if not question:
        return jsonify({"error": "Question vide."}), 400
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400

    def stream():
        for event in _engine.ask_stream(question, document, subject):
            yield _sse_event(event)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/feynman", methods=["POST"])
def api_feynman():
    data = request.get_json(silent=True) or {}
    concept = (data.get("concept") or "").strip()
    explanation = (data.get("explanation") or "").strip()
    document, subject = _scope(data)
    if not concept or not explanation:
        return jsonify({"error": "Indique un concept et ton explication."}), 400
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.feynman(concept, explanation, document, subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/fiche", methods=["POST"])
def api_fiche():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_fiche(document, subject=subject)
    status = 400 if "error" in result else 200
    return jsonify(result), status


@app.route("/api/cards/generate", methods=["POST"])
def api_cards_generate():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    count = data.get("count", 8)
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_cards(document, count, subject=subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/study/next", methods=["POST"])
def api_study_next():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    return jsonify(_engine.next_card(document, subject=subject))


@app.route("/api/study/answer", methods=["POST"])
def api_study_answer():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    card_id = data.get("card_id")
    answer = (data.get("answer") or "").strip()
    if card_id is None or not answer:
        return jsonify({"error": "Réponse vide."}), 400
    result = _engine.submit_answer(card_id, answer, document, subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/flashcards/next", methods=["POST"])
def api_flashcards_next():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    return jsonify(_engine.next_flashcard(document, subject=subject))


@app.route("/api/flashcards/answer", methods=["POST"])
def api_flashcards_answer():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
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
    result = _engine.submit_flashcard(card_id, quality, document, subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/quiz/generate", methods=["POST"])
def api_quiz_generate():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    count = data.get("count", 8)
    if not _engine.has_index():
        return jsonify({"error": "Aucun document indexé. Ajoutez d'abord un PDF."}), 400
    result = _engine.generate_quiz(document, count, subject=subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.route("/api/quiz/next", methods=["POST"])
def api_quiz_next():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    return jsonify(_engine.next_quiz(document, subject=subject))


@app.route("/api/quiz/answer", methods=["POST"])
def api_quiz_answer():
    data = request.get_json(silent=True) or {}
    document, subject = _scope(data)
    card_id = data.get("card_id")
    selected = data.get("selected")
    if card_id is None or selected is None:
        return jsonify({"error": "Réponse manquante."}), 400
    result = _engine.submit_quiz(card_id, selected, document, subject)
    return jsonify(result), (400 if "error" in result else 200)


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": f"Fichier trop volumineux (maximum {MAX_UPLOAD_MB} Mo)."}), 413


@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("pdf")
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier sélectionné."}), 400
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Seuls les fichiers PDF sont acceptés."}), 400
    content = file.stream.read()
    file.stream.seek(0)
    if content[:len(PDF_MAGIC)] != PDF_MAGIC:
        return jsonify({"error": "Ce fichier n'est pas un PDF valide."}), 400
    destination = os.path.join(chatbot.DOCS_DIR, filename)
    if os.path.exists(destination):
        return jsonify({"error": f"« {filename} » existe déjà. Renomme le fichier ou supprime l'ancien de docs/."}), 409
    duplicate = _find_duplicate_document(hashlib.sha256(content).hexdigest())
    if duplicate:
        return jsonify({"error": f"Contenu identique à « {duplicate} », déjà indexé."}), 409
    file.save(destination)
    store.set_document_subject(filename, request.form.get("subject"))
    _engine.rebuild()
    return jsonify(_documents_payload(f"« {filename} » ajouté et indexé."))


@app.route("/api/documents/<name>", methods=["DELETE"])
def api_delete_document(name):
    filename = secure_filename(name)
    if not filename.lower().endswith(".pdf"):
        return jsonify({"error": "Nom de document invalide."}), 400
    path = os.path.join(chatbot.DOCS_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "Document introuvable."}), 404
    os.remove(path)
    store.delete_document(filename)
    _engine.rebuild()
    return jsonify(_documents_payload(f"« {filename} » supprimé."))


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=False)
