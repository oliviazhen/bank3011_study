"""BANK3011 study app.

Run with:   streamlit run app.py
"""
import html
import json
import os
import random
from collections import Counter
from pathlib import Path

import streamlit as st

from engine import bkt, selector
from engine.content import CHOICE_TYPES, SESSION_TYPES, coverage, difficulty_gaps, load_content, load_course, load_sources, validate
from engine.grading import (TYPE_LABELS, definition_correct, grade_blanks, grade_choice, is_typed,
                            points_needed)
from engine.importer import (NEW, TEMPLATE, default_mapping, file_topics, file_week, list_uploads,
                             prepare_upload, save_upload, slug)
from engine.my_questions import check_question, normalise_sid
from engine.llm import LLMUnavailable, grade_explanation, mark_answer
from engine.session import MIN_ROUND, ROUNDS, TopicState, build_round, summarise, update_topic
from engine.storage import Database, Progress

APP_VERSION = "5.0"
ROOT = Path(__file__).parent
print(f"BANK3011 study app version {APP_VERSION} running from {Path(__file__).resolve().parent}", flush=True)
CONTENT_DIR = ROOT / "content"
COURSE_FILE = ROOT / "course.json"
SOURCES_DIR = ROOT / "assets" / "sources"
FORMULA_SHEET = ROOT / "assets" / "formula_sheet.pdf"
DB_PATH = Path(os.environ.get("BANK_DB", ROOT / "progress.db"))
BLUE = "#2563eb"

st.set_page_config(page_title="BANK3011 Study", layout="wide",
                   initial_sidebar_state="collapsed")

st.html(f"""<style>
  /* neutral palette, one accent ({BLUE}), one font, generous spacing */
  .block-container {{ max-width: 960px; padding-top: 4.5rem; padding-bottom: 7rem; }}
  [data-testid="stVerticalBlock"] {{ gap: 1.1rem; }}
  .page-title {{ font-size: 1.6rem; font-weight: 600; margin-bottom: 0.2rem; }}
  .muted {{ font-size: 1rem; color: #71717a; }}
  .points {{ border-top: 1px solid #e4e4e7; margin: 0.6rem 0 1rem; }}
  .point {{ display: flex; gap: 1rem; align-items: baseline; padding: 0.7rem 0; border-bottom: 1px solid #e4e4e7;
            font-size: 1.1rem; line-height: 1.45; }}
  .point-mark {{ flex: 0 0 7.5rem; font-size: 0.95rem; font-weight: 600; color: #71717a; }}
  .point-mark.got {{ color: {BLUE}; }}
  .ideal {{ font-size: 1.1rem; line-height: 1.6; padding: 1rem 1.2rem; background: #f4f4f5; border-radius: 10px;
            white-space: pre-wrap; margin-bottom: 1rem; }}
  .status {{ font-size: 0.85rem; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase; color: #71717a; }}
  .status.s-weak {{ color: #18181b; }}
  .status.s-mastered {{ color: {BLUE}; }}
  [data-testid="stAlertContainer"] {{ background: #f4f4f5 !important; border-left: 4px solid #a1a1aa; border-radius: 8px; }}
  [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color: {BLUE}; }}
  [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{ border-left-color: #18181b; }}
  [data-testid="stAlertContainer"] * {{ color: #18181b !important; }}
  @media (max-width: 700px) {{ .block-container {{ padding-left: 1rem; padding-right: 1rem; }} }}
  .app-title {{ font-size: 1.6rem; font-weight: 700; margin: 0; white-space: nowrap; }}
  .app-version {{ font-size: 0.8rem; opacity: 0.55; }}

  /* session header */
  .round-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1rem;
                font-size: 1.05rem; font-weight: 600; margin-top: 0.5rem; }}
  .round-head .muted {{ font-weight: 400; opacity: 0.7; }}
  .tag {{ display: inline-block; font-size: 0.95rem; padding: 0.15rem 0.6rem; border-radius: 999px;
          background: #f4f4f5; color: #3f3f46; margin: 0.6rem 0 0; }}

  /* fill-the-gap blanks and relationship chains */
  .gap {{ display: inline-block; min-width: 3.2em; padding: 0 0.3em; margin: 0 0.15em; text-align: center;
          border-bottom: 3px solid {BLUE}; color: {BLUE}; font-size: 0.8em; }}
  .chain {{ display: inline-block; font-size: 1.1rem; font-weight: 600; padding: 0.4rem 0.9rem; margin: 0.2rem 0 0.6rem;
            border-radius: 10px; background: rgba(37,99,235,0.08); color: {BLUE}; }}
  .katex {{ font-size: 1.35em !important; }}

  /* question */
  .q-prompt {{ font-size: clamp(1.3rem, 1.05rem + 0.9vw, 1.75rem); font-weight: 600;
              line-height: 1.45; margin: 0.6rem 0 1rem; }}
  [data-testid="stRadio"], [data-testid="stRadio"] > div {{ width: 100%; }}
  [data-testid="stRadioGroup"] {{ gap: 0.6rem; width: 100%; display: flex; flex-direction: column; align-items: stretch; }}
  [data-testid="stRadioGroup"] > div {{ width: 100%; }}
  [data-testid="stRadioOption"] {{ width: 100%; padding: 0.85rem 1rem; border: 1px solid rgba(128,128,128,0.35);
      border-radius: 12px; margin: 0; cursor: pointer; }}
  [data-testid="stRadioOption"]:hover {{ border-color: {BLUE}; }}
  [data-testid="stRadioOption"]:has(input:checked) {{ border: 2px solid {BLUE}; background: rgba(37,99,235,0.08); }}
  [data-testid="stRadioOption"] p {{ font-size: clamp(1.1rem, 1rem + 0.4vw, 1.3rem); line-height: 1.4; }}

  /* buttons, feedback */
  .stButton button, [data-testid="stFormSubmitButton"] button {{ font-size: 1.1rem; min-height: 3rem; padding: 0.5rem 1.4rem; }}
  [data-testid="stAlert"] p, .feedback p {{ font-size: clamp(1.05rem, 1rem + 0.3vw, 1.2rem); line-height: 1.5; }}
  [data-baseweb="tab"] p {{ font-size: 1.15rem; }}

  /* stat tiles, chips, cards */
  .big {{ font-size: clamp(1.6rem, 1.2rem + 1.4vw, 2.4rem); font-weight: 700; margin: 0.3rem 0; }}
  .lead {{ font-size: 1.15rem; opacity: 0.85; line-height: 1.5; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.8rem; margin: 0.6rem 0 1.2rem; }}
  .stat {{ border: 1px solid rgba(128,128,128,0.25); border-radius: 12px; padding: 0.7rem 1rem; }}
  .stat-label {{ font-size: 1rem; opacity: 0.75; }}
  .stat-value {{ font-size: clamp(1.6rem, 1.3rem + 1.1vw, 2.3rem); font-weight: 600; line-height: 1.2; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.4rem 0 1rem; }}
  .chip {{ font-size: 1.05rem; padding: 0.35rem 0.8rem; border-radius: 10px; border: 1px solid rgba(128,128,128,0.3); }}
  .chip.good {{ border-color: {BLUE}; color: {BLUE}; }}
  .chip.weak {{ border-color: #18181b; }}
  .item-name {{ font-size: 1.15rem; font-weight: 600; }}
  .item-sub {{ font-size: 1rem; opacity: 0.75; }}
  [class*="st-key-card_"] {{ border-color: #e4e4e7 !important; height: 100%; }}
  [class*="st-key-card_weak"]     {{ border-color: #18181b !important; }}
  [class*="st-key-card_mastered"] {{ border-color: {BLUE} !important; }}
  .st-key-xcard {{ border-color: #e4e4e7 !important; padding: 0.6rem 0.4rem; }}
  [data-testid="stProgress"] p {{ font-size: 0.95rem; }}

  /* lecture slides in the pop-up: the whole slide fits on screen */
  [class*="st-key-srcimg"] img {{ max-height: 58vh; width: auto !important; max-width: 100%; margin: 0 auto;
      display: block; border: 1px solid rgba(128,128,128,0.3); border-radius: 6px; }}

  /* formula sheet button pinned bottom-right */
  .st-key-formula_fab {{ position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 1000; width: auto; }}
  .st-key-formula_fab button {{ border-radius: 999px; padding: 0.55rem 1.1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }}
</style>""")


