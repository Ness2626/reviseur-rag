from datetime import date

import pytest

import scheduler
from scheduler import CardState


def test_first_successful_review_sets_interval_to_one():
    result = scheduler.review(CardState(), quality=4)
    assert result.repetitions == 1
    assert result.interval == 1


def test_second_successful_review_sets_interval_to_six():
    after_first = scheduler.review(CardState(), quality=4)
    after_second = scheduler.review(after_first, quality=4)
    assert after_second.repetitions == 2
    assert after_second.interval == 6


def test_third_review_multiplies_interval_by_ease():
    state = CardState(ease=2.5, repetitions=2, interval=6)
    result = scheduler.review(state, quality=5)
    assert result.interval == round(6 * result.ease)


def test_failed_review_resets_repetitions_and_interval():
    state = CardState(ease=2.5, repetitions=5, interval=40)
    result = scheduler.review(state, quality=1)
    assert result.repetitions == 0
    assert result.interval == 1


def test_ease_never_drops_below_minimum():
    state = CardState(ease=1.3, repetitions=0, interval=0)
    result = scheduler.review(state, quality=0)
    assert result.ease == scheduler.MIN_EASE


def test_good_answer_increases_ease():
    result = scheduler.review(CardState(ease=2.5), quality=5)
    assert result.ease > 2.5


@pytest.mark.parametrize("quality", [-1, 6, 10])
def test_invalid_quality_raises(quality):
    with pytest.raises(ValueError):
        scheduler.review(CardState(), quality)


def test_next_due_date_adds_interval_days():
    due = scheduler.next_due_date(6, today=date(2026, 1, 1))
    assert due == date(2026, 1, 7)
