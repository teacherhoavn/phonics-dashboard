"""Progress roll-up logic.

Pure functions over the rows returned by the student_group_progress view --
no database, no Streamlit. Kept out of app.py so the rules that decide
"mastered groups 1-3, working on group 4" can be tested directly, and so
importing them never executes the page.
"""

TOTAL_SOUNDS = 42


def group_rows_for(progress: list, student_id: str) -> list:
    """This student's seven group rows, in teaching order."""
    rows = [p for p in progress if p["student_id"] == student_id]
    return sorted(rows, key=lambda p: p["group_number"])


def is_mastered(row: dict) -> bool:
    """Every sound in the group secure.

    Deliberately all-or-nothing: '5 of 6' is not mastery of a group whose
    whole point is the complete set, and a child who is shaky on one sound
    should keep seeing it.
    """
    return bool(row["total_sounds"]) and row["acquired"] == row["total_sounds"]


def _has_results(row: dict) -> bool:
    return bool(row["acquired"] or row["practising"] or row.get("not_yet"))


def mastered_run(rows: list) -> int:
    """How many groups are finished counting from group 1.

    Only a run starting at group 1 counts, so a child who happens to ace
    group 5 early is never reported as having finished 1-5.
    """
    done = 0
    for row in rows:
        if is_mastered(row):
            done += 1
        else:
            break
    return done


def mastery_summary(rows: list) -> str:
    """'Groups 1-3 mastered · working on Group 4 (2/6)' -- the one-line status."""
    if not rows or not any(_has_results(r) for r in rows):
        return "Not tested yet"

    done = mastered_run(rows)
    parts = []
    if done == 1:
        parts.append("Group 1 mastered")
    elif done > 1:
        parts.append(f"Groups 1–{done} mastered")

    working = next((r for r in rows if not is_mastered(r)), None)
    if working is None:
        parts.append("all 7 groups complete 🎉")
    elif _has_results(working):
        parts.append(
            f"working on Group {working['group_number']} "
            f"({working['acquired']}/{working['total_sounds']})"
        )
    elif done:
        parts.append(f"next up Group {working['group_number']}")
    else:
        # Reachable when a later group was tested but an earlier one skipped.
        parts.append(f"starting Group {working['group_number']}")
    return " · ".join(parts)


def suggested_group_number(rows: list) -> int:
    """Default the test screen to the first group that is not finished."""
    for row in rows:
        if not is_mastered(row):
            return row["group_number"]
    return 7


def total_acquired(rows: list) -> int:
    return sum(r["acquired"] for r in rows)


def compact_progress(rows: list) -> str:
    """'G1-3 ✓ · G4 2/6' -- short enough for a grid cell."""
    if not rows:
        return "—"
    done = mastered_run(rows)
    bits = []
    if done == 1:
        bits.append("G1 ✓")
    elif done > 1:
        bits.append(f"G1–{done} ✓")
    working = next((r for r in rows if not is_mastered(r)), None)
    if working and _has_results(working):
        bits.append(f"G{working['group_number']} {working['acquired']}/{working['total_sounds']}")
    return " · ".join(bits) or "—"