# ------------------------------------------------------------------ setup
def _content_stamp() -> float:
    files = [*CONTENT_DIR.glob("*.json"), *(CONTENT_DIR / "uploads").glob("*.json"), CONTENT_DIR / "uploads",
             COURSE_FILE, SOURCES_DIR / "sources.json"]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0)


@st.cache_data
def get_content(stamp: float) -> tuple[dict, list[str], list[dict], dict]:
    concepts = load_content(CONTENT_DIR)
    sources = load_sources(SOURCES_DIR)
    return concepts, validate(concepts, sources), load_course(COURSE_FILE, concepts), sources


def database_target() -> str:
    """DATABASE_URL (Streamlit secrets or environment) for the online database, else the local progress.db."""
    try:
        url = st.secrets.get("DATABASE_URL")
    except Exception:  # noqa: BLE001  no secrets file
        url = None
    return str(url or os.environ.get("DATABASE_URL") or DB_PATH)


@st.cache_resource(show_spinner=False)
def get_database(target: str) -> Database:
    return Database(target)       # one connection pool shared by everyone using the app


concepts, problems, course, SOURCES = get_content(_content_stamp())
WEEKS = {w["week"]: w for w in course}
BANK = [q for c in concepts.values() for q in c["questions"] if q["type"] in SESSION_TYPES]
QMAP = {q["id"]: q for q in BANK}
PRACTICE_TOPICS = {q["concept"] for q in BANK}   # topics with only Explain-it questions stay off the dashboard
ss = st.session_state
try:
    DB = get_database(database_target())
except Exception as e:  # noqa: BLE001
    st.error(f"Couldn't connect to the progress database. Check DATABASE_URL in the app's secrets. ({e})")
    st.stop()


# ------------------------------------------------------------ sign in with your SID
def sign_in_screen() -> None:
    st.markdown("<div class='app-title'>BANK3011</div>", unsafe_allow_html=True)
    st.write("")
    st.markdown("<div class='page-title'>Sign in</div>"
                "<div class='lead'>Enter your SID to load your progress.</div>", unsafe_allow_html=True)
    with st.form("signin", border=False):
        typed = st.text_input("SID", placeholder="abc1234", max_chars=7)
        go = st.form_submit_button("Sign in", type="primary")
    if go:
        sid = normalise_sid(typed)
        if not sid:
            st.error("Your SID is three letters followed by four numbers, for example abc1234.")
        else:
            st.query_params["sid"] = sid      # stays signed in if the page is refreshed
            ss["sid"] = sid
            st.rerun()
    st.caption("Your progress and the questions you write are saved under your SID.")


if "sid" not in ss:
    sid_from_url = normalise_sid(st.query_params.get("sid", ""))
    if sid_from_url:
        ss["sid"] = sid_from_url
if "sid" not in ss:
    sign_in_screen()
    st.stop()
progress = Progress(DB, user=ss["sid"])
if not ss.get("claimed"):                     # local file: earlier progress becomes this student's
    ss["claimed"] = True
    if progress.claim_local():
        ss["upload_done"] = "Your earlier progress has been added to your account"

if not concepts:
    st.error("No content found. Add a JSON file to the content/ folder.")
    st.stop()


def md(text: str) -> str:
    """Escape $ so amounts like $10m ... $90,000 aren't rendered as maths."""
    return str(text).replace("$", "\\$")


def esc(text: str) -> str:
    return md(html.escape(str(text)))


def name(cid: str) -> str:
    return concepts[cid]["name"] if cid in concepts else cid


def week_title(n: int) -> str:
    w = WEEKS.get(n, {})
    parts = [f"Week {n}"] + ([w["title"]] if w.get("title") else []) + \
            ([f"Chapter {w['chapter']}"] if w.get("chapter") else [])
    return " · ".join(parts)


def scope_topics(scope: str) -> set[str]:
    if scope.startswith("week:"):
        return set(WEEKS[int(scope[5:])]["concepts"])
    return set(concepts)


def scope_label(scope: str) -> str:
    return week_title(int(scope[5:])) if scope.startswith("week:") else "All weeks"


def start_from_dashboard(scope: str) -> None:
    """Button callback: go to Practice and start a session for this scope."""
    ss["mode"] = "Practice"
    if not ss.get("sess"):
        ss["pending_scope"] = scope


# --------------------------------------------------- add your own questions
def set_week_title(week: int, title: str) -> None:
    data = json.loads(COURSE_FILE.read_text(encoding="utf-8"))
    for w in data.get("weeks", []):
        if int(w["week"]) == int(week):
            w["title"] = title
            break
    else:
        data.setdefault("weeks", []).append({"week": int(week), "title": title, "chapter": ""})
    COURSE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@st.dialog("Add questions from a file", width="large")
