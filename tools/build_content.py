"""Turn a lecture or a set of notes into a content JSON file using the Claude API.

Usage:
    python tools/build_content.py lectures/Week_6_Credit_risk_part_2.pdf --week 6 --kind lecture \
        --title "Lecture 6 · Credit Risk: Part II"
    python tools/build_content.py notes/BANK3011_8.pdf --week 8 --kind notes --title "Your notes · Week 8"

What it does:
  1. For a lecture: copies the PDF into assets/sources/ and registers it in sources.json, so the
     app can show the slide when you get a question wrong. Notes (--kind notes) are only read to
     write questions; they are never copied into the app or shown.
  2. Extracts the text slide by slide (page markers are kept so questions can cite them).
  3. Asks Claude to write concepts and questions in the same schema as
     content/week_05_credit_risk_part1.json: MCQs at difficulty 1-3, each citing the slide that answers it.
  4. Validates the result (calculation answers, prerequisites, slide numbers) and sends any
     problems back once for a fix.

Text inside images (formulas pasted as pictures, charts) isn't extracted, so check
questions on those slides by hand. ALWAYS skim the output against the lecture before relying on it.
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.content import load_sources, validate  # noqa: E402
from engine.llm import _client, _extract_json  # noqa: E402

BUILD_MODEL = os.environ.get("BANK_BUILD_MODEL", "claude-sonnet-5-5")
SOURCES_DIR = ROOT / "assets" / "sources"

INSTRUCTIONS = """You are building study content for a university banking unit (BANK3011) from a {kind}.

Return ONE JSON object: {{"unit": "BANK3011", "week": <n>, "title": "...", "source": "...", "concepts": [...]}}
using EXACTLY the schema of the example file below. Rules:
- 8-16 concepts. Each concept: id (snake_case, unique, not one of the existing ids), name, week, prerequisites
  (ids of concepts in THIS file, or ids listed under 'Existing concept ids'), definition (in the source's own
  terms), optional formula, misconceptions (traps the material warns about), cards (2-4), questions.
- Every question has "difficulty": 1 = Foundations (definitions, what is X, why does Y happen; NO calculations,
  one-step relationships only), 2 = Application (scenarios, comparisons, chains of two steps, rearranging or linking
  equations), 3 = Mastery (multi-step problems, longer chains, several variables changing at once, synthesis).
- For EACH concept write, following the example file's exact field names:
  * 3-5 "mcq": 4 options, 'answer' = index, 'feedback' = why each wrong option is tempting (null for the correct one).
    Turn every worked example into an MCQ whose wrong options are the results of common mistakes.
  * 2-4 "relationship" (subtype directional / causal / comparison) linking this concept to another: 'concepts' lists
    both ids (this one first); 'relationship' = {{"from": "X ↑", "to": "Y ↓", "steps": n}}. Directional questions use
    options ["Increases", "Decreases", "No change"]. Difficulty 1 must have steps = 1; chains (steps 2+) are 2 or 3.
  * for every equation in the material, "equation" questions (subtype proportionality / variables / rearrange /
    linking) with 'equation' in LaTeX and 'changes' = number of variables changing. Difficulty 1: one variable only,
    no rearranging or linking.
  * 1-2 "cloze": the prompt contains ___ for each gap, and 'blanks' lists accepted answers per gap, with synonyms.
    Blank the key term or relationship, never filler words.
  * 1-2 "definition": subtype "define" (with 'key_points' (2-4) and 'model_answer') and/or subtype "name"
    (a definition in the prompt; 'blanks' = [[accepted names]]).
  Aim for every concept to have at least one question at each difficulty.
- Also add "explain" questions (with 'key_points') for the 3-6 most important 'why' ideas.
{sources_rule}
- Base everything on the source. Don't introduce facts it doesn't contain.
Return JSON only."""


def extract_pages(path: Path, unit: str) -> tuple[str, int]:
    """Text with '--- Slide N ---' markers, and the page count."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        pages = PdfReader(str(path)).pages
        return "\n".join(f"--- {unit} {i} ---\n{p.extract_text() or ''}" for i, p in enumerate(pages, 1)), len(pages)
    if suffix == ".pptx":
        from pptx import Presentation
        out, slides = [], list(Presentation(str(path)).slides)
        for i, slide in enumerate(slides, 1):
            out.append(f"--- {unit} {i} ---")
            out += [s.text_frame.text for s in slide.shapes if s.has_text_frame]
        return "\n".join(out), len(slides)
    raise SystemExit("Use a PDF (or .pptx) so slides can be shown in the app.")


