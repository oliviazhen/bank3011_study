"""Claude API helpers: grading explain-mode answers.

Needs ANTHROPIC_API_KEY in your environment (or a .env file / Streamlit secrets).
The model is configurable with BANK_MODEL; Haiku is the default because
grading short answers is quick and cheap (a fraction of a cent per answer).
"""
import json
import os
import re

DEFAULT_MODEL = os.environ.get("BANK_MODEL", "claude-haiku-5-5")

GRADER_SYSTEM = """You are a strict but encouraging tutor for BANK3011 (bank financial management).
Grade the student's explanation ONLY against the key points and the course definition provided.
Do not reward content that isn't in the key points, and flag anything that contradicts the course material.

Reply with JSON only, no prose before or after, in exactly this shape:
{
  "score": <integer 0-5>,
  "covered": [<key points the answer clearly made, quoted from the list>],
  "missing": [<key points it did not make, quoted from the list>],
  "errors": [<specific statements in the answer that are wrong, with a one-line correction>],
  "feedback": "<2-3 sentences: what was good, the single most important thing to add or fix>"
}
Scoring: 5 = all key points, no errors; 4 = nearly all, no serious errors; 3 = about half;
2 = a few points or a significant error; 1 = mostly missing or confused; 0 = blank or off-topic."""


class LLMUnavailable(RuntimeError):
    pass


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set. Explain mode needs it; everything else works offline.")
    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable("Install the SDK with: pip install anthropic") from e
    return anthropic.Anthropic()


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON in reply: {text[:200]}")
    return json.loads(m.group())


def grade_explanation(concept: dict, question: dict, answer: str, model: str | None = None) -> dict:
    client = _client()
    key_points = "\n".join(f"- {k}" for k in question["key_points"])
    user = (f"Concept: {concept['name']}\n"
            f"Course definition: {concept['definition']}\n\n"
            f"Question: {question['prompt']}\n\n"
            f"Key points:\n{key_points}\n\n"
            f"Student answer:\n\"\"\"\n{answer.strip()}\n\"\"\"")
    reply = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=700,
        system=GRADER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in reply.content if block.type == "text")
    result = _extract_json(text)
    result["score"] = max(0, min(5, int(result.get("score", 0))))
    for key in ("covered", "missing", "errors"):
        result.setdefault(key, [])
    result.setdefault("feedback", "")
    return result


MARKER_SYSTEM = """You are a fair examiner for BANK3011 (bank financial management).
Mark the student's answer against a numbered list of marking points. Each point is worth exactly 1 mark.
Award a point only if the answer clearly makes it (wording may differ). Use the ideal answer only to understand
what each point means. Do not award marks for anything outside the marking points.

Reply with JSON only, no prose before or after, in exactly this shape:
{
  "awarded": [<numbers of the marking points the answer clearly made>],
  "errors": [<statements in the answer that are wrong, each with a one-line correction>],
  "feedback": "<2-3 sentences: what was good, and the single most important thing to add or fix>"
}"""


def mark_answer(question: dict, answer: str, topic: str = "", model: str | None = None) -> dict:
    """Mark an answer point by point. Returns {"awarded": [bool per point], "marks", "out_of", "errors", "feedback"}."""
    client = _client()
    points = question["key_points"]
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    user = (f"Topic: {topic}\nQuestion: {question['prompt']}\n\n"
            + (f"Ideal answer:\n{question['model_answer']}\n\n" if question.get("model_answer") else "")
            + f"Marking points:\n{numbered}\n\nStudent answer:\n\"\"\"\n{answer.strip()}\n\"\"\"")
    reply = client.messages.create(model=model or DEFAULT_MODEL, max_tokens=700, system=MARKER_SYSTEM,
                                   messages=[{"role": "user", "content": user}])
    text = "".join(block.text for block in reply.content if block.type == "text")
    result = _extract_json(text)
    got = set()
    for n in result.get("awarded", []):
        try:
            got.add(int(n))
        except (TypeError, ValueError):
            continue
    awarded = [i in got for i in range(1, len(points) + 1)]
    return {"awarded": awarded, "marks": sum(awarded), "out_of": len(points),
            "errors": list(result.get("errors", [])), "feedback": str(result.get("feedback", ""))}