def upload_dialog(preset_week: int | None = None) -> None:
    st.markdown("<div class='lead'>Upload a JSON file of questions. Each one is checked, then added to the week "
                "you choose and mixed into that week's sessions.</div>", unsafe_allow_html=True)
    weeks = [w["week"] for w in course]
    week = st.selectbox("**1 · Which week are these questions for?**", weeks, format_func=week_title,
                        index=weeks.index(preset_week) if preset_week in weeks else None,
                        placeholder="Choose a week…", key="up_week")
    if week is None:
        st.caption("Choose a week first, then upload your file.")
    else:
        current = WEEKS.get(week, {}).get("title", "")
        new_title = st.text_input("Week title (optional)", value=current, placeholder="e.g. Liquidity Risk",
                                  key=f"up_title_{week}", help="Shown on the dashboard tab and in sessions.")
        file = st.file_uploader("**2 · Upload your question file**", type=["json"], key="up_file")
        if file is not None:
            try:
                data = json.loads(file.getvalue().decode("utf-8-sig"))
                topics = file_topics(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                st.error(f"That file isn't valid JSON ({e}).")
                return
            except ValueError as e:
                st.error(str(e))
                return
            fw = file_week(data)
            if fw and fw != week:
                st.warning(f"The file says it's for Week {fw}, but you chose Week {week}. "
                           f"Your choice wins: the questions go into Week {week}.")
            set_name = st.text_input("**3 · Name this question set**", key=f"up_name_{file.name}",
                                     value=Path(file.name).stem.replace("_", " ").replace("-", " ").strip())

            st.markdown("**4 · Where should each topic go?**")
            st.caption(f"Topics matching one already in Week {week} join it; others become new Week {week} topics. "
                       "Change any of them below.")
            default = default_mapping(topics, concepts, week)
            options = [NEW] + sorted(concepts, key=lambda c: (int(concepts[c]["week"]), name(c)))
            mapping = {}
            for i, t in enumerate(x for x in topics if x["ref"]):
                a, b = st.columns([2, 3], vertical_alignment="center")
                a.markdown(f"**{html.escape(t['ref'])}** · {t['count']} question{'s' if t['count'] != 1 else ''}")
                mapping[t["ref"]] = b.selectbox(
                    t["ref"], options, index=options.index(default.get(t["ref"], NEW)),
                    format_func=lambda o: f"New topic in Week {week}" if o == NEW
                    else f"Add to: {name(o)} (Week {concepts[o]['week']})",
                    key=f"map_{week}_{i}_{slug(t['ref'])}", label_visibility="collapsed")
            no_topic = sum(t["count"] for t in topics if not t["ref"])

            res = prepare_upload(data, concepts, SOURCES, week=week, mapping=mapping, stem=set_name or file.name)
            st.markdown("**5 · Check and add**")
            qs = [q for v in res.by_topic.values() for q in v]
            if qs:
                types = Counter(q["type"] for q in qs)
                levels = Counter(q["difficulty"] for q in qs)
                st.markdown(
                    f"<div class='lead'>Ready to add <b>{res.count}</b> question{'s' if res.count != 1 else ''} "
                    f"to <b>{html.escape(week_title(week) if not new_title else f'Week {week} · {new_title}')}</b>: "
                    + ", ".join(f"{n} {TYPE_LABELS[t].lower()}" for t, n in types.most_common())
                    + " · levels " + ", ".join(f"{ROUNDS[d - 1].name.lower()} {n}" for d, n in sorted(levels.items()))
                    + "</div>", unsafe_allow_html=True)
                if res.new_topics:
                    st.caption("New topics: " + ", ".join(t["name"] for t in res.new_topics.values()))
            if no_topic:
                st.warning(f"{no_topic} question{'s have' if no_topic != 1 else ' has'} no topic and will be skipped.")
            if res.rejected:
                with st.expander(f"{len(res.rejected)} question{'s' if len(res.rejected) != 1 else ''} can't be added"):
                    for label, why in res.rejected:
                        st.markdown(f"- **{html.escape(label)}**: {md(html.escape(why))}")
            if res.warnings:
                with st.expander(f"{len(res.warnings)} note{'s' if len(res.warnings) != 1 else ''}"):
                    for w_ in res.warnings:
                        st.markdown(f"- {md(html.escape(w_))}")
            if st.button(f"Add {res.count} question{'s' if res.count != 1 else ''} to Week {week}",
                         type="primary", disabled=res.count == 0, width="stretch"):
                save_upload(res, CONTENT_DIR, file.name, week=week, set_name=set_name or None)
                if new_title.strip() != (current or ""):
                    set_week_title(week, new_title.strip())
                ss["upload_done"] = f"Added {res.count} questions to Week {week}"
                st.rerun()

    st.divider()
    st.download_button("Download a template file", json.dumps(TEMPLATE, indent=2, ensure_ascii=False),
                       file_name="question_template.json", mime="application/json")
    st.caption("The template shows every question type. Use a topic's name or id to add to it, "
               "or a new name to create a topic.")
    ups = list_uploads(CONTENT_DIR)
    if ups:
        st.markdown("**Your question sets**")
        for u in sorted(ups, key=lambda u: (u["week"] or 0, u["uploaded"])):
            a, b = st.columns([4, 1], vertical_alignment="center")
            a.markdown(f"**{html.escape(str(u['name']))}** · Week {u['week']} · {u['questions']} questions")
            if b.button("Remove", key=f"rm_{u['file']}", width="stretch"):
                u["path"].unlink(missing_ok=True)
                sess = ss.get("sess")
                if sess and set(sess.get("plan", [])) & set(u["ids"]):
                    ss.pop("sess")            # the current session used these questions: start afresh
                ss["upload_done"] = f"Removed “{u['name']}”"
                st.rerun()


# ------------------------------------------------------------ top nav bar
MODES = ["Dashboard", "Practice", "Explain it"]
if ss.get("mode") not in MODES:
    ss["mode"] = "Dashboard"

title_col, nav_col, menu_col = st.columns([3, 5, 2], vertical_alignment="center")
with title_col:
    st.markdown(f"<div class='app-title'>BANK3011</div><div class='app-version'>v{APP_VERSION}</div>",
                unsafe_allow_html=True)
with nav_col:
    st.segmented_control("Mode", MODES,
                         key="mode", label_visibility="collapsed")
with menu_col:
    with st.popover("Settings"):
        st.caption(f"Signed in as {ss['sid']}")
        if st.button("Sign out", width="stretch", key="sign_out"):
            st.query_params.clear()
            ss.clear()
            st.rerun()
        if st.button("Add questions from a file", type="primary", width="stretch", key="open_upload"):
            upload_dialog()
        st.caption(f"{len(concepts)} topics · {len(BANK)} questions")
        cov = coverage(concepts)
        thin = [f"{name(t)} ({', '.join(TYPE_LABELS[k].lower() for k, n in row.items() if n == 0)})"
                for t, row in cov.items() if t in PRACTICE_TOPICS and any(n == 0 for n in row.values())]
        if thin:
            st.caption("Topics without every question type (sessions use another type): " + "; ".join(thin))
        gaps = difficulty_gaps(concepts)
        if gaps:
            st.caption("Topics missing a difficulty level (sessions use a nearby level): " +
                       ", ".join(f"{name(t)} (level {d})" for t, d in gaps))
        if problems:
            st.warning(f"{len(problems)} content problem(s)")
            for p in problems:
                st.write(p)
        if st.checkbox("I want to reset all progress"):
            if st.button("Reset progress", type="primary"):
                progress.reset()
                sid_ = ss["sid"]
                ss.clear()
                ss["sid"] = sid_
                st.rerun()
page = ss.get("mode") or "Dashboard"
if ss.get("upload_done"):
    st.toast(ss.pop("upload_done"))


# ------------------------------------------------------------ PDF rendering
@st.cache_data(max_entries=300)
def render_pdf_page(path: str, page_no: int, stamp: float, scale: float = 2.0) -> bytes:
    """One PDF page (1-based) as PNG bytes. Cached; re-renders if the file changes."""
    import io
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_no - 1]
        buf = io.BytesIO()
        page.render(scale=scale).to_pil().save(buf, format="PNG")
        page.close()
        return buf.getvalue()
    finally:
        pdf.close()


