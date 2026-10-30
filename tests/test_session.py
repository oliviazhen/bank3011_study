"""Tests for the adaptive round engine, one per rule / edge case in the design."""
import random

from engine.content import load_content
from engine.session import (ROUNDS, Answer, TopicState, build_round, retest_levels, summarise,
                            update_topic, weak_topics)

CONTENT = load_content("content")
BANK = [q for c in CONTENT.values() for q in c["questions"] if q["type"] == "mcq"]
SCOPE = set(CONTENT)
R1, R2, R3 = ROUNDS


def make(states=None, asked=(), covered=(), history=None, scope=SCOPE, spec=R1, seed=0, bank=BANK, **kw):
    return build_round(spec, bank, states or {}, scope=set(scope), asked=set(asked), covered=set(covered),
                       history=history or {}, rng=random.Random(seed), **kw)


# ---------------------------------------------------------------- basic shape
def test_round1_is_foundations_only_distinct_topics_no_repeats():
    plan = make()
    assert len(plan.questions) == 8
    assert {q["difficulty"] for q in plan.questions} == {1}
    assert len({q["concept"] for q in plan.questions}) == 8          # one question per topic
    assert len({q["id"] for q in plan.questions}) == 8


def test_each_round_targets_its_difficulty():
    for spec in ROUNDS:
        plan = make(spec=spec, seed=spec.number)
        # every question at the round's level, except topics with no question there (fallback is lower)
        for q in plan.questions:
            assert q["difficulty"] <= spec.difficulty
        assert sum(q["difficulty"] == spec.difficulty for q in plan.questions) >= 7


# ------------------------------------------------------------ weak re-testing
def test_missed_topic_is_retested_with_a_different_question():
    q1 = next(q for q in BANK if q["concept"] == "ltv" and q["difficulty"] == 1)
    states = {"ltv": update_topic(TopicState(), 1, correct=False, ts="t1")}
    plan = make(states, asked={q1["id"]}, covered={"ltv"}, spec=R2)
    retest = [q for q in plan.questions if q["id"] in plan.retest_ids]
    assert [q["concept"] for q in retest] == ["ltv"]
    assert retest[0]["id"] != q1["id"]                     # not the identical question
    assert retest[0]["difficulty"] in (1, 2)                # same or one higher


def test_weak_share_is_about_40_percent():
    states = {t: update_topic(TopicState(), 1, False, "t") for t in list(SCOPE)[:10]}   # 10 weak topics
    plan = make(states, spec=R2)
    assert len(plan.retest_ids) == 3                        # round(8 * 0.4) = 3, the rest carry forward
    assert len(plan.questions) == 8


def test_most_missed_topics_are_retested_first():
    states = {t: update_topic(TopicState(), 1, False, "t") for t in ["ltv", "raroc", "altman_z", "cp_transfer"]}
    states["raroc"] = update_topic(states["raroc"], 1, False, "t2")       # missed twice
    plan = make(states, spec=R2)
    assert "raroc" in {q["concept"] for q in plan.questions if q["id"] in plan.retest_ids}


def test_repeated_failure_does_not_escalate():
    s = TopicState()
    s = update_topic(s, 2, False)
    s = update_topic(s, 2, False)
    assert s.fail_streak == 2
    assert retest_levels(s, target=3) == [2, 1]            # stays at 2, never 3
    assert retest_levels(update_topic(TopicState(), 2, False), target=3) == [3, 2, 1]


def test_retest_never_exceeds_round_level():
    s = update_topic(TopicState(), 3, False)               # missed a mastery question last session
    assert max(retest_levels(s, target=1)) == 1            # round 1 stays calculation-free


def test_passing_the_retest_clears_weak_but_easier_pass_does_not():
    s = update_topic(TopicState(), 2, False)
    assert update_topic(s, 1, True).weak                   # right at an easier level: still weak
    assert not update_topic(s, 2, True).weak               # right at the missed level: cleared
    assert not update_topic(s, 3, True).weak


# ----------------------------------------------------------------- edge cases
def test_topic_without_a_mastery_question_falls_back_to_lower_level():
    plan = make(scope={"cp_transfer"}, spec=R3, size=1)    # cp_transfer has no difficulty-3 question
    assert len(plan.questions) == 1
    assert plan.questions[0]["difficulty"] == 2


