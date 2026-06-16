import os
import sys
import threading

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from groq import Groq
from sentence_transformers import SentenceTransformer
from werkzeug.utils import secure_filename

import chatbot

app = Flask(__name__)
app.secret_key = os.urandom(16)

load_dotenv()
_api_key = os.getenv("GROQ_API_KEY")
if not _api_key:
    print("Erreur : GROQ_API_KEY introuvable dans le fichier .env", file=sys.stderr)
    sys.exit(1)

_client = Groq(api_key=_api_key)
_model = None
_chunks = []
_embeddings = None
_documents = []
_index_lock = threading.Lock()


def rebuild_index():
    global _chunks, _embeddings, _documents
    paths = chatbot.discover_pdfs()
    with _index_lock:
        _chunks, _embeddings = chatbot.build_index_cached(paths, _model)
        _documents = sorted({chunk.source for chunk in _chunks})
    print(f"Index reconstruit : {len(_documents)} document(s), {len(_chunks)} chunks.")


print(f"Chargement du modèle d'embeddings ({chatbot.EMBEDDING_MODEL})...")
_model = SentenceTransformer(chatbot.EMBEDDING_MODEL)
os.makedirs(chatbot.DOCS_DIR, exist_ok=True)
rebuild_index()
print("Index prêt.")


@app.route("/", methods=["GET", "POST"])
def index():
    question = ""
    response = ""
    sources = []
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if not _chunks:
            response = "Aucun document indexé. Ajoutez d'abord un PDF."
        elif question:
            with _index_lock:
                retrieved = chatbot.retrieve(question, _chunks, _embeddings, _model)
            response = chatbot.answer(_client, question, retrieved)
            sources = sorted({chunk.label() for chunk in retrieved})
    return render_template(
        "index.html",
        question=question,
        response=response,
        sources=sources,
        documents=_documents,
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("pdf")
    if not file or not file.filename:
        flash("Aucun fichier sélectionné.")
        return redirect(url_for("index"))
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        flash("Seuls les fichiers PDF sont acceptés.")
        return redirect(url_for("index"))
    file.save(os.path.join(chatbot.DOCS_DIR, filename))
    rebuild_index()
    flash(f"« {filename} » ajouté et indexé.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
