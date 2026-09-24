"""Jolly Phonics Progress Dashboard.

Two faces in one Streamlit app, routed via query params:
  - Teacher area (English), behind Supabase Auth email/password.
  - Parent sheet, read-only, reached via ?token=<access_token>, no login.

The design goal for the teacher area is that a live 1:1 phonics test costs
six taps and no typing. Every screen is measured against that.
"""

import base64
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

import db
import theme
import rollup
from rollup import (
    TOTAL_SOUNDS,
    compact_progress,
    group_rows_for,
    is_mastered,
    mastery_summary,
    suggested_group_number,
    total_acquired,
)

# Which palette to use. Set PHONICS_THEME=classic in .env (or Streamlit
# secrets) to go back to the original quieter design -- see theme.py.
ACTIVE_THEME = theme.resolve(db.get_setting("PHONICS_THEME"))

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

# Three states, not five. A phonics test is a snap judgement made while a
# child is waiting: more options means hesitation, and hesitation is the
# cost this screen exists to remove.
# Labels are short and parallel on purpose. Three words of similar length sit
# three-across on a phone without truncating, and are read at a glance mid-test.
# The stored codes stay explicit ('practising'), only the button text is terse.
STATUSES = [("acquired", "Got it"), ("practising", "Nearly"), ("not_yet", "Not yet")]
STATUS_LABELS = [label for _c, label in STATUSES]
LABEL_TO_STATUS = {label: code for code, label in STATUSES}
STATUS_TO_LABEL = {code: label for code, label in STATUSES}

# Colours and the shape that goes with each status live in theme.py. The
# shape matters: red/amber/green with nothing else is unreadable for anyone
# who cannot separate those hues, and this app is built for a teacher with
# low vision.
def status_chip(code: str) -> str:
    """Status as a coloured pill carrying its symbol -- never colour alone."""
    return theme.status_badge(code, STATUS_TO_LABEL[code], ACTIVE_THEME)


def sound_chip(code: str, grapheme: str) -> str:
    """One tested sound: the letter itself, in its status colour and shape."""
    s = theme.status_style(code, ACTIVE_THEME)
    sym = f"{s['symbol']} " if s["symbol"] else ""
    bg, fg, edge = s["bg"], s["fg"], s.get("edge", s["bg"])
    return (f"<span class='badge' style='background:{bg};color:{fg};"
            f"border:1.5px solid {edge}'>{sym}{grapheme}</span>")

# Lesson scores run 1-10. Absence is a flag on the check-in and "not
# applicable" is simply no score, so neither is ever stored as 0 -- a 0 mixed
# into an average turns "was away" into "did badly" on a parent's trend line,
# and that cannot be undone after a term of entries.
SCORE_MIN, SCORE_MAX = 1, 10
DEFAULT_SCORE = 8

AUTH_COOKIE = "phonics_sb_refresh"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def process_photo(uploaded_file) -> str:
    """Center-crop an uploaded photo to a small square JPEG, base64-encoded."""
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    img = img.resize((256, 256))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def set_browser_cookie(name: str, value: str, days: int = 14):
    components.html(
        f"<script>document.cookie = {name!r} + '=' + {value!r} + "
        f"'; path=/; max-age={days * 86400}; SameSite=Lax';</script>",
        height=0,
    )


def clear_browser_cookie(name: str):
    components.html(
        f"<script>document.cookie = {name!r} + '=; path=/; max-age=0';</script>",
        height=0,
    )


def get_browser_cookie(name: str):
    try:
        return st.context.cookies.get(name)
    except Exception:
        return None


