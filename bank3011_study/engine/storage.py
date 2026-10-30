"""Progress storage, one record per student (SID).

Uses an online Postgres database (e.g. Supabase) when DATABASE_URL is set, otherwise a local SQLite file
(progress.db). Every row carries the student's SID, so each person sees only their own progress.

Tables
  p_mastery      - per topic: BKT probability + counts
  p_attempts     - every answer: question, topic, type, difficulty, session, round, correct, time
  p_topic_state  - per topic: weak flag, level, streaks, missed type (kept between sessions)
  p_sessions     - each practice session: scope, start/finish, summary
  p_explains     - Explain it answers and their marks
  p_my_questions - questions the student wrote (week, topic, ideal answer, marking points)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .bkt import BKTParams
from .session import Answer, TopicState

LOCAL_USER = "local"          # progress from before sign-in existed (local file only)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _schema(id_col: str) -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS p_mastery (
            user_id TEXT NOT NULL, concept_id TEXT NOT NULL, p REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0, updated TEXT,
            PRIMARY KEY (user_id, concept_id))""",
        f"""CREATE TABLE IF NOT EXISTS p_attempts (
            id {id_col}, user_id TEXT NOT NULL, ts TEXT NOT NULL, concept_id TEXT NOT NULL,
            question_id TEXT NOT NULL, qtype TEXT NOT NULL, correct INTEGER NOT NULL,
            p_before REAL, p_after REAL, detail TEXT, difficulty INTEGER, session_id INTEGER, round_no INTEGER)""",
        "CREATE INDEX IF NOT EXISTS p_attempts_user ON p_attempts (user_id)",
        """CREATE TABLE IF NOT EXISTS p_topic_state (
            user_id TEXT NOT NULL, concept_id TEXT NOT NULL, weak INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1, fail_streak INTEGER NOT NULL DEFAULT 0,
            correct_streak INTEGER NOT NULL DEFAULT 0, last_seen TEXT, missed_type TEXT,
            PRIMARY KEY (user_id, concept_id))""",
        f"""CREATE TABLE IF NOT EXISTS p_sessions (
            id {id_col}, user_id TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
            scope TEXT NOT NULL, summary TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS p_explains (
            id {id_col}, user_id TEXT NOT NULL, ts TEXT NOT NULL, concept_id TEXT NOT NULL,
            question_id TEXT NOT NULL, answer TEXT NOT NULL, score INTEGER, feedback TEXT)""",
        """CREATE TABLE IF NOT EXISTS p_my_questions (
            user_id TEXT NOT NULL, qid TEXT NOT NULL, week INTEGER NOT NULL, topic_id TEXT,
            topic TEXT NOT NULL, prompt TEXT NOT NULL, key_points TEXT NOT NULL, model_answer TEXT,
            created TEXT NOT NULL, PRIMARY KEY (user_id, qid))""",
        "CREATE TABLE IF NOT EXISTS p_meta (k TEXT PRIMARY KEY, v TEXT)",
    ]


USER_TABLES = ("p_mastery", "p_attempts", "p_topic_state", "p_sessions", "p_explains", "p_my_questions")


class Database:
    """A thin wrapper that runs the same SQL on SQLite or Postgres. Write SQL with ? placeholders."""

    def __init__(self, target: str | Path = "progress.db"):
        target = str(target)
        self.kind = "pg" if target.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.target = target
        if self.kind == "pg":
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            # prepare_threshold=None: works through Supabase's connection pooler
            self.pool = ConnectionPool(target, min_size=1, max_size=5, open=True, timeout=20,
                                       kwargs={"row_factory": dict_row, "prepare_threshold": None,
                                               "autocommit": False})
        with self.conn() as c:
            for stmt in _schema("BIGSERIAL PRIMARY KEY" if self.kind == "pg" else "INTEGER PRIMARY KEY AUTOINCREMENT"):
                c.run(stmt)
        if self.kind == "sqlite":
            self._migrate_legacy()

    @contextmanager
    def conn(self):
        if self.kind == "pg":
            with self.pool.connection() as raw:      # commits on success, rolls back on error
                yield _Cx(raw, pg=True)
        else:
            raw = sqlite3.connect(self.target)
            raw.row_factory = sqlite3.Row
            try:
                yield _Cx(raw, pg=False)
                raw.commit()
            finally:
                raw.close()

    def close(self) -> None:
        if self.kind == "pg":
            self.pool.close()

    # progress files from before sign-in (v1-v4) used unprefixed tables with no user: keep them as "local"
    def _migrate_legacy(self) -> None:
        with self.conn() as c:
            if c.one("SELECT v FROM p_meta WHERE k='legacy_migrated'"):
                return
            have = {r["name"] for r in c.all("SELECT name FROM sqlite_master WHERE type='table'")}
            if "attempts" in have:
                cols = {r["name"] for r in c.all("PRAGMA table_info(attempts)")}
                d = "difficulty" if "difficulty" in cols else "NULL"
                s = "session_id" if "session_id" in cols else "NULL"
                r = "round" if "round" in cols else "NULL"
                c.run(f"INSERT INTO p_attempts (user_id, ts, concept_id, question_id, qtype, correct, p_before, "
                      f"p_after, detail, difficulty, session_id, round_no) SELECT ?, ts, concept_id, question_id, "
                      f"qtype, correct, p_before, p_after, detail, {d}, {s}, {r} FROM attempts", (LOCAL_USER,))
            if "mastery" in have:
                c.run("INSERT INTO p_mastery SELECT ?, concept_id, p, attempts, correct, updated FROM mastery",
                      (LOCAL_USER,))
            if "topic_state" in have:
                cols = {r["name"] for r in c.all("PRAGMA table_info(topic_state)")}
                m = "missed_type" if "missed_type" in cols else "NULL"
                c.run(f"INSERT INTO p_topic_state SELECT ?, concept_id, weak, level, fail_streak, correct_streak, "
                      f"last_seen, {m} FROM topic_state", (LOCAL_USER,))
            if "sessions" in have:
                c.run("INSERT INTO p_sessions (id, user_id, started, finished, scope, summary) "
                      "SELECT id, ?, started, finished, scope, summary FROM sessions", (LOCAL_USER,))
            if "explains" in have:
                c.run("INSERT INTO p_explains (user_id, ts, concept_id, question_id, answer, score, feedback) "
                      "SELECT ?, ts, concept_id, question_id, answer, score, feedback FROM explains", (LOCAL_USER,))
            c.run("INSERT INTO p_meta (k, v) VALUES ('legacy_migrated', ?)", (_now(),))


