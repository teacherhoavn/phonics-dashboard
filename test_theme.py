"""Contrast and theme tests.

The point of these is that "is it readable?" stops being a matter of
opinion. The app is for a teacher with low vision, so the default theme has
to clear WCAG numerically, and a future palette tweak that breaks that
should fail here rather than ship.

Run:  venv/bin/python test_theme.py
"""

from theme import (
    AA_LARGE,
    AA_NORMAL,
    AAA_NORMAL,
    DEFAULT_THEME,
    THEMES,
    WHITE,
    contrast_ratio,
    css,
    group_card_style,
    resolve,
    status_badge,
)


def test_contrast_ratio_matches_known_values():
    assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    assert round(contrast_ratio("#ffffff", "#ffffff"), 1) == 1.0
    # A well-known AA-passing pair, as a sanity anchor on the formula.
    assert 4.5 <= contrast_ratio("#767676", "#ffffff") <= 4.6


def test_default_theme_body_text_meets_aaa():
    t = THEMES[DEFAULT_THEME]
    assert contrast_ratio(t["ink"], "#ffffff") >= AAA_NORMAL
    assert contrast_ratio(t["ink"], t["panel_bg"]) >= AAA_NORMAL


def test_default_theme_secondary_text_meets_aa():
    t = THEMES[DEFAULT_THEME]
    for key in ("ink_soft", "muted", "accent"):
        ratio = contrast_ratio(t[key], "#ffffff")
        assert ratio >= AA_NORMAL, f"{key} is {ratio:.2f}:1 on white"


def test_default_theme_status_pills_meet_aa():
    for code, s in THEMES[DEFAULT_THEME]["status"].items():
        ratio = contrast_ratio(s["fg"], s["bg"])
        assert ratio >= AA_NORMAL, f"status {code} is {ratio:.2f}:1"


def test_default_theme_group_colours_work_both_ways():
    """Each group colour is used as a fill AND as text, so both must pass."""
    for i, color in enumerate(THEMES[DEFAULT_THEME]["group_colors"], 1):
        assert contrast_ratio(WHITE, color) >= AA_NORMAL, f"white on group {i}"
        assert contrast_ratio(color, "#ffffff") >= AA_NORMAL, f"group {i} on white"


def test_default_theme_hero_text_meets_aa_across_the_gradient():
    t = THEMES[DEFAULT_THEME]
    for stop in ("hero_from", "hero_to"):
        assert contrast_ratio("#ffffff", t[stop]) >= AA_NORMAL, stop


def test_default_theme_borders_are_visible():
    t = THEMES[DEFAULT_THEME]
    for key in ("border", "chip_border"):
        assert contrast_ratio(t[key], "#ffffff") >= AA_LARGE, key


def test_untested_group_card_is_still_legible():
    t = THEMES[DEFAULT_THEME]
    assert contrast_ratio(t["group_untested_fg"], t["group_untested_bg"]) >= AA_NORMAL


def test_no_status_is_distinguished_by_colour_alone():
    """Each status carries a distinct shape, for anyone who cannot rely on hue."""
    symbols = [s["symbol"] for s in THEMES[DEFAULT_THEME]["status"].values()]
    assert all(symbols), "every status needs a symbol in the default theme"
    assert len(set(symbols)) == len(symbols), "symbols must differ from each other"


def test_status_badge_carries_symbol_and_label():
    html = status_badge("not_yet", "Not yet", DEFAULT_THEME)
    assert "Not yet" in html
    assert THEMES[DEFAULT_THEME]["status"]["not_yet"]["symbol"] in html


def test_classic_is_preserved_unchanged_so_the_revert_is_faithful():
    """Reverting must restore the ORIGINAL look, not a touched-up version.

    classic deliberately does not meet AA -- that is precisely why the vivid
    theme exists. Asserting the original values here stops someone
    "improving" classic and quietly making the revert lie.
    """
    t = THEMES["classic"]
    assert t["hero_from"] == "#3b5ea8" and t["hero_to"] == "#2f9199"
    assert t["ink"] == "#1f2937"
    assert t["status"]["practising"]["bg"] == "#d99a17"
    assert t["group_colors"] is None
    # Documents the failure the redesign was fixing: amber on white.
    assert contrast_ratio("#ffffff", t["status"]["practising"]["bg"]) < AA_NORMAL


def test_group_card_style_per_theme():
    # vivid colours by group and distinguishes done from started.
    done = group_card_style(3, "done", "vivid")
    started = group_card_style(3, "started", "vivid")
    assert done[0] == THEMES["vivid"]["group_colors"][2]
    assert started[0] == WHITE and started[1] == done[0]
    assert group_card_style(3, "untested", "vivid")[0] == THEMES["vivid"]["group_untested_bg"]
    # Every group gets a different colour, or they are not telling groups apart.
    fills = {group_card_style(n, "done", "vivid")[0] for n in range(1, 8)}
    assert len(fills) == 7
    # classic ignores the group number and colours by state only.
    assert group_card_style(1, "done", "classic") == group_card_style(7, "done", "classic")


def test_resolve_falls_back_to_default():
    assert resolve(None) == DEFAULT_THEME
    assert resolve("nonsense") == DEFAULT_THEME
    assert resolve("classic") == "classic"


def test_css_renders_for_every_theme():
    for name in THEMES:
        out = css(name)
        assert out.startswith("<style>") and out.endswith("</style>")
        assert "--got-bg" in out and "--fs-grapheme" in out
        # No unfilled placeholders left behind.
        assert "{" in out and "None" not in out.replace("none", "")


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} passed")
