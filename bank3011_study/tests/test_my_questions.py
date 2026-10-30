"""The Write your own question form checks, and SID sign-in."""
from engine.content import load_content
from engine.my_questions import check_question, normalise_sid, question_for

CONCEPTS = load_content("content")


def test_sid_must_be_three_letters_then_four_numbers():
    assert normalise_sid(" ABC1234 ") == "abc1234"
    for bad in ["", "ab1234", "abcd1234", "abc123", "1234abc", "abc 1234", "abc12345"]:
        assert normalise_sid(bad) is None, bad


def test_question_wording_keeps_acronyms():
    assert question_for("Cell respiration") == "Explain cell respiration."
    assert question_for("LCR") == "Explain LCR."


def test_topic_matching_an_existing_topic_in_that_week_is_linked():
    f, err = check_question(CONCEPTS, week=9, topic="liquidity INDEX", ideal_answer="ideal", points=["a", " ", "b"])
    assert err == [] and f["topic_id"] == "liquidity_index" and f["topic"] == "Liquidity index"
    assert f["key_points"] == ["a", "b"] and f["prompt"] == "Explain liquidity INDEX."
    f, _ = check_question(CONCEPTS, week=3, topic="Liquidity index", ideal_answer="ideal", points=["a"])
    assert f["topic_id"] is None                         # not in week 3: a new topic name


def test_missing_fields_are_reported():
    f, err = check_question(CONCEPTS, week=None, topic=" ", ideal_answer="", points=["", " "])
    assert f is None and len(err) == 4
