"""SM-2 spaced repetition (Wozniak, SuperMemo 1987) - the algorithm behind Anki.

You rate each recall 0-5. Good recalls push the next review further out;
a failed recall (< 3) resets the card to tomorrow.
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta

# Ratings offered as buttons in the app
AGAIN, HARD, GOOD, EASY = 1, 3, 4, 5


@dataclass(frozen=True)
class CardState:
    ease: float = 2.5          # ease factor (EF)
    interval: int = 0          # days until next review
    reps: int = 0              # consecutive successful reviews
    due: date = date.min       # date.min = new card, due immediately


def review(state: CardState, quality: int, today: date | None = None) -> CardState:
    """Apply one review with quality 0-5 and return the new card state."""
    if not 0 <= quality <= 5:
        raise ValueError("quality must be 0-5")
    today = today or date.today()

    if quality < 3:
        reps, interval = 0, 1
    else:
        reps = state.reps + 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = round(state.interval * state.ease)

    ease = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(ease, 1.3)

    return replace(state, ease=round(ease, 3), interval=interval, reps=reps,
                   due=today + timedelta(days=interval))


def is_due(state: CardState, today: date | None = None) -> bool:
    return state.due <= (today or date.today())
