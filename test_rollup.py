"""Tests for the roll-up logic and the seeded reference data.

Run:  venv/bin/python -m pytest test_rollup.py -q
      (or venv/bin/python test_rollup.py for a dependency-free run)

These cover the pure functions only -- no Supabase, no Streamlit session.
"""

import re

import rollup
from rollup import (
    compact_progress,
    group_rows_for,
    is_mastered,
    mastery_summary,
    suggested_group_number,
    total_acquired,
)


def g(number, acquired, practising=0, not_yet=0, total=6, student="s1", tested=None):
    return {
        "student_id": student, "group_id": f"g{number}", "group_number": number,
        "total_sounds": total, "acquired": acquired, "practising": practising,
        "not_yet": not_yet, "last_tested_on": tested,
    }


def untested_from(first):
    return [g(n, 0) for n in range(first, 8)]


def test_mastered_is_all_or_nothing():
    assert is_mastered(g(1, 6))
    assert not is_mastered(g(1, 5, practising=1))
    assert not is_mastered(g(1, 0, total=0))


def test_summary_for_untested_student():
    assert mastery_summary(untested_from(1)) == "Not tested yet"
    assert mastery_summary([]) == "Not tested yet"


def test_summary_mid_stream():
    rows = [g(1, 6), g(2, 6), g(3, 6), g(4, 2, practising=2, not_yet=2)] + untested_from(5)
    assert mastery_summary(rows) == "Groups 1–3 mastered · working on Group 4 (2/6)"


def test_summary_single_group_is_not_pluralised():
    rows = [g(1, 6), g(2, 1, not_yet=5)] + untested_from(3)
    assert mastery_summary(rows) == "Group 1 mastered · working on Group 2 (1/6)"


def test_summary_between_groups():
    """Finished a group, next one untouched -- 'next up', not 'working on'."""
    rows = [g(1, 6), g(2, 6)] + untested_from(3)
    assert mastery_summary(rows) == "Groups 1–2 mastered · next up Group 3"


def test_run_must_start_at_group_one():
    """Acing group 5 early must not report groups 1-5 as done."""
    rows = [g(1, 3, not_yet=3)] + [g(n, 0) for n in range(2, 5)] + [g(5, 6)] + untested_from(6)
    assert mastery_summary(rows) == "working on Group 1 (3/6)"


def test_later_group_tested_but_first_one_skipped():
    """Group 5 tested, group 1 never touched -- report the gap, not group 5."""
    rows = [g(n, 0) for n in range(1, 5)] + [g(5, 6)] + untested_from(6)
    assert mastery_summary(rows) == "starting Group 1"


def test_all_groups_complete():
    rows = [g(n, 6) for n in range(1, 8)]
    assert mastery_summary(rows).endswith("all 7 groups complete 🎉")
    assert total_acquired(rows) == 42


def test_suggested_group_skips_finished_ones():
    assert suggested_group_number(untested_from(1)) == 1
    assert suggested_group_number([g(1, 6), g(2, 6)] + untested_from(3)) == 3
    assert suggested_group_number([g(n, 6) for n in range(1, 8)]) == 7


def test_compact_progress_fits_a_cell():
    assert compact_progress([g(1, 6), g(2, 6), g(3, 6), g(4, 2)] + untested_from(5)) \
        == "G1–3 ✓ · G4 2/6"
    assert compact_progress(untested_from(1)) == "—"
    assert compact_progress([g(1, 6)] + untested_from(2)) == "G1 ✓"


def test_group_rows_filters_and_orders():
    rows = [g(3, 0), g(1, 6), g(2, 0), g(1, 0, student="s2")]
    picked = group_rows_for(rows, "s1")
    assert [r["group_number"] for r in picked] == [1, 2, 3]


# -- reference data -------------------------------------------------------

def test_seed_has_42_sounds_in_7_groups_with_unique_codes():
    sql = open("seed_phonics.sql").read()
    block = sql.split("from (values", 1)[1].split(") as v(", 1)[0]
    rows = re.findall(r"\(\s*(\d)\s*,\s*'((?:[^']|'')*)'", block)
    codes = [c for _g, c in rows]
    assert len(codes) == 42, f"expected 42 sounds, found {len(codes)}"
    assert len(set(codes)) == 42, "duplicate sound codes"
    counts = {}
    for gnum, _c in rows:
        counts[int(gnum)] = counts.get(int(gnum), 0) + 1
    assert counts == {n: 6 for n in range(1, 8)}, counts


