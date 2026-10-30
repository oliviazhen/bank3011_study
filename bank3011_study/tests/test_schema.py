"""The validator must catch malformed questions of each new type."""
import copy

from engine.content import validate

BASE = {"id": "c1", "name": "C1", "week": 7, "definition": "d", "prerequisites": [], "cards": [],
        "misconceptions": [], "_source": "t"}
OTHER = {**BASE, "id": "c2", "name": "C2"}


def problems_for(q):
    c1 = copy.deepcopy(BASE)
    c1["questions"] = [{"concept": "c1", "concepts": ["c1", *q.pop("_others", [])], **q}]
    return validate({"c1": c1, "c2": {**copy.deepcopy(OTHER), "questions": []}})


GOOD = {
    "relationship": {"id": "r", "type": "relationship", "subtype": "directional", "difficulty": 1, "prompt": "p",
                     "options": ["Increases", "Decreases", "No change"], "answer": 0, "explanation": "e",
                     "relationship": {"from": "X ↑", "to": "Y ↑", "steps": 1}, "_others": ["c2"]},
    "equation": {"id": "e", "type": "equation", "subtype": "proportionality", "difficulty": 1, "prompt": "p",
                 "equation": "y = x", "changes": 1, "options": ["a", "b"], "answer": 0, "explanation": "e"},
    "cloze": {"id": "z", "type": "cloze", "difficulty": 1, "prompt": "A ___ and a ___.",
              "blanks": [["x"], ["y", "z"]], "explanation": "e"},
    "define": {"id": "d", "type": "definition", "subtype": "define", "difficulty": 1, "prompt": "Define X.",
               "key_points": ["a", "b"], "model_answer": "m", "explanation": "e"},
    "name": {"id": "n", "type": "definition", "subtype": "name", "difficulty": 1, "prompt": "p",
             "blanks": [["X"]], "explanation": "e"},
}


def test_good_examples_pass():
    for q in GOOD.values():
        assert problems_for(copy.deepcopy(q)) == [], q["id"]


def bad(name, **changes):
    q = copy.deepcopy(GOOD[name])
    q.update(changes)
    return problems_for(q)


def test_multi_step_chain_cannot_be_round_1():
    assert bad("relationship", relationship={"from": "X", "to": "Z", "steps": 2})
    assert not bad("relationship", relationship={"from": "X", "to": "Z", "steps": 2}, difficulty=2)


def test_relationship_needs_two_concepts():
    assert bad("relationship", _others=[])


def test_round_1_equation_changes_one_variable():
    assert bad("equation", changes=2)
    assert bad("equation", subtype="rearrange")
    assert not bad("equation", changes=2, difficulty=3)


def test_cloze_gaps_must_match_blanks():
    assert bad("cloze", prompt="Only one ___ here.")
    assert bad("cloze", blanks=[["x"], []])


def test_definitions_need_their_fields():
    assert bad("define", key_points=["only one"])
    assert bad("define", model_answer="")
    assert bad("name", blanks=[["a"], ["b"]])


def test_unknown_subtype_and_concept():
    assert bad("relationship", subtype="sideways")
    assert bad("relationship", _others=["nope"])
