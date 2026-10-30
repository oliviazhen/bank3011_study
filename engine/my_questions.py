"""Questions students write in the app, and SID sign-in checks.

Questions are saved per student in the progress database (Progress.add_my_question); this module only
checks the form and works out the wording and topic.
"""
from __future__ import annotations

import re

from .importer import slug

SID_RE = re.compile(r"^[a-z]{3}\d{4}$")


def normalise_sid(text: str) -> str | None:
    """'ABC1234 ' -> 'abc1234'; anything not three letters and four numbers -> None."""
    sid = (text or "").strip().lower()
    return sid if SID_RE.match(sid) else None


def question_for(topic: str) -> str:
    """The question shown for a topic: 'Explain cell respiration.' (keeps acronyms such as LCR as typed)."""
    topic = topic.strip().rstrip(".")
    if len(topic) > 1 and topic[0].isupper() and not topic[1].isupper():
        topic = topic[0].lower() + topic[1:]
    return f"Explain {topic}."


def check_question(concepts: dict[str, dict], *, week: int | None, topic: str, ideal_answer: str,
                   points: list[str]) -> tuple[dict | None, list[str]]:
    """Check the four form fields. Returns (fields to save, []) or (None, reasons).

    A topic whose name matches an existing topic in the same week is linked to it (topic_id).
    """
    topic = (topic or "").strip()
    points = [p.strip() for p in points if p and p.strip()]
    errors = []
    if week is None:
        errors.append("Choose a week.")
    if not topic:
        errors.append("Type a topic.")
    if not (ideal_answer or "").strip():
        errors.append("Write the ideal answer.")
    if not points:
        errors.append("Add at least one marking point.")
    if errors:
        return None, errors
    match = [cid for cid, c in concepts.items()
             if int(c.get("week", 0)) == int(week) and slug(topic) in (slug(cid), slug(c.get("name", "")))]
    topic_id = match[0] if match else None
    return {"week": int(week), "topic": concepts[topic_id]["name"] if topic_id else topic, "topic_id": topic_id,
            "prompt": question_for(topic), "key_points": points, "model_answer": ideal_answer.strip()}, []
