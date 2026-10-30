"""Importing question sets that students upload as JSON.

Accepted shapes
    {"concepts": [{"id": ..., "questions": [...]}, ...]}     same format as content/*.json
    {"questions": [...], "week": 7}                         questions tagged with "topic"
    [ {...}, {...} ]                                        a plain list of questions

Each question is normalised (friendly field names, answers given as option text, topics given
by name, sensible defaults), then checked with the same validator as the built-in bank. Valid
questions are saved to content/uploads/<name>.json, which load_content merges into the bank.
Invalid ones are reported with the reason and left out.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .content import CHOICE_TYPES, SESSION_TYPES, UPLOADS_SUBDIR, validate

ALIASES = {"keyPoints": "key_points", "keypoints": "key_points", "modelAnswer": "model_answer",
           "optionSources": "option_sources", "question": "prompt", "text": "prompt", "choices": "options",
           "correct": "answer", "correct_answer": "answer", "correctAnswer": "answer", "level": "difficulty",
           "explain": "explanation", "accepted": "blanks", "answers": "blanks"}
DEFAULT_DIFFICULTY = {"definition": 1, "cloze": 1}   # everything else defaults to 2


@dataclass
class ImportResult:
    by_topic: dict[str, list[dict]] = field(default_factory=dict)   # topic id -> accepted questions
    new_topics: dict[str, dict] = field(default_factory=dict)       # topic id -> new concept header
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (question label, reason)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self.by_topic.values())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:40] or "topic"


def _raw_questions(data) -> tuple[list[tuple[dict, dict | None]], int | None]:
    """[(question, concept header or None)], file-level week."""
    if isinstance(data, list):
        return [(q, None) for q in data], None
    if not isinstance(data, dict):
        raise ValueError("The file must contain a JSON object or a list of questions.")
    week = data.get("week")
    out = []
    for c in data.get("concepts", []) or []:
        header = {k: v for k, v in c.items() if k != "questions"}
        out += [(q, header) for q in c.get("questions", []) or []]
    out += [(q, None) for q in data.get("questions", []) or []]
    if not out:
        raise ValueError("No questions found. Use {\"questions\": [...]}, {\"concepts\": [...]} or a list.")
    return out, week


def _ref_of(raw: dict, header: dict | None) -> str | None:
    """The topic a question says it belongs to (concept header, or 'topic' / 'concept' / first of 'concepts')."""
    if header and (header.get("id") or header.get("name")):
        return str(header.get("name") or header.get("id")).strip()
    if not isinstance(raw, dict):
        return None
    ref = raw.get("topic") or raw.get("concept") or (raw.get("concepts") or [None])[0]
    return str(ref).strip() if ref else None


def _match(ref: str, concepts: dict, week: int | None = None) -> str | None:
    """Existing topic matching `ref` by id or name (case-insensitive), optionally only in `week`."""
    low = ref.lower()
    for cid, c in concepts.items():
        if week is not None and int(c.get("week", 0)) != int(week):
            continue
        if cid.lower() == low or slug(cid) == slug(ref) or c.get("name", "").strip().lower() == low:
            return cid
    return None


def file_topics(data) -> list[dict]:
    """Topics named in an uploaded file, in order: [{"ref", "count"}]. ref None = questions with no topic."""
    raw_list, _ = _raw_questions(data)
    order: dict = {}          # slug -> [first spelling, count]; "RAROC" and "raroc" are the same topic
    for raw, header in raw_list:
        ref = _ref_of(raw, header)
        key = slug(ref) if ref else None
        if key not in order:
            order[key] = [ref, 0]
        order[key][1] += 1
    return [{"ref": r, "count": n} for r, n in order.values()]


def file_week(data) -> int | None:
    """The week a file says it's for, if any (used only as a suggestion)."""
    try:
        return int(data.get("week")) if isinstance(data, dict) and data.get("week") else None
    except (TypeError, ValueError):
        return None


NEW = "__new__"


def default_mapping(topics: list[dict], concepts: dict, week: int) -> dict[str, str]:
    """Suggested destination for each topic: an existing topic in the chosen week with the same
    name/id, otherwise a new topic in that week."""
    return {t["ref"]: (_match(t["ref"], concepts, week) or NEW) for t in topics if t["ref"]}


