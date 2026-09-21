-- ============================================================
-- Row Level Security for the Jolly Phonics dashboard.
-- Run after schema.sql and seed_phonics.sql.
--
--   - "authenticated" users come in two roles:
--       admins  (rows in admin_users) -- full CRUD
--       viewers (any other Auth user) -- read-only
--     After creating the teacher's account, promote it with:
--       insert into admin_users (user_id)
--       select id from auth.users where email = 'her@example.com';
--   - "anon" = the publishable key used by the pre-auth login page and
--     the parent sheet. Anon gets NO direct table access; the only path
--     to student data is get_student_sheet(), gated on the per-student
--     access_token.
-- ============================================================

create table if not exists admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz default now()
);

-- Only the is_admin() security-definer function ever reads this table.
alter table admin_users enable row level security;
revoke all on admin_users from anon, authenticated;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from admin_users where user_id = auth.uid())
$$;

revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to authenticated;

alter table classes         enable row level security;
alter table students        enable row level security;
alter table phonics_groups  enable row level security;
alter table phonics_sounds  enable row level security;
alter table test_sessions   enable row level security;
alter table test_results    enable row level security;
alter table checkin_criteria enable row level security;
alter table checkins         enable row level security;
alter table checkin_scores   enable row level security;

-- Reads open to every authenticated user; writes gated on admin.
do $$
declare t text;
begin
  foreach t in array array[
    'classes', 'students', 'phonics_groups', 'phonics_sounds',
    'test_sessions', 'test_results',
    'checkin_criteria', 'checkins', 'checkin_scores'
  ] loop
    execute format('drop policy if exists "authenticated read access" on %I', t);
    execute format(
      'create policy "authenticated read access" on %I
         for select to authenticated using (true)', t);
    execute format('drop policy if exists "admin write access" on %I', t);
    execute format(
      'create policy "admin write access" on %I
         for all to authenticated
         using (public.is_admin()) with check (public.is_admin())', t);
  end loop;
end $$;

-- Defense in depth: Supabase grants anon table-level privileges by default
-- on new tables. RLS alone already blocks anon (no policy = no rows), but
-- revoking the grants means a future RLS misconfiguration still cannot
-- expose data.
revoke all on classes, students, phonics_groups, phonics_sounds,
  test_sessions, test_results,
  checkin_criteria, checkins, checkin_scores from anon;

-- The two derived views are security_invoker (see schema.sql), so they
-- enforce the policies above on behalf of whoever queries them.
grant select on student_sound_current, student_group_progress,
  checkin_averages to authenticated;
revoke all on student_sound_current, student_group_progress,
  checkin_averages from anon;

-- ============================================================
-- Parent sheet: one token-gated RPC.
--
-- security definer runs with the owner's privileges (bypassing RLS
-- internally), but only ever returns data for the single student matching
-- the token argument.
--
-- The payload is deliberately small: who the child is, which groups are
-- done, and the handful of sounds to practise at home. No history, no
-- per-test breakdown -- a parent needs today's homework, not an audit log.
-- ============================================================

create or replace function public.get_student_sheet(p_access_token text)
returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  v_student_id uuid;
  v_result json;
begin
  select s.id into v_student_id
  from students s
  where s.access_token = p_access_token and s.archived = false;

  if v_student_id is null then
    return null;
  end if;

  select json_build_object(
    'student', (
      select json_build_object('name', s.name, 'photo_b64', s.photo_b64,
                               'class_name', c.name)
      from students s left join classes c on c.id = s.class_id
      where s.id = v_student_id
    ),
    'groups', (
      select coalesce(json_agg(json_build_object(
        'group_number', p.group_number, 'sounds_preview', g.sounds_preview,
        'total_sounds', p.total_sounds, 'acquired', p.acquired,
        'practising', p.practising, 'last_tested_on', p.last_tested_on
      ) order by p.group_number), '[]'::json)
      from student_group_progress p
      join phonics_groups g on g.id = p.group_id
      where p.student_id = v_student_id
    ),
    'practise', (
      select coalesce(json_agg(json_build_object(
        'code', ps.code, 'grapheme', ps.grapheme, 'label', ps.label,
        'example_word', ps.example_word, 'status', c.status,
        'group_number', g.group_number
      ) order by g.group_number, ps.order_index), '[]'::json)
      from student_sound_current c
      join phonics_sounds ps on ps.id = c.sound_id
      join phonics_groups g on g.id = ps.group_id
      where c.student_id = v_student_id and c.status <> 'acquired'
    ),
    'timeline', (
      select coalesce(json_agg(x), '[]'::json) from (
        select json_build_object(
          'tested_on', t.tested_on, 'group_number', g.group_number,
          'secure', (select count(*) from test_results r
                     where r.session_id = t.id and r.status = 'acquired'),
          'total', (select count(*) from test_results r where r.session_id = t.id)
        ) as x
        from test_sessions t join phonics_groups g on g.id = t.group_id
        where t.student_id = v_student_id
        order by t.tested_on desc, t.created_at desc limit 10
      ) sub
    ),
    -- Criteria the teacher has chosen to show parents, in her order.
    'criteria', (
      select coalesce(json_agg(json_build_object(
        'code', cc.code, 'name_vi', cc.name_vi
      ) order by cc.order_index), '[]'::json)
      from checkin_criteria cc
      where cc.active and cc.parent_visible
    ),
    -- The web chart: each criterion averaged over the last four attended
    -- lessons, so one off-day does not reshape what a parent sees.
    'radar', (
      select coalesce(json_object_agg(code, avg_score), '{}'::json) from (
        select cc.code, round(avg(s.score)::numeric, 2) as avg_score
        from checkin_scores s
        join checkin_criteria cc on cc.id = s.criterion_id
        where cc.active and cc.parent_visible and s.checkin_id in (
          select id from checkins
          where student_id = v_student_id and absent = false
          order by checkin_date desc limit 4)
        group by cc.code
      ) r
    ),
    -- One point per attended lesson, oldest first. Absences are absent
    -- from this list entirely, so the line shows a gap and never a zero.
    'trend', (
      select coalesce(json_agg(json_build_object(
        'date', checkin_date, 'average', average) order by checkin_date), '[]'::json)
      from (select * from checkin_averages where student_id = v_student_id
            order by checkin_date desc limit 12) t
    ),
    'last_checkin', (
      select json_build_object(
        'checkin_date', c.checkin_date, 'absent', c.absent, 'notes', c.notes,
        'scores', (
          select coalesce(json_object_agg(cc.code, s.score), '{}'::json)
          from checkin_scores s join checkin_criteria cc on cc.id = s.criterion_id
          where s.checkin_id = c.id and cc.active and cc.parent_visible
        ))
      from checkins c
      where c.student_id = v_student_id
      order by c.checkin_date desc limit 1
    )
  ) into v_result;

  return v_result;
end;
$$;

revoke all on function public.get_student_sheet(text) from public;
grant execute on function public.get_student_sheet(text) to anon, authenticated;
