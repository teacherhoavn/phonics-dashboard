"""Tests for editing the roster.

The teacher created nineteen classes when she meant nineteen students, and
had no way to fix it herself. These cover the editing that was added so she
can, and the guard that stops a class deletion taking student data with it.

Run:  venv/bin/python test_admin.py
"""

import os
import tempfile

import local_backend


def fresh():
    local_backend.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
    b = local_backend.SqliteBackend()
    return b, b.list_classes()[0]


def test_student_can_be_renamed():
    b, _ = fresh()
    s = b.list_students()[0]
    b.update_student(s["id"], {"name": "Nguyễn Tường Vy"})
    # Look up by id: the list is sorted by name, so a rename moves the row.
    after = {x["id"]: x["name"] for x in b.list_students()}
    assert after[s["id"]] == "Nguyễn Tường Vy"


def test_student_can_move_between_classes():
    b, cls = fresh()
    b.add_class("Kid 2", None)
    other = [c for c in b.list_classes() if c["id"] != cls["id"]][0]
    s = b.list_students(class_id=cls["id"])[0]
    b.update_student(s["id"], {"class_id": other["id"]})
    assert [x["id"] for x in b.list_students(class_id=other["id"])] == [s["id"]]


def test_student_archive_round_trips():
    b, _ = fresh()
    s = b.list_students()[0]
    b.update_student(s["id"], {"archived": 1})
    assert s["id"] not in [x["id"] for x in b.list_students()]
    assert s["id"] in [x["id"] for x in b.list_students(include_archived=True)]
    b.update_student(s["id"], {"archived": 0})
    assert s["id"] in [x["id"] for x in b.list_students()]


def test_class_name_and_level_are_editable():
    b, cls = fresh()
    b.update_class(cls["id"], {"name": "Lớp Kid 1", "level": "Phonics 1"})
    got = b.list_classes()[0]
    assert got["name"] == "Lớp Kid 1" and got["level"] == "Phonics 1"


def test_empty_class_can_be_deleted():
    b, _ = fresh()
    b.add_class("Spare", None)
    spare = [c for c in b.list_classes() if c["name"] == "Spare"][0]
    b.delete_class(spare["id"])
    assert "Spare" not in [c["name"] for c in b.list_classes()]


def test_class_with_students_cannot_be_deleted():
    """The mistake this protects against is unrecoverable, so it is refused
    in the backend and not only disabled in the UI."""
    b, cls = fresh()
    assert b.list_students(class_id=cls["id"])
    try:
        b.delete_class(cls["id"])
    except ValueError:
        pass
    else:
        raise AssertionError("deleting a class with students should be refused")
    assert cls["id"] in [c["id"] for c in b.list_classes()]


def test_archived_students_still_block_deletion():
    """Archived is hidden, not gone -- their tests are still in the database."""
    b, cls = fresh()
    for s in b.list_students(class_id=cls["id"]):
        b.update_student(s["id"], {"archived": 1})
    assert b.list_students(class_id=cls["id"]) == []
    try:
        b.delete_class(cls["id"])
    except ValueError:
        return
    raise AssertionError("archived students should still block deletion")


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); passed += 1; print(f"  ok  {name}")
    print(f"\n{passed} passed")