def _normalise(raw: dict, warn: list[str], label: str) -> dict:
    q = {ALIASES.get(k, k): copy.deepcopy(v) for k, v in raw.items()}
    for k in ("topic", "_upload", "concept"):
        q.pop(k, None)

    # type
    if not q.get("type"):
        if q.get("options"):
            q["type"] = "mcq"
        elif "___" in str(q.get("prompt", "")):
            q["type"] = "cloze"
        elif q.get("key_points"):
            q["type"] = "definition"
    q["type"] = str(q.get("type", "")).strip().lower()
    q["type"] = {"multiple choice": "mcq", "multiple_choice": "mcq", "fill in the gap": "cloze", "fill_gap": "cloze",
                 "gap": "cloze", "fill": "cloze", "definitions": "definition"}.get(q["type"], q["type"])
    if q["type"] == "definition" and not q.get("subtype"):
        q["subtype"] = "define" if q.get("key_points") else "name"

    # answers given as option text or a letter -> index
    if q["type"] in CHOICE_TYPES and isinstance(q.get("answer"), str) and q.get("options"):
        a = q["answer"].strip()
        opts = [str(o).strip().lower() for o in q["options"]]
        if a.lower() in opts:
            q["answer"] = opts.index(a.lower())
        elif len(a) == 1 and a.upper() in "ABCDEFGH" and "ABCDEFGH".index(a.upper()) < len(opts):
            q["answer"] = "ABCDEFGH".index(a.upper())

    # blanks: allow "x", ["x", "y"] (one gap with synonyms, or one answer per gap)
    if q["type"] == "cloze" or (q["type"] == "definition" and q.get("subtype") == "name"):
        b = q.get("blanks")
        gaps = str(q.get("prompt", "")).count("___") if q["type"] == "cloze" else 1
        if isinstance(b, str):
            b = [[b]]
        elif isinstance(b, list) and b and all(isinstance(x, str) for x in b):
            b = [[x] for x in b] if gaps > 1 and len(b) == gaps else [b]
        if b is not None:
            q["blanks"] = [[str(x) for x in grp] for grp in b]

    # difficulty
    if q.get("difficulty") is None:
        q["difficulty"] = DEFAULT_DIFFICULTY.get(q["type"], 2)
        warn.append(f"{label}: no difficulty given, set to {q['difficulty']}.")
    else:
        try:
            q["difficulty"] = int(q["difficulty"])
        except (TypeError, ValueError):
            pass
    if q["type"] == "relationship" and isinstance(q.get("relationship"), dict):
        q["relationship"].setdefault("steps", 1)
    q.setdefault("explanation", "")
    return q


def prepare_upload(data, concepts: dict[str, dict], sources: dict | None = None, *, week: int,
                   mapping: dict[str, str] | None = None, stem: str = "upload") -> ImportResult:
    """Parse, normalise and validate an uploaded question set for `week`. Nothing is saved here.

    mapping: topic ref -> existing topic id, or NEW to create the topic in `week`.
             Defaults to default_mapping (same-named topic in that week, else new).
    """
    res = ImportResult()
    raw_list, _ = _raw_questions(data)
    week = int(week)
    mapping = mapping or default_mapping(file_topics(data), concepts, week)
    mapping = {slug(k): v for k, v in mapping.items()}            # match refs however they're capitalised
    used_ids = {q["id"] for c in concepts.values() for q in c["questions"]}
    stem = slug(stem)
    ref_to_topic: dict[str, str] = {}

    def topic_for(ref: str, header: dict | None) -> str:
        key = slug(ref)
        if key in ref_to_topic:
            return ref_to_topic[key]
        target = mapping.get(key, NEW)
        if target != NEW and target in concepts:
            ref_to_topic[key] = target
            return target
        tid = slug((header or {}).get("id") or ref)
        if tid in concepts or tid in res.new_topics:
            tid = f"{tid}_w{week}"
        base, n = tid, 2
        while tid in concepts or tid in res.new_topics:
            tid, n = f"{base}_{n}", n + 1
        same = _match(ref, concepts)            # same topic in another week: borrow its proper name
        nice = (header or {}).get("name") or (concepts[same]["name"] if same else ref)
        res.new_topics[tid] = {"id": tid, "name": nice, "week": week,
                               "definition": (header or {}).get("definition") or "Added from your question set.",
                               "prerequisites": [], "cards": [], "misconceptions": []}
        ref_to_topic[key] = tid
        return tid

    for i, (raw, header) in enumerate(raw_list, 1):
        label = f"#{i}" + (f" ({raw.get('id')})" if isinstance(raw, dict) and raw.get("id") else "")
        if not isinstance(raw, dict):
            res.rejected.append((label, "not a JSON object"))
            continue
        ref = _ref_of(raw, header)
        if not ref:
            res.rejected.append((label, "no topic: add \"topic\" (a topic name or id)"))
            continue
        topic = topic_for(ref, header)

        q = _normalise(raw, res.warnings, label)
        if q["type"] not in SESSION_TYPES:
            res.rejected.append((label, f"type must be one of {', '.join(SESSION_TYPES)}"))
            continue
        base = str(q.get("id") or f"{stem}_{i}")
        qid, n = base, 2
        while qid in used_ids:
            qid, n = f"{base}_{n}", n + 1
        if qid != base and q.get("id"):
            res.warnings.append(f"{label}: id already in the bank, renamed to {qid}.")
        q["id"] = qid
        # linked topics: map file refs through the same routing; keep only ones that exist
        known = set(concepts) | set(res.new_topics)
        others = []
        for c in q.get("concepts", []):
            if slug(c) == slug(ref):
                continue
            c = ref_to_topic.get(slug(c), str(c))
            if c != topic and c not in others:
                others.append(c)
        if [c for c in others if c not in known]:
            res.warnings.append(f"{label}: unknown linked topics dropped: {[c for c in others if c not in known]}.")
        q["concepts"] = [topic, *[c for c in others if c in known]]
        if sources is not None and q.get("sources"):
            good = [x for x in q["sources"] if isinstance(x, dict) and x.get("doc") in sources]
            if len(good) != len(q["sources"]):
                res.warnings.append(f"{label}: slide references to unknown documents dropped.")
            q["sources"] = good

        # validate this question on its own, against the real topics
        scratch = {cid: {**{k: v for k, v in c.items() if k != "questions"}, "questions": []}
                   for cid, c in {**concepts, **res.new_topics}.items()}
        scratch[topic]["questions"] = [{**copy.deepcopy(q), "concept": topic}]
        # only this question is in `scratch`, so every problem reported is about it (or its new topic)
        problems = [p.split(": ", 1)[-1] for p in validate(scratch, sources)]
        if problems:
            res.rejected.append((label, "; ".join(problems)))
            continue
        used_ids.add(qid)
        res.by_topic.setdefault(topic, []).append(q)

    # new topics with no accepted questions aren't worth creating
    res.new_topics = {k: v for k, v in res.new_topics.items() if k in res.by_topic}
    return res


