"""Composition d'un examen blanc et calcul de la note finale.

Ni base de données ni appel LLM ici : le module décide de la répartition des
questions selon le stock de cartes disponible, assemble le sujet, et convertit
les ratios de réussite en note sur 20. La notation elle-même reste celle des
modes existants (QCM, questions ouvertes, exercices).
"""

import random

DEFAULT_QUESTION_COUNT = 10
MIN_QUESTION_COUNT = 3
MAX_QUESTION_COUNT = 20
LONG_EXAM_THRESHOLD = 8
MAX_EXERCISES = 2
MAX_SCORE = 20
WEAK_RATIO = 0.6


def plan(count, quiz_available, open_available, exercises_relevant=True):
    count = max(MIN_QUESTION_COUNT, min(MAX_QUESTION_COUNT, count))
    exercise_count = min(MAX_EXERCISES if count >= LONG_EXAM_THRESHOLD else 1, count)
    if not exercises_relevant:
        exercise_count = 0
    card_budget = count - exercise_count
    quiz_count = min(card_budget // 2, quiz_available)
    open_count = min(card_budget - quiz_count, open_available)
    quiz_count = min(card_budget - open_count, quiz_available)
    return {"quiz": quiz_count, "open": open_count, "exercise": exercise_count}


def _quiz_question(card):
    options = list(card["options"])
    random.shuffle(options)
    return {
        "type": "quiz",
        "card_id": card["id"],
        "question": card["question"],
        "options": options,
        "document": card["document"],
    }


def _open_question(card):
    return {
        "type": "open",
        "card_id": card["id"],
        "question": card["question"],
        "document": card["document"],
    }


def _exercise_question(exercise):
    question = {
        "type": "exercise",
        "kind": exercise["kind"],
        "title": exercise["title"],
        "statement": exercise["statement"],
        "format": exercise["format"],
        "params": exercise["params"],
    }
    if exercise.get("options"):
        question["options"] = exercise["options"]
    return question


def build(quiz_cards, open_cards, exercise_items):
    questions = (
        [_quiz_question(card) for card in quiz_cards]
        + [_open_question(card) for card in open_cards]
        + [_exercise_question(item) for item in exercise_items]
    )
    random.shuffle(questions)
    return questions


def weak_labels(results):
    labels = []
    seen = set()
    for result in results:
        label = result.get("label")
        if result["ratio"] >= WEAK_RATIO or not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        labels.append(label)
    return labels


def final_score(ratios):
    if not ratios:
        return 0.0
    return round(sum(ratios) / len(ratios) * MAX_SCORE, 1)
