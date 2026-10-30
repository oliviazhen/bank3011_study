"""Adaptive multi-round quiz sessions.

A session is 3 rounds of rising difficulty, each with its own mix of question types:

    Round 1  Foundations  difficulty 1   relationship 30% · equation 20% · fill-the-gap 25% · definition 25%
                                        (one-step X → Y relationships; equations with one variable changing)
    Round 2  Application  difficulty 2   relationship 30% · equation 20% · MCQ 35% · fill-the-gap 15%
                                        (chains, comparisons, rearranging and linking equations)
    Round 3  Mastery      difficulty 3   MCQ 40% · relationship 30% · equation 30%
                                        (multi-step problems and chains, several variables changing at once)

Each round mixes
  * re-tests of weak topics (~40% of slots): a DIFFERENT question on the same topic, preferably of a
    DIFFERENT TYPE from the one missed, at the missed level or one above (never above the round's
    level), with no escalation for a topic that keeps being missed;
  * new material at the round's difficulty, filled type by type to match the round's mix, favouring
    low-mastery topics and showing topics with a long correct streak less often.

Re-tests count toward the type mix. When a type's quota can't be filled, the slot falls back to
another type rather than leaving the round short.

Everything here is pure (no Streamlit, no database) so it can be unit-tested.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

ROUND_SIZE = 8          # questions per round
WEAK_SHARE = 0.4        # share of a round reserved for re-testing weak topics
MIN_ROUND = 3           # a round smaller than this is skipped
STRONG_STREAK = 3       # correct answers in a row after which a topic is shown less often
STRONG_WEIGHT = 0.25    # ...this much less often
SESSION_TYPES = ("mcq", "relationship", "equation", "cloze", "definition")


@dataclass(frozen=True)
class RoundSpec:
    number: int
    name: str
    difficulty: int
    blurb: str
    mix: tuple[tuple[str, float], ...]     # (question type, share of the round)


ROUNDS = (
    RoundSpec(1, "Foundations", 1, "Definitions, fill-the-gap, one-step relationships and what each equation means.",
              (("relationship", 0.30), ("equation", 0.20), ("cloze", 0.25), ("definition", 0.25))),
    RoundSpec(2, "Application", 2, "Chains of cause and effect, comparisons, and putting equations to work.",
              (("relationship", 0.30), ("equation", 0.20), ("mcq", 0.35), ("cloze", 0.15))),
    RoundSpec(3, "Mastery", 3, "Multi-step problems, longer chains and several variables changing at once.",
              (("mcq", 0.40), ("relationship", 0.30), ("equation", 0.30))),
)


@dataclass
class TopicState:
    """What we know about one topic, kept between sessions."""
    weak: bool = False          # missed and not yet re-tested successfully
    level: int = 1              # difficulty at which it was last missed
    fail_streak: int = 0        # misses in a row
    correct_streak: int = 0     # correct answers in a row
    last_seen: str | None = None
    missed_type: str | None = None   # question type it was last missed on (re-tests prefer another type)


@dataclass(frozen=True)
class Answer:
    question_id: str
    topic: str
    difficulty: int
    correct: bool
    round: int
    ts: str = ""
    qtype: str = "mcq"


@dataclass
class RoundPlan:
    spec: RoundSpec
    questions: list[dict]
    retest_ids: set[str] = field(default_factory=set)     # which questions are weak-topic re-tests
    skipped_weak: list[str] = field(default_factory=list)  # weak topics with no question left to ask
    quota: dict[str, int] = field(default_factory=dict)    # the type mix this round aimed for


# --------------------------------------------------------------- topic state
def update_topic(state: TopicState, difficulty: int, correct: bool, ts: str = "",
                 qtype: str | None = None) -> TopicState:
    """Apply one answer to a topic's state."""
    if correct:
        weak = state.weak and difficulty < state.level   # passing at (or above) the missed level clears it
        return replace(state, weak=weak, fail_streak=0, correct_streak=state.correct_streak + 1, last_seen=ts)
    return replace(state, weak=True, level=difficulty, fail_streak=state.fail_streak + 1,
                   correct_streak=0, last_seen=ts, missed_type=qtype or state.missed_type)


