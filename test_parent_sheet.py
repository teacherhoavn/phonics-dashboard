"""Parent sheet tests.

The sheet is strictly OUTPUT: parents read it, and there is no path by which
they can write anything back. Parents reply on Zalo, which is the channel
they already use — an in-app reply would be one more inbox for the teacher
to check.

These tests hold that line, and cover what the sheet actually shows.

Run:  venv/bin/python test_parent_sheet.py
"""

import os
import tempfile

import local_backend


def fresh():
    """A throwaway demo database, so tests never touch the real one."""
    local_backend.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    b = local_backend.SqliteBackend()
    token = b.conn.execute(
        "select access_token from students where name like 'An%'"
    ).fetchone()["access_token"]
    return b, token


def test_sheet_is_read_only_no_write_path_exists():
    """If a write path ever comes back, it should be a deliberate decision."""
    b, _ = fresh()
    for attr in ("submit_parent_response", "recent_parent_responses"):
        assert not hasattr(b, attr), f"{attr} should not exist on the backend"
    assert not os.path.exists("test_parent.py"), "old reply tests should be gone"


def test_no_parent_writable_tables_remain():
    b, _ = fresh()
    tables = {
        r["name"] for r in b.conn.execute(
            "select name from sqlite_master where type='table'"
        )
    }
    assert "parent_responses" not in tables
    assert "parent_response_sounds" not in tables


def test_sheet_returns_the_named_student_only():
    b, token = fresh()
    sheet = b.get_student_sheet(token)
    assert sheet["student"]["name"].startswith("An")
    assert set(sheet) == {"student", "groups", "practise", "timeline",
                          "criteria", "radar", "trend", "last_checkin"}


def test_bad_token_returns_nothing():
    b, _ = fresh()
    assert b.get_student_sheet("not-a-real-token") is None


def test_archived_student_link_stops_working():
    b, token = fresh()
    sid = b.conn.execute(
        "select id from students where access_token=?", (token,)
    ).fetchone()["id"]
    b.set_student_archived(sid, True)
    assert b.get_student_sheet(token) is None


def test_practise_list_holds_only_unfinished_sounds():
    b, token = fresh()
    practise = b.get_student_sheet(token)["practise"]
    assert practise, "the demo student should have sounds left to practise"
    assert all(p["status"] != "acquired" for p in practise)


def test_practise_list_is_in_teaching_order():
    b, token = fresh()
    practise = b.get_student_sheet(token)["practise"]
    keys = [(p["group_number"], p["grapheme"]) for p in practise]
    assert keys == sorted(keys, key=lambda k: k[0]) or len(keys) <= 1


def test_absence_is_never_a_zero_in_the_trend():
    """The whole reason absence is a flag: a 0 would read as "did badly"."""
    from datetime import date, timedelta

    b, token = fresh()
    sid = b.conn.execute(
        "select id from students where access_token=?", (token,)
    ).fetchone()["id"]
    crits = b.list_criteria()
    b.save_checkin(sid, date.today() - timedelta(days=2),
                   {crits[0]["id"]: 9, crits[1]["id"]: 9})
    b.save_checkin(sid, date.today() - timedelta(days=1), {}, absent=True)
    trend = b.get_student_sheet(token)["trend"]
    assert all(p["average"] > 0 for p in trend)
    assert not any(str(p["date"]).endswith(
        (date.today() - timedelta(days=1)).isoformat()[-5:]) for p in trend)


def test_not_applicable_criteria_are_left_out_of_the_average():
    """No homework set must not drag the average down."""
    from datetime import date

    b, token = fresh()
    sid = b.conn.execute(
        "select id from students where access_token=?", (token,)
    ).fetchone()["id"]
    crits = b.list_criteria()
    b.save_checkin(sid, date.today(), {crits[0]["id"]: 10, crits[1]["id"]: 10})
    trend = b.get_student_sheet(token)["trend"]
    assert trend[-1]["average"] == 10.0


def test_parent_hidden_criteria_stay_off_the_sheet():
    from datetime import date

    b, token = fresh()
    sid = b.conn.execute(
        "select id from students where access_token=?", (token,)
    ).fetchone()["id"]
    crits = b.list_criteria()
    b.update_criterion(crits[1]["id"], {"parent_visible": 0})
    b.save_checkin(sid, date.today(), {c["id"]: 9 for c in crits})
    sheet = b.get_student_sheet(token)
    assert crits[1]["code"] not in [c["code"] for c in sheet["criteria"]]
    assert crits[1]["code"] not in sheet["radar"]


