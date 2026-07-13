import json
import random
import re
import threading

import numpy as np
from rank_bm25 import BM25Okapi

import chatbot
import store

FICHE_BUDGET_CHARS = 16000
MAX_CARDS = 15
QUIZ_CORRECT_GRADE = 5
QUIZ_WRONG_GRADE = 1
RRF_K = 60
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text):
    return TOKEN_PATTERN.findall(text.lower())


def _reciprocal_rank_fusion(*rank_lists, k=RRF_K):
    scores = {}
    for ranks in rank_lists:
        for position, local_index in enumerate(ranks):
            scores[local_index] = scores.get(local_index, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=scores.get, reverse=True)


def _within_budget(chunks, budget=FICHE_BUDGET_CHARS):
    total = sum(len(chunk.text) for chunk in chunks)
    if total <= budget:
        return chunks
    keep = max(1, int(len(chunks) * budget / total))
    stride = len(chunks) / keep
    return [chunks[int(i * stride)] for i in range(keep)]


class RagEngine:
    """Moteur RAG avec état (index, modèle) encapsulé et thread-safe.

    Sépare la logique de retrieval/génération de la couche web. Les modes de
    révision (quiz, fiches, flashcards...) se branchent par-dessus cette classe.
    """

    def __init__(self, groq_client, embedding_model, top_k=chatbot.TOP_K):
        self._client = groq_client
        self._model = embedding_model
        self._top_k = top_k
        self._lock = threading.Lock()
        self._chunks = []
        self._embeddings = None
        self._documents = []
        self._bm25 = None

    def rebuild(self):
        paths = chatbot.discover_pdfs()
        with self._lock:
            self._chunks, self._embeddings = chatbot.build_index_cached(paths, self._model)
            self._documents = sorted({chunk.source for chunk in self._chunks})
            self._bm25 = BM25Okapi([_tokenize(c.text) for c in self._chunks]) if self._chunks else None
        return self._documents

    def documents(self):
        return list(self._documents)

    def has_index(self):
        return bool(self._chunks)

    def _retrieve(self, question, document=None):
        if document:
            indices = [i for i, c in enumerate(self._chunks) if c.source == document]
        else:
            indices = list(range(len(self._chunks)))
        if not indices:
            return []

        subset = self._embeddings[indices]
        query_vec = self._model.encode([question], normalize_embeddings=True)[0]
        vector_scores = subset @ query_vec
        vector_ranks = np.argsort(vector_scores)[::-1]

        bm25_scores = np.asarray(self._bm25.get_scores(_tokenize(question)))[indices]
        bm25_ranks = np.argsort(bm25_scores)[::-1]

        fused = _reciprocal_rank_fusion(vector_ranks, bm25_ranks)
        best = fused[:self._top_k]
        return [self._chunks[indices[i]] for i in best]

    def ask(self, question, document=None):
        with self._lock:
            retrieved = self._retrieve(question, document)
        if not retrieved:
            return {"answer": "Aucun passage pertinent trouvé.", "sources": []}
        answer = chatbot.answer(self._client, question, retrieved)
        sources = sorted({chunk.label() for chunk in retrieved})
        return {"answer": answer, "sources": sources}

    def feynman(self, concept, explanation, document=None):
        with self._lock:
            retrieved = self._retrieve(concept, document)
        if not retrieved:
            return {"error": "Aucun passage pertinent trouvé pour ce concept."}
        feedback = chatbot.feynman_feedback(self._client, concept, explanation, retrieved)
        sources = sorted({chunk.label() for chunk in retrieved})
        return {"feedback": feedback, "sources": sources}

    def generate_fiche(self, document=None):
        with self._lock:
            if document:
                chunks = [chunk for chunk in self._chunks if chunk.source == document]
            else:
                chunks = list(self._chunks)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        scope_label = document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        fiche = chatbot.summarize_fiche(self._client, selected, scope_label)
        return {"fiche": fiche, "scope": scope_label}

    def generate_cards(self, document=None, count=8):
        with self._lock:
            if document:
                chunks = [chunk for chunk in self._chunks if chunk.source == document]
            else:
                chunks = list(self._chunks)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        count = max(1, min(MAX_CARDS, count))
        scope_label = document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        cards = chatbot.generate_cards(self._client, selected, count, scope_label)
        if not cards:
            return {"error": "La génération n'a produit aucune carte."}
        added = store.add_cards(document or "corpus", cards)
        return {"added": added, "scope": scope_label, "progress": store.progress(document, kind="open")}

    def next_card(self, document=None):
        card = store.next_due_card(document, kind="open")
        if not card:
            return {"card": None, "progress": store.progress(document, kind="open")}
        return {
            "card": {"id": card["id"], "question": card["question"], "document": card["document"]},
            "progress": store.progress(document, kind="open"),
        }

    def submit_answer(self, card_id, user_answer, document=None):
        card = store.get_card(card_id)
        if not card:
            return {"error": "Carte introuvable."}
        grade = chatbot.grade_answer(self._client, card["question"], card["answer"], user_answer)
        schedule = store.record_review(card_id, grade["score"])
        return {
            "score": grade["score"],
            "feedback": grade["feedback"],
            "reference": card["answer"],
            "next_due_in_days": schedule["interval"] if schedule else None,
            "progress": store.progress(document, kind="open"),
        }

    def next_flashcard(self, document=None):
        card = store.next_due_card(document, kind="open")
        if not card:
            return {"card": None, "progress": store.progress(document, kind="open")}
        return {
            "card": {
                "id": card["id"],
                "question": card["question"],
                "answer": card["answer"],
                "document": card["document"],
            },
            "progress": store.progress(document, kind="open"),
        }

    def submit_flashcard(self, card_id, quality, document=None):
        if not store.get_card(card_id):
            return {"error": "Carte introuvable."}
        schedule = store.record_review(card_id, quality)
        return {
            "next_due_in_days": schedule["interval"] if schedule else None,
            "progress": store.progress(document, kind="open"),
        }

    def generate_quiz(self, document=None, count=8):
        with self._lock:
            if document:
                chunks = [chunk for chunk in self._chunks if chunk.source == document]
            else:
                chunks = list(self._chunks)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        count = max(1, min(MAX_CARDS, count))
        scope_label = document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        cards = chatbot.generate_quiz(self._client, selected, count, scope_label)
        if not cards:
            return {"error": "La génération n'a produit aucune question."}
        added = store.add_cards(document or "corpus", cards)
        return {"added": added, "scope": scope_label, "progress": store.progress(document, kind="quiz")}

    def next_quiz(self, document=None):
        card = store.next_due_card(document, kind="quiz")
        if not card:
            return {"card": None, "progress": store.progress(document, kind="quiz")}
        options = list(card["options"])
        random.shuffle(options)
        return {
            "card": {
                "id": card["id"],
                "question": card["question"],
                "options": options,
                "document": card["document"],
            },
            "progress": store.progress(document, kind="quiz"),
        }

    def submit_quiz(self, card_id, selected, document=None):
        card = store.get_card(card_id)
        if not card or not card.get("options"):
            return {"error": "Carte introuvable."}
        correct_answers = self._decode_correct(card["answer"])
        chosen = set(selected) if isinstance(selected, list) else {selected}
        correct = chosen == set(correct_answers)
        schedule = store.record_review(card_id, QUIZ_CORRECT_GRADE if correct else QUIZ_WRONG_GRADE)
        return {
            "correct": correct,
            "answers": correct_answers,
            "explanation": card.get("explanation"),
            "next_due_in_days": schedule["interval"] if schedule else None,
            "progress": store.progress(document, kind="quiz"),
        }

    @staticmethod
    def _decode_correct(answer):
        try:
            decoded = json.loads(answer)
        except (ValueError, TypeError):
            return [answer]
        return decoded if isinstance(decoded, list) else [answer]

    def progress(self, document=None, kind=None):
        return store.progress(document, kind=kind)

    def dashboard(self, document=None):
        return store.dashboard(document)