def test_repeated_graphemes_are_disambiguated():
    """'oo' and 'th' each appear twice; keying on the grapheme would collide."""
    sql = open("seed_phonics.sql").read()
    block = sql.split("from (values", 1)[1].split(") as v(", 1)[0]
    codes = [c for _g, c in re.findall(r"\(\s*(\d)\s*,\s*'((?:[^']|'')*)'", block)]
    for code in ("oo_short", "oo_long", "th_unvoiced", "th_voiced"):
        assert code in codes, code


def test_local_backend_matches_the_seed_file():
    """The demo backend parses the same SQL, so the two cannot drift."""
    from local_backend import _parse_seed

    groups, sounds = _parse_seed()
    assert len(groups) == 7
    assert len(sounds) == 42
    assert {s[1] for s in sounds} >= {"s", "c_k", "oo_short", "th_voiced", "ar"}


def test_status_from_words_all_some_none():
    from rollup import status_from_words

    assert status_from_words(5, 5) == "acquired"
    assert status_from_words(4, 5) == "practising"
    assert status_from_words(1, 5) == "practising"
    assert status_from_words(0, 5) == "not_yet"
    # A sound with no words recorded cannot be called secure.
    assert status_from_words(0, 0) == "not_yet"


def test_word_list_covers_every_sound():
    """Each of the 42 sounds needs words, or it can never be scored."""
    import re

    from phonics_words_data import WORDS

    sql = open("seed_phonics.sql").read()
    block = sql.split("from (values", 1)[1].split(") as v(", 1)[0]
    codes = {c for _g, c in re.findall(r"\(\s*(\d)\s*,\s*'((?:[^']|'')*)'", block)}
    assert set(WORDS) == codes, f"mismatch: {set(WORDS) ^ codes}"
    assert all(WORDS.values()), "every sound needs at least one word"


def test_the_two_th_sounds_get_the_right_words():
    """Her document lists voiced th first; the app lists unvoiced first, so
    these were matched by sound rather than by position."""
    from phonics_words_data import WORDS

    assert "this" in WORDS["th_voiced"] and "that" in WORDS["th_voiced"]
    assert "thin" in WORDS["th_unvoiced"] and "three" in WORDS["th_unvoiced"]


def test_a_sound_with_no_test_behind_it_reads_as_untested():
    """The regression this guards: the word pills default to green, so a
    child who had never been tested showed a green 100% on every sound
    while the header above correctly said 0 secure."""
    tested, correct, total = rollup.sound_score(["w1", "w2"], {})
    assert tested is False
    assert total == 2


def test_a_tested_sound_reports_its_score():
    tested, correct, total = rollup.sound_score(
        ["w1", "w2", "w3"], {"w1": True, "w2": False, "w3": True})
    assert (tested, correct, total) == (True, 2, 3)
    assert rollup.status_from_words(correct, total) == "practising"


def test_all_wrong_is_tested_not_untested():
    """None right and never tested look the same in the counts and are not
    the same thing -- one is a result, the other is the absence of one."""
    tested, correct, total = rollup.sound_score(["w1"], {"w1": False})
    assert (tested, correct) == (True, 0)


def test_a_word_added_after_the_test_counts_as_read():
    """It matches what the pills do: an unknown word defaults to green, so
    a newly added word does not silently downgrade an old result."""
    tested, correct, total = rollup.sound_score(["w1", "new"], {"w1": True})
    assert (tested, correct, total) == (True, 2, 2)


def test_badge_colour_turns_green_at_eighty_percent():
    """37 of the 42 sounds have exactly five words, so 4/5 IS the boundary
    and is the whole point of the change."""
    assert rollup.colour_from_words(5, 5) == "acquired"
    assert rollup.colour_from_words(4, 5) == "acquired"
    assert rollup.colour_from_words(3, 5) == "practising"


def test_badge_colour_is_pink_only_when_nothing_was_read():
    """One word right is still progress, and shows as such."""
    assert rollup.colour_from_words(1, 5) == "practising"
    assert rollup.colour_from_words(0, 5) == "not_yet"


def test_badge_colour_holds_at_other_list_lengths():
    """Four- and eight-word lists exist too, so the rule is a percentage
    rather than a count."""
    assert rollup.colour_from_words(4, 4) == "acquired"
    assert rollup.colour_from_words(3, 4) == "practising"   # 75%
    assert rollup.colour_from_words(7, 8) == "acquired"     # 88%
    assert rollup.colour_from_words(6, 8) == "practising"   # 75%


def test_the_badge_colour_does_not_change_what_counts_as_secure():
    """The decision behind this: 4/5 shows green to be encouraging, but a
    group is still only mastered when every word is right. If these two
    ever collapse into one rule, children start being moved on early."""
    assert rollup.colour_from_words(4, 5) == "acquired"
    assert rollup.status_from_words(4, 5) == "practising"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} passed")