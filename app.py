import os
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from groq import Groq
from sentence_transformers import SentenceTransformer
from werkzeug.utils import secure_filename

import chatbot
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

_engine = RagEngine(Groq(api_key=_api_key), _model)
_engine.rebuild()
print(f"Index prêt : {len(_engine.documents())} document(s).")


@app.route("/")
def index():
    return render_template("index.html", documents=_engine.documents())


@app.route("/api/documents")
def api_documents():
    return jsonify({"documents": _engine.documents()})


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
    app.run(host="127.0.0.1", port=5000, debug=False)
