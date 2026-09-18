# Jolly Phonics Progress Dashboard

A Streamlit + Supabase app for a solo Jolly Phonics teacher. Built around one
goal: **a live 1:1 letter-sound test should cost six taps and no typing.**

Two faces, one app:

- **Teacher area**, behind Supabase Auth email/password.
- **Parent sheet**, read-only, reached via a private link
  (`?token=<student-access-token>` — no login).

This is a standalone project. It shares no database, credentials or code with
any other app in this folder.

## The screens

| Screen | What it is for |
| --- | --- |
| **Phonics test** | The fast one. Tap a child → the group they're on is pre-selected → tap once per sound → Save. Nothing is written until Save, so tapping never waits on the network. |
| **Class check-in** | Whole-class grid for the skills a sound test can't measure (blending, segmenting, letter formation, pencil grip, tricky words, joining in). Pre-filled from each child's last check-in, so you only change what moved. |
| **Student progress** | Per-child roll-up: "Groups 1–3 mastered · working on Group 4 (3/6)", the seven group cards, test history, and the parent link. |
| **Students / Classes** | Roster admin, with archiving and optional headshots. |

### Why letter sounds are not in the check-in grid

The check-in grid covers six skills; letter-sound recognition is deliberately
not one of them. The test screen already measures it sound by sound, and
re-rating it in the grid would mean entering the same judgement twice. Instead
the grid shows a **read-only `Phonics` column** fed from the test results
(`G1–3 ✓ · G4 3/6`), so the two screens stay one source of truth.

### Statuses and scales

- **Test statuses** (3): `Got it` / `Nearly` / `Not yet`. Three, not five — a
  snap judgement made while a child waits shouldn't offer room to hesitate.
  Labels are short and similar in length so they sit three-across on a phone.
- **Check-in scale** (1–4): Not yet · Emerging · Developing · Secure. Four, not
  five — for beginners the middle of a five-point scale carries no information.
- **Group mastery** is all-or-nothing: all six sounds `Got it`. "5 of 6" is not
  mastery of a group whose point is the complete set.

## The 42 sounds

Seven groups of six, standard Jolly Phonics teaching order, seeded by
`seed_phonics.sql`:

| Group | Sounds |
| --- | --- |
| 1 | s a t i p n |
| 2 | c k · e h r m d |
| 3 | g o u l f b |
| 4 | ai j oa ie ee or |
| 5 | z w ng v oo(book) oo(moon) |
| 6 | y x ch sh th(thin) th(this) |
| 7 | qu ou oi ue er ar |

Two things worth knowing:

- Group 2 opens with **`c k`** — the two letters that both make the /k/ sound,
  taught together. It is not the `ck` digraph, which comes later with the
  alternative spellings.
- **`oo`** and **`th`** each appear twice with different sounds. Rows are keyed
  on a stable `code` (`oo_short`, `oo_long`, `th_unvoiced`, `th_voiced`) rather
  than on the printed grapheme, which would collide.

Editions vary slightly. To change a sound's example word or action hint, edit
`seed_phonics.sql` and re-run it — it matches on `code` and updates in place,
leaving every test result intact.

## Look and feel, and how to change your mind about it

The default theme is **vivid**: high contrast, colourful, larger type. It was
built for a teacher with low vision, so "is this readable?" is answered by
numbers rather than by eye — `theme.py` carries a WCAG contrast function and
`test_theme.py` enforces the floors:

- body text at **7:1 or better** (WCAG AAA) on both white and panel backgrounds
- every other text/background pair at **4.5:1 or better** (AA), including all
  seven group colours used *both* as a fill under white text and as text on
  white
- borders and focus rings at 3:1 or better
- **nothing is signalled by colour alone.** Each status carries a distinct
  shape as well as a colour and a word: `✓ Got it`, `~ Nearly`, `✗ Not yet`.
  Red/amber/green with nothing else is the most common accessibility mistake
  in a progress UI, and it is the one a colour-blind or low-vision reader
  actually loses.

Colour also does real work rather than just decorating: each of the seven
phonics groups has its own colour, so a group is recognisable at a glance on
the progress strip and the parent sheet.

Two fixes worth knowing about, because neither is visible in a palette file:

- Streamlit renders `st.caption` at **0.6 opacity**, which blended dark text
  toward white and left it around **3.6:1 at 14.7px** — below the AA floor, on
  text that carries actual instructions. Captions are forced back to full
  opacity, a checked colour and 1rem.
- Tap targets on the test screen are **52px**, above the 44px minimum.

### Reverting

