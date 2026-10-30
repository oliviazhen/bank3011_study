import random
from datetime import date

from engine import bkt, selector
from engine.content import load_content, numbers_match, parse_number, safe_eval, validate
from engine.sm2 import AGAIN, GOOD, CardState, review

CONTENT = load_content("content")


def test_content_is_valid():
    assert validate(CONTENT) == []


def test_bkt_moves_the_right_way():
    p = 0.3
    assert bkt.update(p, True) > p
    assert bkt.update(p, False) < bkt.update(p, True)


def test_bkt_guessable_mcq_counts_less_than_calculation():
    mcq = {"type": "mcq", "options": ["a", "b", "c", "d"]}
    calc = {"type": "steps"}
    assert bkt.update(0.3, True, bkt.params_for(calc)) > bkt.update(0.3, True, bkt.params_for(mcq))


def test_bkt_reaches_mastery_after_a_run_of_correct_answers():
    p = bkt.BKTParams().prior
    for _ in range(8):
        p = bkt.update(p, True, bkt.params_for({"type": "steps"}))
    assert p >= bkt.MASTERED


def test_sm2_intervals():
    today = date(2026, 11, 1)
    s = review(CardState(), GOOD, today)
    assert s.interval == 1
    s = review(s, GOOD, today)
    assert s.interval == 6
    s = review(s, GOOD, today)
    assert s.interval == round(6 * s.ease) or s.interval == 15
    failed = review(s, AGAIN, today)
    assert failed.interval == 1 and failed.reps == 0 and failed.ease >= 1.3


def test_parse_number_variants():
    assert parse_number("$1,964,285.71") == 1964285.71
    assert parse_number("(2.09)") == -2.09
    assert parse_number("9.07%") == 9.07
    assert parse_number("−2.09m") == -2.09
    assert parse_number("abc") is None
    assert numbers_match(7.13, 7.1)          # within 1%
    assert not numbers_match(7.13, 6.9)


def test_safe_eval_blocks_code():
    assert safe_eval("D*L*dR/(1+R)", {"D": 4, "L": 1e7, "dR": 0.055, "R": 0.12}) == 4 * 1e7 * 0.055 / 1.12
    try:
        safe_eval("__import__('os')", {})
        assert False, "should have raised"
    except ValueError:
        pass


def test_locked_concepts_not_served_to_a_beginner():
    rng = random.Random(1)
    week5 = {cid: c for cid, c in CONTENT.items() if c["week"] == 5}
    served = {selector.choose_concept(week5, {}, rng=rng) for _ in range(300)}
    assert served == {"cr_basics"}   # the only concept with no prerequisites
    # once the foundation is solid, the dependants open up
    served = {selector.choose_concept(week5, {"cr_basics": 0.8}, rng=rng) for _ in range(300)}
    assert {"npl_cycle", "gross_return", "loan_structure_pd"} <= served
    assert "raroc" not in served and "altman_z" not in served


def test_remediation_drops_to_deepest_weak_prerequisite():
    # missed RAROC; gross_return is shaky, and so is the cr_basics it rests on
    mastery = {"cr_basics": 0.3, "gross_return": 0.4, "loan_structure_pd": 0.7}
    assert selector.choose_concept(CONTENT, mastery, last_missed="raroc") == "cr_basics"
    # missed RAROC but foundations are fine: no remediation, normal adaptive pick
    mastery = {"cr_basics": 0.9, "gross_return": 0.7, "loan_structure_pd": 0.7}
    assert selector.weakest_prerequisite(CONTENT["raroc"], mastery, CONTENT) is None


def test_week_scope_only_serves_that_week():
    rng = random.Random(3)
    week7 = {cid for cid, c in CONTENT.items() if c["week"] == 7}
    served = {selector.choose_concept(CONTENT, {"cr_basics": 0.8}, scope=week7, rng=rng) for _ in range(200)}
    assert served <= week7


def test_every_concept_has_three_mcqs():
    for cid, c in CONTENT.items():
        assert sum(q["type"] == "mcq" for q in c["questions"]) >= 3, cid


def test_course_has_a_tab_for_every_week():
    from engine.content import load_course
    course = load_course("course.json", CONTENT)
    assert [w["week"] for w in course] == list(range(1, 13))
    assert next(w for w in course if w["week"] == 7)["concepts"]
    assert not next(w for w in course if w["week"] == 3)["concepts"]


def test_every_question_cites_a_real_slide_or_page():
    from engine.content import load_sources
    sources = load_sources("assets/sources")
    assert validate(CONTENT, sources) == []
    for c in CONTENT.values():
        for q in c["questions"]:
            assert q.get("sources") or q.get("_set"), q["id"]   # your own questions may have no slide


def test_each_week_cites_its_own_lectures():
    lecture = {5: {"week05_lecture"}, 7: {"week07_lecture"}, 8: {"week08_lecture"},
               9: {"week09_lecture", "week09_di_lecture"}, 10: {"week10_lecture"}, 11: {"week11_lecture"}}
    for week, docs in lecture.items():
        concepts = [c for c in CONTENT.values() if c["week"] == week and not c.get("_upload")]
        assert concepts, week
        for c in concepts:
            for q in c["questions"]:
                if q["type"] == "explain":
                    continue
                assert q.get("sources") and all(s["doc"] in docs for s in q["sources"]), q["id"]
