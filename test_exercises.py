import random

import pytest

import exercises


@pytest.fixture(autouse=True)
def _seed():
    random.seed(1234)


def test_new_exercise_respects_requested_kind():
    exo = exercises.new_exercise("modexp")
    assert exo["kind"] == "modexp"
    assert exo["format"] == "number"


def test_rsa_verify_has_exactly_one_valid_option():
    exo = exercises.new_exercise("rsa_verify")
    p, q, e, m = exo["params"]["p"], exo["params"]["q"], exo["params"]["e"], exo["params"]["m"]
    n, hm = p * q, m % 10
    valid = [s for s in exo["options"] if pow(s, e, n) == hm]
    assert len(valid) == 1


def test_grade_rsa_verify_accepts_correct_signature():
    exo = exercises.new_exercise("rsa_verify")
    answer, _ = exercises._solve_rsa_verify(exo["params"])
    assert exercises.grade("rsa_verify", exo["params"], answer)["correct"] is True
    assert exercises.grade("rsa_verify", exo["params"], answer + 1)["correct"] is False


def test_modexp_answer_matches_python_pow():
    exo = exercises.new_exercise("modexp")
    a, b, n = exo["params"]["a"], exo["params"]["b"], exo["params"]["n"]
    result = exercises.grade("modexp", exo["params"], pow(a, b, n))
    assert result["correct"] is True
    assert result["answer"] == pow(a, b, n)


def test_rsa_private_exponent_is_modular_inverse():
    exo = exercises.new_exercise("rsa_private_exponent")
    p, q, e = exo["params"]["p"], exo["params"]["q"], exo["params"]["e"]
    phi = (p - 1) * (q - 1)
    answer = exercises.grade("rsa_private_exponent", exo["params"], 0)["answer"]
    assert (e * answer) % phi == 1


def test_grade_handles_non_numeric_answer():
    exo = exercises.new_exercise("modexp")
    assert exercises.grade("modexp", exo["params"], "abc")["correct"] is False


def test_grade_unknown_kind_returns_error():
    assert "error" in exercises.grade("nope", {}, 1)
