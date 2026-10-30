"""Loading, validating and marking study content.

Content lives in content/*.json. Each file holds {"concepts": [...]}; files are
merged, so you can keep one file per week (week_02.json, week_03.json ...).

Calculation questions can carry their own arithmetic check:
    "vars":  {"A": 100, "L": 90}
    steps:   {"ask": "k = L/A", "expr": "L/A", "answer": 0.9}
The validator evaluates every `expr` and flags any `answer` that doesn't match,
which catches arithmetic mistakes in generated or hand-typed questions.
"""
import ast
import json
import math
import operator
import re
from pathlib import Path

REQUIRED_CONCEPT_KEYS = {"id", "name", "week", "definition"}
QTYPES = {"mcq", "relationship", "equation", "cloze", "definition", "steps", "explain"}
SESSION_TYPES = ("mcq", "relationship", "equation", "cloze", "definition")   # types used in quiz sessions
CHOICE_TYPES = {"mcq", "relationship", "equation"}
SUBTYPES = {"relationship": {"directional", "causal", "comparison"},
            "equation": {"proportionality", "variables", "rearrange", "linking"},
            "definition": {"define", "name"}}


# ---------------------------------------------------------------- loading
UPLOADS_SUBDIR = "uploads"   # content/uploads/*.json: question sets added from the app


def load_content(content_dir: str | Path) -> dict[str, dict]:
    """Load content/*.json, then merge content/uploads/*.json on top.

    Uploaded files add questions to existing topics (matched by concept id) or bring new topics.
    """
    concepts: dict[str, dict] = {}
    main = sorted(Path(content_dir).glob("*.json"))
    uploads = sorted((Path(content_dir) / UPLOADS_SUBDIR).glob("*.json"))
    for path in [*main, *uploads]:
        data = json.loads(path.read_text(encoding="utf-8"))
        uploaded = path in uploads
        for c in data.get("concepts", []):
            for q in c.get("questions", []):
                q["concept"] = c["id"]          # primary topic, used by the session engine
                others = [x for x in q.get("concepts", []) if x != c["id"]]
                q["concepts"] = [c["id"], *others]
                if uploaded:
                    q["_upload"] = path.name
                    q["_set"] = data.get("set_name") or path.stem
            if uploaded and c["id"] in concepts:          # extra questions for an existing topic
                concepts[c["id"]]["questions"].extend(c.get("questions", []))
                continue
            c.setdefault("prerequisites", [])
            c.setdefault("questions", [])
            c.setdefault("cards", [])
            c.setdefault("misconceptions", [])
            c["_source"] = path.name
            if uploaded:
                c["_set"] = data.get("set_name") or path.stem
            concepts[c["id"]] = c
    return concepts


def load_course(course_path: str | Path, concepts: dict[str, dict]) -> list[dict]:
    """The unit's weeks, for the dashboard tabs.

    Reads course.json if present, then adds any week that has content but isn't
    listed. Each entry: {"week", "title", "chapter", "concepts": [ids]}.
    """
    path = Path(course_path)
    weeks: dict[int, dict] = {}
    if path.exists():
        for w in json.loads(path.read_text(encoding="utf-8")).get("weeks", []):
            weeks[int(w["week"])] = {"week": int(w["week"]), "title": w.get("title", ""),
                                     "chapter": str(w.get("chapter", "") or "")}
    for cid, c in concepts.items():
        n = int(c["week"])
        weeks.setdefault(n, {"week": n, "title": "", "chapter": ""})
        weeks[n].setdefault("concepts", []).append(cid)
    for w in weeks.values():
        w.setdefault("concepts", [])
    return [weeks[n] for n in sorted(weeks)]


def load_sources(sources_dir: str | Path) -> dict[str, dict]:
    """Course documents (lectures, notes) that questions cite, from sources.json."""
    path = Path(sources_dir) / "sources.json"
    if not path.exists():
        return {}
    docs = json.loads(path.read_text(encoding="utf-8")).get("docs", {})
    for doc_id, d in docs.items():
        d["id"] = doc_id
        d["path"] = str(Path(sources_dir) / d["file"])
    return docs


