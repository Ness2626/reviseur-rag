import json
import os
import random
import re
import threading

import numpy as np
from rank_bm25 import BM25Okapi

import chatbot
import exam
import exercises
import store

FICHE_BUDGET_CHARS = 16000
MAX_CARDS = 15
QUIZ_CORRECT_GRADE = 5
QUIZ_WRONG_GRADE = 1
EXERCISE_CORRECT_GRADE = 5
EXERCISE_WRONG_GRADE = 1
OPEN_MAX_SCORE = 5
BLANK_ANSWER_GRADE = 0
RRF_K = 60
RERANK_CANDIDATES = 20
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def _tokenize(text):
    return TOKEN_PATTERN.findall(text.lower())


def _cited_numbers(answer_text, passage_count):
    cited = set()
    for match in CITATION_PATTERN.finditer(answer_text):
        for number_text in re.findall(r"\d+", match.group(1)):
            number = int(number_text)
            if 1 <= number <= passage_count:
                cited.add(number)
    return cited


def _build_citations(answer_text, retrieved):
    cited = _cited_numbers(answer_text, len(retrieved))
    if not cited:
        cited = set(range(1, len(retrieved) + 1))
    return [
        {"id": number, "label": chunk.label(), "text": chunk.text}
        for number, chunk in enumerate(retrieved, start=1)
        if number in cited
    ]


def _reciprocal_rank_fusion(*rank_lists, k=RRF_K):
    scores = {}
    for ranks in rank_lists:
        for position, local_index in enumerate(ranks):
            scores[local_index] = scores.get(local_index, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=scores.get, reverse=True)