def weak_topics(states: dict[str, TopicState], scope: set[str]) -> list[str]:
    """Weak topics in scope, most-missed first, then most recently missed."""
    weak = [t for t in scope if states.get(t, TopicState()).weak]
    return sorted(weak, key=lambda t: (states[t].fail_streak, states[t].last_seen or ""), reverse=True)


def retest_levels(state: TopicState, target: int) -> list[int]:
    """Difficulties to try when re-testing a weak topic, in order of preference.

    Same or one above the missed level, never above this round's level; if the topic
    has been missed twice in a row, stay at the missed level (reinforce, don't escalate).
    Lower levels are the fallback when nothing else is left.
    """
    base = min(state.level, target)
    prefs = [base] if state.fail_streak >= 2 else [min(base + 1, target), base]
    prefs += list(range(base - 1, 0, -1))
    return [d for i, d in enumerate(prefs) if d >= 1 and d not in prefs[:i]]


def quotas(size: int, mix: dict[str, float]) -> dict[str, int]:
    """Split `size` slots across types by share, using largest remainders (always sums to size)."""
    total = sum(mix.values()) or 1
    raw = {t: size * w / total for t, w in mix.items()}
    out = {t: math.floor(v) for t, v in raw.items()}
    for t in sorted(raw, key=lambda t: raw[t] - out[t], reverse=True)[: size - sum(out.values())]:
        out[t] += 1
    return out


# ------------------------------------------------------------ question choice
def _pick(bank: list[dict], topic: str, levels: list[int], exclude: set[str], history: dict[str, str],
          rng: random.Random, types: list[str] | None = None) -> dict | None:
    """First available question on `topic`, trying `levels` in order and, within a level, `types` in order.

    Never repeats a question in `exclude` (this session). Prefers questions never seen before,
    then the least recently seen (history: question id -> last seen).
    """
    for d in levels:
        for t in (types if types is not None else [None]):
            pool = [q for q in bank if q["concept"] == topic and q.get("difficulty") == d
                    and q["id"] not in exclude and (t is None or q["type"] == t)]
            if pool:
                unseen = [q for q in pool if q["id"] not in history]
                if unseen:
                    return rng.choice(unseen)
                return min(pool, key=lambda q: (history[q["id"]], rng.random()))
    return None