def register_source(path: Path, doc_id: str, title: str, kind: str, unit: str, pages: int) -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    target = SOURCES_DIR / f"{doc_id}{path.suffix.lower()}"
    if path.resolve() != target.resolve():
        shutil.copyfile(path, target)
    reg_path = SOURCES_DIR / "sources.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else {"docs": {}}
    reg["docs"][doc_id] = {"file": target.name, "title": title, "kind": kind, "unit": unit, "pages": pages}
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Registered {target.name} as '{doc_id}' ({pages} {unit.lower()}s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path, help="lecture slides or notes (PDF preferred)")
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--kind", choices=["lecture", "notes"], default="lecture")
    ap.add_argument("--title", help="how the app labels this document, e.g. 'Lecture 6 · Credit Risk: Part II'")
    ap.add_argument("--doc-id", help="short id; default week06_lecture etc.")
    ap.add_argument("--model", default=BUILD_MODEL)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    unit = "Slide" if args.kind == "lecture" else "Page"
    cite = args.kind == "lecture"   # personal notes are private: never copied into the app or shown
    doc_id = args.doc_id or f"week{args.week:02d}_{args.kind}"
    if not re.fullmatch(r"[a-z0-9_]+", doc_id):
        raise SystemExit("--doc-id must be lowercase letters, digits and underscores")
    title = args.title or f"Week {args.week} {'lecture' if args.kind == 'lecture' else 'notes'}"

    text, n_pages = extract_pages(args.file, unit)
    if cite and args.file.suffix.lower() == ".pdf":
        register_source(args.file, doc_id, title, args.kind, unit, n_pages)
    sources = load_sources(SOURCES_DIR)

    example = (ROOT / "content" / "week_05_credit_risk_part1.json").read_text(encoding="utf-8")
    existing = sorted({c["id"] for f in (ROOT / "content").glob("*.json")
                       for c in json.loads(f.read_text(encoding="utf-8"))["concepts"]})

    client = _client()
    sources_rule = (
        f'- EVERY question must have "sources": [{{"doc": "{doc_id}", "page": <n>}}], citing the {unit} number(s) '
        f"(from the '--- {unit} N ---' markers) that actually answer it, most relevant first. If one wrong option is "
        f'answered by a different {unit.lower()}, add "option_sources": one entry per option ({{"doc","page"}} or null).'
        if cite else "- Do NOT add 'sources' to questions: these notes are private and are never shown in the app.")
    prompt = INSTRUCTIONS.format(kind="lecture slide deck" if args.kind == "lecture" else "student's notes",
                                 sources_rule=sources_rule)
    messages = [{"role": "user", "content":
                 f"{prompt}\n\nExisting concept ids: {', '.join(existing)}\n\n"
                 f"<example_file>\n{example}\n</example_file>\n\n"
                 f"<source doc=\"{doc_id}\" week=\"{args.week}\" title=\"{title}\">\n{text}\n</source>"}]

    problems: list[str] = []
    for attempt in range(2):
        print(f"Asking {args.model} (attempt {attempt + 1})...")
        reply = client.messages.create(model=args.model, max_tokens=32000, messages=messages)
        reply_text = "".join(b.text for b in reply.content if b.type == "text")
        data = _extract_json(reply_text)

        # validate together with existing content so cross-week prerequisites resolve
        merged = {}
        for f in (ROOT / "content").glob("*.json"):
            for c in json.loads(f.read_text(encoding="utf-8"))["concepts"]:
                for k in ("prerequisites", "questions", "cards"):
                    c.setdefault(k, [])
                merged[c["id"]] = c
        for c in data["concepts"]:
            for k in ("prerequisites", "questions", "cards"):
                c.setdefault(k, [])
            c["_source"] = "new"
            merged[c["id"]] = c
        problems = [p for p in validate(merged, sources) if "[new]" in p or "cycle" in p]
        if cite:
            problems += [f"{q['id']}: has no 'sources'" for c in data["concepts"] for q in c["questions"]
                         if not q.get("sources")]
        if not problems:
            break
        print(f"{len(problems)} problem(s) found; asking for a fix:\n  " + "\n  ".join(problems))
        messages += [{"role": "assistant", "content": reply_text},
                     {"role": "user", "content": "The validator found these problems. Return the full corrected JSON only:\n"
                      + "\n".join(problems)}]

    for c in data["concepts"]:
        c.pop("_source", None)
    out = args.out or ROOT / "content" / f"week_{args.week:02d}_{args.kind}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    n_q = sum(len(c["questions"]) for c in data["concepts"])
    print(f"Wrote {out} - {len(data['concepts'])} concepts, {n_q} questions.")
    if problems:
        print("WARNING: problems remain - fix these by hand:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
