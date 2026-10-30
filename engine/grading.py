"""Grading for every question type.

    mcq / relationship / equation   discrete options: exact match on the chosen index
    cloze, definition (name)         typed answers: normalised, synonyms, small typos allowed
    definition (define)              key-point coverage, from Claude or from the student's self-check
"""
from __future__ import annotations

import math
import re
import unicodedata

from .content import numbers_match, parse_number

CHOICE_TYPES = {"mcq", "relationship", "equation"}
TYPED_TYPES = {"cloze"}            # plus definition/name
SESSION_TYPES = {"mcq", "relationship", "equation", "cloze", "definition"}
DEFINITION_PASS = 2 / 3            # share of key points needed (2 of 3, 3 of 4) for a definition to count as correct

TYPE_LABELS = {"mcq": "Multiple choice", "relationship": "Relationship", "equation": "Equation",
               "cloze": "Fill the gap", "definition": "Definition"}

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉ₜ", "0123456789t")
_SYMBOLS = {"×": "*", "·": "*", "−": "-", "–": "-", "—": "-", "÷": "/", "Φ": "phi", "φ": "phi", "ϕ": "phi",
            "γ": "gamma", "Δ": "delta", "β": "beta", "%": " percent"}
_ARTICLES = {"a", "an", "the"}
# Pairs that are one or two letters apart but mean the opposite: never accept one for the other.
_OPPOSITES = [("increase", "decrease"), ("increases", "decreases"), ("rise", "fall"), ("higher", "lower"),
              ("secured", "unsecured"), ("senior", "junior"), ("lender", "borrower"), ("debit", "credit")]


def normalise(text: str) -> str:
    """Lower-case, unify symbols and subscripts, drop punctuation and leading articles."""
    t = unicodedata.normalize("NFKC", str(text)).translate(_SUB)
    for k, v in _SYMBOLS.items():
        t = t.replace(k, v)
    t = t.lower().strip()
    t = re.sub(r"[^\w\s*/+\-=.()]", " ", t)          # keep maths symbols, drop other punctuation
    t = re.sub(r"\s+", " ", t).strip(" .")
    words = t.split(" ")
    while len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def _compact(t: str) -> str:
    return re.sub(r"[\s\-_()]", "", t)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _opposites(a: str, b: str) -> bool:
    return any({a, b} == {x, y} or (x in a and y in b) or (y in a and x in b) for x, y in _OPPOSITES)


def blank_matches(given: str, accepted: list[str]) -> bool:
    """Does a typed answer match any accepted answer for one blank?"""
    g = normalise(given)
    if not g:
        return False
    g_num = parse_number(given) if re.fullmatch(r"[\s$(−\-+]*[\d.,]+\s*%?[)\s]*", str(given)) else None
    for acc in accepted:
        a = normalise(acc)
        if g_num is not None:
            a_num = parse_number(acc) if re.fullmatch(r"[\s$(−\-+]*[\d.,]+\s*%?[)\s]*", str(acc)) else None
            if a_num is not None and numbers_match(a_num, g_num, tol=abs(a_num) * 0.002 + 1e-9):
                return True
            continue
        gc, ac = _compact(g), _compact(a)
        if g == a or gc == ac or gc.rstrip("s") == ac.rstrip("s"):
            return True
        if _opposites(gc, ac):
            continue
        # small typos: only for longer words, and the first letter must match
        if len(ac) >= 5 and gc[:1] == ac[:1]:
            allowed = 2 if len(ac) >= 9 and gc[:3] == ac[:3] else 1
            if edit_distance(gc, ac) <= allowed:
                return True
    return False


def grade_choice(q: dict, choice: int) -> bool:
    return choice == q["answer"]


def grade_blanks(q: dict, responses: list[str]) -> tuple[bool, list[bool]]:
    """All blanks must be right for the question to count as correct."""
    per = [blank_matches(r, acc) for r, acc in zip(responses, q["blanks"])]
    per += [False] * (len(q["blanks"]) - len(per))
    return all(per), per


def points_needed(n_points: int) -> int:
    return math.ceil(n_points * DEFINITION_PASS - 1e-9)


def definition_correct(n_covered: int, n_points: int) -> bool:
    return n_points > 0 and n_covered >= points_needed(n_points)


def is_typed(q: dict) -> bool:
    return q["type"] == "cloze" or (q["type"] == "definition" and q.get("subtype") == "name")


def is_free_text(q: dict) -> bool:
    return q["type"] == "definition" and q.get("subtype") == "define"
