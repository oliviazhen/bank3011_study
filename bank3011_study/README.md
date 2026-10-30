# BANK3011 Study App

An active-recall study app. Each study session is **3 rounds that get harder**
(Foundations → Application → Mastery). Each round mixes five kinds of question and brings back
the topics you missed, **as a different kind of question**. When you get one wrong, a pop-up
shows the lecture slide that answers it.

Current content: Credit Risk (Chapter 10), 15 topics, 172 questions, every one linked to a
Lecture 5 slide.

## Run it

```bash
cd bank3011_study
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

It opens at http://localhost:8501. The version shows under the title (v4.2). If you see an
old layout, stop every running copy (Ctrl + C) and start again from the new folder.
Set `ANTHROPIC_API_KEY` to have Claude grade your definitions (and for **Explain it**); without
it, you grade definitions yourself against the key points.

## Question types

| Type | What it tests | How it's answered and graded |
|---|---|---|
| **Relationship** | How one concept affects another: *directional* (X ↑ → Y?), *causal*, *comparison* | Choose an option; auto-graded. The X → Y chain is shown after you answer |
| **Equation** | What an equation *means*: *proportionality*, *variables*, *rearrange*, *linking* | Equation shown above the options; auto-graded |
| **Fill the gap** | Key terms and relationships with the term blanked out | Type each gap. Synonyms, case, spacing and small typos are accepted; opposites (increase/decrease, MMR₁/MMR₂) never are |
| **Definition** | *Define it* in your own words, or *name it* from a definition | Name it: typed and auto-graded. Define it: Claude (with an API key) or your self-check ticks off key points; 2 of 3 (or 3 of 4) passes. The model answer is always shown |
| **Multiple choice** | Applied scenarios and multi-step calculations | Auto-graded, with why each wrong option is tempting |

## How a session works

| Round | Level | Type mix |
|---|---|---|
| 1 · Foundations | 1: one-step X → Y, one variable changing, no calculations | relationship 30% · equation 20% · fill the gap 25% · definition 25% |
| 2 · Application | 2: two-step chains, comparisons, rearranging/linking equations | relationship 30% · equation 20% · multiple choice 35% · fill the gap 15% |
| 3 · Mastery | 3: longer chains, several variables at once, multi-step problems | multiple choice 40% · relationship 30% · equation 30% |

Each round has 8 questions:
- **About 40% are re-tests** of topics you missed. Each one is a *different question*, and where possible a *different type* from the one you missed (a missed definition might come back as fill-the-gap or an equation question). It's at the level you missed or one above, never above the round's level, and a topic you keep missing isn't made harder.
- **Re-tests count toward the round's type mix.** If a type can't be filled (e.g. there's no equation for "commercial paper"), another type takes its place, so the round doesn't come up short.
- **The rest is new material.** Low-mastery topics come first; topics with 3+ correct in a row appear about 4× less often. No question repeats within a session.

At the end you get your score per round and per question type, the topics you mastered, and the
topics to revisit (with the lecture slide for each). Weak topics, and the type you missed them
on, are saved, so the next session's round 1 starts with them.

Settings are at the top of `engine/session.py` (`ROUNDS` mixes, `ROUND_SIZE`, `WEAK_SHARE`, …)
and `engine/grading.py` (`DEFINITION_PASS`).

## Question schema (`content/*.json`)

Every question: `id`, `type`, `difficulty` (1–3), `prompt`, `explanation`, `sources` (lecture
slides), and optional `concepts` (the topics it tests; the topic it's filed under is first and is
the one marked weak if missed). Then by type:

```json
{"type": "relationship", "subtype": "directional", "concepts": ["ltv", "cr_basics"],
 "relationship": {"from": "LTV ↑", "to": "PD ↑", "steps": 1},
 "options": ["Increases", "Decreases", "No change"], "answer": 0, "feedback": [null, "...", "..."]}

{"type": "equation", "subtype": "proportionality", "changes": 1,
 "equation": "RAROC = \\frac{\\text{income}}{D \\times L \\times \\Delta R/(1+R)}",
 "options": ["Halves", "Doubles", "No change", "Quadruples"], "answer": 0, "feedback": [...]}

{"type": "cloze", "prompt": "Under a floating rate, interest rate risk is borne by the ___ ...",
 "blanks": [["borrower", "borrowers"], ["bank", "lender"]]}

{"type": "definition", "subtype": "define", "key_points": ["...", "..."], "model_answer": "..."}
{"type": "definition", "subtype": "name", "blanks": [["credit spread"]]}

{"type": "mcq", "options": [...], "answer": 0, "feedback": [...]}
```

The validator (`python -m pytest`, 71 tests) checks every field, and also that level-1
relationships are one step, level-1 equations change one variable, each `___` has a `blanks`
entry, and every slide reference exists. The ⚙️ menu lists topics missing a question type.

**Progress** (`progress.db`): `attempts` logs every answer (question, topic, type, difficulty,
session, round, correct, your response); `topic_state` keeps each topic's weak flag, missed
level, missed type and streaks between sessions; `sessions` keeps each session's summary. Older
progress files are upgraded automatically.

## Adding your own questions

Open **⚙️ → ➕ Add your own questions**, or use the **➕ Add questions for Week N** button on any
week's dashboard tab.

1. **Choose the week.** You must pick it before uploading; questions go into that week's section.
2. **Optionally give the week a title**, e.g. "Liquidity Risk". It's saved to `course.json` and shown on the tab.
3. **Upload a `.json` file.** "⬇ Download a template file" in the dialog shows every question type.
4. **Name the question set.** The name appears as a 📁 tag on its questions and topic cards.
5. **Choose where each topic goes.** A topic matching one already in that week joins it; anything else becomes
   a new topic in that week. You can change any of these, e.g. send questions to the Week 5 RAROC topic.
6. **Check the preview and add.** It shows counts by type and level, plus any questions that can't be added and why.

Accepted file shapes: `{"questions": [...]}`, `{"concepts": [...]}` (same as `content/*.json`) or a plain
list. Each question needs a `topic` (a name or id). Friendly forms are accepted: `question`/`choices`/
`correct`, answers as option text or a letter, `keyPoints`/`modelAnswer`, a single string for one blank,
and a missing `type` or `difficulty` (inferred, with a note). Every question goes through the same
validator as the built-in bank.

Sets are saved in `content/uploads/` and can be removed from the same dialog. A set needs questions at
several levels to fill all three rounds; a small set gives a shorter session.

## Privacy

Personal notes are never bundled with or shown by the app. Questions cite lecture slides only.

## Adding the next lecture

```bash
python tools/build_content.py "Topic_6_Week_6_Credit_risk_part_2.pdf" --week 6 --kind lecture \
    --title "Lecture 6 · Credit Risk: Part II"
```

It registers the lecture and asks Claude for all five question types at all three levels, each
citing its slide, then validates the result. `--kind notes` reads your notes to write questions
but never copies them into the app. Or send the lecture to Claude in chat to build and check it.

## Content by week (v4.3)

| Week | Lecture | Topics | Questions |
|---|---|---|---|
| 5 | Lecture 5 · Credit Risk: Part I | 15 | 172 (all five types) |
| 7 | Lecture 6 · Credit Risk: Part II (loan portfolios) | 8 | 60 |
| 8 | Lecture 7 · Credit Risk: Part III & Sovereign Risk | 7 | 68 |
| 9 | Lecture 9 · Liquidity Risk + Lecture 10 · Deposit Insurance | 7 + 5 | 57 + 37 |
| 10 | Lecture 11 · Capital Adequacy | 6 | 44 |
| 11 | Lecture 12 · Foreign Exchange Risk | 4 | 28 |

Weeks 7–11 are multiple choice (including relationship and equation questions). Every question
cites the slide in that week's lecture that answers it. Personal notes are never bundled.

## Signing in and saving progress (v5.0)

Everyone signs in with their SID (three letters and four numbers, e.g. abc1234). Progress, Explain it marks and
the questions each person writes are saved under their SID, so each student sees only their own.

- **On your computer:** progress is saved in `progress.db`. Progress from earlier versions is given to the first
  SID that signs in.
- **On the website:** set `DATABASE_URL` in the app's Secrets to a Postgres database (e.g. a free Supabase
  project, using its "Session pooler" connection string). Progress then survives restarts.
- Anyone who knows a SID can open that student's progress; there's no password.

## Writing your own questions

Explain it → **Write your own question**: Week, Topic, Ideal answer and Marking points (add or remove points;
each is worth 1 mark). The question is shown as "Explain <topic>." and is saved under your SID. Filter Explain it
by week and topic and work through one question at a time. Answers are marked out of the number of points: by
Claude when an API key is set, otherwise by ticking the points yourself.
