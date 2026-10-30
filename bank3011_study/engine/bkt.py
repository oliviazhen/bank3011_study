"""Bayesian Knowledge Tracing (Corbett & Anderson, 1994).

Each concept has a probability P(L) that you have mastered it. After every
answer we update that belief with Bayes' rule, allowing for:

    G (guess)  - chance of answering correctly WITHOUT knowing it
    S (slip)   - chance of answering wrongly despite knowing it
    T (learn)  - chance you learned it from this attempt (feedback, worked solution)
"""
from dataclasses import dataclass

MASTERED = 0.95   # treat a concept as mastered above this
UNLOCK = 0.60     # a prerequisite must reach this before dependants are served


@dataclass(frozen=True)
class BKTParams:
    prior: float = 0.10   # P(L0): starting belief before any answers
    guess: float = 0.20
    slip: float = 0.10
    learn: float = 0.10


def update(p_mastery: float, correct: bool, params: BKTParams = BKTParams()) -> float:
    """Return the new mastery probability after one observed answer."""
    g, s, t = params.guess, params.slip, params.learn
    p = p_mastery

    if correct:
        evidence = p * (1 - s) + (1 - p) * g
        posterior = p * (1 - s) / evidence
    else:
        evidence = p * s + (1 - p) * (1 - g)
        posterior = p * s / evidence

    # Transition: you may have learned it from this attempt.
    p_next = posterior + (1 - posterior) * t
    return min(max(p_next, 0.001), 0.999)


def guess_rate_for(question: dict) -> float:
    """How easy is it to guess this question type? Feeds the G parameter."""
    qtype = question.get("type")
    if question.get("options"):                       # mcq, relationship, equation
        return 1.0 / max(len(question["options"]), 2)
    if qtype == "cloze" or (qtype == "definition" and question.get("subtype") == "name"):
        return 0.03                                   # typed answers are hard to guess
    if qtype == "definition":
        return 0.10
    if qtype == "steps":
        # Can't guess a number, but you can get one right by plugging into a
        # formula you don't really understand, so this isn't near zero.
        return 0.10
    if qtype == "explain":
        return 0.10
    return 0.20


def params_for(question: dict) -> BKTParams:
    return BKTParams(guess=guess_rate_for(question))


def status(p: float) -> str:
    if p >= MASTERED:
        return "mastered"
    if p >= UNLOCK:
        return "developing"
    if p > BKTParams().prior + 0.001:
        return "weak"
    return "new"