# ------------------------------------------------------- safe arithmetic
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "exp": math.exp, "abs": abs,
          "round": round, "sum": sum, "min": min, "max": max}


def safe_eval(expr: str, variables: dict[str, float]) -> float:
    """Evaluate a small arithmetic expression without using eval()."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            raise ValueError(f"unknown variable '{node.id}'")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        raise ValueError(f"unsupported expression: {ast.dump(node)[:60]}")
    return ev(ast.parse(expr, mode="eval"))


# ------------------------------------------------------------- validation
def _check_refs(refs, sources: dict, where: str, problems: list[str]) -> None:
    for ref in refs:
        if ref is None:
            continue
        doc = sources.get(ref.get("doc"))
        if doc is None:
            problems.append(f"{where}: unknown source document '{ref.get('doc')}'")
        elif not 1 <= int(ref.get("page", 0)) <= int(doc.get("pages", 10**6)):
            problems.append(f"{where}: {doc['unit'].lower()} {ref.get('page')} is outside "
                            f"'{ref['doc']}' (1-{doc['pages']})")


def validate(concepts: dict[str, dict], sources: dict | None = None) -> list[str]:
    """Return a list of human-readable problems (empty list = all good).

    Pass `sources` (from load_sources) to also check every slide/page reference.
    """
    problems: list[str] = []
    qids: set[str] = set()

    for cid, c in concepts.items():
        where = f"[{c.get('_source', '?')}] {cid}"
        missing = REQUIRED_CONCEPT_KEYS - c.keys()
        if missing:
            problems.append(f"{where}: missing {sorted(missing)}")
        for p in c["prerequisites"]:
            if p not in concepts:
                problems.append(f"{where}: unknown prerequisite '{p}'")
            if p == cid:
                problems.append(f"{where}: lists itself as a prerequisite")

        for q in c["questions"]:
            qw = f"{where} / {q.get('id', '?')}"
            if q.get("id") in qids:
                problems.append(f"{qw}: duplicate question id")
            qids.add(q.get("id"))
            if sources is not None:
                _check_refs(q.get("sources", []), sources, qw, problems)
                _check_refs(q.get("option_sources", []), sources, qw + " option_sources", problems)
                if "option_sources" in q and len(q["option_sources"]) != len(q.get("options", [])):
                    problems.append(f"{qw}: option_sources must have one entry per option")
            if q.get("type") not in QTYPES:
                problems.append(f"{qw}: type must be one of {sorted(QTYPES)}")
                continue
            t, d = q["type"], q.get("difficulty")
            if t in SESSION_TYPES and d not in (1, 2, 3):
                problems.append(f"{qw}: 'difficulty' must be 1 (foundations), 2 (application) or 3 (mastery)")
            if t in SUBTYPES and q.get("subtype") not in SUBTYPES[t]:
                problems.append(f"{qw}: 'subtype' must be one of {sorted(SUBTYPES[t])}")
            for other in q.get("concepts", [])[1:]:
                if other not in concepts:
                    problems.append(f"{qw}: unknown concept '{other}' in 'concepts'")
            if t in CHOICE_TYPES:
                opts = q.get("options", [])
                if len(opts) < 2:
                    problems.append(f"{qw}: needs at least 2 options")
                if not isinstance(q.get("answer"), int) or not 0 <= q["answer"] < len(opts):
                    problems.append(f"{qw}: 'answer' must be the index of the correct option")
                if "feedback" in q and len(q["feedback"]) != len(opts):
                    problems.append(f"{qw}: 'feedback' needs one entry per option")
            if t == "relationship":
                rel = q.get("relationship") or {}
                if not (rel.get("from") and rel.get("to") and isinstance(rel.get("steps"), int) and rel["steps"] >= 1):
                    problems.append(f"{qw}: 'relationship' needs from, to and steps (>= 1)")
                elif d == 1 and rel["steps"] > 1:
                    problems.append(f"{qw}: a {rel['steps']}-step chain can't be difficulty 1 (round 1 is one step only)")
                if len(q.get("concepts", [])) < 2:
                    problems.append(f"{qw}: relationship questions must link two or more concepts")
            elif t == "equation":
                if not q.get("equation"):
                    problems.append(f"{qw}: equation questions need 'equation' (LaTeX)")
                if not isinstance(q.get("changes", 1), int) or q.get("changes", 1) < 1:
                    problems.append(f"{qw}: 'changes' must be a whole number >= 1")
                elif d == 1 and (q.get("changes", 1) > 1 or q.get("subtype") in ("rearrange", "linking")):
                    problems.append(f"{qw}: difficulty 1 equation questions change a single variable only")
            elif t == "cloze" or (t == "definition" and q.get("subtype") == "name"):
                blanks = q.get("blanks", [])
                if not blanks or not all(isinstance(b, list) and b and all(isinstance(x, str) for x in b) for b in blanks):
                    problems.append(f"{qw}: 'blanks' must be a list of accepted-answer lists")
                if t == "cloze" and q.get("prompt", "").count("___") != len(blanks):
                    problems.append(f"{qw}: {q.get('prompt', '').count('___')} gaps (___) but {len(blanks)} blanks")
                if t == "definition" and len(blanks) != 1:
                    problems.append(f"{qw}: name-the-concept questions have exactly one blank")
            elif t == "definition":
                if len(q.get("key_points", [])) < 2 or not q.get("model_answer"):
                    problems.append(f"{qw}: define questions need key_points (2+) and model_answer")
            elif q["type"] == "steps":
                variables = dict(q.get("vars", {}))
                for i, step in enumerate(q.get("steps", []), 1):
                    if not isinstance(step.get("answer"), (int, float)):
                        problems.append(f"{qw} step {i}: answer must be a number")
                        continue
                    if "expr" in step:
                        try:
                            value = safe_eval(step["expr"], variables)
                        except Exception as e:  # noqa: BLE001
                            problems.append(f"{qw} step {i}: can't evaluate expr ({e})")
                            continue
                        if not numbers_match(step["answer"], value, step.get("tol")):
                            problems.append(f"{qw} step {i}: answer {step['answer']} "
                                            f"but expr gives {value:.6g}")
                        if step.get("name"):
                            variables[step["name"]] = value
                    elif step.get("name"):
                        variables[step["name"]] = step["answer"]
            elif q["type"] == "explain" and not q.get("key_points"):
                problems.append(f"{qw}: explain questions need key_points")

    # cycle check on the prerequisite graph
    state: dict[str, int] = {}

    def visit(n, path):
        state[n] = 1
        for p in concepts.get(n, {}).get("prerequisites", []):
            if state.get(p) == 1:
                problems.append(f"prerequisite cycle: {' -> '.join(path + [p])}")
            elif p in concepts and state.get(p) is None:
                visit(p, path + [p])
        state[n] = 2

    for cid in concepts:
        if cid not in state:
            visit(cid, [cid])
    return problems


def difficulty_gaps(concepts: dict[str, dict]) -> list[tuple[str, int]]:
    """(topic, difficulty) pairs with no session question. Not errors: sessions fall back to a nearby level."""
    return [(cid, d) for cid, c in concepts.items() for d in (1, 2, 3)
            if not any(q["type"] in SESSION_TYPES and q.get("difficulty") == d for q in c["questions"])]


def coverage(concepts: dict[str, dict]) -> dict[str, dict[str, int]]:
    """topic -> {type: number of session questions}."""
    return {cid: {t: sum(q["type"] == t for q in c["questions"]) for t in SESSION_TYPES}
            for cid, c in concepts.items()}


# ---------------------------------------------------------------- marking
_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_number(text: str) -> float | None:
    """Accept '-2.09', '$-2.09m', '(2.09)', '2,090,000', '1.5%' (→ 1.5)."""
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("$", "").replace("−", "-")
    negative = t.startswith("(") and t.endswith(")")
    m = _NUM.search(t)
    if not m:
        return None
    value = float(m.group())
    return -abs(value) if negative else value


def numbers_match(expected: float, given: float | None, tol: float | None = None) -> bool:
    if given is None:
        return False
    if tol is not None:
        return abs(given - expected) <= tol
    # default: within 1% relative, or 0.01 absolute for small numbers
    return abs(given - expected) <= max(0.01 * abs(expected), 0.01)