def pdf_page_count(path: str) -> int:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


@st.dialog("Formula sheet", width="large")
def show_formula_sheet() -> None:
    path, stamp = str(FORMULA_SHEET), FORMULA_SHEET.stat().st_mtime
    try:
        for i in range(1, pdf_page_count(path) + 1):
            st.image(render_pdf_page(path, i, stamp, 2.2), width="stretch")
    except ImportError:
        st.error("Install the PDF renderer with: pip install pypdfium2")
    st.download_button("Download PDF", FORMULA_SHEET.read_bytes(), file_name="BANK3011_Formula_Sheet.pdf",
                       mime="application/pdf")


if FORMULA_SHEET.exists():
    with st.container(key="formula_fab"):
        if st.button("Formula sheet", key="open_formula_sheet", type="primary"):
            show_formula_sheet()


# ---------------------------------------------------- lecture-slide pop-up
def refs_for(q: dict, choice: int | None = None) -> list[dict]:
    """Slides to show: the one answering the chosen wrong option first, then the question's own."""
    opt = q.get("option_sources") or [None] * len(q.get("options", []))
    refs = ([opt[choice]] if choice is not None and choice != q["answer"] and choice < len(opt) and opt[choice]
            else []) + q.get("sources", [])
    seen, out = set(), []
    for r in refs:
        k = (r["doc"], int(r["page"]))
        if r["doc"] in SOURCES and k not in seen:
            seen.add(k)
            out.append(r)
    return out


def ref_label(ref: dict, short: bool = False) -> str:
    d = SOURCES[ref["doc"]]
    return f"{d['unit']} {ref['page']}" if short else f"{d['title']} · {d['unit']} {ref['page']}"


def show_page(ref: dict, key: str) -> None:
    d = SOURCES[ref["doc"]]
    off_key = f"pg_off_{key}"
    page = min(max(int(ref["page"]) + ss.get(off_key, 0), 1), int(d["pages"]))
    try:
        png = render_pdf_page(d["path"], page, Path(d["path"]).stat().st_mtime, 2.0)
    except ImportError:
        st.error("Install the PDF renderer with: pip install pypdfium2")
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't open {d['file']}: {e}")
        return
    cited = page == int(ref["page"])
    st.caption(f"{d['title']} · {d['unit']} {page} of {d['pages']}"
               + ("  ·  the slide that answers this question" if cited else ""))
    with st.container(key=f"srcimg_{key}"):
        st.image(png, width="stretch")
    a, b, c = st.columns(3)
    if a.button("Previous slide", key=f"prev_{key}", disabled=page <= 1, width="stretch"):
        ss[off_key] = ss.get(off_key, 0) - 1
        st.rerun(scope="fragment")
    if b.button("Back to cited slide", key=f"home_{key}", disabled=cited, width="stretch"):
        ss[off_key] = 0
        st.rerun(scope="fragment")
    if c.button("Next slide", key=f"next_{key}", disabled=page >= int(d["pages"]), width="stretch"):
        ss[off_key] = ss.get(off_key, 0) + 1
        st.rerun(scope="fragment")


@st.dialog("Why: from the lecture", width="large")
def explain_dialog(q: dict, res: dict | None = None) -> None:
    res = res or {}
    choice = res.get("choice")
    if choice is not None and choice != q["answer"]:
        st.markdown(f"<div class='feedback'><p><b>You chose:</b> {esc(q['options'][choice])}</p>"
                    f"<p><b>Correct answer:</b> {esc(q['options'][q['answer']])}</p></div>",
                    unsafe_allow_html=True)
        why = (q.get("feedback") or [None] * len(q["options"]))[choice]
        if why:
            st.warning(f"**Why your option is wrong:** {md(why)}")
    elif res.get("per_blank") and not res.get("correct"):
        rows = [f"<p>You wrote <b>{esc(given or '(blank)')}</b>: " + ("correct" if ok else f"the answer is <b>{esc(acc[0])}</b>") + "</p>"
                for given, ok, acc in zip(res["responses"], res["per_blank"], q["blanks"])]
        st.markdown("<div class='feedback'>" + "".join(rows) + "</div>", unsafe_allow_html=True)
    elif q.get("model_answer"):
        st.info(f"**Model answer:** {md(q['model_answer'])}")
    if q.get("model_answer") is None or choice is not None:
        st.info(f"**Explanation:** {md(q['explanation'])}")
    if q.get("source_note"):
        st.caption(md(q['source_note']))
    refs = refs_for(q, choice)
    if len(refs) == 1:
        show_page(refs[0], f"{q['id']}_0")
    elif refs:
        for i, (tab, ref) in enumerate(zip(st.tabs([ref_label(r, short=True) for r in refs]), refs)):
            with tab:
                show_page(ref, f"{q['id']}_{i}")
    st.divider()
    if st.button("Continue", type="primary", width="stretch", key="dlg_continue"):
        st.rerun()


# =============================================================== DASHBOARD
def page_dashboard() -> None:
    mastery = progress.mastery()
    states = progress.topic_states()
    attempts = progress.attempts(limit=10_000)
    weeks = [w for w in course if w["concepts"]]
    tabs = st.tabs(["All weeks"] + [f"Week {w['week']}" for w in course])
    with tabs[0]:
        overview([c for c in concepts if c in PRACTICE_TOPICS], "all", "All weeks", mastery, states, attempts)
    for tab, w in zip(tabs[1:], course):
        with tab:
            ids = [c for c in w["concepts"] if c in PRACTICE_TOPICS]
            if ids:
                overview(ids, f"week:{w['week']}", week_title(w["week"]), mastery, states, attempts)
                if st.button(f"Add questions to Week {w['week']}", key=f"add_w{w['week']}", type="tertiary"):
                    upload_dialog(w["week"])
            else:
                st.subheader(week_title(w["week"]))
                st.markdown("<div class='lead'>No questions for this week yet.</div>", unsafe_allow_html=True)
                st.write("")
                if st.button(f"Add questions for Week {w['week']}", key=f"add_w{w['week']}", type="primary"):
                    upload_dialog(w["week"])
    if not weeks:
        st.info("No content yet.")


