import io
import os
import uuid

import pytest
from pypdf import PdfWriter

import store


def blank_pdf_bytes():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": uuid.uuid4().hex})
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


def test_ask_streams_sse_events(app_module, client, monkeypatch):
    def fake_ask_stream(question, document, subject):
        yield {"delta": "Bon"}
        yield {"delta": "jour"}
        yield {"citations": [{"id": 1, "label": "x.pdf p.1", "text": "un passage"}]}

    monkeypatch.setattr(app_module._engine, "has_index", lambda: True)
    monkeypatch.setattr(app_module._engine, "ask_stream", fake_ask_stream)

    response = client.post("/api/ask", json={"question": "Salut ?"})

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    assert body.count("data: ") == 3
    assert '"delta": "Bon"' in body
    assert '"citations"' in body


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


def test_serve_indexed_pdf_returns_pdf(client):
    data = {"pdf": (io.BytesIO(blank_pdf_bytes()), "viewable.pdf")}
    client.post("/api/upload", data=data)
    response = client.get("/docs/viewable.pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_serve_rejects_non_pdf_name(client):
    response = client.get("/docs/app.py")
    assert response.status_code == 404


def test_serve_missing_pdf_returns_404(client):
    response = client.get("/docs/inexistant.pdf")
    assert response.status_code == 404


def test_export_csv_contains_bom_header_and_cards(client):
    store.add_cards("export.pdf", [{"question": "Q1;test", "answer": "A1"}])
    store.add_cards("export.pdf", [{"question": "Q2", "answer": "A2", "options": ["A2", "B", "C", "D"]}])

    response = client.get("/api/export/csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    body = response.get_data(as_text=True)
    assert body.startswith(chr(0xFEFF) + "question;reponse;source")
    assert '"Q1;test";A1;export.pdf' in body
    assert "Q2;A2;export.pdf" in body


def test_upload_rejects_duplicate_content(client):
    pdf = blank_pdf_bytes()
    first = client.post("/api/upload", data={"pdf": (io.BytesIO(pdf), "original.pdf")})
    assert first.status_code == 200
    second = client.post("/api/upload", data={"pdf": (io.BytesIO(pdf), "copie.pdf")})
    assert second.status_code == 409
    assert "identique" in second.get_json()["error"]


def test_delete_document_removes_file_and_cards(client):
    data = {"pdf": (io.BytesIO(blank_pdf_bytes()), "todelete.pdf"), "subject": "crypto"}
    client.post("/api/upload", data=data)
    store.add_cards("todelete.pdf", [{"question": "Q", "answer": "A"}])

    response = client.delete("/api/documents/todelete.pdf")

    assert response.status_code == 200
    assert not os.path.exists(os.path.join("docs", "todelete.pdf"))
    assert store.all_cards("todelete.pdf") == []


def test_delete_missing_document_returns_404(client):
    response = client.delete("/api/documents/inexistant.pdf")
    assert response.status_code == 404


def test_upload_registers_subject(client):
    data = {"pdf": (io.BytesIO(blank_pdf_bytes()), "crypto1.pdf"), "subject": "crypto"}
    upload = client.post("/api/upload", data=data)
    assert upload.status_code == 200

    body = client.get("/api/documents").get_json()
    assert body["document_subjects"].get("crypto1.pdf") == "crypto"
    assert "crypto" in body["subjects"]


def test_export_csv_filters_by_subject(client):
    store.set_document_subject("scoped.pdf", "matiereX")
    store.add_cards("scoped.pdf", [{"question": "QX", "answer": "AX"}])
    store.add_cards("other.pdf", [{"question": "QY", "answer": "AY"}])

    response = client.get("/api/export/csv?subject=matiereX")

    body = response.get_data(as_text=True)
    assert "scoped.pdf" in body
    assert "other.pdf" not in body


def test_export_csv_filters_by_document(client):
    store.add_cards("only_a.pdf", [{"question": "QA", "answer": "AA"}])
    store.add_cards("only_b.pdf", [{"question": "QB", "answer": "AB"}])

    response = client.get("/api/export/csv?document=only_a.pdf")

    body = response.get_data(as_text=True)
    assert "only_a.pdf" in body
    assert "only_b.pdf" not in body