def build_round(spec: RoundSpec, bank: list[dict], states: dict[str, TopicState], *,
                scope: set[str], asked: set[str], covered: set[str], history: dict[str, str],
                mastery: dict[str, float] | None = None, size: int = ROUND_SIZE,
                weak_share: float = WEAK_SHARE, rng: random.Random | None = None) -> RoundPlan:
    """Build one round.

    bank     session questions (each with 'id', 'type', 'concept', 'difficulty')
    states   topic state (weak flags, missed type etc.), already updated with every earlier answer
    scope    topics this session covers (all weeks, or one week)
    asked    question ids already asked this session (never repeated)
    covered  topics already asked this session (new material prefers others)
    history  question id -> when it was last answered, across all sessions
    mastery  topic -> mastery probability (0-1), lower = more likely to be picked
    """
    rng = rng or random.Random()
    mastery = mastery or {}
    bank = [q for q in bank if q["concept"] in scope and q.get("type", "mcq") in SESSION_TYPES]
    mix = dict(spec.mix)
    quota = quotas(size, mix)
    chosen: list[dict] = []
    used_topics: set[str] = set()
    taken = set(asked)
    plan = RoundPlan(spec, chosen, quota=dict(quota))

    def take(q: dict, retest: bool = False) -> None:
        chosen.append(q)
        taken.add(q["id"])
        used_topics.add(q["concept"])
        if q["type"] in quota and quota[q["type"]] > 0:
            quota[q["type"]] -= 1
        if retest:
            plan.retest_ids.add(q["id"])

    # 1) re-test weak topics with a different question, preferably of a different type (~40%)
    weak_slots = min(size, max(1, math.floor(size * weak_share + 0.5))) if size > 1 else 0
    for topic in weak_topics(states, scope):
        if len(plan.retest_ids) >= weak_slots:
            break
        st = states[topic]
        levels = retest_levels(st, spec.difficulty)
        base = min(st.level, spec.difficulty)
        main, lower = [d for d in levels if d >= base], [d for d in levels if d < base]
        topic_types = {q["type"] for q in bank if q["concept"] == topic}
        # other types first, those this round still needs most at the front; the missed type last
        others = sorted(topic_types - {st.missed_type}, key=lambda t: (-quota.get(t, 0), t not in mix, t))
        same = [st.missed_type] if st.missed_type in topic_types else []
        q = None
        for lv, tps in ((main, others), (main, same), (lower, others), (lower, same)):
            if lv and tps:
                q = _pick(bank, topic, lv, taken, history, rng, types=tps)
                if q:
                    break
        if q is None:
            plan.skipped_weak.append(topic)
            continue
        take(q, retest=True)

    # 2) new material, type by type, at this round's difficulty (lower levels as a fallback)
    levels = list(range(spec.difficulty, 0, -1))

    def weight(t: str) -> float:
        w = (1 - mastery.get(t, 0.1)) ** 2 + 0.05
        if states.get(t, TopicState()).correct_streak >= STRONG_STREAK:
            w *= STRONG_WEIGHT
        return w

    def has(t: str, qtype: str | None) -> bool:
        return any(q["concept"] == t and q["id"] not in taken and q["difficulty"] <= spec.difficulty
                   and (qtype is None or q["type"] == qtype) for q in bank)

    def fill_one(types: list[str] | None, allow_repeat_topic: bool = False) -> bool:
        """Add one question of one of `types` (None = any) on a fresh topic. False if impossible."""
        for prefer_uncovered in (True, False):
            pool = [t for t in sorted(scope) if (allow_repeat_topic or t not in used_topics)
                    and (not prefer_uncovered or t not in covered)
                    and any(has(t, ty) for ty in (types or [None]))]
            while pool:
                t = rng.choices(pool, weights=[weight(x) for x in pool], k=1)[0]
                pool.remove(t)
                q = _pick(bank, t, levels, taken, history, rng, types=types)
                if q is not None:
                    take(q)
                    return True
        return False

    # fill the scarcest types first so common types don't use up the topics they need
    slots = [t for t, n in quota.items() for _ in range(n)]
    slots.sort(key=lambda ty: sum(q["type"] == ty and q["difficulty"] <= spec.difficulty for q in bank))
    unfilled = 0
    for ty in slots:
        if len(chosen) >= size:
            break
        if not fill_one([ty]):
            unfilled += 1
    fallback_types = [t for t in mix] + [t for t in SESSION_TYPES if t not in mix]
    for _ in range(unfilled):                      # quota couldn't be met: any type, round's types first
        if len(chosen) >= size or not fill_one(fallback_types):
            break
    while len(chosen) < size:                       # small pool: allow a second question per topic
        if not fill_one(fallback_types, allow_repeat_topic=True):
            break

    rng.shuffle(chosen)
    return plan


# ------------------------------------------------------------------ summary
def summarise(answers: list[Answer], states: dict[str, TopicState], scope: set[str],
              skipped: set[str] | None = None) -> dict:
    """End-of-session report."""
    per_round: dict[int, tuple[int, int]] = {}
    per_type: dict[str, tuple[int, int]] = {}
    for a in answers:
        c, n = per_round.get(a.round, (0, 0))
        per_round[a.round] = (c + a.correct, n + 1)
        c, n = per_type.get(a.qtype, (0, 0))
        per_type[a.qtype] = (c + a.correct, n + 1)

    by_topic: dict[str, list[Answer]] = {}
    for a in answers:
        by_topic.setdefault(a.topic, []).append(a)

    mastered = sorted(t for t, ans in by_topic.items()
                      if all(a.correct for a in ans) and max(a.difficulty for a in ans) >= 2
                      and not states.get(t, TopicState()).weak)
    still_weak = weak_topics(states, scope)
    focus = still_weak[:3]
    if not focus:   # nothing weak: suggest the least-practised topics in scope
        focus = sorted(scope - set(mastered), key=lambda t: len(by_topic.get(t, [])))[:3]
    total_c = sum(c for c, _ in per_round.values())
    total_n = sum(n for _, n in per_round.values())
    return {
        "per_round": per_round,
        "per_type": per_type,
        "score": (total_c, total_n),
        "mastered": mastered,
        "still_weak": still_weak,
        "focus": focus,
        "needs_more_questions": sorted(skipped or set()),
    }