def overview(ids: list[str], scope: str, title: str, mastery: dict, states: dict, attempts: list) -> None:
    ids_set = set(ids)
    head, btn = st.columns([3, 2], vertical_alignment="bottom")
    head.subheader(title)
    btn.button("Start a session", key=f"start_{scope}", type="primary", width="stretch",
               on_click=start_from_dashboard, args=(scope,))

    mine = [a for a in attempts if a["concept_id"] in ids_set]
    n_mastered = sum(bkt.status(selector.mastery_of(mastery, c)) == "mastered" for c in ids)
    n_revisit = sum(states.get(c, TopicState()).weak for c in ids)
    acc = sum(a["correct"] for a in mine) / len(mine) if mine else None
    stats = [("Mastered", f"{n_mastered} / {len(ids)}"), ("To revisit", n_revisit),
             ("Answered", len(mine)), ("Accuracy", f"{acc:.0%}" if acc is not None else "–")]
    st.markdown("<div class='stats'>" + "".join(
        f"<div class='stat'><div class='stat-label'>{k}</div><div class='stat-value'>{v}</div></div>"
        for k, v in stats) + "</div>", unsafe_allow_html=True)

    tried_ids = {a["concept_id"] for a in mine}
    st.markdown("#### Topics")
    order = sorted(ids, key=lambda c: (not states.get(c, TopicState()).weak, selector.mastery_of(mastery, c)))
    for r in range(0, len(order), 3):
        cols = st.columns(3, gap="medium")
        for col, cid in zip(cols, order[r:r + 3]):
            with col:
                p = selector.mastery_of(mastery, cid)
                # red only for topics flagged to revisit; otherwise from mastery (low-but-tried = developing)
                status = bkt.status(p)
                if states.get(cid, TopicState()).weak:
                    status = "weak"
                elif status == "weak":
                    status = "developing"
                with st.container(border=True, key=f"card_{status}_{scope}_{cid}"):
                    tried = cid in tried_ids
                    label = {"weak": "To revisit", "developing": "Developing", "mastered": "Mastered",
                             "new": "Not started"}[status if tried or status == "weak" else "new"]
                    st.markdown(f"<div class='status s-{status}'>{label}</div>"
                                f"<div class='item-name'>{html.escape(name(cid))}</div>", unsafe_allow_html=True)
                    if concepts[cid].get("_set"):
                        st.markdown(f"<div class='item-sub'>{html.escape(concepts[cid]['_set'])}</div>",
                                    unsafe_allow_html=True)
                    st.progress(p if tried else 0.0, text=f"{p:.0%} mastery" if tried else None)


# =============================================================== PRACTICE
def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def new_session(scope: str) -> None:
    ss["sess"] = {"id": progress.start_session(scope), "scope": scope, "round": 0, "stage": "intro",
                  "asked": [], "covered": [], "skipped": [], "plan": [], "retest": [], "pos": 0,
                  "results": {}, "drafts": {}, "finished": False}
    plan_round()


def plan_round() -> None:
    """Build the current round from the latest topic state; skip rounds with too few questions."""
    s = ss["sess"]
    while s["round"] < len(ROUNDS):
        plan = build_round(ROUNDS[s["round"]], BANK, progress.topic_states(), scope=scope_topics(s["scope"]),
                           asked=set(s["asked"]), covered=set(s["covered"]), history=progress.question_history(),
                           mastery=progress.mastery(), rng=random.Random())
        s["skipped"] += [t for t in plan.skipped_weak if t not in s["skipped"]]
        if len(plan.questions) >= MIN_ROUND:
            s.update(plan=[q["id"] for q in plan.questions], retest=list(plan.retest_ids), pos=0, stage="intro")
            return
        s["round"] += 1                       # not enough material at this level: move on
    s["stage"] = "summary"


def record_answer(q: dict, res: dict) -> None:
    """Save one graded answer: answer log, mastery, and the topic's weak/strong state."""
    s = ss["sess"]
    correct = res["correct"]
    mastery = progress.mastery()
    before = selector.mastery_of(mastery, q["concept"])
    after = bkt.update(before, correct, bkt.params_for(q))
    detail = {k: v for k, v in res.items() if k != "correct"}
    ts = progress.record_attempt(q["concept"], q["id"], q["type"], correct, before, after, detail,
                                 difficulty=q["difficulty"], session_id=s["id"], round_no=s["round"] + 1)
    state = progress.topic_states().get(q["concept"], TopicState())
    progress.save_topic_state(q["concept"], update_topic(state, q["difficulty"], correct, ts, qtype=q["type"]))
    s["asked"].append(q["id"])
    s["covered"].append(q["concept"])
    s["results"][q["id"]] = res


def page_practice() -> None:
    if ss.get("pending_scope") and not ss.get("sess"):
        new_session(ss.pop("pending_scope"))
    s = ss.get("sess")
    if not s:
        return start_screen()
    {"intro": round_intro, "question": question_screen, "round_done": round_done,
     "summary": summary_screen}[s["stage"]]()


def start_screen() -> None:
    scopes = ["all"] + [f"week:{w['week']}" for w in course if w["concepts"]]
    st.markdown("<div class='big'>Ready to study?</div>"
                "<div class='lead'>Three rounds that get harder: <b>Foundations, Application, then Mastery</b>. "
                "Each round brings back the topics you missed, with a different kind of question.</div>",
                unsafe_allow_html=True)
    scope = "all"
    if len(scopes) > 2:   # only offer a choice when there's more than one week of content
        scope = st.segmented_control("Cover", scopes, default="all", format_func=scope_label) or "all"
    weak = [t for t, s in progress.topic_states().items() if s.weak and t in scope_topics(scope)]
    if weak:
        st.markdown(f"<div class='lead' style='margin-top:1rem'>Round 1 starts with <b>{len(weak)}</b> "
                    f"topic{'s' if len(weak) != 1 else ''} to revisit from last time.</div>", unsafe_allow_html=True)
    st.write("")
    if st.button("Start session", type="primary"):
        new_session(scope)
        st.rerun()


def round_header(s: dict) -> None:
    spec = ROUNDS[s["round"]]
    st.markdown(f"<div class='round-head'><span>Round {spec.number} of {len(ROUNDS)} · {spec.name}</span>"
                f"<span class='muted'>Question {min(s['pos'] + 1, len(s['plan']))} of {len(s['plan'])}</span></div>",
                unsafe_allow_html=True)
    st.progress(s["pos"] / max(len(s["plan"]), 1))


def round_intro() -> None:
    s = ss["sess"]
    spec = ROUNDS[s["round"]]
    n, k = len(s["plan"]), len(s["retest"])
    st.markdown(f"<div class='big'>Round {spec.number} · {spec.name}</div>"
                f"<div class='lead'>{spec.blurb}<br>{n} questions"
                + (f", including {k} on topics you missed." if k else ".") + "</div>", unsafe_allow_html=True)
    st.write("")
    if st.button("Begin", type="primary"):
        s["stage"] = "question"
        st.rerun()


SUBTYPE_LABELS = {"directional": "If X changes…", "causal": "Cause and effect", "comparison": "Compare",
                  "proportionality": "What happens if…", "variables": "What does it mean?",
                  "rearrange": "Rearrange", "linking": "Which equation?", "define": "Define it", "name": "Name it"}


def prompt_html(q: dict) -> str:
    text = esc(q["prompt"])
    if q["type"] == "cloze":
        n = len(q["blanks"])
        for i in range(n):
            text = text.replace("___", f"<span class='gap'>{i + 1 if n > 1 else '&nbsp;?&nbsp;'}</span>", 1)
    return f"<div class='q-prompt'>{text}</div>"


