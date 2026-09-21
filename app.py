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

# The class check-in criteria. Letter-sound recognition is deliberately
# absent -- the test screen measures it sound by sound, and asking her to
# also rate it here would be entering the same judgement twice.
#
# These are the four remaining Jolly Phonics core skills (blending,
# segmenting, letter formation, tricky words) plus the two things that
# actually predict trouble at this age: pencil grip and whether the child
# joins in at all.
# (field, short grid header, full name, what it means)
# The grid header is short on purpose -- nine columns have to fit a tablet
# screen -- but parents and the column legend get the full name, because
# "Grip" and "Tricky" mean nothing to someone outside the classroom.
SKILL_CRITERIA = [
    ("blending_rating", "Blend", "Blending",
     "Runs sounds together to read a word (c-a-t → cat)"),
    ("segmenting_rating", "Segment", "Segmenting",
     "Hears the separate sounds in a spoken word (cat → c-a-t)"),
    ("letter_formation_rating", "Letters", "Letter formation",
     "Forms letters correctly — right start point and direction"),
    ("pencil_grip_rating", "Grip", "Pencil grip",
     "Holds the pencil in a tripod grip without reminders"),
    ("tricky_words_rating", "Tricky", "Tricky words",
     "Reads the tricky words taught so far (the, I, he, was…)"),
    ("participation_rating", "Joins in", "Joining in",
     "Does the actions, sings, attends to the lesson"),
]
SKILL_FIELDS = [f for f, _s, _n, _d in SKILL_CRITERIA]
SKILL_LABELS = [s for _f, s, _n, _d in SKILL_CRITERIA]
LABEL_TO_SKILL = {s: f for f, s, _n, _d in SKILL_CRITERIA}

# 1-4, not 1-5: for beginners the middle of a five-point scale carries no
# information, and fewer options makes the grid faster.
RATING_SCALE = ["1 · Not yet", "2 · Emerging", "3 · Developing", "4 · Secure"]
RATING_TO_INT = {label: i + 1 for i, label in enumerate(RATING_SCALE)}
INT_TO_RATING = {i + 1: label for i, label in enumerate(RATING_SCALE)}

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

def _sound_key(student_id: str, group_id: str, sound_id: str) -> str:
    # Group and student are in the key so switching either starts clean
    # rather than inheriting the previous child's taps.
    return f"snd_{student_id}_{group_id}_{sound_id}"