Set one value in `.env` (or Streamlit secrets):

```
PHONICS_THEME=classic
```

That restores the original quieter blue-grey design and type scale. No other
change is needed — `app.py` reads every colour, symbol and font size from
`theme.py`, and all of `BASE_CSS` is written against CSS custom properties
that the active theme fills in.

`classic` is preserved exactly as it was, and `test_theme.py` asserts those
original values so nobody can "improve" it and make the revert lie. It does
**not** meet AA — its amber "Nearly" is 2.45:1 against white — which is
precisely why `vivid` is the default. A test documents that too.

**The mobile layout work is separate from the theme** and survives the
revert: one-row sounds, the collapsed student picker and the hidden chrome
are in `BASE_CSS`, not in either palette. Switching to `classic` changes
colour and type, not layout.

## On a phone

The Phonics test screen is built for a phone held one-handed during a lesson,
and is checked at 375px wide:

- Status buttons are 44px tall — Streamlit's default 32px is a miss-prone
  target, and this screen is nothing but tapping.
- Each sound stays on **one row** (big grapheme left, three buttons right).
  Streamlit stacks columns below ~640px, which otherwise turned six sounds
  into twelve rows and pushed Save two screens down.
- The class picker and the roster of name buttons are hidden once a child is
  chosen, behind a **Change child** button. During a session the class never
  changes and the child changes every few minutes, but on a phone those two
  controls cost a screenful of scrolling each.
- The app banner, the first-run help text, the Jolly Phonics action hints and
  the sound lists on the group cards are hidden under 640px. They are useful
  on a laptop and pure overhead mid-test.
- The seven group cards stay a single strip rather than stacking into seven
  blocks — this matters most on the parent sheet, which parents open on a
  phone.

Net effect on a 375×812 screen: the first sound moved from 1301px down the
page to 564px, each sound from 110px tall to 60px, and Save from 2076px to
1044px. One short scroll brings all six sounds and the Save button into view
together.

**The class check-in grid is the exception.** It is a nine-column
spreadsheet, so on a phone it scrolls sideways inside its own box (the page
itself never scrolls sideways). It is usable there, but it is genuinely
nicer on a tablet or laptop. The phonics test — the one run live during a
lesson — is the phone-first screen.