def answer_input(q: dict, res: dict | None) -> dict | None:
    """Render the right input for the question type. Returns a graded result when submitted."""
    s = ss["sess"]
    locked = res is not None
    if q["type"] in CHOICE_TYPES:
        with st.form(f"q_{q['id']}"):
            picked = st.radio("Answer", q["options"], index=res.get("choice") if locked else None,
                              label_visibility="collapsed", disabled=locked, format_func=md)
            go = st.form_submit_button("Check answer", type="primary", disabled=locked)
        if go and not locked:
            if picked is None:
                st.warning("Pick an answer first.")
                return None
            choice = q["options"].index(picked)
            return {"correct": grade_choice(q, choice), "choice": choice}
        return None

    if is_typed(q):   # fill-the-gap, or name the concept
        n = len(q["blanks"])
        with st.form(f"q_{q['id']}"):
            labels = ["Your answer"] if n == 1 else [f"Gap {i + 1}" for i in range(n)]
            cols = st.columns(min(n, 3)) if n > 1 else [st.container()]
            vals = [cols[i % len(cols)].text_input(labels[i], key=f"in_{q['id']}_{i}", disabled=locked)
                    for i in range(n)]
            go = st.form_submit_button("Check answer", type="primary", disabled=locked)
        if go and not locked:
            if not any(v.strip() for v in vals):
                st.warning("Type an answer first.")
                return None
            correct, per = grade_blanks(q, vals)
            return {"correct": correct, "responses": vals, "per_blank": per}
        return None

    # definition: define it in your own words
    draft = s["drafts"].get(q["id"])
    if draft is None:
        with st.form(f"q_{q['id']}"):
            text = st.text_area("Your definition", height=150, label_visibility="collapsed",
                                placeholder="Write the definition in your own words…", disabled=locked)
            go = st.form_submit_button("Check answer", type="primary", disabled=locked)
        if go and not locked:
            if len(text.split()) < 4:
                st.warning("Write at least a sentence.")
                return None
            if ai_available():
                try:
                    with st.spinner("Checking your definition against the key points…"):
                        g = grade_explanation(concepts[q["concept"]], q, text)
                    covered = [k for k in q["key_points"] if k in g.get("covered", [])] or g.get("covered", [])
                    n_cov = min(len(covered), len(q["key_points"]))
                    return {"correct": definition_correct(n_cov, len(q["key_points"])), "response": text,
                            "covered": covered[:len(q["key_points"])], "graded_by": "ai",
                            "feedback": g.get("feedback", ""), "errors": g.get("errors", [])}
                except Exception as e:  # noqa: BLE001  fall back to self-check
                    st.caption(f"AI grading unavailable ({e}); check it yourself instead.")
            s["drafts"][q["id"]] = text
            st.rerun()
        return None

    # self-check: compare with the model answer and tick the key points you included
    st.markdown(f"<div class='lead'><b>Your answer:</b> {esc(draft)}</div>", unsafe_allow_html=True)
    st.info(f"**Model answer:** {md(q['model_answer'])}")
    with st.form(f"self_{q['id']}"):
        st.markdown("**Tick each key point your answer included:**")
        ticks = [st.checkbox(md(k), key=f"kp_{q['id']}_{i}", disabled=locked) for i, k in enumerate(q["key_points"])]
        go = st.form_submit_button("Submit self-check", type="primary", disabled=locked)
    if go and not locked:
        covered = [k for k, t in zip(q["key_points"], ticks) if t]
        return {"correct": definition_correct(len(covered), len(q["key_points"])), "response": draft,
                "covered": covered, "graded_by": "self"}
    return None


def show_feedback(q: dict, res: dict) -> None:
    ok = res["correct"]
    if q["type"] in CHOICE_TYPES:
        if ok:
            st.success("Correct.")
        else:
            st.error(f"Not quite. The answer is: **{md(q['options'][q['answer']])}**")
            why = (q.get("feedback") or [None] * len(q["options"]))[res["choice"]]
            if why:
                st.warning(f"**Why your option is wrong:** {md(why)}")
        if q["type"] == "relationship":
            rel = q["relationship"]
            st.markdown(f"<div class='chain'>{esc(rel['from'])} &nbsp;leads to&nbsp; {esc(rel['to'])}</div>",
                        unsafe_allow_html=True)
    elif is_typed(q):
        if ok:
            st.success("Correct.")
        else:
            st.error("Not quite.")
        for i, (given, good, acc) in enumerate(zip(res["responses"], res["per_blank"], q["blanks"])):
            lab = "" if len(q["blanks"]) == 1 else f"Gap {i + 1}: "
            also = f" (also accepted: {', '.join(acc[1:3])})" if len(acc) > 1 else ""
            st.markdown(f"{lab}You wrote **{md(html.escape(given or '(blank)'))}**: "
                        + ("correct" if good else f"the answer is **{md(acc[0])}**{md(also)}"))
    else:   # definition
        n, total = len(res.get("covered", [])), len(q["key_points"])
        how = "Claude" if res.get("graded_by") == "ai" else "your self-check"
        verdict = f"{n} of {total} key points (by {how}; {points_needed(total)} needed)."
        if ok:
            st.success(f"Good definition: {verdict}")
        else:
            st.error(f"Not quite: {verdict}")
        if res.get("graded_by") == "ai" and res.get("feedback"):
            st.write(res["feedback"])
        missing = [k for k in q["key_points"] if k not in res.get("covered", [])]
        if missing:
            st.markdown("**Key points to add:**\n" + "\n".join(f"- {md(k)}" for k in missing))
        if res.get("graded_by") == "ai":
            st.info(f"**Model answer:** {md(q['model_answer'])}")
        return
    st.info(f"**Explanation:** {md(q['explanation'])}")


def question_screen() -> None:
    s = ss["sess"]
    q = QMAP[s["plan"][s["pos"]]]
    round_header(s)
    tags = [TYPE_LABELS.get(q["type"], q["type"]) +
            (f" · {SUBTYPE_LABELS[q['subtype']]}" if q.get("subtype") in SUBTYPE_LABELS else "")]
    if q["id"] in s["retest"]:
        tags.append("Another go at a topic you missed")
    if q.get("_set"):
        tags.append(q['_set'])
    st.markdown(" ".join(f"<span class='tag'>{html.escape(t)}</span>" for t in tags), unsafe_allow_html=True)
    st.markdown(prompt_html(q), unsafe_allow_html=True)
    if q["type"] == "equation":
        st.latex(q["equation"])

    res = s["results"].get(q["id"])
    new = answer_input(q, res)
    if new is not None and res is None:
        record_answer(q, new)
        st.rerun()

    if res is not None:
        show_feedback(q, res)
        refs = refs_for(q, res.get("choice"))
        last = s["pos"] + 1 >= len(s["plan"])
        a, b = st.columns(2)
        if refs and a.button(f"Show the lecture slide ({ref_label(refs[0], short=True)})",
                             key=f"src_{q['id']}", width="stretch"):
            explain_dialog(q, res)
        if b.button("Finish round" if last else "Next question", type="primary", width="stretch"):
            s["pos"] += 1
            if last:
                s["stage"] = "round_done"
            st.rerun()
        if not res["correct"] and not s.get(f"shown_{q['id']}"):   # wrong: open the slide once
            s[f"shown_{q['id']}"] = True
            explain_dialog(q, res)

    st.write("")
    if st.button("End session", type="tertiary"):
        s["stage"] = "summary"
        st.rerun()