class _Cx:
    """One connection: run / one / all / insert_id, with ? placeholders and dict rows on both databases."""

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.pg else sql

    def run(self, sql: str, params: tuple = ()) -> None:
        self.raw.execute(self._sql(sql), params)

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.raw.execute(self._sql(sql), params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        r = self.raw.execute(self._sql(sql), params).fetchone()
        return dict(r) if r else None

    def insert_id(self, sql: str, params: tuple = ()) -> int:
        return int(self.raw.execute(self._sql(sql + " RETURNING id"), params).fetchone()["id"])


class Progress:
    """One student's progress. `db` may be a Database or a path/URL (a Database is created for it)."""

    def __init__(self, db: Database | str | Path = "progress.db", user: str = LOCAL_USER):
        self.db = db if isinstance(db, Database) else Database(db)
        self.user = user

    def _conn(self):
        return self.db.conn()

    # ------------------------------------------------------------ mastery
    def mastery(self) -> dict[str, float]:
        with self._conn() as c:
            return {r["concept_id"]: r["p"] for r in
                    c.all("SELECT concept_id, p FROM p_mastery WHERE user_id=?", (self.user,))}

    def record_attempt(self, concept_id: str, question_id: str, qtype: str,
                       correct: bool, p_before: float, p_after: float,
                       detail: dict | None = None, *, difficulty: int | None = None,
                       session_id: int | None = None, round_no: int | None = None) -> str:
        now = _now()
        with self._conn() as c:
            c.run("INSERT INTO p_attempts (user_id, ts, concept_id, question_id, qtype, correct, p_before, p_after, "
                  "detail, difficulty, session_id, round_no) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (self.user, now, concept_id, question_id, qtype, int(correct), p_before, p_after,
                   json.dumps(detail or {}), difficulty, session_id, round_no))
            c.run("INSERT INTO p_mastery (user_id, concept_id, p, attempts, correct, updated) VALUES (?,?,?,1,?,?) "
                  "ON CONFLICT (user_id, concept_id) DO UPDATE SET p=excluded.p, "
                  "attempts=p_mastery.attempts+1, correct=p_mastery.correct+excluded.correct, updated=excluded.updated",
                  (self.user, concept_id, p_after, int(correct), now))
        return now

    def recent_question_ids(self, n: int = 10) -> list[str]:
        with self._conn() as c:
            rows = c.all("SELECT question_id FROM p_attempts WHERE user_id=? ORDER BY id DESC LIMIT ?", (self.user, n))
        return [r["question_id"] for r in rows][::-1]

    def attempts(self, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            return c.all("SELECT * FROM p_attempts WHERE user_id=? ORDER BY id DESC LIMIT ?", (self.user, limit))

    # ----------------------------------------------------------- explains
    def record_explain(self, concept_id: str, question_id: str, answer: str,
                       score: int | None, feedback: dict) -> None:
        with self._conn() as c:
            c.run("INSERT INTO p_explains (user_id, ts, concept_id, question_id, answer, score, feedback) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (self.user, _now(), concept_id, question_id, answer, score, json.dumps(feedback)))

    # ------------------------------------------------- your own questions
    def my_questions(self) -> list[dict]:
        with self._conn() as c:
            rows = c.all("SELECT * FROM p_my_questions WHERE user_id=? ORDER BY week, created", (self.user,))
        for r in rows:
            r["key_points"] = json.loads(r["key_points"])
        return rows

    def add_my_question(self, *, week: int, topic: str, topic_id: str | None, prompt: str,
                        key_points: list[str], model_answer: str) -> str:
        with self._conn() as c:
            used = {r["qid"] for r in c.all("SELECT qid FROM p_my_questions WHERE user_id=?", (self.user,))}
            n = 1
            while f"my_{n}" in used:
                n += 1
            qid = f"my_{n}"
            c.run("INSERT INTO p_my_questions (user_id, qid, week, topic_id, topic, prompt, key_points, model_answer, "
                  "created) VALUES (?,?,?,?,?,?,?,?,?)",
                  (self.user, qid, int(week), topic_id, topic, prompt, json.dumps(key_points), model_answer, _now()))
        return qid

    def remove_my_question(self, qid: str) -> None:
        with self._conn() as c:
            c.run("DELETE FROM p_my_questions WHERE user_id=? AND qid=?", (self.user, qid))

    # ------------------------------------------------------ topic state
    def topic_states(self) -> dict[str, TopicState]:
        with self._conn() as c:
            rows = c.all("SELECT * FROM p_topic_state WHERE user_id=?", (self.user,))
        return {r["concept_id"]: TopicState(bool(r["weak"]), r["level"], r["fail_streak"],
                                            r["correct_streak"], r["last_seen"], r["missed_type"]) for r in rows}

    def save_topic_state(self, concept_id: str, s: TopicState) -> None:
        with self._conn() as c:
            c.run("INSERT INTO p_topic_state (user_id, concept_id, weak, level, fail_streak, correct_streak, last_seen, "
                  "missed_type) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (user_id, concept_id) DO UPDATE SET "
                  "weak=excluded.weak, level=excluded.level, fail_streak=excluded.fail_streak, "
                  "correct_streak=excluded.correct_streak, last_seen=excluded.last_seen, missed_type=excluded.missed_type",
                  (self.user, concept_id, int(s.weak), s.level, s.fail_streak, s.correct_streak, s.last_seen,
                   s.missed_type))

    def question_history(self) -> dict[str, str]:
        """question id -> when it was last answered (any session)."""
        with self._conn() as c:
            return {r["question_id"]: r["ts"] for r in
                    c.all("SELECT question_id, MAX(ts) AS ts FROM p_attempts WHERE user_id=? GROUP BY question_id",
                          (self.user,))}

    # --------------------------------------------------------- sessions
    def start_session(self, scope: str) -> int:
        with self._conn() as c:
            return c.insert_id("INSERT INTO p_sessions (user_id, started, scope) VALUES (?,?,?)",
                               (self.user, _now(), scope))

    def finish_session(self, session_id: int, summary: dict) -> None:
        with self._conn() as c:
            c.run("UPDATE p_sessions SET finished=?, summary=? WHERE id=? AND user_id=?",
                  (_now(), json.dumps(summary), session_id, self.user))

    def session_answers(self, session_id: int) -> list[Answer]:
        with self._conn() as c:
            rows = c.all("SELECT * FROM p_attempts WHERE user_id=? AND session_id=? ORDER BY id",
                         (self.user, session_id))
        return [Answer(r["question_id"], r["concept_id"], r["difficulty"] or 1, bool(r["correct"]),
                       r["round_no"] or 1, r["ts"], r["qtype"]) for r in rows]

    def last_session(self) -> dict | None:
        with self._conn() as c:
            return c.one("SELECT * FROM p_sessions WHERE user_id=? AND finished IS NOT NULL ORDER BY id DESC LIMIT 1",
                         (self.user,))

    # ------------------------------------------------------------- admin
    def is_empty(self) -> bool:
        with self._conn() as c:
            return not c.one("SELECT 1 AS x FROM p_attempts WHERE user_id=? LIMIT 1", (self.user,)) and \
                not c.one("SELECT 1 AS x FROM p_my_questions WHERE user_id=? LIMIT 1", (self.user,))

    def claim_local(self) -> bool:
        """On a local file: give progress saved before sign-in existed to this student, if they have none yet."""
        if self.db.kind != "sqlite" or self.user == LOCAL_USER or not self.is_empty():
            return False
        with self._conn() as c:
            if not c.one("SELECT 1 AS x FROM p_attempts WHERE user_id=? LIMIT 1", (LOCAL_USER,)):
                return False
            for t in USER_TABLES:
                c.run(f"UPDATE {t} SET user_id=? WHERE user_id=?", (self.user, LOCAL_USER))
        return True

    def reset(self) -> None:
        """Delete this student's practice progress (their own questions are kept)."""
        with self._conn() as c:
            for t in ("p_mastery", "p_attempts", "p_topic_state", "p_sessions", "p_explains"):
                c.run(f"DELETE FROM {t} WHERE user_id=?", (self.user,))


def default_prior() -> float:
    return BKTParams().prior
