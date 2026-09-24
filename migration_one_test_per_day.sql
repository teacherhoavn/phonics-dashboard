-- Run this ONCE in the Supabase SQL editor.
--
-- What it fixes: pressing "Save test" more than once recorded a separate
-- test each time, so a child's parent page listed the same test six or
-- seven times in one day. The app no longer does that -- saving again now
-- overwrites the test already on record for that date -- but the duplicates
-- already saved are still in the database, and this clears them.
--
-- Which one is kept: the LAST one saved for each child, group and date.
-- Every save wrote the whole form, so the newest row is what was on screen
-- when she finished. Deleting a test takes its sounds and words with it
-- (on delete cascade), so nothing is left behind half-attached.
--
-- The whole thing is one transaction: if any part fails, nothing changes.

-- ---------------------------------------------------------------------------
-- Optional: look before you delete. Run this on its own first -- it changes
-- nothing and shows how many duplicate tests will go, and for whom.
-- ---------------------------------------------------------------------------
--   select s.name, g.group_number, t.tested_on, count(*) as tests_recorded
--   from test_sessions t
--   join students s on s.id = t.student_id
--   join phonics_groups g on g.id = t.group_id
--   group by s.name, g.group_number, t.tested_on
--   having count(*) > 1
--   order by t.tested_on desc, s.name;

begin;

delete from test_sessions t
using test_sessions keep
where t.student_id = keep.student_id
  and t.group_id   = keep.group_id
  and t.tested_on  = keep.tested_on
  -- Compared as a pair so a tie on created_at still picks one and only one
  -- row to keep, rather than deleting both or neither.
  and (t.created_at, t.id) < (keep.created_at, keep.id);

-- Belt and braces: even if some future version of the app gets this wrong,
-- the database will refuse a second test for the same child, group and date.
alter table test_sessions
  add constraint test_sessions_one_per_day
  unique (student_id, group_id, tested_on);

commit;

-- Afterwards, the query at the top should return no rows at all.