def round_done() -> None:
    s = ss["sess"]
    spec = ROUNDS[s["round"]]
    ids = s["plan"]
    right = sum(s["results"].get(i, {}).get("correct", False) for i in ids)
    missed = []
    for i in ids:
        if not s["results"].get(i, {}).get("correct", False) and QMAP[i]["concept"] not in missed:
            missed.append(QMAP[i]["concept"])
    final = s["round"] + 1 >= len(ROUNDS)
    st.markdown(f"<div class='big'>Round {spec.number} done: {right} / {len(ids)}</div>", unsafe_allow_html=True)
    if missed:
        where = "saved for your next session" if final else f"coming back in round {spec.number + 1}, as a different kind of question"
        st.markdown(f"<div class='lead'>Topics {where}:</div><div class='chips'>" +
                    "".join(f"<span class='chip weak'>{html.escape(name(t))}</span>" for t in missed) + "</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<div class='lead'>No misses. Nice work.</div>", unsafe_allow_html=True)
    st.write("")
    if st.button("See your results" if final else f"Start round {spec.number + 1}", type="primary"):
        s["round"] += 1
        if final:
            s["stage"] = "summary"
        else:
            plan_round()
        st.rerun()


def summary_screen() -> None:
    s = ss["sess"]
    scope = scope_topics(s["scope"])
    answers = progress.session_answers(s["id"])
    states = progress.topic_states()
    rep = summarise(answers, states, scope, skipped=set(s["skipped"]))
    if not s["finished"]:
        progress.finish_session(s["id"], rep)
        s["finished"] = True

    def tiles(items):
        return "<div class='stats'>" + "".join(
            f"<div class='stat'><div class='stat-label'>{html.escape(k)}</div>"
            f"<div class='stat-value'>{c} / {n}</div></div>" for k, (c, n) in items) + "</div>"

    c, n = rep["score"]
    st.markdown(f"<div class='big'>Session complete: {c} / {n}</div>", unsafe_allow_html=True)
    st.markdown(tiles([(f"Round {r.number} · {r.name}", rep["per_round"].get(r.number, (0, 0))) for r in ROUNDS]),
                unsafe_allow_html=True)
    if rep["per_type"]:
        st.markdown("#### By question type")
        st.markdown(tiles([(TYPE_LABELS.get(t, t), v) for t, v in rep["per_type"].items()]), unsafe_allow_html=True)

    if rep["mastered"]:
        st.markdown("#### Mastered")
        st.markdown("<div class='chips'>" + "".join(
            f"<span class='chip good'>{html.escape(name(t))}</span>" for t in rep["mastered"]) + "</div>",
            unsafe_allow_html=True)

    st.markdown("#### Focus next session")
    if rep["still_weak"]:
        st.caption("These are saved: your next session's round 1 starts with them.")
    for t in rep["focus"]:
        missed_q = next((QMAP[a.question_id] for a in reversed(answers)
                         if a.topic == t and not a.correct and a.question_id in QMAP), None)
        slide = ""
        if missed_q and refs_for(missed_q, None):
            slide = " · Review " + ref_label(refs_for(missed_q, None)[0])
        state = states.get(t, TopicState())
        level = f"missed at {ROUNDS[state.level - 1].name.lower()} level" if state.weak else "not covered yet"
        st.markdown(f"<div class='item-name'>{html.escape(name(t))}</div>"
                    f"<div class='item-sub'>{level}{html.escape(slide)}</div><br>", unsafe_allow_html=True)
    if rep["needs_more_questions"]:
        st.caption("Ran out of fresh questions for: " + ", ".join(name(t) for t in rep["needs_more_questions"]))

    a, b = st.columns(2)
    if a.button("Start a new session", type="primary", width="stretch"):
        scope_ = s["scope"]
        ss.pop("sess")
        new_session(scope_)
        st.rerun()
    if b.button("Back to dashboard", width="stretch"):
        ss.pop("sess")
        ss["mode"] = "Dashboard"
        st.rerun()


# ============================================================== EXPLAIN IT
def _add_point() -> None:
    ss["wx_ids"].append(max(ss["wx_ids"], default=0) + 1)


def _remove_point(pid: int) -> None:
    ss["wx_ids"].remove(pid)
    ss.pop(f"wx_point_{pid}", None)


@st.dialog("Write your own question", width="large")
def write_explain_dialog() -> None:
    weeks = [w["week"] for w in course]
    week = st.selectbox("Week", weeks, format_func=lambda w: f"Week {w}", key="wx_week", index=None,
                        placeholder="Choose a week")
    topic = st.text_input("Topic", key="wx_topic", placeholder="e.g. Liquidity index")
    ideal = st.text_area("Ideal answer", key="wx_ideal", height=170,
                         placeholder="Write the answer you would want to give in the exam.")

    st.markdown("**Marking points**")
    st.caption("The key points an answer is scored against. Each point is worth 1 mark.")
    ss.setdefault("wx_ids", [1, 2, 3])
    for n, pid in enumerate(ss["wx_ids"], 1):
        a, b = st.columns([6, 1], vertical_alignment="bottom")
        a.text_input(f"Point {n}", key=f"wx_point_{pid}", placeholder="e.g. Measures the loss from a fire sale")
        b.button("Remove", key=f"wx_rm_{pid}", on_click=_remove_point, args=(pid,),
                 disabled=len(ss["wx_ids"]) <= 1, width="stretch")
    points = [ss.get(f"wx_point_{pid}", "") for pid in ss["wx_ids"]]
    a, b = st.columns([1, 2], vertical_alignment="center")
    a.button("Add point", key="wx_add", on_click=_add_point, width="stretch")
    filled = sum(bool(p.strip()) for p in points)
    b.caption(f"Total: {filled} mark{'s' if filled != 1 else ''}")

    st.write("")
    if st.button("Save question", type="primary", width="stretch", key="wx_save"):
        fields, errors = check_question(concepts, week=week, topic=topic, ideal_answer=ideal, points=points)
        if errors:
            for e in errors:
                st.error(e)
            return
        qid = progress.add_my_question(**fields)
        for k in [k for k in ss.keys() if str(k).startswith("wx_")]:
            ss.pop(k, None)
        ss["explain_pick"] = qid
        ss["upload_done"] = f"Question saved to Week {fields['week']}"
        st.rerun()


