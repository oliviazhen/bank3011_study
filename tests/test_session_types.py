"""Type mix per round and type-switching re-tests."""
import random
from collections import Counter

from engine.content import load_content
from engine.session import (ROUNDS, Answer, TopicState, build_round, quotas, summarise, update_topic)

CONTENT = load_content("content")
SESSION = ("mcq", "relationship", "equation", "cloze", "definition")
BANK = [q for c in CONTENT.values() for q in c["questions"] if q["type"] in SESSION]
SCOPE = set(CONTENT)
R1, R2, R3 = ROUNDS


def make(states=None, spec=R1, seed=0, scope=SCOPE, asked=(), covered=(), **kw):
    return build_round(spec, BANK, states or {}, scope=set(scope), asked=set(asked), covered=set(covered),
                       history={}, rng=random.Random(seed), **kw)


def test_quotas_sum_to_round_size():
    assert quotas(8, dict(R1.mix)) == {"relationship": 2, "equation": 2, "cloze": 2, "definition": 2}
    for spec in ROUNDS:
        assert sum(quotas(8, dict(spec.mix)).values()) == 8


def test_round1_matches_its_type_mix_and_is_one_step():
    for seed in range(20):
        plan = make(seed=seed)
        counts = Counter(q["type"] for q in plan.questions)
        assert counts == Counter(quotas(8, dict(R1.mix))), counts
        for q in plan.questions:
            assert q["difficulty"] == 1
            if q["type"] == "relationship":
                assert q["relationship"]["steps"] == 1
            if q["type"] == "equation":
                assert q.get("changes", 1) == 1 and q["subtype"] in ("proportionality", "variables")


def test_later_rounds_follow_their_mix():
    for spec in (R2, R3):
        for seed in range(10):
            counts = Counter(q["type"] for q in make(spec=spec, seed=seed).questions)
            assert counts == Counter(quotas(8, dict(spec.mix))), (spec.name, counts)


def test_retest_switches_type():
    for missed in ("definition", "cloze", "equation", "relationship"):
        states = {"raroc": update_topic(TopicState(), 1, False, "t", qtype=missed)}
        assert states["raroc"].missed_type == missed
        for seed in range(10):
            plan = make(states, spec=R2, seed=seed)
            [retest] = [q for q in plan.questions if q["id"] in plan.retest_ids]
            assert retest["concept"] == "raroc" and retest["type"] != missed


def test_retest_falls_back_to_same_type_when_no_other_type_left():
    other = {q["id"] for q in BANK if q["concept"] == "cp_transfer" and q["type"] != "cloze"}
    states = {"cp_transfer": update_topic(TopicState(), 1, False, qtype="cloze")}
    plan = make(states, spec=R1, asked=other)
    retest = [q for q in plan.questions if q["id"] in plan.retest_ids]
    assert [q["type"] for q in retest] in ([], ["cloze"])        # cp has only one cloze: it may be used up
    asked_cloze = {q["id"] for q in BANK if q["concept"] == "cp_transfer" and q["type"] == "cloze"}
    plan = make(states, spec=R1, asked=other | asked_cloze)
    assert "cp_transfer" in plan.skipped_weak                     # nothing left at all: reported


def test_retests_count_toward_the_type_mix():
    states = {t: update_topic(TopicState(), 1, False, "t", qtype="mcq") for t in ["ltv", "raroc", "altman_z"]}
    for seed in range(10):
        plan = make(states, spec=R1, seed=seed)
        counts = Counter(q["type"] for q in plan.questions)
        assert len(plan.retest_ids) == 3 and len(plan.questions) == 8
        assert counts == Counter(quotas(8, dict(R1.mix))), counts   # re-tests used round-1 types, not mcq


def test_type_quota_falls_back_when_scope_has_no_equations():
    scope = {"npl_cycle", "lgd_seniority", "cp_transfer", "ead_features"}   # none has an equation question
    plan = make(scope=scope, spec=R1)
    assert len(plan.questions) == 8
    assert all(q["type"] != "equation" for q in plan.questions)
    assert all(q["concept"] in scope for q in plan.questions)


def test_round1_has_no_plain_mcq_when_material_exists():
    for seed in range(20):
        assert all(q["type"] != "mcq" for q in make(seed=seed).questions)


def test_full_session_no_repeats_with_all_types():
    states, asked, covered = {}, set(), set()
    rng = random.Random(9)
    for spec in ROUNDS:
        plan = build_round(spec, BANK, states, scope=SCOPE, asked=asked, covered=covered, history={}, rng=rng)
        assert len(plan.questions) == 8
        for q in plan.questions:
            assert q["id"] not in asked
            asked.add(q["id"]); covered.add(q["concept"])
            ok = rng.random() < 0.6
            states[q["concept"]] = update_topic(states.get(q["concept"], TopicState()), q["difficulty"], ok,
                                                qtype=q["type"])


def test_summary_reports_accuracy_by_type():
    answers = [Answer("a", "ltv", 1, True, 1, qtype="cloze"), Answer("b", "ltv", 1, False, 1, qtype="definition"),
               Answer("c", "raroc", 2, True, 2, qtype="cloze")]
    s = summarise(answers, {}, {"ltv", "raroc"})
    assert s["per_type"] == {"cloze": (2, 2), "definition": (0, 1)}