def _scope_text(cards):
    return " ".join(
        f"{card['question']} {card.get('topic') or ''} {card['document']}" for card in cards
    )


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

    def __init__(self, groq_client, embedding_model, reranker=None, top_k=chatbot.TOP_K):
        self._client = groq_client
        self._model = embedding_model
        self._reranker = reranker
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

    def unindexed_documents(self):
        indexed = set(self._documents)
        return sorted(
            name for name in (os.path.basename(path) for path in chatbot.discover_pdfs())
            if name not in indexed
        )

    def has_index(self):
        return bool(self._chunks)

    def _scoped_sources(self, document, subject):
        if subject:
            return set(store.documents_in_subject(subject))
        if document:
            return {document}
        return None

    def _scope_chunks(self, document, subject):
        allowed = self._scoped_sources(document, subject)
        if allowed is None:
            return list(self._chunks)
        return [chunk for chunk in self._chunks if chunk.source in allowed]

    def _fuse_candidates(self, question, indices):
        subset = self._embeddings[indices]
        query_vec = self._model.encode([question], normalize_embeddings=True)[0]
        vector_scores = subset @ query_vec
        vector_ranks = np.argsort(vector_scores)[::-1]

        bm25_scores = np.asarray(self._bm25.get_scores(_tokenize(question)))[indices]
        bm25_ranks = np.argsort(bm25_scores)[::-1]

        fused = _reciprocal_rank_fusion(vector_ranks, bm25_ranks)
        return [indices[i] for i in fused]

    def _rerank(self, question, chunk_indices):
        if self._reranker is None or not chunk_indices:
            return chunk_indices[:self._top_k]
        pairs = [(question, self._chunks[i].text) for i in chunk_indices]
        scores = self._reranker.predict(pairs)
        order = np.argsort(scores)[::-1][:self._top_k]
        return [chunk_indices[i] for i in order]

    def _retrieve(self, question, document=None, subject=None):
        allowed = self._scoped_sources(document, subject)
        if allowed is None:
            indices = list(range(len(self._chunks)))
        else:
            indices = [i for i, c in enumerate(self._chunks) if c.source in allowed]
        if not indices:
            return []

        fused_indices = self._fuse_candidates(question, indices)
        candidates = fused_indices[:RERANK_CANDIDATES]
        best = self._rerank(question, candidates)
        return [self._chunks[i] for i in best]

    def ask_stream(self, question, document=None, subject=None):
        with self._lock:
            retrieved = self._retrieve(question, document, subject)
        if not retrieved:
            yield {"delta": "Aucun passage pertinent trouvé."}
            yield {"citations": []}
            return
        answer_parts = []
        for delta in chatbot.answer_stream(self._client, question, retrieved):
            answer_parts.append(delta)
            yield {"delta": delta}
        full_answer = "".join(answer_parts)
        yield {"citations": _build_citations(full_answer, retrieved)}

    def feynman(self, concept, explanation, document=None, subject=None):
        with self._lock:
            retrieved = self._retrieve(concept, document, subject)
        if not retrieved:
            return {"error": "Aucun passage pertinent trouvé pour ce concept."}
        feedback = chatbot.feynman_feedback(self._client, concept, explanation, retrieved)
        store.add_feynman_entry(concept, explanation, feedback)
        sources = sorted({chunk.label() for chunk in retrieved})
        return {"feedback": feedback, "sources": sources}

    def feynman_history(self):
        return store.feynman_history()

    def generate_fiche(self, document=None, subject=None):
        with self._lock:
            chunks = self._scope_chunks(document, subject)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        scope_label = subject or document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        fiche = chatbot.summarize_fiche(self._client, selected, scope_label)
        return {"fiche": fiche, "scope": scope_label}

    def generate_cards(self, document=None, count=8, subject=None):
        with self._lock:
            chunks = self._scope_chunks(document, subject)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        count = max(1, min(MAX_CARDS, count))
        scope_label = subject or document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        cards = chatbot.generate_cards(self._client, selected, count, scope_label)
        if not cards:
            return {"error": "La génération n'a produit aucune carte."}
        added = store.add_cards(document or subject or "corpus", cards)
        return {"added": added, "scope": scope_label,
                "progress": store.progress(document, kind="open", subject=subject)}

    def next_card(self, document=None, subject=None):
        card = store.next_due_card(document, kind="open", subject=subject)
        if not card:
            return {"card": None, "progress": store.progress(document, kind="open", subject=subject)}
        return {
            "card": {"id": card["id"], "question": card["question"], "document": card["document"]},
            "progress": store.progress(document, kind="open", subject=subject),
        }

    def submit_answer(self, card_id, user_answer, document=None, subject=None):
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
            "progress": store.progress(document, kind="open", subject=subject),
        }

    def next_flashcard(self, document=None, subject=None):
        card = store.next_due_card(document, kind="open", subject=subject)
        if not card:
            return {"card": None, "progress": store.progress(document, kind="open", subject=subject)}
        return {
            "card": {
                "id": card["id"],
                "question": card["question"],
                "answer": card["answer"],
                "document": card["document"],
            },
            "progress": store.progress(document, kind="open", subject=subject),
        }

    def submit_flashcard(self, card_id, quality, document=None, subject=None):
        if not store.get_card(card_id):
            return {"error": "Carte introuvable."}
        schedule = store.record_review(card_id, quality)
        return {
            "next_due_in_days": schedule["interval"] if schedule else None,
            "progress": store.progress(document, kind="open", subject=subject),
        }

    def generate_quiz(self, document=None, count=8, subject=None):
        with self._lock:
            chunks = self._scope_chunks(document, subject)
        if not chunks:
            return {"error": "Aucun contenu pour ce document."}
        count = max(1, min(MAX_CARDS, count))
        scope_label = subject or document or "l'ensemble du corpus"
        selected = _within_budget(chunks)
        cards = chatbot.generate_quiz(self._client, selected, count, scope_label)
        if not cards:
            return {"error": "La génération n'a produit aucune question."}
        added = store.add_cards(document or subject or "corpus", cards)
        return {"added": added, "scope": scope_label,
                "progress": store.progress(document, kind="quiz", subject=subject)}

    def next_quiz(self, document=None, subject=None):
        card = store.next_due_card(document, kind="quiz", subject=subject)
        if not card:
            return {"card": None, "progress": store.progress(document, kind="quiz", subject=subject)}
        options = list(card["options"])
        random.shuffle(options)
        return {
            "card": {
                "id": card["id"],
                "question": card["question"],
                "options": options,
                "document": card["document"],
            },
            "progress": store.progress(document, kind="quiz", subject=subject),
        }

    def submit_quiz(self, card_id, selected, document=None, subject=None):
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
            "progress": store.progress(document, kind="quiz", subject=subject),
        }

    def submit_exercise(self, kind, params, given):
        result = exercises.grade(kind, params, given)
        if "error" in result:
            return result
        grade = EXERCISE_CORRECT_GRADE if result["correct"] else EXERCISE_WRONG_GRADE
        schedule = store.record_skill_review(kind, grade)
        result["next_due_in_days"] = schedule["interval"] if schedule else None
        result["progress"] = store.skills_progress()
        return result

    def new_exam(self, count=exam.DEFAULT_QUESTION_COUNT, document=None, subject=None):
        quiz_pool = store.sample_cards(count, kind="quiz", document=document, subject=subject)
        open_pool = store.sample_cards(count, kind="open", document=document, subject=subject)
        if not quiz_pool and not open_pool:
            return {"error": "Aucune carte pour ce périmètre. Génère d'abord des questions ou un QCM."}
        kinds = exercises.kinds_matching(_scope_text(quiz_pool + open_pool))
        counts = exam.plan(count, len(quiz_pool), len(open_pool), bool(kinds))
        drawn = [exercises.new_exercise(random.choice(kinds)) for _ in range(counts["exercise"])]
        questions = exam.build(quiz_pool[:counts["quiz"]], open_pool[:counts["open"]], drawn)
        return {"questions": questions, "scope": subject or document or "l'ensemble du corpus"}

    @staticmethod
    def _card_label(card):
        return card["topic"] or card["document"]

    def _grade_open(self, answer, document, subject):
        card_id = answer.get("card_id")
        card = store.get_card(card_id)
        if not card:
            return None
        given = (answer.get("answer") or "").strip()
        if not given:
            store.record_review(card_id, BLANK_ANSWER_GRADE)
            return {"type": "open", "ratio": 0.0, "score": 0, "label": self._card_label(card),
                    "feedback": "Aucune réponse donnée.", "reference": card["answer"]}
        result = self.submit_answer(card_id, given, document, subject)
        if "error" in result:
            return None
        return {"type": "open", "ratio": result["score"] / OPEN_MAX_SCORE,
                "score": result["score"], "feedback": result["feedback"],
                "reference": result["reference"], "label": self._card_label(card)}

    def _grade_quiz(self, answer, document, subject):
        card = store.get_card(answer.get("card_id"))
        if not card:
            return None
        result = self.submit_quiz(answer.get("card_id"), answer.get("selected") or [], document, subject)
        if "error" in result:
            return None
        return {"type": "quiz", "ratio": 1.0 if result["correct"] else 0.0,
                "correct": result["correct"], "answers": result["answers"],
                "explanation": result["explanation"], "label": self._card_label(card)}

    def _grade_exercise(self, answer):
        result = self.submit_exercise(answer.get("kind"), answer.get("params") or {}, answer.get("answer"))
        if "error" in result:
            return None
        return {"type": "exercise", "ratio": 1.0 if result["correct"] else 0.0,
                "correct": result["correct"], "answer": result["answer"],
                "solution": result["solution"], "label": answer.get("title")}

    def _grade_exam_answer(self, answer, document, subject):
        if answer.get("type") == "quiz":
            return self._grade_quiz(answer, document, subject)
        if answer.get("type") == "exercise":
            return self._grade_exercise(answer)
        return self._grade_open(answer, document, subject)

    def grade_exam(self, answers, duration_s=None, document=None, subject=None):
        if not answers:
            return {"error": "Copie vide."}
        results = [self._grade_exam_answer(answer, document, subject) for answer in answers]
        if any(result is None for result in results):
            return {"error": "Copie invalide : une question ne correspond à aucune carte."}
        scope = subject or document or "l'ensemble du corpus"
        score = exam.final_score([result["ratio"] for result in results])
        store.add_exam(score, len(results), duration_s, scope)
        return {"score": score, "max_score": exam.MAX_SCORE, "results": results, "scope": scope,
                "to_review": exam.weak_labels(results)}

    @staticmethod
    def _decode_correct(answer):
        try:
            decoded = json.loads(answer)
        except (ValueError, TypeError):
            return [answer]
        return decoded if isinstance(decoded, list) else [answer]

    def progress(self, document=None, kind=None, subject=None):
        return store.progress(document, kind=kind, subject=subject)

    def dashboard(self, document=None, subject=None):
        return store.dashboard(document, subject=subject)

    def subjects(self):
        return store.subjects()

    def document_subjects(self):
        return store.document_subjects()