def explain_entries() -> list[dict]:
    """Every Explain it question: the course's, then this student's own. Each: week, topic key/name, question."""
    out = [{"week": int(c["week"]), "tkey": cid, "tname": c["name"], "q": q, "mine": False}
           for cid, c in concepts.items() for q in c["questions"] if q["type"] == "explain"]
    for r in progress.my_questions():
        tkey = r["topic_id"] if r["topic_id"] in concepts else f"w{r['week']}:{slug(r['topic'])}"
        out.append({"week": r["week"], "tkey": tkey, "tname": r["topic"], "mine": True,
                    "q": {"id": r["qid"], "type": "explain", "prompt": r["prompt"], "key_points": r["key_points"],
                          "model_answer": r["model_answer"]}})
    out.sort(key=lambda e: (e["week"], e["tname"].lower(), e["mine"], e["q"]["id"]))
    return out


def _explain_marks(q: dict, result: dict) -> None:
    """Show the mark, then each marking point with Awarded / Not awarded."""
    marks, out_of = result["marks"], len(q["key_points"])
    st.markdown(f"<div class='big'>{marks} / {out_of} mark{'s' if out_of != 1 else ''}</div>", unsafe_allow_html=True)
    if result.get("feedback"):
        st.write(result["feedback"])
    rows = "".join(f"<div class='point'><span class='point-mark {'got' if ok else ''}'>"
                   f"{'Awarded' if ok else 'Not awarded'}</span>{esc(k)}</div>"
                   for k, ok in zip(q["key_points"], result["awarded"]))
    st.markdown(f"<div class='points'>{rows}</div>", unsafe_allow_html=True)
    for e in result.get("errors", []):
        st.warning(f"Check this: {md(e)}")
    if q.get("model_answer"):
        st.markdown("**Ideal answer**")
        st.markdown(f"<div class='ideal'>{esc(q['model_answer'])}</div>", unsafe_allow_html=True)
    refs = refs_for(q)
    if refs:
        with st.expander("See the lecture slide"):
            show_page(refs[0], f"x_{q['id']}")


def page_explain() -> None:
    entries = explain_entries()
    head, btn = st.columns([3, 2], vertical_alignment="center")
    head.markdown("<div class='page-title'>Explain it</div>"
                  "<div class='lead'>Answer in your own words, as you would in the exam.</div>",
                  unsafe_allow_html=True)
    if btn.button("Write your own question", type="primary", width="stretch", key="wx_open"):
        write_explain_dialog()
    if not entries:
        st.info("No questions yet. Write your own question to get started.")
        return

    pick = ss.pop("explain_pick", None)
    picked = next((e for e in entries if e["mine"] and e["q"]["id"] == pick), None)
    if picked:                                         # just saved: show it, with matching filters
        ss["xf_week"], ss["xf_topic"] = picked["week"], picked["tkey"]
    weeks = sorted({e["week"] for e in entries})
    if ss.get("xf_week") not in [None, *weeks]:
        ss["xf_week"] = None
    f1, f2 = st.columns(2)
    week = f1.selectbox("Week", [None, *weeks], key="xf_week",
                        format_func=lambda w: "All weeks" if w is None else f"Week {w}")
    names = {e["tkey"]: e["tname"] for e in entries if week is None or e["week"] == week}
    topics = sorted(names, key=lambda k: names[k].lower())
    if ss.get("xf_topic") not in [None, *topics]:
        ss["xf_topic"] = None
    topic = f2.selectbox("Topic", [None, *topics], key="xf_topic",
                         format_func=lambda k: "All topics" if k is None else names[k])
    shown = [e for e in entries if (week is None or e["week"] == week) and (topic is None or e["tkey"] == topic)]
    if ss.get("xf_last") != (week, topic):            # filters changed: back to the first question
        ss["xf_last"], ss["xf_pos"] = (week, topic), 0
    if picked:
        ss["xf_pos"] = next(i for i, e in enumerate(shown) if e is picked or (e["mine"] and e["q"]["id"] == pick))
    pos = min(ss.get("xf_pos", 0), len(shown) - 1)
    e = shown[pos]
    q = e["q"]

    st.write("")
    a, b, c = st.columns([2, 1, 1], vertical_alignment="center")
    a.markdown(f"<div class='muted'>Question {pos + 1} of {len(shown)}</div>", unsafe_allow_html=True)
    if b.button("Previous", key="xf_prev", disabled=pos == 0, width="stretch"):
        ss["xf_pos"] = pos - 1
        st.rerun()
    if c.button("Next", key="xf_next", disabled=pos >= len(shown) - 1, width="stretch"):
        ss["xf_pos"] = pos + 1
        st.rerun()

    with st.container(border=True, key="xcard"):
        meta = f"Week {e['week']} · {e['tname']}" + (" · Your question" if e["mine"] else "")
        st.markdown(f"<div class='muted'>{esc(meta)}</div>"
                    f"<div class='q-prompt'>{esc(q['prompt'])}</div>"
                    f"<div class='muted'>{len(q['key_points'])} mark{'s' if len(q['key_points']) != 1 else ''}</div>",
                    unsafe_allow_html=True)
        with st.form(f"explain_{q['id']}", border=False):
            answer = st.text_area("Your answer", height=200, label_visibility="collapsed",
                                  placeholder="Write your answer here.")
            go = st.form_submit_button("Mark my answer", type="primary")
    key = f"xres_{q['id']}"
    if go:
        if len(answer.split()) < 5:
            st.warning("Write at least a sentence or two.")
        elif ai_available():
            try:
                with st.spinner("Marking"):
                    result = mark_answer(q, answer, topic=e["tname"])
                progress.record_explain(e["tkey"], q["id"], answer, result["marks"], result)
                ss[key] = result
            except Exception as ex:  # noqa: BLE001
                st.error(f"Marking isn't available right now ({ex}). Mark it yourself below.")
                ss[key] = {"self": True, "answer": answer}
        else:
            ss[key] = {"self": True, "answer": answer}

    res = ss.get(key)
    if res and res.get("self") and "marks" not in res:
        st.markdown("**Mark it yourself**")
        if q.get("model_answer"):
            st.markdown(f"<div class='ideal'>{esc(q['model_answer'])}</div>", unsafe_allow_html=True)
        with st.form(f"selfmark_{q['id']}", border=False):
            st.caption("Tick each marking point your answer made. Each is worth 1 mark.")
            ticks = [st.checkbox(k, key=f"xt_{q['id']}_{i}") for i, k in enumerate(q["key_points"])]
            done = st.form_submit_button("Submit marks", type="primary")
        if done:
            result = {"awarded": ticks, "marks": sum(ticks), "out_of": len(ticks), "errors": [], "feedback": "",
                      "self": True}
            progress.record_explain(e["tkey"], q["id"], res["answer"], result["marks"], result)
            ss[key] = result
            st.rerun()
    elif res and "marks" in res:
        _explain_marks(q, res)

    if e["mine"]:
        st.write("")
        if st.button("Delete this question", key=f"wx_del_{q['id']}", type="tertiary"):
            progress.remove_my_question(q["id"])
            ss.pop(key, None)
            ss["upload_done"] = "Question deleted"
            st.rerun()


{"Dashboard": page_dashboard, "Practice": page_practice, "Explain it": page_explain}.get(page, page_dashboard)()
