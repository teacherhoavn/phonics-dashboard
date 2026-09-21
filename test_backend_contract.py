"""The two backends must stay interchangeable.

app.py talks to whichever backend is configured and never checks which one
it has. If a method is added to one and not the other, the app works in demo
mode on a laptop and raises AttributeError on the teacher's live app -- which
is exactly how a release once reached her broken.

Run:  venv/bin/python test_backend_contract.py
"""

import inspect

from db import SupabaseBackend
from local_backend import SqliteBackend

# Not part of the shared contract: the parent sheet is served by a Postgres
# function for Supabase, and reimplemented in Python for the demo file.
DEMO_ONLY = {"get_student_sheet", "conn", "DEFAULT_CRITERIA"}
SUPABASE_ONLY = {"client"}


def public(cls):
    return {
        name for name, value in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def test_both_backends_expose_the_same_methods():
    supa = public(SupabaseBackend) - SUPABASE_ONLY
    demo = public(SqliteBackend) - DEMO_ONLY
    missing_in_demo = sorted(supa - demo)
    missing_in_supabase = sorted(demo - supa)
    assert not missing_in_demo, f"SqliteBackend is missing: {missing_in_demo}"
    assert not missing_in_supabase, f"SupabaseBackend is missing: {missing_in_supabase}"


def test_shared_methods_take_the_same_arguments():
    """A call written for one backend has to work on the other."""
    shared = (public(SupabaseBackend) - SUPABASE_ONLY) & (public(SqliteBackend) - DEMO_ONLY)
    for name in sorted(shared):
        a = list(inspect.signature(getattr(SupabaseBackend, name)).parameters)
        b = list(inspect.signature(getattr(SqliteBackend, name)).parameters)
        assert a == b, f"{name}: SupabaseBackend{a} vs SqliteBackend{b}"


def test_the_check_in_methods_the_screens_call_exist():
    """Named explicitly, because these are the ones that broke live."""
    for name in ("list_criteria", "add_criterion", "update_criterion",
                 "save_checkin", "checkins_on", "latest_checkins",
                 "list_student_checkins"):
        assert hasattr(SupabaseBackend, name), f"SupabaseBackend.{name}"
        assert hasattr(SqliteBackend, name), f"SqliteBackend.{name}"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); passed += 1; print(f"  ok  {name}")
    print(f"\n{passed} passed")
