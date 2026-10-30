"""Choosing the next question.

Combines three ideas:
  * Knowledge space theory - only serve concepts whose prerequisites are unlocked
  * Remediation           - after a miss, drop back to a weak prerequisite
  * Interleaving          - sample across concepts (weighted to weak ones)
                            rather than drilling one topic in a block
"""
import random

from .bkt import MASTERED, UNLOCK, BKTParams


def mastery_of(mastery: dict[str, float], concept_id: str) -> float:
    return mastery.get(concept_id, BKTParams().prior)


def unlocked(concept: dict, mastery: dict[str, float]) -> bool:
    return all(mastery_of(mastery, p) >= UNLOCK for p in concept.get("prerequisites", []))


def weakest_prerequisite(concept: dict, mastery: dict[str, float], concepts: dict) -> str | None:
    """Walk down the prerequisite graph to the deepest weak, unlocked prerequisite."""
    weak = [p for p in concept.get("prerequisites", [])
            if p in concepts and mastery_of(mastery, p) < UNLOCK]
    if not weak:
        return None
    target = min(weak, key=lambda p: mastery_of(mastery, p))
    deeper = weakest_prerequisite(concepts[target], mastery, concepts)
    return deeper or target


def choose_concept(concepts: dict, mastery: dict[str, float], *,
                   last_missed: str | None = None,
                   focus: str | None = None,
                   scope: set[str] | None = None,
                   rng: random.Random | None = None) -> str:
    """Pick the next concept.

    scope: restrict practice to these concepts (e.g. one week). Prerequisites
    outside the scope don't lock a concept, since you chose to study this week,
    but remediation can still send you back to an earlier week after a miss.
    """
    rng = rng or random.Random()

    if focus:
        return focus

    # Remediation: you just missed something whose foundations are shaky.
    if last_missed and last_missed in concepts:
        prereq = weakest_prerequisite(concepts[last_missed], mastery, concepts)
        if prereq:
            return prereq

    ids = [cid for cid in concepts if scope is None or cid in scope]

    def open_(cid: str) -> bool:
        return all(mastery_of(mastery, p) >= UNLOCK for p in concepts[cid].get("prerequisites", [])
                   if scope is None or p in scope)

    pool = [cid for cid in ids if open_(cid) and mastery_of(mastery, cid) < MASTERED]
    if not pool:  # everything mastered: keep everything in light rotation
        pool = ids

    # Weight by how far from mastery each concept is (interleaved, biased to weak).
    weights = [(1 - mastery_of(mastery, cid)) ** 2 + 0.02 for cid in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def choose_question(concept: dict, recent_ids: list[str], *,
                    qtypes: tuple[str, ...] = ("mcq", "steps"),
                    rng: random.Random | None = None) -> dict | None:
    rng = rng or random.Random()
    qs = [q for q in concept.get("questions", []) if q["type"] in qtypes]
    if not qs:
        return None
    fresh = [q for q in qs if q["id"] not in recent_ids[-6:]]
    return rng.choice(fresh or qs)
