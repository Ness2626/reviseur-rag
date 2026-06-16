"""Algorithme de répétition espacée SM-2 (SuperMemo 2).

Fonction pure : prend l'état d'une carte et la qualité de la réponse (0-5),
retourne le nouvel état. Aucun effet de bord, donc trivial à tester.
"""

from dataclasses import dataclass
from datetime import date, timedelta

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
QUALITY_MIN = 0
QUALITY_MAX = 5
PASS_THRESHOLD = 3
FIRST_INTERVAL = 1
SECOND_INTERVAL = 6


@dataclass(frozen=True)
class CardState:
    ease: float = DEFAULT_EASE
    repetitions: int = 0
    interval: int = 0


def review(state, quality):
    if not QUALITY_MIN <= quality <= QUALITY_MAX:
        raise ValueError(f"quality doit être dans [{QUALITY_MIN}, {QUALITY_MAX}], reçu {quality}")
    ease = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(MIN_EASE, ease)
    if quality < PASS_THRESHOLD:
        return CardState(ease=ease, repetitions=0, interval=FIRST_INTERVAL)
    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval = FIRST_INTERVAL
    elif repetitions == 2:
        interval = SECOND_INTERVAL
    else:
        interval = round(state.interval * ease)
    return CardState(ease=ease, repetitions=repetitions, interval=interval)


def next_due_date(interval, today=None):
    today = today or date.today()
    return today + timedelta(days=interval)
