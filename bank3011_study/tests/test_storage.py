"""Progress storage: per-student records on SQLite, and on Postgres when TEST_DATABASE_URL is set."""
import os
import sqlite3
import uuid

import pytest

from engine.session import TopicState, update_topic
from engine.storage import LOCAL_USER, Database, Progress

PG_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "pg"])
def db(request, tmp_path):
    if request.param == "sqlite":
        yield Database(tmp_path / "p.db")
        return
    if not PG_URL:
        pytest.skip("set TEST_DATABASE_URL to test against Postgres")
    import psycopg
    schema = "t_" + uuid.uuid4().hex[:8]                 # a fresh schema per test
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {schema}")
    d = Database(f"{PG_URL}?options=-csearch_path%3D{schema}")
    yield d
    d.close()
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {schema} CASCADE")


def test_topic_state_and_sessions_round_trip(db):
    p = Progress(db, user="abc1234")
    sid = p.start_session("week:7")
    ts = p.record_attempt("ltv", "ltv_q2", "mcq", False, 0.1, 0.05, difficulty=2, session_id=sid, round_no=2)
    p.save_topic_state("ltv", update_topic(TopicState(), 2, False, ts, qtype="cloze"))
    p.record_attempt("ltv", "ltv_q3", "mcq", True, 0.05, 0.3, difficulty=2, session_id=sid, round_no=2)
    p.finish_session(sid, {"score": [1, 2]})

    p2 = Progress(db, user="abc1234")                    # a new visit: weak topics persist
    s = p2.topic_states()["ltv"]
    assert s.weak and s.level == 2 and s.fail_streak == 1 and s.missed_type == "cloze"
    answers = p2.session_answers(sid)
    assert [(a.question_id, a.correct, a.round) for a in answers] == [("ltv_q2", False, 2), ("ltv_q3", True, 2)]
    assert set(p2.question_history()) == {"ltv_q2", "ltv_q3"}
    assert p2.last_session()["scope"] == "week:7"
    assert p2.mastery() == {"ltv": 0.3}
    assert len(p2.attempts()) == 2


def test_each_student_sees_only_their_own_progress(db):
    a, b = Progress(db, user="abc1234"), Progress(db, user="xyz9876")
    a.record_attempt("ltv", "q1", "mcq", True, 0.1, 0.4)
    a.save_topic_state("ltv", TopicState(weak=True))
    a.add_my_question(week=9, topic="Liquidity index", topic_id="liquidity_index", prompt="Explain liquidity index.",
                      key_points=["p1", "p2"], model_answer="ideal")
    assert b.mastery() == {} and b.topic_states() == {} and b.attempts() == [] and b.my_questions() == []
    sb = b.start_session("all")
    assert b.session_answers(sb) == [] and b.last_session() is None
    b.reset()                                            # resetting b leaves a alone
    assert a.mastery() == {"ltv": 0.4} and a.topic_states()["ltv"].weak


def test_my_questions_add_list_remove(db):
    p = Progress(db, user="abc1234")
    q1 = p.add_my_question(week=10, topic="Basel III", topic_id=None, prompt="Explain Basel III.",
                           key_points=["CET1", "Buffers"], model_answer="ideal")
    q2 = p.add_my_question(week=9, topic="Bank runs", topic_id="bank_runs", prompt="Explain bank runs.",
                           key_points=["First come, first served"], model_answer="ideal")
    assert (q1, q2) == ("my_1", "my_2")
    mine = p.my_questions()
    assert [m["week"] for m in mine] == [9, 10] and mine[1]["key_points"] == ["CET1", "Buffers"]
    p.reset()                                            # reset keeps your own questions
    assert len(p.my_questions()) == 2
    p.remove_my_question("my_1")
    assert [m["qid"] for m in p.my_questions()] == ["my_2"]
    assert p.add_my_question(week=9, topic="x", topic_id=None, prompt="p", key_points=["k"], model_answer="m") == "my_1"


def test_old_progress_file_moves_to_the_first_student_who_signs_in(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, concept_id TEXT "
                "NOT NULL, question_id TEXT NOT NULL, qtype TEXT NOT NULL, correct INTEGER NOT NULL, p_before REAL, "
                "p_after REAL, detail TEXT)")
    con.execute("INSERT INTO attempts (ts, concept_id, question_id, qtype, correct) VALUES ('t','ltv','q','mcq',1)")
    con.execute("CREATE TABLE topic_state (concept_id TEXT PRIMARY KEY, weak INTEGER NOT NULL DEFAULT 0, level INTEGER "
                "NOT NULL DEFAULT 1, fail_streak INTEGER NOT NULL DEFAULT 0, correct_streak INTEGER NOT NULL DEFAULT 0, "
                "last_seen TEXT)")
    con.execute("INSERT INTO topic_state VALUES ('ltv', 1, 2, 1, 0, 't')")
    con.commit(); con.close()

    d = Database(db)
    assert Progress(d, user=LOCAL_USER).question_history() == {"q": "t"}
    me = Progress(d, user="abc1234")
    assert me.claim_local() is True
    assert me.question_history() == {"q": "t"} and me.topic_states()["ltv"].level == 2
    assert Progress(d, user="xyz9876").claim_local() is False      # only claimed once
    Database(db)                                                   # reopening doesn't copy the old rows again
    assert len(me.attempts()) == 1