def save_upload(res: ImportResult, content_dir: str | Path, filename: str, *, week: int,
                set_name: str | None = None) -> Path:
    """Write accepted questions to content/uploads/<name>.json and return its path."""
    folder = Path(content_dir) / UPLOADS_SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}_{slug(Path(filename).stem)}.json"
    concepts_out = []
    for topic, qs in res.by_topic.items():
        header = res.new_topics.get(topic, {"id": topic})
        clean = [{k: v for k, v in q.items() if not k.startswith("_") and k != "concept"} for q in qs]
        concepts_out.append({**header, "questions": clean})
    path.write_text(json.dumps({"set_name": set_name or Path(filename).stem, "week": int(week),
                                "source_file": filename, "uploaded": stamp, "concepts": concepts_out},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_uploads(content_dir: str | Path) -> list[dict]:
    out = []
    for p in sorted((Path(content_dir) / UPLOADS_SUBDIR).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            n = sum(len(c.get("questions", [])) for c in d.get("concepts", []))
            out.append({"path": p, "file": p.name, "name": d.get("set_name") or d.get("source_file", p.name),
                        "week": d.get("week"), "questions": n, "uploaded": d.get("uploaded", ""),
                        "ids": [q.get("id") for c in d.get("concepts", []) for q in c.get("questions", [])]})
        except (OSError, json.JSONDecodeError):
            out.append({"path": p, "file": p.name, "name": p.name, "week": None, "questions": 0,
                        "uploaded": "unreadable", "ids": []})
    return out


TEMPLATE = {
    "questions": [
        {"topic": "RAROC", "type": "mcq", "difficulty": 2,
         "prompt": "Which change raises a loan's RAROC?",
         "options": ["A higher fee", "A longer duration", "A larger adverse-scenario ΔR", "A higher funding cost"],
         "answer": "A higher fee",
         "feedback": [None, "Longer duration raises capital at risk.", "A larger ΔR raises capital at risk.",
                      "Higher funding cost lowers the all-in spread."],
         "explanation": "Fees are part of one-year income, the numerator of RAROC."},
        {"topic": "ltv", "type": "relationship", "subtype": "directional", "difficulty": 1,
         "prompt": "House prices fall while the loan is unchanged. What happens to the bank's LGD?",
         "options": ["Increases", "Decreases", "No change"], "answer": 0,
         "concepts": ["ltv", "lgd_seniority"], "relationship": {"from": "Prices ↓ (LTV ↑)", "to": "LGD ↑", "steps": 1},
         "explanation": "A thinner equity buffer means a forced sale may not cover the loan."},
        {"topic": "raroc", "type": "equation", "subtype": "proportionality", "difficulty": 1,
         "prompt": "The loan size L doubles and nothing else changes. What happens to capital at risk?",
         "equation": "\\Delta L = -D \\times L \\times \\frac{\\Delta R}{1 + R}", "changes": 1,
         "options": ["Doubles", "Halves", "No change"], "answer": "Doubles",
         "explanation": "Capital at risk is proportional to L."},
        {"topic": "Credit spreads and implied PD", "type": "cloze", "difficulty": 1,
         "prompt": "The credit spread is the yield on a risky bond minus the yield on a ___ bond of the same maturity.",
         "blanks": [["risk-free", "risk free", "government", "treasury"]],
         "explanation": "C = k − i."},
        {"topic": "raroc", "type": "definition", "subtype": "define", "difficulty": 1,
         "prompt": "Define capital at risk in RAROC.",
         "keyPoints": ["The potential loss in the loan's value", "Under an adverse credit scenario (e.g. 99th percentile)",
                       "Measured with duration: D × L × ΔR / (1 + R)"],
         "modelAnswer": "The potential fall in the loan's value under an adverse credit scenario, measured as D × L × ΔR/(1 + R)."},
        {"topic": "Securitisation", "type": "definition", "subtype": "name", "difficulty": 1,
         "prompt": "Name the concept: pooling loans and selling securities backed by their cash flows.",
         "blanks": ["securitisation", "securitization"],
         "explanation": "A new topic: uploading a question with an unknown topic creates it."},
    ],
}