def render_phonics_test(backend):
    st.subheader("Phonics test")
    st.markdown(
        '<p class="screen-help">Pick a child, pick a group, tap once per sound. '
        "Nothing is written until you press Save, so tapping stays instant.</p>",
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

    # Date is almost always today, so it lives behind a summary line rather
    # than taking a labelled input's worth of screen on every test.
    if "test_date" not in st.session_state:
        st.session_state.test_date = date.today()
    with st.expander(f"Group {group_number}: {group['sounds_preview']}  ·  "
                     f"{st.session_state.test_date.strftime('%-d %b %Y')}"):
        st.date_input("Test date", key="test_date")
    tested_on = st.session_state.test_date

    prefill = backend.latest_results_for_group(student["id"], group["id"])
    this_row = next((r for r in rows if r["group_number"] == group_number), None)
    if this_row and this_row["last_tested_on"]:
        st.caption(
            f"Last tested {fmt_date(this_row['last_tested_on'])} · "
            f"{this_row['acquired']}/{this_row['total_sounds']} secure — "
            "change only what moved."
        )

    sounds = backend.list_sounds(group_id=group["id"])

    # --- bulk shortcut: a child who knows the whole set shouldn't cost 6 taps
    st.caption("Whole group the same? Set all six at once:")
    bulk_cols = st.columns(3)
    for i, (code, label) in enumerate(STATUSES):
        if bulk_cols[i].button(label, key=f"bulk_{code}", use_container_width=True):
            for snd in sounds:
                st.session_state[_sound_key(student["id"], group["id"], snd["id"])] = \
                    STATUS_TO_LABEL[code]
            st.rerun()

    # --- the six sounds ----------------------------------------------------
    for snd in sounds:
        key = _sound_key(student["id"], group["id"], snd["id"])
        default = STATUS_TO_LABEL.get(prefill.get(snd["id"]))
        c1, c2 = st.columns([1, 3])
        c1.markdown(
            f'<div class="sound-card">'
            f'<span class="sound-grapheme">{snd["grapheme"]}</span>'
            # The example word doubles as the disambiguator for the two
            # sounds written "oo" and the two written "th".
            f'<span class="sound-meta">{snd["example_word"] or snd["label"]}</span></div>'
            f'<div class="sound-action">{snd["action_hint"] or ""}</div>',
            unsafe_allow_html=True,
        )
        with c2:
            # Seed the last test's result into session state once, instead of
            # passing `default=`. "Mark all" also writes these keys, and a
            # widget given both a default and a session-state value makes
            # Streamlit print a warning under every sound. Seeding once keeps
            # taps sticky across reruns and gives each widget one source.
            if key not in st.session_state:
                st.session_state[key] = default
            st.segmented_control(
                snd["label"], STATUS_LABELS,
                key=key, label_visibility="collapsed",
            )

    marked = {
        snd["id"]: LABEL_TO_STATUS[st.session_state[_sound_key(student["id"], group["id"], snd["id"])]]
        for snd in sounds
        if st.session_state.get(_sound_key(student["id"], group["id"], snd["id"]))
    }

    st.divider()
    with st.expander("Add a note (optional)"):
        st.caption("Skip this during a live test — it is never required to save.")
        st.text_area("Note", key=f"note_{student['id']}_{group['id']}",
                     label_visibility="collapsed")

    col_s, col_i = st.columns([1, 3])
    save = col_s.button("Save test", type="primary", use_container_width=True,
                        disabled=not marked)
    col_i.markdown(
        f"<div style='padding-top:.5rem;color:#6b7280'>{len(marked)} of "
        f"{len(sounds)} sounds marked</div>",
        unsafe_allow_html=True,
    )

    if save:
        note = st.session_state.get(f"note_{student['id']}_{group['id']}")
        backend.save_test_session(
            student["id"], group["id"], tested_on, marked, note=note
        )
        # Drop the widget state so the next visit reflects what was saved
        # rather than a stale in-session tap.
        for snd in sounds:
            st.session_state.pop(_sound_key(student["id"], group["id"], snd["id"]), None)
        st.session_state.pop(f"note_{student['id']}_{group['id']}", None)
        acquired = sum(1 for v in marked.values() if v == "acquired")
        st.success(
            f"Saved Group {group_number} for {student['name']} — "
            f"{acquired}/{len(sounds)} secure."
        )
        st.rerun()

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

def _checkin_column_config():
    config = {
        short: st.column_config.SelectboxColumn(
            short, options=RATING_SCALE, help=f"{name} — {desc}",
        )
        for (_f, short, name, desc) in SKILL_CRITERIA
    }
    config["Student"] = st.column_config.TextColumn("Student", disabled=True, width="small")
    config["Phonics"] = st.column_config.TextColumn(
        "Phonics", disabled=True, width="small",
        help="Read-only. Comes from the Phonics test screen — never typed here.",
    )
    config["Notes"] = st.column_config.TextColumn("Notes", width="medium")
    return config


def render_class_checkin(backend):
    st.subheader("Class check-in")
    st.caption(
        "Rate the whole class in one grid. It starts from each student's last "
        "check-in, so you only change what moved. Letter sounds are not here — "
        "they come from the Phonics test screen and show as a read-only column."
    )

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

    latest = backend.latest_checkins([s["id"] for s in students])
    progress = backend.group_progress([s["id"] for s in students])

    rows = []
    for s in students:
        last = latest.get(s["id"], {})
        row = {
            "Student": s["name"],
            "Phonics": compact_progress(group_rows_for(progress, s["id"])),
        }
        for field, short, _name, _desc in SKILL_CRITERIA:
            row[short] = INT_TO_RATING.get(last.get(field))
        row["Notes"] = ""
        rows.append(row)

    with st.expander("What the columns mean"):
        for _f, short, name, desc in SKILL_CRITERIA:
            st.markdown(f"- **{short}** — {name}: {desc}")
        st.caption("Scale: 1 Not yet · 2 Emerging · 3 Developing · 4 Secure")
        st.caption(
            "Letter sounds are not rated here — the Phonics column is filled "
            "in from the test screen and cannot be edited."
        )

    edited = st.data_editor(
        pd.DataFrame(rows),
        column_config=_checkin_column_config(),
        disabled=["Student", "Phonics"],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=f"grid_{class_options[class_name]}_{checkin_date.isoformat()}",
    )

    if st.button("Save class check-in", type="primary"):
        payload = []
        for s, new in zip(students, edited.to_dict("records")):
            values = {
                LABEL_TO_SKILL[label]: RATING_TO_INT.get(new[label])
                for label in SKILL_LABELS
            }
            notes = (new["Notes"] or "").strip() or None
            # A row nobody touched is a student who wasn't assessed today,
            # not a student who scored zero -- skip rather than store blanks.
            if not any(v for v in values.values()) and not notes:
                continue
            payload.append(
                {
                    "student_id": s["id"],
                    "checkin_date": checkin_date.isoformat(),
                    "notes": notes,
                    **values,
                }
            )
        if payload:
            backend.insert_checkins(payload)
            st.success(f"Check-ins saved for {len(payload)} student(s).")
            st.rerun()
        else:
            st.warning("Nothing to save — every row was empty.")


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
        checkins = backend.list_checkins(student["id"], limit=10)
        if not checkins:
            st.caption("No check-ins recorded yet.")
        else:
            hist = pd.DataFrame(
                [
                    {"Date": fmt_date(c["checkin_date"]),
                     **{short: c.get(field) for field, short, _n, _d in SKILL_CRITERIA},
                     "Notes": c.get("notes") or ""}
                    for c in checkins
                ]
            )
            st.dataframe(hist, hide_index=True, use_container_width=True)
            st.caption("1 Not yet · 2 Emerging · 3 Developing · 4 Secure")

    if not read_only:
        st.divider()
        st.markdown("**Parent sheet link**")
        base = st.text_input(
            "Your app's URL", value=st.session_state.get("app_base_url", ""),
            placeholder="https://your-app.streamlit.app", key="app_base_url",
        )
        link = f"{base.rstrip('/')}/?token={student['access_token']}" if base else \
            f"?token={student['access_token']}"
        st.code(link, language=None)
        st.caption("Private link — anyone with it can see this child's sheet.")

        if base:
            col_q, col_t = st.columns([1, 2])
            col_q.image(build_qr_png(link), width=180)
            col_t.warning(
                "**Do not print this until the app is on its final public "
                "address.** A QR code contains the whole URL, so every "
                "printed copy stops working if the address changes later."
            )
        else:
            st.info(
                "Enter the app's public URL above to generate a QR code for "
                "this child's parents."
            )


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
    # The six check-in criteria, parent wording.
    "skills": {
        "blending_rating": "Ghép âm",
        "segmenting_rating": "Tách âm",
        "letter_formation_rating": "Viết chữ",
        "pencil_grip_rating": "Cầm bút",
        "tricky_words_rating": "Từ khó",
        "participation_rating": "Tham gia trên lớp",
    },
    "scale": {
        1: "1 · Chưa làm được",
        2: "2 · Bắt đầu",
        3: "3 · Đang tiến bộ",
        4: "4 · Vững",
    },
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

    last = data.get("last_checkin")
    if last:
        st.markdown(f"### {SHEET['checkin']}")
        st.caption(fmt_date(last.get("checkin_date")))
        cols = st.columns(3)
        for i, (field, _short, _name, _desc) in enumerate(SKILL_CRITERIA):
            value = last.get(field)
            name = SHEET["skills"][field]
            cols[i % 3].markdown(
                f"**{name}** — {SHEET['scale'].get(value, '—')}" if value
                else f"{name} — —"
            )
        if last.get("notes"):
            st.info(last["notes"])


# ---------------------------------------------------------------------------
# Auth + shell
# ---------------------------------------------------------------------------

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
            st.session_state.backend = backend
            st.session_state.is_admin = backend.is_admin()
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
    st.session_state.backend = backend
    st.session_state.is_admin = backend.is_admin()
    # Supabase rotates refresh tokens: store the new one for next reload.
    set_browser_cookie(AUTH_COOKIE, new_token)
    return True


def render_teacher_app():
    backend = st.session_state.backend
    read_only = not st.session_state.get("is_admin", False)

    with st.sidebar:
        try:
            st.write(f"Logged in as **{backend.current_email()}**")
        except Exception:
            del st.session_state.backend
            st.rerun()
            return
        if getattr(backend, "is_demo", False):
            st.caption("🧪 Demo mode — local demo.db")
        if read_only:
            st.caption("👁️ Read-only access")
        if st.button("Log out"):
            backend.sign_out()
            del st.session_state.backend
            clear_browser_cookie(AUTH_COOKIE)
            st.rerun()
        st.divider()
        sections = ["Phonics test", "Class check-in", "Student progress",
                    "Students", "Classes"]
        if read_only:
            sections = ["Student progress", "Students", "Classes"]
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


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if db.USE_SUPABASE and not (db.SUPABASE_URL and db.SUPABASE_KEY):
    st.error("SUPABASE_URL / SUPABASE_KEY are not configured.")
    st.stop()

_token = st.query_params.get("token")
if _token:
    render_parent_sheet(_token)
elif "backend" in st.session_state:
    render_teacher_app()
elif db.USE_SUPABASE and try_resume_session():
    render_teacher_app()
else:
    render_login()

# Streamlit Community Cloud pins a ~46px badge to the bottom-right corner of
# every page, and it sat on top of the last row of practise cards -- hiding a
# sound a parent is meant to work on. A spacer is deliberately used instead of
# padding Streamlit's own container: those class names are internal and change
# between releases, so a selector here would break silently on an upgrade.
st.markdown("<div style='height:4rem'></div>", unsafe_allow_html=True)