def test_timeline_is_teacher_activity_newest_first():
    """This is the 'what the teacher has done' record parents see."""
    b, token = fresh()
    timeline = b.get_student_sheet(token)["timeline"]
    assert timeline, "demo student has tests"
    dates = [row["tested_on"] for row in timeline]
    assert dates == sorted(dates, reverse=True)
    for row in timeline:
        assert row["secure"] <= row["total"]
        assert "group_number" in row


def test_timeline_reflects_a_new_test():
    from datetime import date

    b, token = fresh()
    sid = b.conn.execute(
        "select id from students where access_token=?", (token,)
    ).fetchone()["id"]
    before = len(b.get_student_sheet(token)["timeline"])
    group = b.list_groups()[5]
    sounds = b.list_sounds(group_id=group["id"])
    b.save_test_session(
        sid, group["id"], date.today(), {s["id"]: "acquired" for s in sounds}
    )
    after = b.get_student_sheet(token)["timeline"]
    assert len(after) == before + 1
    assert after[0]["secure"] == after[0]["total"] == 6


def test_group_summary_covers_all_seven():
    b, token = fresh()
    groups = b.get_student_sheet(token)["groups"]
    assert sorted(g["group_number"] for g in groups) == list(range(1, 8))


def test_saving_the_same_test_twice_keeps_one_test():
    """The bug this guards: she pressed Save several times on one test and
    the parent timeline listed it as six separate tests in a day."""
    from datetime import date

    b, token = fresh()
    student = b.conn.execute(
        "select id from students where name like 'An%'").fetchone()["id"]
    group = b.list_groups()[0]
    sounds = b.list_sounds(group_id=group["id"])
    on = date(2026, 9, 24)

    before = len(b.list_test_sessions(student, limit=50))
    first = b.save_test_session(
        student, group["id"], on, {s["id"]: "acquired" for s in sounds})
    again = b.save_test_session(
        student, group["id"], on, {s["id"]: "acquired" for s in sounds})

    assert first == again, "a second save should reuse the same test"
    assert len(b.list_test_sessions(student, limit=50)) == before + 1


def test_re_saving_replaces_the_result_rather_than_adding_to_it():
    """A sound she has just un-ticked has to disappear from the record."""
    from datetime import date

    b, _ = fresh()
    student = b.conn.execute(
        "select id from students where name like 'An%'").fetchone()["id"]
    group = b.list_groups()[0]
    sounds = b.list_sounds(group_id=group["id"])
    on = date(2026, 9, 24)

    b.save_test_session(student, group["id"], on,
                        {s["id"]: "acquired" for s in sounds})
    sess = b.save_test_session(student, group["id"], on,
                               {sounds[0]["id"]: "not_yet"})

    results = b.get_session_results(sess)
    assert len(results) == 1, "the earlier sounds should be gone, not merged"
    assert results[0]["status"] == "not_yet"


def test_a_different_date_is_still_a_new_test():
    from datetime import date

    b, _ = fresh()
    student = b.conn.execute(
        "select id from students where name like 'An%'").fetchone()["id"]
    group = b.list_groups()[0]
    sound = b.list_sounds(group_id=group["id"])[0]["id"]

    a = b.save_test_session(student, group["id"], date(2026, 9, 24),
                            {sound: "acquired"})
    c = b.save_test_session(student, group["id"], date(2026, 9, 25),
                            {sound: "acquired"})
    assert a != c


def test_a_different_group_on_the_same_day_is_still_a_new_test():
    """She does test two groups in one lesson -- that is not a double save."""
    from datetime import date

    b, _ = fresh()
    student = b.conn.execute(
        "select id from students where name like 'An%'").fetchone()["id"]
    groups = b.list_groups()
    on = date(2026, 9, 24)

    a = b.save_test_session(student, groups[0]["id"], on,
                            {b.list_sounds(group_id=groups[0]["id"])[0]["id"]: "acquired"})
    c = b.save_test_session(student, groups[1]["id"], on,
                            {b.list_sounds(group_id=groups[1]["id"])[0]["id"]: "acquired"})
    assert a != c


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} passed")