## Running it locally

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m streamlit run app.py
```

With no `.env`, the app starts in **demo mode**: a local SQLite `demo.db`
with three fake students at different stages, no login (any email and password
gets you in). That is for development and review only — it has no auth and no
RLS, and nothing in `local_backend.py` runs once real credentials are set.

Delete `demo.db` to reset the demo data.

## Pointing it at a real Supabase project

This is the five-minute step. Nothing in the app code changes.

1. Create a Supabase project.
2. In the SQL editor, run in order: **`schema.sql`**, **`seed_phonics.sql`**,
   **`rls_policies.sql`**.
3. Create the teacher's account: Supabase Dashboard → Authentication → Users →
   Add user (email + password).
4. Promote that account to admin:

   ```sql
   insert into admin_users (user_id)
   select id from auth.users where email = 'her@example.com';
   ```

5. Copy `.env.example` to `.env` and fill in `SUPABASE_URL` and `SUPABASE_KEY`
   (the anon/publishable key — **never** the service-role key).

Restart, and the app switches to Supabase automatically: `db.USE_SUPABASE` is
true as soon as both values are present.

## Deploying (Streamlit Community Cloud, free)

Parents can only use their link once the app is on a public URL.

1. Push this folder to a GitHub repository. `.gitignore` already excludes
   `.env` and `demo.db`.
2. At https://share.streamlit.io sign in with GitHub → New app → pick the repo,
   branch, and `app.py`.
3. In the app's **Settings → Secrets**, add:

   ```toml
   SUPABASE_URL = "https://your-project-ref.supabase.co"
   SUPABASE_KEY = "your-anon-key"
   ```

4. Deploy. Paste the public URL into the "Your app's URL" box on the Student
   progress page so the parent links it generates are complete.

Streamlit Cloud secrets take priority over `.env` (see `db.get_setting`), so
the same commit works locally and deployed.

## The parent sheet is output only

Parents **read** the sheet; there is no way for them to write anything back.
An in-app reply was built and then deliberately removed: Zalo is the channel
these parents already use, and a second inbox would be one more thing for
the teacher to check. The app exists to save her time, not to add a queue.

The sheet shows the child's group progress, the handful of sounds to practise
at home, and a **teacher involvement timeline** — the dates she tested and
what the child scored. That timeline is built from `test_sessions`, which
nothing outside the teacher's login can write, so it stands up as proof of
work for paying parents.

`test_parent_sheet.py` asserts that no parent-writable table or write method
exists, so a reply path can only come back as a deliberate decision rather
than by drift.

### Why there is no phrase library

An earlier design had a library of tappable Vietnamese tips ("don't add a
schwa to /b/"). It was dropped deliberately: machine-translated *pedagogical
advice* is not safe to put in front of parents. If it comes back, the right
shape is for the teacher to write her own phrases once, in her own words,
and tap to reuse them — not for them to be translated for her.

⚠️ The parent-facing strings that do exist (about 15 short UI labels, in the
`SHEET` dict in `app.py`) are a first draft and **must be reviewed by the
teacher before any parent sees them.** Each carries its English meaning as a
comment.

## QR codes

Each child's parents get one private link, issued once as a QR code from the
Student progress screen.

**Do not print any QR code until the app is on its final public URL.** A QR
encodes the whole address, so every printed copy dies if the address changes
— and these are meant to be issued once and last. The order is: her Supabase
and Streamlit accounts exist → the public URL is fixed → then print.

A token cannot be un-shared. If a link leaks, rotating it invalidates that
child's printed QR, so the reprint is the cost.

## Security model

- Logged-in users have one of two roles, enforced by RLS in the database, not
  just hidden in the UI:
  - **Admin** (rows in `admin_users`): full CRUD.
  - **Viewer** (any other Auth user): can read everything, cannot write. The
    app shows a read-only interface *and* the database rejects writes made
    directly with their session.
- **Parents**: the anon key has zero direct table access (RLS plus revoked
  grants). The sheet reads exclusively through the
  `get_student_sheet(token)` security-definer function, which returns only the
  one student matching the token.
- **Parents cannot write at all.** There is no parent write path: the anon
  key has no table privileges and `get_student_sheet` is the only function
  it may execute. A leaked link exposes one child's progress; it can never
  change anything.
- Both derived views are declared `security_invoker = on`, so they enforce the
  caller's policies instead of the view owner's.

To add a read-only helper: Supabase Dashboard → Authentication → Users → Add
user, then share the app URL. New accounts are viewers by default.

## Data model

```
classes ──< students ──< test_sessions ──< test_results >── phonics_sounds >── phonics_groups
                     └─< skill_checkins
```

`test_sessions` + `test_results` are an **append-only history**: one row per
sound per sitting. A student's *current* status for a sound is derived by the
`student_sound_current` view (latest session wins), and `student_group_progress`
rolls that up per group. Nothing stores a "mastered" flag, so a re-test or a
deleted session can never leave a stale one behind.

## Files

| File | |
| --- | --- |
| `app.py` | All Streamlit UI and the two main screens. |
| `theme.py` | Palettes, type scale, all CSS, and the WCAG contrast function. |
| `rollup.py` | Pure progress logic ("mastered 1–3, working on 4"). No I/O. |
| `db.py` | Every database call, behind named functions. Picks the backend. |
| `local_backend.py` | SQLite stand-in for demo mode. Dev only. |
| `schema.sql` | Tables and the two derived views. |
| `seed_phonics.sql` | The 7 groups and 42 sounds. Idempotent. |
| `rls_policies.sql` | Roles, RLS policies, and the parent-sheet function. |
| `test_rollup.py` | Tests for `rollup.py` and the seed data. |
| `test_theme.py` | Contrast floors and theme-switching tests. |
| `test_parent_sheet.py` | Parent sheet contents, and that it stays read-only. |

## Tests

```sh
venv/bin/python test_rollup.py
venv/bin/python test_theme.py
venv/bin/python test_parent_sheet.py
```

Covers the roll-up rules and asserts the seed file really holds 42 uniquely
coded sounds in 7 groups of 6 — and that `local_backend.py`, which parses that
same file, agrees with it.

## Not built (and why)

- **Badges and weekly streaks.** The ESL app's streak measures weekly check-in
  averages, which doesn't map onto a scheme where progress is "24 of 42 sounds".
  The progress bar and group cards carry that meaning already.
- **Radar / trend charts.** Six criteria on a 1–4 scale for a five-year-old is
  not enough signal to justify the surface area.
- **Tricky words as testable items.** Currently one check-in rating. Making them
  tappable like sounds is the natural next step; it would need a new item table
  rather than a change to `phonics_sounds`.

The parent sheet is in English. Every visible string is in the `SHEET` dict at
the top of that section, so translating it is a one-dict change.
