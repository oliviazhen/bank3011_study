"""Uploading question sets: week routing, normalising, validating, saving and merging."""
import copy
import random
import shutil
from pathlib import Path

import pytest

from engine.content import load_content, load_course, load_sources, validate
from engine.importer import (NEW, TEMPLATE, default_mapping, file_topics, list_uploads, prepare_upload,
                             save_upload)
from engine.session import ROUNDS, build_round

ROOT = Path(__file__).resolve().parents[1]
SOURCES = load_sources(ROOT / "assets" / "sources")


@pytest.fixture
def content_dir(tmp_path):
    d = tmp_path / "content"
    d.mkdir()
    for f in (ROOT / "content").glob("*.json"):
        shutil.copy(f, d / f.name)
    return d


def test_file_topics_and_default_mapping_respect_the_chosen_week(content_dir):
    concepts = load_content(content_dir)
    topics = file_topics(TEMPLATE)
    assert [(t["ref"], t["count"]) for t in topics] == [("RAROC", 3), ("ltv", 1),       # RAROC + raroc grouped
                                                        ("Credit spreads and implied PD", 1), ("Securitisation", 1)]
    m5 = default_mapping(topics, concepts, 5)
    assert m5["RAROC"] == "raroc" and m5["ltv"] == "ltv" and m5["Securitisation"] == NEW
    m3 = default_mapping(topics, concepts, 3)
    assert set(m3.values()) == {NEW}                         # nothing in week 3 yet: all new topics there


def test_week5_upload_joins_existing_topics(content_dir):
    concepts = load_content(content_dir)
    res = prepare_upload(copy.deepcopy(TEMPLATE), concepts, SOURCES, week=5, stem="template")
    assert res.rejected == []
    assert res.count == len(TEMPLATE["questions"])
    assert set(res.by_topic) == {"raroc", "ltv", "implied_pd_spread", "securitisation"}
    assert res.new_topics["securitisation"]["week"] == 5
    mcq = res.by_topic["raroc"][0]
    assert mcq["answer"] == 0                                 # "A higher fee" -> index 0
    define = next(q for q in res.by_topic["raroc"] if q["type"] == "definition")
    assert define["key_points"] and define["model_answer"]    # keyPoints / modelAnswer aliases


def test_week3_upload_creates_its_own_topics(content_dir):
    concepts = load_content(content_dir)
    res = prepare_upload(copy.deepcopy(TEMPLATE), concepts, SOURCES, week=3)
    assert res.rejected == []
    assert all(t["week"] == 3 for t in res.new_topics.values())
    assert set(res.by_topic) == set(res.new_topics)           # nothing went into week 5 topics
    raroc3 = next(t for t in res.new_topics.values() if t["name"] in ("RAROC", "raroc"))
    assert raroc3["id"] == "raroc_w3"                          # distinct from week 5's "raroc"
    assert len(res.by_topic["raroc_w3"]) == 3                  # "RAROC" and "raroc" routed to the same topic
    assert res.new_topics["ltv_w3"]["name"] == "Loan-to-value (LTV) and the security buffer"   # not just "ltv"


def test_manual_mapping_overrides_the_week(content_dir):
    concepts = load_content(content_dir)
    mapping = default_mapping(file_topics(TEMPLATE), concepts, 3)
    mapping["RAROC"] = mapping["raroc"] = "raroc"              # user: add these to week 5's RAROC instead
    res = prepare_upload(copy.deepcopy(TEMPLATE), concepts, SOURCES, week=3, mapping=mapping)
    assert len(res.by_topic["raroc"]) == 3 and "raroc_w3" not in res.new_topics


def test_plain_list_letters_and_defaults(content_dir):
    concepts = load_content(content_dir)
    data = [{"topic": "LTV", "question": "Which ratio compares the loan to the property value?",
             "choices": ["LTV", "RAROC", "CMR", "EAD"], "correct": "a"},
            {"topic": "ltv", "prompt": "LTV = loan ÷ ___", "blanks": "property value"}]
    res = prepare_upload(data, concepts, SOURCES, week=5)
    assert res.rejected == []
    q1, q2 = res.by_topic["ltv"]
    assert (q1["type"], q1["answer"], q1["difficulty"]) == ("mcq", 0, 2)
    assert (q2["type"], q2["blanks"], q2["difficulty"]) == ("cloze", [["property value"]], 1)
    assert any("no difficulty" in w for w in res.warnings)


