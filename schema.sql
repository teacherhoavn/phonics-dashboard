-- ============================================================
-- Jolly Phonics Progress Dashboard -- schema
--
-- Standalone: this project shares no database, config or code with
-- fable-dashboard. Run this file, then seed_phonics.sql, then
-- rls_policies.sql, in that order, in the Supabase SQL editor.
-- ============================================================

-- Needed for gen_random_uuid() / gen_random_bytes().
create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- Roster
-- ------------------------------------------------------------

create table if not exists classes (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  level text,
  archived boolean not null default false,
  created_at timestamptz default now()
);

create table if not exists students (
  id uuid primary key default gen_random_uuid(),
  class_id uuid references classes(id),
  name text not null,
  -- Parent's name and phone kept apart: her register has them as separate
  -- columns, and a combined field makes names unsearchable and numbers
  -- awkward to call from a phone.
  parent_name text,
  parent_contact text,
  -- Small base64 JPEG in the row itself, so a headshot is reachable only
  -- through the same paths as the rest of the student data.
  photo_b64 text,
  -- Per-student secret for the parent sheet (?token=...). Generated here so
  -- it is never guessable from anything the teacher types.
  access_token text unique not null default encode(gen_random_bytes(16), 'hex'),
  archived boolean not null default false,
  -- Her paper register has a fixed numbered order, and matching it is what
  -- lets her find a child mid-lesson. Null sorts last, so a newly added
  -- student appears at the bottom rather than jumping into the middle.
  order_index int,
  created_at timestamptz default now()
);

create index if not exists students_class_idx on students(class_id);

-- ------------------------------------------------------------
-- Jolly Phonics reference data (7 groups, 42 letter sounds)
--
-- Seeded by seed_phonics.sql, not created by the teacher. It is a
-- published scheme, so the app treats it as read-only reference data.
-- ------------------------------------------------------------

create table if not exists phonics_groups (
  id uuid primary key default gen_random_uuid(),
  group_number int not null unique check (group_number between 1 and 7),
  -- "s a t i p n" -- shown in pickers so she can find a group by its sounds.
  sounds_preview text not null
);

create table if not exists phonics_sounds (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references phonics_groups(id) on delete cascade,
  -- Stable key, safe to reference from code. NOT the grapheme: group 5 has
  -- two sounds written "oo" and group 6 has two written "th", so the printed
  -- form alone cannot identify a sound. Hence oo_short/oo_long,
  -- th_unvoiced/th_voiced.
  code text not null unique,
  -- What is actually printed on the flashcard ("s", "oo", "th", "c k").
  grapheme text not null,
  -- Disambiguated for the teacher's screen ("oo (book)", "th (this)").
  label text not null,
  example_word text,
  -- The Jolly Phonics action, as a one-line reminder during a test.
  action_hint text,
  order_index int not null
);

create index if not exists phonics_sounds_group_idx on phonics_sounds(group_id, order_index);

-- ------------------------------------------------------------
-- Phonics group tests (the tap-only 1:1 test screen)
--
-- One session = one student, one group, one sitting. Results are stored
-- per sound as an immutable history; a student's *current* status for a
-- sound is derived from the most recent session (see the views below)
-- rather than stored as a counter, so re-tests and corrections can never
-- leave a stale "mastered" flag behind.
-- ------------------------------------------------------------

create table if not exists test_sessions (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id) on delete cascade,
  group_id uuid not null references phonics_groups(id),
  tested_on date not null default current_date,
  -- Optional, and never required to finish a test: typing during a live
  -- test is the exact cost this app exists to remove.
  note text,
  created_at timestamptz default now()
);

create index if not exists test_sessions_student_idx on test_sessions(student_id, tested_on desc);

create table if not exists test_results (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references test_sessions(id) on delete cascade,
  sound_id uuid not null references phonics_sounds(id),
  status text not null check (status in ('not_yet', 'practising', 'acquired')),
  unique (session_id, sound_id)
);

create index if not exists test_results_session_idx on test_results(session_id);

-- ------------------------------------------------------------
-- Class check-in: the skills a letter-sound test cannot measure.
--
-- Deliberately does NOT include letter-sound recognition -- that is what
-- the group test measures, sound by sound. Re-rating it here would mean
-- entering the same judgement twice, so the check-in grid shows the tested
-- progress as a read-only column instead.
--
-- Scale is 1-4 (1 Not yet, 2 Emerging, 3 Developing, 4 Secure). Four
-- points, not five: for beginners the middle of a 5-point scale is noise,
-- and fewer options means a faster grid.
-- ------------------------------------------------------------

create table if not exists skill_checkins (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(id) on delete cascade,
  checkin_date date not null default current_date,
  blending_rating int check (blending_rating between 1 and 4),
  segmenting_rating int check (segmenting_rating between 1 and 4),
  letter_formation_rating int check (letter_formation_rating between 1 and 4),
  pencil_grip_rating int check (pencil_grip_rating between 1 and 4),
  tricky_words_rating int check (tricky_words_rating between 1 and 4),
  participation_rating int check (participation_rating between 1 and 4),
  notes text,
  created_at timestamptz default now()
);

create index if not exists skill_checkins_student_idx on skill_checkins(student_id, checkin_date desc);

-- ------------------------------------------------------------
-- Derived views
--
-- security_invoker = on is required: a Postgres view otherwise runs with
-- its owner's privileges and would hand out rows that the querying user's
-- RLS policies forbid.
-- ------------------------------------------------------------

-- A student's latest recorded status for each sound they have been tested on.
create or replace view student_sound_current
with (security_invoker = on) as
select distinct on (ts.student_id, tr.sound_id)
  ts.student_id,
  tr.sound_id,
  tr.status,
  ts.tested_on
from test_sessions ts
join test_results tr on tr.session_id = ts.id
order by ts.student_id, tr.sound_id, ts.tested_on desc, ts.created_at desc;

-- Per-student, per-group roll-up: the "mastered groups 1-3, working on 4" view.
-- Every student is crossed with every group so untested groups still appear
-- with a zero count, which is what the progress screen needs to show.
create or replace view student_group_progress
with (security_invoker = on) as
select
  s.id as student_id,
  g.id as group_id,
  g.group_number,
  count(ps.id) as total_sounds,
  count(*) filter (where c.status = 'acquired') as acquired,
  count(*) filter (where c.status = 'practising') as practising,
  count(*) filter (where c.status = 'not_yet') as not_yet,
  max(c.tested_on) as last_tested_on
from students s
cross join phonics_groups g
join phonics_sounds ps on ps.group_id = g.id
left join student_sound_current c
  on c.student_id = s.id and c.sound_id = ps.id
group by s.id, g.id, g.group_number;
