import random

import pytest

import exam


@pytest.fixture(autouse=True)
def _seed():
    random.seed(4242)


def _cards(count, with_options=False):
    return [
        {"id": i, "question": f"Q{i}", "document": "cours.pdf",
         "options": ["a", "b"] if with_options else None}
        for i in range(count)
    ]


def _exercise():
    return {"kind": "modexp", "title": "Exponentiation modulaire", "statement": "Calcule 2^3 mod 5",
            "format": "number", "params": {"a": 2, "b": 3, "n": 5}}


def test_plan_reserves_two_exercises_for_long_exam():
    counts = exam.plan(10, quiz_available=20, open_available=20)
    assert counts["exercise"] == 2
    assert counts["quiz"] + counts["open"] + counts["exercise"] == 10


def test_plan_reserves_single_exercise_for_short_exam():
    counts = exam.plan(5, quiz_available=20, open_available=20)
    assert counts["exercise"] == 1
    assert counts["quiz"] + counts["open"] == 4


def test_plan_shifts_budget_to_available_kind():
    counts = exam.plan(10, quiz_available=0, open_available=20)
    assert counts["quiz"] == 0
    assert counts["open"] == 8


def test_plan_shrinks_exam_when_card_stock_is_short():
    counts = exam.plan(10, quiz_available=1, open_available=1)
    assert counts["quiz"] == 1
    assert counts["open"] == 1
    assert counts["exercise"] == 2


def test_plan_clamps_requested_count():
    assert sum(exam.plan(999, 50, 50).values()) == exam.MAX_QUESTION_COUNT
    assert sum(exam.plan(0, 50, 50).values()) == exam.MIN_QUESTION_COUNT


def test_build_mixes_every_kind_of_question():
    questions = exam.build(_cards(2, with_options=True), _cards(2), [_exercise()])
    assert len(questions) == 5
    assert {q["type"] for q in questions} == {"quiz", "open", "exercise"}


def test_build_keeps_quiz_options_and_card_ids():
    questions = exam.build(_cards(1, with_options=True), [], [])
    assert sorted(questions[0]["options"]) == ["a", "b"]
    assert questions[0]["card_id"] == 0


def test_build_exposes_exercise_params_for_grading():
    questions = exam.build([], [], [_exercise()])
    assert questions[0]["params"] == {"a": 2, "b": 3, "n": 5}
    assert questions[0]["kind"] == "modexp"


def test_final_score_averages_ratios_over_twenty():
    assert exam.final_score([1.0, 1.0]) == 20.0
    assert exam.final_score([1.0, 0.0]) == 10.0
    assert exam.final_score([0.6, 0.8, 1.0]) == 16.0


def test_final_score_of_empty_copy_is_zero():
    assert exam.final_score([]) == 0.0


def test_plan_drops_exercises_when_not_relevant_to_scope():
    counts = exam.plan(10, quiz_available=20, open_available=20, exercises_relevant=False)
    assert counts["exercise"] == 0
    assert counts["quiz"] + counts["open"] == 10


def test_weak_labels_lists_missed_notions_without_duplicates():
    results = [
        {"ratio": 0.0, "label": "signature RSA"},
        {"ratio": 0.2, "label": "Signature RSA"},
        {"ratio": 1.0, "label": "handshake TLS"},
        {"ratio": 0.6, "label": "certificats"},
    ]
    assert exam.weak_labels(results) == ["signature RSA"]


def test_weak_labels_ignores_results_without_label():
    assert exam.weak_labels([{"ratio": 0.0, "label": None}]) == []