def test_weak_topic_with_nothing_left_is_skipped_and_reported():
    ltv_ids = {q["id"] for q in BANK if q["concept"] == "ltv"}
    states = {"ltv": update_topic(TopicState(), 1, False)}
    plan = make(states, asked=ltv_ids, spec=R2)
    assert "ltv" in plan.skipped_weak
    assert "ltv" not in {q["concept"] for q in plan.questions}


def test_small_scope_shrinks_the_round_instead_of_repeating():
    scope = {"cp_transfer", "mortality_rates"}
    plan = make(scope=scope, spec=R1)
    ids = [q["id"] for q in plan.questions]
    assert len(ids) == len(set(ids)) <= 5                  # only 5 foundation questions exist in scope
    assert {q["concept"] for q in plan.questions} <= scope


def test_no_question_repeats_across_a_whole_session():
    states, asked, covered = {}, set(), set()
    rng = random.Random(4)
    for spec in ROUNDS:
        plan = build_round(spec, BANK, states, scope=SCOPE, asked=asked, covered=covered, history={}, rng=rng)
        for q in plan.questions:
            assert q["id"] not in asked
            asked.add(q["id"])
            covered.add(q["concept"])
            ok = rng.random() < 0.6
            states[q["concept"]] = update_topic(states.get(q["concept"], TopicState()), q["difficulty"], ok)
    assert len(asked) == 24


def test_all_correct_means_no_retests():
    plan = make({t: TopicState(correct_streak=1) for t in SCOPE}, spec=R2)
    assert plan.retest_ids == set()
    assert len(plan.questions) == 8


def test_strong_topics_are_shown_less_often():
    strong = {"cr_basics": TopicState(correct_streak=5)}
    hits_strong = sum("cr_basics" in {q["concept"] for q in make(strong, spec=R2, seed=s).questions}
                      for s in range(300))
    hits_normal = sum("cr_basics" in {q["concept"] for q in make({}, spec=R2, seed=s).questions}
                      for s in range(300))
    assert hits_strong < hits_normal * 0.8


def test_unseen_questions_preferred_over_previously_seen():
    ltv_d2 = [q["id"] for q in BANK if q["concept"] == "ltv" and q["difficulty"] == 2]
    history = {ltv_d2[0]: "2026-10-01"}
    plan = make(scope={"ltv"}, spec=R2, size=1, history=history)
    assert plan.questions[0]["id"] == ltv_d2[1]


def test_weak_topics_carry_into_next_session_round1():
    carried = {"raroc": update_topic(TopicState(), 3, False, "last-session")}
    plan = make(carried, spec=R1)
    retest = [q for q in plan.questions if q["id"] in plan.retest_ids]
    assert [q["concept"] for q in retest] == ["raroc"]
    assert retest[0]["difficulty"] == 1


def test_weak_topic_order_is_most_missed_then_most_recent():
    states = {"a": TopicState(weak=True, fail_streak=1, last_seen="2026-10-01"),
              "b": TopicState(weak=True, fail_streak=1, last_seen="2026-10-05"),
              "c": TopicState(weak=True, fail_streak=3, last_seen="2026-09-01")}
    assert weak_topics(states, {"a", "b", "c"}) == ["c", "b", "a"]


# -------------------------------------------------------------------- summary
def test_summary():
    answers = [Answer("q1", "ltv", 1, True, 1), Answer("q2", "raroc", 1, False, 1),
               Answer("q3", "ltv", 2, True, 2), Answer("q4", "raroc", 2, False, 2),
               Answer("q5", "cp_transfer", 1, True, 1)]
    states = {"ltv": TopicState(correct_streak=2), "raroc": TopicState(weak=True, level=2, fail_streak=2),
              "cp_transfer": TopicState(correct_streak=1)}
    s = summarise(answers, states, {"ltv", "raroc", "cp_transfer"}, skipped={"altman_z"})
    assert s["per_round"] == {1: (2, 3), 2: (1, 2)}
    assert s["score"] == (3, 5)
    assert s["mastered"] == ["ltv"]                         # cp_transfer only seen at difficulty 1
    assert s["still_weak"] == ["raroc"]
    assert s["focus"] == ["raroc"]
    assert s["needs_more_questions"] == ["altman_z"]