def test_invalid_questions_are_rejected_with_reasons_others_kept(content_dir):
    concepts = load_content(content_dir)
    data = {"questions": [
        {"topic": "raroc", "type": "cloze", "difficulty": 1, "prompt": "Two gaps ___ and ___.", "blanks": [["x"]]},
        {"topic": "raroc", "type": "relationship", "difficulty": 1, "subtype": "directional", "prompt": "p",
         "options": ["Increases", "Decreases"], "answer": 0, "concepts": ["raroc", "ltv"],
         "relationship": {"from": "A", "to": "C", "steps": 2}},
        {"topic": "raroc", "type": "mcq", "difficulty": 2, "prompt": "ok?", "options": ["yes", "no"], "answer": 0},
        {"type": "mcq", "difficulty": 1, "prompt": "no topic", "options": ["a", "b"], "answer": 0},
        "not an object",
    ]}
    res = prepare_upload(data, concepts, SOURCES, week=5)
    assert res.count == 1
    reasons = " | ".join(r for _, r in res.rejected)
    assert len(res.rejected) == 4
    assert "gaps" in reasons and "one step" in reasons and "no topic" in reasons


def test_duplicate_ids_are_renamed(content_dir):
    concepts = load_content(content_dir)
    data = [{"id": "raroc_q4", "topic": "raroc", "type": "mcq", "difficulty": 2, "prompt": "p",
             "options": ["a", "b"], "answer": 1}]
    res = prepare_upload(data, concepts, SOURCES, week=5)
    assert res.by_topic["raroc"][0]["id"] == "raroc_q4_2"
    assert any("renamed" in w for w in res.warnings)


def test_saved_week3_set_appears_in_week3_and_in_sessions(content_dir):
    before = load_content(content_dir)
    res = prepare_upload(copy.deepcopy(TEMPLATE), before, SOURCES, week=3)
    save_upload(res, content_dir, "liquidity.json", week=3, set_name="My liquidity questions")

    after = load_content(content_dir)
    assert validate(after, SOURCES) == []
    assert len(after["raroc"]["questions"]) == len(before["raroc"]["questions"])   # week 5 untouched
    course = load_course(ROOT / "course.json", after)
    week3 = next(w for w in course if w["week"] == 3)
    assert set(week3["concepts"]) == set(res.new_topics)       # shows up in the Week 3 tab
    [up] = list_uploads(content_dir)
    assert (up["name"], up["week"], up["questions"]) == ("My liquidity questions", 3, 6)
    q = after["raroc_w3"]["questions"][0]
    assert q["_set"] == "My liquidity questions"

    bank = [q for c in after.values() for q in c["questions"]
            if q["type"] in ("mcq", "relationship", "equation", "cloze", "definition")]
    plan = build_round(ROUNDS[0], bank, {}, scope=set(week3["concepts"]), asked=set(), covered=set(), history={},
                       rng=random.Random(0))
    assert plan.questions and all(q["_set"] == "My liquidity questions" for q in plan.questions)


def test_week5_set_merges_into_existing_topics(content_dir):
    before = load_content(content_dir)
    n = len(before["raroc"]["questions"])
    save_upload(prepare_upload(copy.deepcopy(TEMPLATE), before, SOURCES, week=5), content_dir, "x.json", week=5)
    after = load_content(content_dir)
    assert len(after["raroc"]["questions"]) == n + 3 and after["raroc"]["name"] == "RAROC"


def test_bad_files(content_dir):
    concepts = load_content(content_dir)
    with pytest.raises(ValueError):
        prepare_upload({"nothing": 1}, concepts, SOURCES, week=5)
    with pytest.raises(ValueError):
        prepare_upload("text", concepts, SOURCES, week=5)