def build_qr_png(url: str) -> bytes:
    """QR for a child's private parent link.

    The QR encodes the FULL url, host included -- so these must not be
    printed until the app is on its final public address. A QR printed
    against a laptop's LAN address, or against a URL that later moves, is
    dead paper.
    """
    import qrcode

    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def app_base_url() -> str:
    """Where this app is being served from.

    Worked out from the page the teacher is already looking at, so she never
    has to type it -- and so a QR can never be generated against a stale
    address she pasted once and forgot. APP_BASE_URL overrides it if the app
    is ever put behind its own domain.
    """
    configured = db.get_setting("APP_BASE_URL")
    if configured:
        return str(configured).rstrip("/")
    try:
        from urllib.parse import urlparse

        parts = urlparse(st.context.url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except Exception:
        pass
    return ""


def parent_link(student: dict) -> str:
    base = app_base_url()
    return f"{base}/?token={student['access_token']}" if base else \
        f"?token={student['access_token']}"


def render_parent_link(student: dict, show_qr: bool = True):
    """The child's private link, plus the QR she prints for their parents."""
    link = parent_link(student)
    st.markdown(f"**{student['name']}**")
    st.code(link, language=None)
    if show_qr and app_base_url():
        st.image(build_qr_png(link), width=200)
    elif show_qr:
        st.warning("Could not work out this app's address, so no QR yet. "
                   "Open the app on its real web address rather than through "
                   "a preview, or set APP_BASE_URL in the app's secrets.")
    st.caption("Private link — anyone who has it can see this child's page.")


def fmt_date(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%-d %b %Y")
    except ValueError:
        return str(value)


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Phonics Progress", page_icon="🔤", layout="wide")

st.markdown(theme.css(ACTIVE_THEME), unsafe_allow_html=True)


def render_hero(title: str, subtitle: str = None, photo_b64: str = None,
                app_chrome: bool = False):
    """app_chrome marks the teacher-area banner, which is hidden on phones."""
    photo = (
        f'<img src="data:image/jpeg;base64,{photo_b64}" '
        'style="width:64px;height:64px;border-radius:50%;object-fit:cover;'
        'border:3px solid rgba(255,255,255,.7);margin-right:1rem;float:left">'
        if photo_b64 else ""
    )
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    klass = "hero hero--app" if app_chrome else "hero"
    st.markdown(
        f'<div class="{klass}">{photo}<h1>{title}</h1>{sub}'
        '<div style="clear:both"></div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Screen 1: the phonics group test (tap-only)
# ---------------------------------------------------------------------------

# The chosen test date is kept in a plain session key, NOT only in the date
# widget's own key. Streamlit discards a widget's stored value on any run
# where that widget is not drawn, and the "change child" screen does not draw
# it -- so relying on the widget key silently reset the date to today between
# children, which is precisely when a backfill needs it to stay put.
DATE_KEY = "test_date_value"


def _remember_date():
    st.session_state[DATE_KEY] = st.session_state.test_date


def _use_today():
    """Reset the test date. A callback, because Streamlit forbids writing to a
    widget's key after that widget has been created in the same run."""
    st.session_state[DATE_KEY] = date.today()
    st.session_state.test_date = date.today()


def render_phonics_test(backend):
    st.subheader("Phonics test")
    st.markdown(
        '<p class="screen-help">Pick a child, pick a group, then open each sound '
        "and un-tick any word they could not read. Nothing is saved until you "
        "press Save test.</p>",
        unsafe_allow_html=True,
    )

    classes = backend.list_classes()
    if not classes:
        st.info("Add a class first.")
        return
    class_options = {c["name"]: c["id"] for c in classes}
    class_names = list(class_options.keys())
    if st.session_state.get("test_class_name") not in class_names:
        st.session_state.test_class_name = class_names[0]

    # The class picker and the roster of name buttons are only shown while
    # actually choosing a child. On a phone they cost a screenful of
    # scrolling each, and during a testing session the class never changes
    # and the child changes once every few minutes.
    picking = (
        st.session_state.get("test_student_id") is None
        or st.session_state.get("test_picking", False)
    )

    if picking and len(class_names) > 1:
        st.session_state.test_class_name = st.selectbox(
            "Class", class_names,
            index=class_names.index(st.session_state.test_class_name),
            key="test_class",
        )

    class_name = st.session_state.test_class_name
    students = backend.list_students(class_id=class_options[class_name])
    if not students:
        st.info("This class has no students yet.")
        return

    progress = backend.group_progress([s["id"] for s in students])

    if picking:
        st.markdown("**Tap a student**")
        # Two across on a phone, four on a wide screen: full-width rows turn
        # a class of twelve into twelve rows of scrolling.
        cols = st.columns(min(len(students), 4))
        for i, s in enumerate(students):
            rows = group_rows_for(progress, s["id"])
            if cols[i % len(cols)].button(
                s["name"], key=f"pick_{s['id']}", use_container_width=True,
                help=mastery_summary(rows),
            ):
                st.session_state.test_student_id = s["id"]
                st.session_state.test_picking = False
                st.rerun()
        return

    student = next(
        (s for s in students if s["id"] == st.session_state.get("test_student_id")), None
    )
    if not student:
        # The selected child was archived or moved class since we last looked.
        st.session_state.test_picking = True
        st.rerun()
        return

    rows = group_rows_for(progress, student["id"])
    head, change = st.columns([3, 1])
    head.markdown(
        f'<div class="test-head"><b>{student["name"]}</b> — '
        f'<span class="only-wide">{mastery_summary(rows)}</span>'
        f'<span class="only-narrow">{compact_progress(rows)}</span>'
        f' · {total_acquired(rows)}/{TOTAL_SOUNDS} secure</div>',
        unsafe_allow_html=True,
    )
    if change.button("Change child", use_container_width=True, key="change_child"):
        st.session_state.test_picking = True
        st.rerun()

    # --- group picker, defaulted to the group they are actually on ---------
    groups = backend.list_groups()
    by_number = {g["group_number"]: g for g in groups}
    suggested = suggested_group_number(rows)
    labels = {f"G{g['group_number']}": g["group_number"] for g in groups}

    picked_label = st.segmented_control(
        "Group to test", list(labels.keys()), default=f"G{suggested}",
        key=f"grp_{student['id']}",
    )
    group_number = labels.get(picked_label or f"G{suggested}", suggested)
    group = by_number[group_number]

    # The date is almost always today, so it stays behind a summary line
    # rather than taking a labelled input's worth of screen on every test --
    # but the line has to say "date" plainly, or entering an older test looks
    # impossible.
    if DATE_KEY not in st.session_state:
        st.session_state[DATE_KEY] = date.today()
    tested_on = st.session_state[DATE_KEY]
    backdated = tested_on != date.today()

    with st.expander(
        f"📅 Test date: {tested_on.strftime('%-d %b %Y')}"
        f"  ·  Group {group_number}: {group['sounds_preview']}",
        expanded=backdated,
    ):
        st.date_input(
            "Record this test on", value=tested_on, key="test_date",
            on_change=_remember_date,
            help="Pick an earlier date to enter tests you ran before using the app.",
        )
        st.caption(
            "The date stays until you change it, so a set of older tests can be "
            "entered one child after another without setting it each time."
        )
    tested_on = st.session_state[DATE_KEY]

    # Because the date persists between children, an unnoticed one would
    # quietly file today's tests under a past date.
    if backdated:
        left, right = st.columns([3, 1])
        left.warning(
            f"Saving to **{tested_on.strftime('%-d %b %Y')}** — not today."
        )
        right.button("Use today", on_click=_use_today, use_container_width=True,
                     key="reset_test_date")

    prefill = backend.latest_results_for_group(student["id"], group["id"])
    this_row = next((r for r in rows if r["group_number"] == group_number), None)
    if this_row and this_row["last_tested_on"]:
        st.caption(
            f"Last tested {fmt_date(this_row['last_tested_on'])} · "
            f"{this_row['acquired']}/{this_row['total_sounds']} secure — "
            "change only what moved."
        )

    sounds = backend.list_sounds(group_id=group["id"])
    words_by_sound = backend.words_for_group(group["id"])
    previous_words = backend.latest_word_results(student["id"], group["id"])

    st.caption(
        "Words start **green**. Tap one to mark it **red** if the child could "
        "not read it, so a child who reads them all needs no taps. The score "
        "above each sound updates when you press Save test."
    )

    # Shortcuts have to sit OUTSIDE the form -- a form only allows its own
    # submit button -- so these cost one page update each. They are for the
    # child who reads everything or nothing, not per-word work.
    def _set_all(correct: bool):
        for s2 in sounds:
            key = f"w_{student['id']}_{group['id']}_{s2['id']}"
            st.session_state[key] = (
                [w["word"] for w in words_by_sound.get(s2["id"], [])] if correct else [])

    quick1, quick2, _rest = st.columns([1, 1, 1.4])
    if quick1.button("Got it all", use_container_width=True, key="tick_all",
                     help="Tick every word in every sound."):
        _set_all(True)
        st.rerun()
    if quick2.button("Not yet, any", use_container_width=True, key="clear_all",
                     help="Clear every word in every sound."):
        _set_all(False)
        st.rerun()

    # Everything below sits in one form. Streamlit contacts the server on
    # every widget change, so tapping 30 word pills outside a form would mean
    # 30 page waits on her phone; inside one, nothing is sent until Save.
    with st.form(f"test_{student['id']}_{group['id']}_{tested_on.isoformat()}"):
        picked = {}
        for snd in sounds:
            words = words_by_sound.get(snd["id"], [])
            saved = [w for w in words
                     if previous_words.get(w["id"], True)] if previous_words else words
            # The score shown is the one on record: inside a form the pills
            # do not reach the server until Save, so this is last test's
            # result until she saves this one.
            status = rollup.status_from_words(len(saved), len(words))
            s = theme.status_style(status, ACTIVE_THEME)
            pct = round(100 * len(saved) / len(words)) if words else 0
            st.markdown(
                f"<div class='sound-head'><span class='sound-grapheme'>"
                f"{snd['grapheme']}</span>"
                f"<span class='badge' style='background:{s['bg']};color:{s['fg']};"
                f"border:1.5px solid {s.get('edge', s['bg'])}'>"
                f"{s['symbol']} {pct}% · {len(saved)}/{len(words)}</span></div>",
                unsafe_allow_html=True,
            )
            with st.expander(f"{snd['label']} — {snd['example_word'] or ''}"):
                picked[snd["id"]] = st.pills(
                    snd["label"], [w["word"] for w in words],
                    selection_mode="multi",
                    default=[w["word"] for w in saved],
                    key=f"w_{student['id']}_{group['id']}_{snd['id']}",
                    label_visibility="collapsed",
                )

        note = st.text_area("Note for this test (optional)", max_chars=600,
                            key=f"note_{student['id']}_{group['id']}")
        saved_test = st.form_submit_button("Save test", type="primary",
                                           use_container_width=True)

    if saved_test:
        statuses, word_results = {}, {}
        for snd in sounds:
            words = words_by_sound.get(snd["id"], [])
            chosen = set(picked.get(snd["id"]) or [])
            for w in words:
                word_results[w["id"]] = w["word"] in chosen
            statuses[snd["id"]] = rollup.status_from_words(
                sum(1 for w in words if w["word"] in chosen), len(words))
        backend.save_test_session(student["id"], group["id"], tested_on,
                                  statuses, note=note, word_results=word_results)
        secure = sum(1 for v in statuses.values() if v == "acquired")
        st.success(f"Saved Group {group_number} for {student['name']} — "
                   f"{secure}/{len(sounds)} secure.")

    render_lesson_scores(backend, student, tested_on)

    # --- recent tests, with a way to undo a mis-entry ----------------------
    sessions = backend.list_test_sessions(student["id"], limit=8)
    if sessions:
        with st.expander(f"Recent tests for {student['name']} ({len(sessions)})"):
            for sess in sessions:
                results = backend.get_session_results(sess["id"])
                dots = " ".join(
                    sound_chip(r["status"], r["phonics_sounds"]["grapheme"])
                    for r in sorted(results, key=lambda r: r["phonics_sounds"]["order_index"])
                )
                c1, c2 = st.columns([5, 1])
                c1.markdown(
                    f"**Group {sess['phonics_groups']['group_number']}** · "
                    f"{fmt_date(sess['tested_on'])} — {dots}"
                    + (f"<br><span class='sound-meta'>{sess['note']}</span>"
                       if sess.get("note") else ""),
                    unsafe_allow_html=True,
                )
                if c2.button("Delete", key=f"del_sess_{sess['id']}"):
                    backend.delete_test_session(sess["id"])
                    st.rerun()


# ---------------------------------------------------------------------------
# Screen 2: class check-in grid
# ---------------------------------------------------------------------------

def render_lesson_scores(backend, student, on_date):
    """The lesson criteria for the child already on screen.

    Everything sits inside a form on purpose. Streamlit sends a request to
    the server on every widget change, and on a phone that made each tap of
    the old plus/minus buttons wait for a page update. Inside a form nothing
    is sent until Save, so typing six numbers costs one round trip instead
    of a dozen.
    """
    criteria = backend.list_criteria()
    if not criteria:
        return

    st.divider()
    existing = backend.checkins_on([student["id"]], on_date).get(student["id"])
    previous = backend.latest_checkins([student["id"]]).get(student["id"], {})
    source = existing["scores"] if existing else previous.get("scores", {})

    with st.form(f"scores_{student['id']}_{on_date.isoformat()}"):
        st.markdown(f"**Lesson scores** · {on_date.strftime('%-d %b')}")
        st.caption(
            "Type a score from **1 to 10** for each, then press Save. It starts "
            "from last lesson, so change only what moved. Leave one blank if it "
            "did not apply — no homework set, say."
        )
        away = st.checkbox(
            "Away today", value=bool(existing["absent"]) if existing else False,
            help="Saves the lesson as an absence. It is left out of the "
                 "averages rather than counted as a zero.",
        )

        values = {}
        for c in criteria:
            values[c["id"]] = st.number_input(
                c["name_en"], min_value=SCORE_MIN, max_value=SCORE_MAX, step=1,
                value=source.get(c["id"]), help=c.get("description_en"),
                key=f"sc_{student['id']}_{c['id']}_{on_date.isoformat()}",
                placeholder="1–10",
            )

        note = st.text_area(
            "Note for this lesson (optional)",
            value=(existing or {}).get("notes") or "", max_chars=600,
        )
        saved = st.form_submit_button("Save lesson scores", type="primary",
                                      use_container_width=True)

    if saved:
        backend.save_checkin(
            student["id"], on_date,
            {} if away else {k: v for k, v in values.items() if v},
            absent=away, notes=note,
        )
        if away:
            st.success(f"{student['name']} marked away for {on_date.strftime('%-d %b')}.")
        else:
            scored = len([v for v in values.values() if v])
            st.success(f"Saved {scored} score(s) for {student['name']}.")


def render_class_checkin(backend):
    st.subheader("Class check-in")
    criteria = backend.list_criteria()
    if not criteria:
        st.info("No criteria yet — add some on the Criteria page.")
        return

    classes = backend.list_classes()
    if not classes:
        st.info("Add a class first.")
        return
    class_options = {c["name"]: c["id"] for c in classes}
    col1, col2 = st.columns([2, 1])
    class_name = col1.selectbox("Class", list(class_options.keys()), key="grid_class")
    checkin_date = col2.date_input("Date", value=date.today(), key="grid_date")

    students = backend.list_students(class_id=class_options[class_name])
    if not students:
        st.info("This class has no students yet.")
        return

    ids = [s["id"] for s in students]
    today_rows = backend.checkins_on(ids, checkin_date)
    previous = backend.latest_checkins(ids)
    progress = backend.group_progress(ids)

    st.caption(
        "Scores are out of 10, starting from each child's last lesson. Tick "
        "**Away** for an absence — it is left out of the averages rather than "
        "counted as a zero. Leave a cell blank if it did not apply."
    )
    with st.expander("What the columns mean"):
        for c in criteria:
            st.markdown(f"- **{c['name_en']}** — {c.get('description_en') or ''}")

    rows = []
    for s in students:
        here = today_rows.get(s["id"])
        source = here["scores"] if here else previous.get(s["id"], {}).get("scores", {})
        row = {
            "#": s.get("order_index"),
            "Student": s["name"],
            "Phonics": compact_progress(group_rows_for(progress, s["id"])),
            "Away": bool(here["absent"]) if here else False,
        }
        for c in criteria:
            row[c["short_label"]] = source.get(c["id"])
        row["Notes"] = (here or {}).get("notes") or ""
        rows.append(row)

    config = {
        "#": st.column_config.NumberColumn("#", disabled=True, width="small"),
        "Student": st.column_config.TextColumn("Student", disabled=True),
        "Phonics": st.column_config.TextColumn(
            "Phonics (from tests)", disabled=True,
            help="Read-only. Comes from the Phonics test screen."),
        "Away": st.column_config.CheckboxColumn("Away"),
        "Notes": st.column_config.TextColumn("Notes"),
    }
    for c in criteria:
        config[c["short_label"]] = st.column_config.NumberColumn(
            c["short_label"], min_value=SCORE_MIN, max_value=SCORE_MAX, step=1,
            width="small", help=f"{c['name_en']} — {c.get('description_en') or ''}")

    edited = st.data_editor(
        pd.DataFrame(rows), column_config=config,
        disabled=["#", "Student", "Phonics"], hide_index=True,
        use_container_width=True, num_rows="fixed",
        key=f"grid_{class_options[class_name]}_{checkin_date.isoformat()}",
    )

    if st.button("Save class check-in", type="primary"):
        saved = away = 0
        for s, new_row in zip(students, edited.to_dict("records")):
            absent = bool(new_row["Away"])
            scores = {}
            for c in criteria:
                v = new_row[c["short_label"]]
                if not pd.isna(v):
                    scores[c["id"]] = int(v)
            notes = (new_row["Notes"] or "").strip() or None
            # A row nobody touched is a child not assessed today, not a child
            # who scored nothing -- skip rather than store an empty check-in.
            if not absent and not scores and not notes:
                continue
            backend.save_checkin(s["id"], checkin_date, scores,
                                 absent=absent, notes=notes)
            saved += 1
            away += 1 if absent else 0
        if saved:
            st.success(f"Saved {saved} check-in(s)" + (f", {away} away." if away else "."))
            st.rerun()
        else:
            st.warning("Nothing to save — every row was empty.")


def render_criteria(backend, read_only: bool = False):
    st.subheader("Check-in criteria")
    st.caption(
        "What you score each lesson. Rename them, reorder them, hide one you "
        "stopped using, or add your own — the check-in grid, the phonics test "
        "screen and the parent page all follow this list."
    )
    criteria = backend.list_criteria(include_inactive=True)
    rows = [
        {
            "Order": c["order_index"],
            "Name": c["name_en"],
            "Vietnamese": c["name_vi"],
            "Short": c["short_label"],
            "What it means": c.get("description_en") or "",
            "In use": bool(c["active"]),
            "Parents see": bool(c["parent_visible"]),
        }
        for c in criteria
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config={
            "Order": st.column_config.NumberColumn("Order", min_value=1, step=1,
                                                   width="small"),
            "Name": st.column_config.TextColumn("Name", required=True),
            "Vietnamese": st.column_config.TextColumn(
                "Vietnamese", help="What parents see on their page."),
            "Short": st.column_config.TextColumn(
                "Short", width="small", help="Column header in the check-in grid."),
            "What it means": st.column_config.TextColumn("What it means"),
            "In use": st.column_config.CheckboxColumn(
                "In use", help="Untick to stop scoring it. Past scores are kept."),
            "Parents see": st.column_config.CheckboxColumn("Parents see"),
        },
        hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=read_only, key="criteria_editor",
    )

    if read_only:
        return

    if st.button("Save criteria", type="primary"):
        changed = 0
        for original, new_row in zip(criteria, edited.to_dict("records")):
            fields = {}
            for col, field in (("Name", "name_en"), ("Vietnamese", "name_vi"),
                               ("Short", "short_label"),
                               ("What it means", "description_en")):
                value = (new_row[col] or "").strip() or None
                if value != (original.get(field) or None):
                    fields[field] = value
            if int(new_row["Order"]) != original["order_index"]:
                fields["order_index"] = int(new_row["Order"])
            for col, field in (("In use", "active"), ("Parents see", "parent_visible")):
                if bool(new_row[col]) != bool(original[field]):
                    fields[field] = bool(new_row[col])
            if fields:
                backend.update_criterion(original["id"], fields)
                changed += 1
        st.success(f"Saved {changed} change(s).") if changed else st.info("Nothing changed.")
        if changed:
            st.rerun()

    with st.expander("Add a criterion"):
        with st.form("new_criterion", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name")
            name_vi = c2.text_input("Vietnamese (shown to parents)")
            c3, c4 = st.columns([1, 3])
            short = c3.text_input("Short label")
            desc = c4.text_input("What it means")
            if st.form_submit_button("Add") and name.strip():
                backend.add_criterion({
                    "code": name.strip().lower().replace(" ", "_")[:40],
                    "name_en": name.strip(),
                    "name_vi": (name_vi.strip() or name.strip()),
                    "short_label": (short.strip() or name.strip()[:6]),
                    "description_en": desc.strip() or None,
                    "order_index": max([c["order_index"] for c in criteria] or [0]) + 1,
                })
                st.rerun()


# ---------------------------------------------------------------------------
# Screen 3: per-student progress
# ---------------------------------------------------------------------------

def render_progress(backend, read_only: bool = False):
    st.subheader("Student progress")
    students = backend.list_students()
    if not students:
        st.info("No students yet.")
        return

    names = {f"{s['name']} — {(s.get('classes') or {}).get('name', '—')}": s for s in students}
    picked = st.selectbox("Student", list(names.keys()), key="prog_student")
    student = names[picked]

    rows = group_rows_for(backend.group_progress([student["id"]]), student["id"])
    acquired = total_acquired(rows)

    render_hero(student["name"], mastery_summary(rows), student.get("photo_b64"))

    st.progress(acquired / TOTAL_SOUNDS, text=f"{acquired} of {TOTAL_SOUNDS} letter sounds secure")

    groups = {g["group_number"]: g for g in backend.list_groups()}
    cols = st.columns(7)
    for i, row in enumerate(rows):
        g = groups[row["group_number"]]
        if is_mastered(row):
            state, mark = "done", "✓"
        elif row["acquired"] or row["practising"] or row["not_yet"]:
            state, mark = "started", f"{row['acquired']}/{row['total_sounds']}"
        else:
            state, mark = "untested", "—"
        bg, fg, bd = theme.group_card_style(row["group_number"], state, ACTIVE_THEME)
        cols[i].markdown(
            f"<div class='group-card' style='background:{bg};color:{fg};border-color:{bd}'>"
            f"<div class='gc-n'>G{row['group_number']}</div>"
            f"<div class='gc-m'>{mark}</div>"
            f"<div class='gc-p'>{g['sounds_preview']}</div></div>",
            unsafe_allow_html=True,
        )

    st.divider()
    left, right = st.columns(2)

    with left:
        st.markdown("**Test history**")
        sessions = backend.list_test_sessions(student["id"], limit=15)
        if not sessions:
            st.caption("No tests recorded yet.")
        for sess in sessions:
            results = backend.get_session_results(sess["id"])
            dots = " ".join(
                sound_chip(r["status"], r["phonics_sounds"]["grapheme"])
                for r in sorted(results, key=lambda r: r["phonics_sounds"]["order_index"])
            )
            st.markdown(
                f"Group {sess['phonics_groups']['group_number']} · "
                f"{fmt_date(sess['tested_on'])}<br>{dots}",
                unsafe_allow_html=True,
            )

    with right:
        st.markdown("**Check-in history**")
        criteria = backend.list_criteria(include_inactive=True)
        checkins = backend.list_student_checkins(student["id"], limit=10)
        if not checkins:
            st.caption("No check-ins recorded yet.")
        else:
            by_id = {c["id"]: c["short_label"] for c in criteria}
            hist = []
            for c in checkins:
                row = {"Date": fmt_date(c["checkin_date"])}
                if c.get("absent"):
                    row.update({s: None for s in by_id.values()})
                    row["Notes"] = "Away"
                else:
                    scores = c.get("scores") or {
                        s["criterion_id"]: s["score"]
                        for s in (c.get("checkin_scores") or [])
                    }
                    row.update({by_id[k]: v for k, v in scores.items() if k in by_id})
                    row["Notes"] = c.get("notes") or ""
                hist.append(row)
            st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
            st.caption("Scores are out of 10. A blank means not scored that lesson.")

    if not read_only:
        st.divider()
        st.markdown("**Parent sheet link**")
        render_parent_link(student)


# ---------------------------------------------------------------------------
# Roster screens
# ---------------------------------------------------------------------------

def render_classes(backend, read_only: bool = False):
    st.subheader("Classes")
    if not read_only:
        with st.form("new_class", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Class name")
            level = c2.text_input("Level (e.g. Jolly Phonics 1)")
            if st.form_submit_button("Add class") and name.strip():
                backend.add_class(name.strip(), level.strip() or None)
                st.rerun()

    classes = backend.list_classes(include_archived=True)
    if not classes:
        st.caption("No classes yet.")
        return

    st.caption(
        "Edit names and levels straight in the grid, then Save. Archiving hides "
        "a class without losing anything."
    )
    rows = [
        {"Class": c["name"], "Level": c.get("level") or "", "Archived": bool(c["archived"])}
        for c in classes
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config={
            "Class": st.column_config.TextColumn("Class", required=True),
            "Level": st.column_config.TextColumn("Level"),
            "Archived": st.column_config.CheckboxColumn("Archived"),
        },
        hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=read_only, key="classes_editor",
    )

    if not read_only and st.button("Save class changes", type="primary"):
        changed = 0
        for original, new_row in zip(classes, edited.to_dict("records")):
            fields = {}
            name = (new_row["Class"] or "").strip()
            if name and name != original["name"]:
                fields["name"] = name
            level = (new_row["Level"] or "").strip() or None
            if level != (original.get("level") or None):
                fields["level"] = level
            if bool(new_row["Archived"]) != bool(original["archived"]):
                fields["archived"] = bool(new_row["Archived"])
            if fields:
                backend.update_class(original["id"], fields)
                changed += 1
        st.success(f"Saved {changed} change(s).") if changed else st.info("Nothing changed.")
        if changed:
            st.rerun()

    if read_only:
        return

    with st.expander("Delete a class permanently"):
        # Deleting is guarded on the class being empty rather than cascading:
        # a class deleted by accident would take every test and check-in of
        # every student in it, and none of that can be undone.
        st.caption(
            "This cannot be undone. A class can only be deleted once it has no "
            "students — move them to another class on the Students page first, "
            "or archive the class instead."
        )
        counts = {
            c["id"]: len(backend.list_students(class_id=c["id"], include_archived=True))
            for c in classes
        }
        options = {f"{c['name']} — {counts[c['id']]} student(s)": c for c in classes}
        picked = st.selectbox("Class", list(options.keys()), key="del_class_pick")
        target = options[picked]
        if counts[target["id"]]:
            st.warning(
                f"**{target['name']}** still has {counts[target['id']]} student(s), "
                "so it cannot be deleted yet."
            )
        else:
            confirm = st.checkbox(
                f"Yes, permanently delete **{target['name']}**", key="del_class_confirm"
            )
            if st.button("Delete class", disabled=not confirm):
                try:
                    backend.delete_class(target["id"])
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.success(f"Deleted {target['name']}.")
                    st.rerun()


def render_students(backend, read_only: bool = False):
    st.subheader("Students")
    classes = backend.list_classes(include_archived=True)
    if not classes:
        st.info("Add a class first.")
        return
    class_by_name = {c["name"]: c["id"] for c in classes}
    class_names = list(class_by_name.keys())

    if not read_only:
        with st.form("new_student", clear_on_submit=True):
            c1, c2 = st.columns(2)
            class_name = c1.selectbox("Class", class_names)
            name = c2.text_input("Student name")
            c3, c4 = st.columns(2)
            parent_name = c3.text_input("Parent name (optional)")
            contact = c4.text_input("Phone (optional)")
            photo = st.file_uploader("Photo (optional headshot)",
                                     type=["jpg", "jpeg", "png", "webp"])
            if st.form_submit_button("Add student") and name.strip():
                existing_order = [
                    s.get("order_index") or 0
                    for s in backend.list_students(include_archived=True)
                ]
                backend.add_student(
                    class_by_name[class_name], name.strip(), contact.strip() or None,
                    process_photo(photo) if photo else None,
                    parent_name=parent_name.strip() or None,
                    order_index=(max(existing_order) if existing_order else 0) + 1,
                )
                st.rerun()

    students = backend.list_students(include_archived=True)
    if not students:
        st.caption("No students yet.")
        return

    active = sum(1 for s in students if not s["archived"])
    archived_n = len(students) - active
    st.caption(
        f"**{active} student(s)**"
        + (f" · {archived_n} archived" if archived_n else "")
        + " — in her register order. Change a **#** to move a child, fix a "
        "spelling, or archive one. Edit in the grid and press Save; nothing is "
        "written until you do."
    )
    name_by_id = {c["id"]: c["name"] for c in classes}
    rows = [
        {
            "#": s.get("order_index"),
            "Student": s["name"],
            "Class": name_by_id.get((s.get("classes") or {}).get("id"), class_names[0]),
            "Parent": s.get("parent_name") or "",
            "Phone": s.get("parent_contact") or "",
            "Archived": bool(s["archived"]),
        }
        for s in students
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config={
            "#": st.column_config.NumberColumn(
                "#", min_value=1, step=1, width="small",
                help="Her register order. Change a number and press Save to move a child.",
            ),
            "Student": st.column_config.TextColumn("Student", required=True),
            "Class": st.column_config.SelectboxColumn("Class", options=class_names),
            "Parent": st.column_config.TextColumn("Parent"),
            "Phone": st.column_config.TextColumn("Phone"),
            "Archived": st.column_config.CheckboxColumn("Archived"),
        },
        hide_index=True, use_container_width=True, num_rows="fixed",
        disabled=read_only, key="students_editor",
    )

    if not read_only and st.button("Save student changes", type="primary"):
        changed = 0
        for original, new_row in zip(students, edited.to_dict("records")):
            fields = {}
            name = (new_row["Student"] or "").strip()
            if name and name != original["name"]:
                fields["name"] = name
            order = new_row["#"]
            order = None if pd.isna(order) else int(order)
            if order != original.get("order_index"):
                fields["order_index"] = order
            parent = (new_row["Parent"] or "").strip() or None
            if parent != (original.get("parent_name") or None):
                fields["parent_name"] = parent
            contact = (new_row["Phone"] or "").strip() or None
            if contact != (original.get("parent_contact") or None):
                fields["parent_contact"] = contact
            class_id = class_by_name.get(new_row["Class"])
            if class_id and class_id != (original.get("classes") or {}).get("id"):
                fields["class_id"] = class_id
            if bool(new_row["Archived"]) != bool(original["archived"]):
                fields["archived"] = bool(new_row["Archived"])
            if fields:
                backend.update_student(original["id"], fields)
                changed += 1
        st.success(f"Saved {changed} change(s).") if changed else st.info("Nothing changed.")
        if changed:
            st.rerun()

    if read_only:
        return

    st.divider()
    st.markdown("**Parent links** — tap a child to see their link and QR code")
    active = [s for s in students if not s["archived"]]
    if active:
        cols = st.columns(min(len(active), 4))
        for i, s in enumerate(active):
            selected = st.session_state.get("qr_student_id") == s["id"]
            if cols[i % len(cols)].button(
                s["name"], key=f"qr_{s['id']}", use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.qr_student_id = s["id"]
                st.rerun()

        chosen = next((s for s in active
                       if s["id"] == st.session_state.get("qr_student_id")), None)
        if chosen:
            render_parent_link(chosen)
        else:
            st.caption("Tap a name above.")

        with st.expander(f"All {len(active)} QR codes — for printing in one go"):
            if not app_base_url():
                st.warning("Open the app on its real web address to print QR codes.")
            else:
                st.caption(
                    "One card per family. Print this page, cut them up, and hand "
                    "each parent their own."
                )
                for start in range(0, len(active), 3):
                    row = active[start:start + 3]
                    qcols = st.columns(3)
                    for col, s in zip(qcols, row):
                        col.markdown(f"**{s['name']}**")
                        col.image(build_qr_png(parent_link(s)), width=150)

    # Photos cannot live in the grid, so they get their own control rather
    # than being settable only at the moment a student is created.
    with st.expander("Add or change a photo"):
        by_label = {s["name"]: s for s in students}
        who = st.selectbox("Student", list(by_label.keys()), key="photo_student")
        shot = st.file_uploader("Photo", type=["jpg", "jpeg", "png", "webp"],
                                key="photo_file")
        if st.button("Save photo", disabled=shot is None):
            backend.update_student(by_label[who]["id"], {"photo_b64": process_photo(shot)})
            st.success(f"Photo updated for {who}.")
            st.rerun()


def radar_svg(labels: list, values: list, accent: str, ink: str,
              fill: str = None) -> str:
    """The skill web, hand-drawn.

    Drawn as SVG rather than pulled from a charting library: it has to match
    the theme in both light and dark, and every extra dependency is another
    thing that can break on an upgrade. The viewBox is deliberately wider
    than it is tall -- Vietnamese criterion names are long, and the side
    labels were being cut off by a square one.
    """
    import math
    import textwrap

    n = len(labels)
    if n < 3:
        return ""
    w, h, cx, cy, r = 420, 330, 210, 150, 92

    def point(i, value):
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        d = r * (value / SCORE_MAX)
        return cx + d * math.cos(angle), cy + d * math.sin(angle)

    rings = "".join(
        '<polygon points="{}" fill="none" stroke="{}" stroke-width="1" opacity=".3"/>'.format(
            " ".join(f"{x:.1f},{y:.1f}" for x, y in
                     (point(i, SCORE_MAX * f) for i in range(n))), ink)
        for f in (0.25, 0.5, 0.75, 1.0)
    )
    spokes = "".join(
        '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="{}" '
        'stroke-width="1" opacity=".25"/>'.format(cx, cy, *point(i, SCORE_MAX), ink)
        for i in range(n)
    )
    pts = [point(i, v or 0) for i, v in enumerate(values)]
    shape = (
        '<polygon points="{}" fill="{}" fill-opacity=".75" stroke="{}" '
        'stroke-width="2.5" stroke-linejoin="round"/>'.format(
            " ".join(f"{x:.1f},{y:.1f}" for x, y in pts), fill or accent, accent)
    )
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{accent}"/>'
                   for x, y in pts)
    names = ""
    for i, label in enumerate(labels):
        x, y = point(i, SCORE_MAX * 1.24)
        anchor = "middle" if abs(x - cx) < 20 else ("start" if x > cx else "end")
        lines = textwrap.wrap(label, 11) or [label]
        y -= (len(lines) - 1) * 6
        spans = "".join(
            f'<tspan x="{x:.1f}" dy="{0 if j == 0 else 13}">{line}</tspan>'
            for j, line in enumerate(lines))
        names += (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
                  f'dominant-baseline="middle" font-size="12" font-weight="600" '
                  f'fill="{ink}">{spans}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
            f'style="max-width:420px;display:block;margin:0 auto" '
            f'role="img">{rings}{spokes}{shape}{dots}{names}</svg>')


def trend_svg(points: list, accent: str, ink: str, muted: str) -> str:
    """Average per lesson over time. Absences are simply not in `points`, so
    the line shows a gap rather than dropping to zero."""
    if len(points) < 2:
        return ""
    w, h, pad_l, pad_b, pad_t = 340, 180, 26, 26, 12
    xs = [pad_l + (w - pad_l - 8) * i / (len(points) - 1) for i in range(len(points))]
    ys = [h - pad_b - (h - pad_b - pad_t) * ((p["average"] - 1) / (SCORE_MAX - 1))
          for p in points]
    grid = "".join(
        '<line x1="{}" y1="{:.1f}" x2="{}" y2="{:.1f}" stroke="{}" stroke-width="1" '
        'opacity=".25"/><text x="4" y="{:.1f}" font-size="10" fill="{}">{}</text>'.format(
            pad_l, y, w - 8, y, ink, y + 3, muted, v)
        for v, y in ((v, h - pad_b - (h - pad_b - pad_t) * ((v - 1) / (SCORE_MAX - 1)))
                     for v in (2, 6, 10))
    )
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{pad_l},{h - pad_b} " + line + f" {xs[-1]:.1f},{h - pad_b}"
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{accent}"/>'
                   for x, y in zip(xs, ys))
    last = (f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="6" fill="none" '
            f'stroke="{accent}" stroke-width="2.5"/>')
    ends = (f'<text x="{pad_l}" y="{h - 8}" font-size="10" fill="{muted}">'
            f'{fmt_date(points[0]["date"])}</text>'
            f'<text x="{w - 8}" y="{h - 8}" font-size="10" fill="{muted}" '
            f'text-anchor="end">{fmt_date(points[-1]["date"])}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="display:block" role="img">'
            f'{grid}<polygon points="{area}" fill="{accent}" fill-opacity=".18"/>'
            f'<polyline points="{line}" fill="none" stroke="{accent}" stroke-width="2.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>{dots}{last}{ends}</svg>')


def lesson_streak(points: list, threshold: int = 8) -> int:
    """Consecutive attended lessons averaging at or above the threshold,
    counting back from the most recent."""
    run = 0
    for p in reversed(points):
        if (p["average"] or 0) >= threshold:
            run += 1
        else:
            break
    return run


def lesson_medals(points: list, radar: dict, criteria: list) -> list:
    """Earned from the data, never awarded by hand."""
    out = []
    if lesson_streak(points) >= 4:
        out.append(("🔥", SHEET["medal_streak"]))
    if points and (points[-1]["average"] or 0) >= 9:
        out.append(("🌟", SHEET["medal_great"]))
    if len(points) >= 3:
        first = sum(p["average"] for p in points[:2]) / 2
        last = sum(p["average"] for p in points[-2:]) / 2
        if last - first >= 1.5:
            out.append(("📈", SHEET["medal_improved"]))
    if radar and len(radar) >= 3 and all(v >= 8 for v in radar.values()):
        out.append(("🎯", SHEET["medal_allround"]))
    if len(points) >= 8:
        out.append(("💪", SHEET["medal_regular"]))
    return out


# ---------------------------------------------------------------------------
# Parent sheet (no login, ?token=...)
#
# Deliberately not a copy of the ESL parent portal: no radar chart, no
# badges, no streak. A phonics parent needs one thing -- which sounds to
# practise this week -- and anything else on the page buries it.
#
# All visible strings are in SHEET so translating the page is one dict.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Every parent-facing string, in one place.
#
# ⚠️  NEEDS A NATIVE REVIEW BEFORE ANY PARENT SEES IT. These are short UI
# labels, not teaching advice -- the phrase library of pedagogical tips was
# dropped precisely because machine-translated advice is not safe to put in
# front of parents. Even so, the teacher should read these 20 lines and
# correct the wording and register before launch.
#
# English kept alongside as `_en` comments so she can see what each is meant
# to say while correcting it.
# ---------------------------------------------------------------------------

SHEET = {
    # "{name}'s phonics progress"
    "title": "Tiến độ học ghép vần của {name}",
    # "{acquired} of 42 letter sounds secure"
    "subtitle": "Đã thuộc {acquired} trên 42 âm",
    # "Sound groups"
    "groups": "Các nhóm âm",
    # "Practise these at home"
    "practise": "Luyện tập ở nhà",
    # "Say the sound, not the letter name, then the word."
    "practise_help": "Đọc ÂM của chữ (không đọc tên chữ), rồi đọc từ ví dụ.",
    "dot_key": "Mỗi âm được đánh dấu theo kết quả lần kiểm tra gần nhất.",
    "all_done": "Tất cả các âm đã kiểm tra đều đạt — rất tốt! 🎉",
    # "Latest class check-in"
    "checkin": "Nhận xét trên lớp gần nhất",
    "not_found": "Liên kết không hợp lệ. Vui lòng hỏi lại cô giáo.",
    "nothing": "Chưa có kết quả — mời quý phụ huynh xem lại sau buổi kiểm tra tới.",
    # --- teacher involvement timeline ---
    # "What we have done"
    "timeline": "Cô đã kiểm tra những gì",
    "timeline_row": "Nhóm {group} — {secure}/{total} âm đạt",
    # Status words on the parent side. The teacher area stays English.
    "status": {
        "acquired": "Đã thuộc",
        "practising": "Gần thuộc",
        "not_yet": "Chưa thuộc",
    },
    # Skill web / trend / medals
    "web": "Cân bằng kỹ năng",
    "trend": "Xu hướng học tập",
    "trend_help": "Điểm trung bình mỗi buổi học (trên 10).",
    "medals": "Huy hiệu",
    "streak": "🔥 Chuỗi {n} buổi học xuất sắc",
    "no_streak": "Hãy cố gắng để bắt đầu chuỗi buổi học xuất sắc nhé!",
    "medal_streak": "Chuỗi 4 buổi chuyên cần",
    "medal_great": "Buổi học xuất sắc",
    "medal_improved": "Tiến bộ vượt bậc",
    "medal_allround": "Học sinh toàn diện",
    "medal_regular": "Người bền bỉ",
    "absent": "Buổi này con vắng mặt.",
    "score_of": "{score}/10",
    "not_scored": "—",
}


def sheet_chip(code: str) -> str:
    """Status pill in Vietnamese, for the parent sheet only."""
    return theme.status_badge(code, SHEET["status"][code], ACTIVE_THEME)


def render_parent_sheet(token: str):
    data = db.get_student_sheet(token)
    if not data:
        st.error(SHEET["not_found"])
        return

    student = data["student"]
    groups = data.get("groups") or []
    acquired = sum(g["acquired"] for g in groups)

    render_hero(
        SHEET["title"].format(name=student["name"]),
        SHEET["subtitle"].format(acquired=acquired),
        student.get("photo_b64"),
    )

    if not groups:
        st.info(SHEET["nothing"])
        return

    st.progress(acquired / TOTAL_SOUNDS)

    st.markdown(f"### {SHEET['groups']}")
    cols = st.columns(7)
    for i, g in enumerate(sorted(groups, key=lambda g: g["group_number"])):
        done = g["total_sounds"] and g["acquired"] == g["total_sounds"]
        started = g["acquired"] or g["practising"] or g.get("not_yet")
        state = "done" if done else ("started" if started else "untested")
        mark = "✓" if done else (
            f"{g['acquired']}/{g['total_sounds']}" if started else "—")
        bg, fg, bd = theme.group_card_style(g["group_number"], state, ACTIVE_THEME)
        cols[i].markdown(
            f"<div class='group-card' style='background:{bg};color:{fg};border-color:{bd}'>"
            f"<div class='gc-n'>G{g['group_number']}</div>"
            f"<div class='gc-m'>{mark}</div>"
            f"<div class='gc-p'>{g['sounds_preview']}</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown(f"### {SHEET['practise']}")
    practise = data.get("practise") or []
    if not practise:
        st.success(SHEET["all_done"])
    else:
        st.caption(SHEET["practise_help"] + "  \n" + SHEET["dot_key"])
        st.markdown(
            "<div style='margin:.2rem 0 .6rem'>"
            + " ".join(sheet_chip(c) for c in ("practising", "not_yet"))
            + "</div>",
            unsafe_allow_html=True,
        )
        # Six at most: a homework list longer than that gets ignored.
        # Rendered as one wrapping row rather than st.columns, which would
        # stack into six full-width blocks on the phone most parents use.
        cards = "".join(
            f"<div class='practise-card'><div class='g'>{p['grapheme']}</div>"
            f"<div class='w'>{p['example_word'] or ''}</div>"
            f"<div class='w'>{sheet_chip(p['status'])}</div></div>"
            for p in practise[:6]
        )
        st.markdown(f"<div class='practise-row'>{cards}</div>", unsafe_allow_html=True)

    # --- what the teacher has done (proof of work, parent-visible) --------
    timeline = data.get("timeline") or []
    if timeline:
        st.markdown(f"### {SHEET['timeline']}")
        for row in timeline:
            st.markdown(
                f"**{fmt_date(row['tested_on'])}** — "
                + SHEET["timeline_row"].format(
                    group=row["group_number"], secure=row["secure"], total=row["total"]
                )
            )

    # --- lesson scores: web, trend, medals --------------------------------
    criteria = data.get("criteria") or []
    radar = data.get("radar") or {}
    trend = data.get("trend") or []
    palette = theme.THEMES[ACTIVE_THEME]
    accent = palette.get("accent_edge", palette["accent"])
    ink, muted = palette["ink"], palette["muted"]

    if radar and len(criteria) >= 3:
        st.markdown(f"### {SHEET['web']}")
        labels = [c["name_vi"] for c in criteria if c["code"] in radar]
        values = [float(radar[c["code"]]) for c in criteria if c["code"] in radar]
        st.markdown(
            radar_svg(labels, values, accent, ink,
                      fill=palette.get("accent_fill", accent)),
            unsafe_allow_html=True)

    if len(trend) >= 2:
        st.markdown(f"### {SHEET['trend']}")
        st.caption(SHEET["trend_help"])
        st.markdown(trend_svg([{"date": p["date"], "average": float(p["average"])}
                               for p in trend], accent, ink, muted),
                    unsafe_allow_html=True)

    if trend:
        streak = lesson_streak([{"average": float(p["average"])} for p in trend])
        st.markdown(
            f"<div class='badge' style='background:{palette['status']['acquired']['bg']};"
            f"color:{palette['status']['acquired']['fg']};"
            f"border:1.5px solid {palette['status']['acquired'].get('edge', accent)}'>"
            + (SHEET["streak"].format(n=streak) if streak else SHEET["no_streak"])
            + "</div>", unsafe_allow_html=True)

    medals = lesson_medals([{"average": float(p["average"])} for p in trend],
                           {k: float(v) for k, v in radar.items()}, criteria)
    if medals:
        st.markdown(f"### {SHEET['medals']}")
        st.markdown(
            "<div class='practise-row'>" + "".join(
                f"<div class='practise-card'><div class='g'>{emoji}</div>"
                f"<div class='w'>{name}</div></div>" for emoji, name in medals
            ) + "</div>", unsafe_allow_html=True)

    last = data.get("last_checkin")
    if last:
        st.markdown(f"### {SHEET['checkin']}")
        st.caption(fmt_date(last.get("checkin_date")))
        if last.get("absent"):
            st.info(SHEET["absent"])
        else:
            scores = last.get("scores") or {}
            cols = st.columns(3)
            for i, c in enumerate(criteria):
                value = scores.get(c["code"])
                cols[i % 3].markdown(
                    f"**{c['name_vi']}** — "
                    + (SHEET["score_of"].format(score=value) if value
                       else SHEET["not_scored"])
                )
        if last.get("notes"):
            st.info(last["notes"])

# ---------------------------------------------------------------------------
# Auth + shell
# ---------------------------------------------------------------------------

# The authenticated client is stored, never the backend object built around
# it. Streamlit keeps session state across a code update, so a stored
# instance of OUR class outlives the module that defined it -- after a
# deploy that adds a method, every logged-in session raises AttributeError
# until the user signs out. Rebuilding the wrapper each run keeps the code
# and the session in step; the client belongs to the supabase package, which
# our deploys never redefine.
def current_backend():
    auth = st.session_state.get("auth")
    if not auth:
        return None
    if auth.get("demo"):
        from local_backend import SqliteBackend

        return SqliteBackend()
    return db.SupabaseBackend(auth["client"])


def remember_login(backend):
    st.session_state.auth = {
        "demo": getattr(backend, "is_demo", False),
        "client": getattr(backend, "client", None),
    }
    st.session_state.is_admin = backend.is_admin()


def render_login():
    render_hero("Phonics Progress", "Teacher login")
    if not db.USE_SUPABASE:
        st.warning(
            "**Demo mode** — no Supabase configured, so this is running on a "
            "local `demo.db` with fake students. Any email and password will "
            "get you in. Fill in `.env` to switch to a real project."
        )
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        try:
            backend, refresh = db.sign_in(email, password)
            remember_login(backend)
            if refresh:
                set_browser_cookie(AUTH_COOKIE, refresh)
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")


def try_resume_session() -> bool:
    """Resume a login from the refresh-token cookie after a page reload.

    Matters more here than in a desktop app: she is on a tablet mid-lesson,
    and being bounced to a login screen between two children is exactly the
    interruption this app is meant to remove.
    """
    refresh_token = get_browser_cookie(AUTH_COOKIE)
    if not refresh_token:
        return False
    try:
        backend, new_token = db.resume(refresh_token)
    except Exception:
        clear_browser_cookie(AUTH_COOKIE)
        return False
    if not backend:
        return False
    remember_login(backend)
    # Supabase rotates refresh tokens: store the new one for next reload.
    set_browser_cookie(AUTH_COOKIE, new_token)
    return True


def render_teacher_app():
    backend = current_backend()
    read_only = not st.session_state.get("is_admin", False)

    with st.sidebar:
        try:
            st.write(f"Logged in as **{backend.current_email()}**")
        except Exception:
            st.session_state.pop("auth", None)
            st.rerun()
            return
        if getattr(backend, "is_demo", False):
            st.caption("🧪 Demo mode — local demo.db")
        if read_only:
            st.caption("👁️ Read-only access")
        if st.button("Log out"):
            backend.sign_out()
            st.session_state.pop("auth", None)
            clear_browser_cookie(AUTH_COOKIE)
            st.rerun()
        st.divider()
        sections = ["Phonics test", "Class check-in", "Student progress",
                    "Students", "Classes", "Criteria"]
        if read_only:
            sections = ["Student progress", "Students", "Classes", "Criteria"]
        page = st.radio("Section", sections)

    render_hero("Phonics Progress", "Read-only view" if read_only else None,
                app_chrome=True)

    if page == "Phonics test":
        render_phonics_test(backend)
    elif page == "Class check-in":
        render_class_checkin(backend)
    elif page == "Student progress":
        render_progress(backend, read_only)
    elif page == "Students":
        render_students(backend, read_only)
    elif page == "Classes":
        render_classes(backend, read_only)
    elif page == "Criteria":
        render_criteria(backend, read_only)


def run_teacher_app():
    """render_teacher_app(), with a readable message for a half-updated app.

    A deploy can leave Streamlit running the new app.py against a db.py that
    is still the copy loaded at start-up, so calls to newly added backend
    methods raise AttributeError. Nothing in the page can repair that -- the
    stale module is already imported -- so say what happened and what fixes
    it instead of showing the teacher a traceback.
    """
    try:
        render_teacher_app()
    except AttributeError as exc:
        st.error(
            "**The app was updated while this page was open**, so it is "
            "running a mix of old and new code.\n\n"
            "Reload the page. If that does not help, open **Manage app** at "
            "the bottom right and press **Reboot**."
        )
        with st.expander("Technical detail"):
            st.exception(exc)
        st.stop()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if db.USE_SUPABASE and not (db.SUPABASE_URL and db.SUPABASE_KEY):
    st.error("SUPABASE_URL / SUPABASE_KEY are not configured.")
    st.stop()

_token = st.query_params.get("token")
if _token:
    render_parent_sheet(_token)
elif "auth" in st.session_state:
    run_teacher_app()
elif db.USE_SUPABASE and try_resume_session():
    run_teacher_app()
else:
    render_login()

# Streamlit Community Cloud pins a ~46px badge to the bottom-right corner of
# every page, and it sat on top of the last row of practise cards -- hiding a
# sound a parent is meant to work on. A spacer is deliberately used instead of
# padding Streamlit's own container: those class names are internal and change
# between releases, so a selector here would break silently on an upgrade.
st.markdown("<div style='height:4rem'></div>", unsafe_allow_html=True)
