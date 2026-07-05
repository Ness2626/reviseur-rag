import io
import os

import pytest
from pypdf import PdfWriter


def blank_pdf_bytes():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def app_module(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("appwork")
    previous_dir = os.getcwd()
    os.chdir(workdir)
    import app
    app.app.config["TESTING"] = True
    yield app
    os.chdir(previous_dir)


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


def test_index_page_serves_with_csp_header(client):
    response = client.get("/")
    assert response.status_code == 200
    csp = response.headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp


def test_documents_endpoint_returns_list(client):
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert isinstance(response.get_json()["documents"], list)


def test_stats_include_document_count(client):
    response = client.post("/api/stats", json={})
    assert response.status_code == 200
    assert "documents" in response.get_json()


def test_ask_rejects_empty_question(client):
    response = client.post("/api/ask", json={"question": "   "})
    assert response.status_code == 400


def test_ask_without_index_returns_explicit_error(client):
    response = client.post("/api/ask", json={"question": "Qu'est-ce que RSA ?"})
    assert response.status_code == 400
    assert "Aucun document" in response.get_json()["error"]


def test_feynman_requires_concept_and_explanation(client):
    response = client.post("/api/feynman", json={"concept": "RSA", "explanation": ""})
    assert response.status_code == 400


def test_upload_without_file_is_rejected(client):
    response = client.post("/api/upload", data={})
    assert response.status_code == 400


def test_upload_rejects_wrong_extension(client):
    data = {"pdf": (io.BytesIO(b"%PDF-1.4 fake"), "notes.txt")}
    response = client.post("/api/upload", data=data)
    assert response.status_code == 400
    assert "PDF" in response.get_json()["error"]


def test_upload_rejects_wrong_magic_bytes(client):
    data = {"pdf": (io.BytesIO(b"MZ\x90\x00 executable deguise"), "malware.pdf")}
    response = client.post("/api/upload", data=data)
    assert response.status_code == 400
    assert "pas un PDF valide" in response.get_json()["error"]


def test_upload_accepts_real_pdf_then_refuses_duplicate(client):
    data = {"pdf": (io.BytesIO(blank_pdf_bytes()), "cours.pdf")}
    first = client.post("/api/upload", data=data)
    assert first.status_code == 200
    assert os.path.exists(os.path.join("docs", "cours.pdf"))

    again = {"pdf": (io.BytesIO(blank_pdf_bytes()), "cours.pdf")}
    second = client.post("/api/upload", data=again)
    assert second.status_code == 409
    assert "existe déjà" in second.get_json()["error"]


def test_upload_neutralizes_path_traversal(client):
    data = {"pdf": (io.BytesIO(blank_pdf_bytes()), "../../evasion.pdf")}
    response = client.post("/api/upload", data=data)
    assert response.status_code == 200
    assert os.path.exists(os.path.join("docs", "evasion.pdf"))
    assert not os.path.exists(os.path.join("..", "..", "evasion.pdf"))


def test_upload_too_large_returns_json_413(client, app_module):
    original_limit = app_module.app.config["MAX_CONTENT_LENGTH"]
    app_module.app.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        data = {"pdf": (io.BytesIO(b"%PDF" + b"x" * 4096), "gros.pdf")}
        response = client.post("/api/upload", data=data)
    finally:
        app_module.app.config["MAX_CONTENT_LENGTH"] = original_limit
    assert response.status_code == 413
    assert "volumineux" in response.get_json()["error"]


def test_flashcard_answer_validates_quality(client):
    response = client.post("/api/flashcards/answer", json={"card_id": 1, "quality": "abc"})
    assert response.status_code == 400
    response = client.post("/api/flashcards/answer", json={"card_id": 1, "quality": 7})
    assert response.status_code == 400


def test_quiz_answer_requires_selection(client):
    response = client.post("/api/quiz/answer", json={"card_id": 1})
    assert response.status_code == 400


def test_exercise_grade_rejects_malformed_payload(client):
    response = client.post("/api/exercise/grade", json={"kind": None, "params": "pas un dict"})
    assert response.status_code == 400
