import json
from types import SimpleNamespace

import numpy as np
import pytest

import chatbot
import store
from rag_engine import RagEngine, _within_budget


class FakeGroqClient:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content = self._responses.pop(0) if self._responses else "réponse factice"
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeEmbedder:
    VOCAB = ("rsa", "tcp", "aes")

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([1.0 if word in lowered else 0.0 for word in self.VOCAB])
        return np.asarray(vectors)


CHUNKS = [
    chatbot.Chunk("La signature RSA repose sur la clé privée.", "crypto.pdf", 1),
    chatbot.Chunk("TCP garantit l'ordre des segments.", "reseaux.pdf", 3),
]
EMBEDDINGS = FakeEmbedder().encode([c.text for c in CHUNKS])


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(chatbot, "discover_pdfs", lambda: ["crypto.pdf", "reseaux.pdf"])
    monkeypatch.setattr(chatbot, "build_index_cached", lambda paths, model: (list(CHUNKS), EMBEDDINGS))
    built = RagEngine(FakeGroqClient(), FakeEmbedder(), top_k=1)
    built.rebuild()
    return built


@pytest.fixture
def empty_engine(monkeypatch):
    monkeypatch.setattr(chatbot, "discover_pdfs", lambda: [])
    monkeypatch.setattr(chatbot, "build_index_cached", lambda paths, model: ([], None))
    built = RagEngine(FakeGroqClient(), FakeEmbedder())
    built.rebuild()
    return built


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store.init_db(str(tmp_path / "revision.db"))
    return tmp_path


def test_rebuild_lists_documents_sorted(engine):
    assert engine.documents() == ["crypto.pdf", "reseaux.pdf"]
    assert engine.has_index()


def test_ask_returns_answer_and_sources(engine):
    result = engine.ask("comment marche rsa ?")
    assert result["answer"] == "réponse factice"
    assert result["sources"] == ["crypto.pdf p.1"]


def test_ask_sends_context_and_model_to_llm(engine):
    engine.ask("comment marche rsa ?")
    call = engine._client.calls[0]
    assert call["model"] == chatbot.GROQ_MODEL
    prompt = call["messages"][1]["content"]
    assert "[crypto.pdf p.1]" in prompt
    assert "clé privée" in prompt


def test_ask_filters_by_document(engine):
    result = engine.ask("parle-moi de rsa", document="reseaux.pdf")
    assert result["sources"] == ["reseaux.pdf p.3"]


def test_ask_without_index_returns_no_passage(empty_engine):
    result = empty_engine.ask("n'importe quoi")
    assert result["answer"] == "Aucun passage pertinent trouvé."
    assert result["sources"] == []
    assert empty_engine._client.calls == []


def test_feynman_returns_feedback_and_sources(engine):
    result = engine.feynman("rsa", "on signe avec la clé privée")
    assert result["feedback"] == "réponse factice"
    assert result["sources"] == ["crypto.pdf p.1"]


def test_feynman_without_index_returns_error(empty_engine):
    result = empty_engine.feynman("rsa", "explication")
    assert "error" in result


def test_generate_fiche_without_content_returns_error(empty_engine):
    result = empty_engine.generate_fiche()
    assert "error" in result


def test_generate_cards_stores_valid_cards(engine, workdir):
    payload = json.dumps({"cards": [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": ""},
    ]})
    engine._client._responses = [payload]
    result = engine.generate_cards(document="crypto.pdf")
    assert result["added"] == 1
    assert result["progress"]["total"] == 1


def test_generate_cards_with_empty_output_returns_error(engine, workdir):
    engine._client._responses = [json.dumps({"cards": []})]
    result = engine.generate_cards(document="crypto.pdf")
    assert "error" in result


def test_generate_quiz_rejects_malformed_cards(engine, workdir):
    payload = json.dumps({"cards": [
        {"question": "OK", "options": ["a", "b", "c", "d"], "correct": ["a"], "explanation": "e"},
        {"question": "correct absent des options", "options": ["a", "b"], "correct": ["z"]},
        {"question": "pas d'options", "correct": ["a"]},
    ]})
    engine._client._responses = [payload]
    result = engine.generate_quiz(document="crypto.pdf")
    assert result["added"] == 1


def test_submit_answer_grades_and_reschedules(engine, workdir):
    store.add_cards("crypto.pdf", [{"question": "Q", "answer": "A"}])
    card = store.next_due_card("crypto.pdf", kind="open")
    engine._client._responses = [json.dumps({"score": 4, "feedback": "Bien."})]
    result = engine.submit_answer(card["id"], "ma réponse")
    assert result["score"] == 4
    assert result["feedback"] == "Bien."
    assert result["reference"] == "A"
    assert result["next_due_in_days"] >= 1


def test_submit_answer_unknown_card_returns_error(engine, workdir):
    result = engine.submit_answer(999, "réponse")
    assert "error" in result


def test_submit_quiz_multi_answers_all_or_nothing(engine, workdir):
    store.add_cards("crypto.pdf", [{
        "question": "Q",
        "answer": json.dumps(["a", "b"]),
        "options": ["a", "b", "c", "d"],
    }])
    card = store.next_due_card("crypto.pdf", kind="quiz")
    partial = engine.submit_quiz(card["id"], ["a"])
    assert partial["correct"] is False
    assert sorted(partial["answers"]) == ["a", "b"]
    full = engine.submit_quiz(card["id"], ["b", "a"])
    assert full["correct"] is True


def test_decode_correct_tolerates_plain_string():
    assert RagEngine._decode_correct('["a", "b"]') == ["a", "b"]
    assert RagEngine._decode_correct("pas du json") == ["pas du json"]


def test_within_budget_downsamples_but_keeps_at_least_one():
    chunks = [chatbot.Chunk("x" * 1000, "d.pdf", i) for i in range(20)]
    kept = _within_budget(chunks, budget=4000)
    assert 1 <= len(kept) <= 4
    assert _within_budget(chunks[:1], budget=10)
