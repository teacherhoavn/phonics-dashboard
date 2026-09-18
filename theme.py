"""Look and feel, as swappable palettes.

Two complete themes:

  vivid    (default) -- high-contrast and colourful, with a larger type
                        scale. Built for a teacher with low vision: every
                        text/background pair is checked against WCAG, the
                        seven phonics groups each get their own colour, and
                        nothing is signalled by colour alone.
  classic             -- the original quieter blue-grey design.

To switch, set PHONICS_THEME in .env (or Streamlit secrets):

    PHONICS_THEME=classic

Nothing else in the app needs to change: app.py reads colours, symbols and
the type scale from here, and every rule in BASE_CSS is written against CSS
custom properties that the active theme fills in.

test_theme.py enforces the contrast floors, so a future palette edit that
makes text hard to read fails the tests rather than shipping.
"""

from __future__ import annotations

# --- WCAG contrast ---------------------------------------------------------

def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio, 1.0 (invisible) to 21.0 (black on white)."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# AA wants 4.5:1 for body text and 3:1 for large text. This app aims at AA
# for everything and AAA (7:1) for body copy, because the teacher it is for
# has low vision and will be reading it on a phone in a classroom.
AA_NORMAL = 4.5
AA_LARGE = 3.0
AAA_NORMAL = 7.0

WHITE = "#ffffff"

# --- Themes ----------------------------------------------------------------

THEMES = {
    "vivid": {
        "label": "Vivid (high contrast)",
        "ink": "#14181f",          # body text on white -- 15.9:1
        "ink_soft": "#3d4653",     # secondary text    -- 8.9:1
        "muted": "#55606e",        # least important   -- 6.5:1
        "page_bg": "#ffffff",
        "panel_bg": "#f2f5fa",
        "border": "#7a8698",
        "focus": "#0b4fd8",
        "hero_from": "#5b21a8",
        "hero_to": "#0f5fa8",
        "accent": "#0f5fa8",
        # Each status: background, text on it, and a SHAPE, so the three are
        # still distinguishable without seeing colour at all.
        "status": {
            "acquired":   {"bg": "#136b2f", "fg": WHITE, "symbol": "✓"},
            "practising": {"bg": "#9a4a06", "fg": WHITE, "symbol": "~"},
            "not_yet":    {"bg": "#a8152a", "fg": WHITE, "symbol": "✗"},
        },
        # Unselected button: white, dark text, heavy border. The difference
        # from the selected state is fill *and* weight, not hue.
        "chip_bg": "#ffffff",
        "chip_fg": "#14181f",
        "chip_border": "#5c6675",
        # One colour per phonics group, all legible under white text.
        "group_colors": [
            "#b01254", "#6a1b9a", "#1052a8", "#00635c",
            "#1f6b22", "#a03c00", "#4a342e",
        ],
        "group_untested_bg": "#e7ebf1",
        "group_untested_fg": "#3d4653",
        "type": {
            "base": "1.05rem",
            "grapheme": "2.6rem",
            "grapheme_sm": "2.2rem",
            "meta": "0.95rem",
            "button": "1rem",
            "hero": "1.6rem",
            "hero_sm": "1.3rem",
            "tap_min": "52px",
        },
    },
    "classic": {
        "label": "Classic (original)",
        "ink": "#1f2937",
        "ink_soft": "#6b7280",
        "muted": "#9aa3af",
        "page_bg": "#ffffff",
        "panel_bg": "#f4f6fb",
        "border": "#e5e7eb",
        "focus": "#3b5ea8",
        "hero_from": "#3b5ea8",
        "hero_to": "#2f9199",
        "accent": "#273f73",
        "status": {
            "acquired":   {"bg": "#2f8f4e", "fg": WHITE, "symbol": ""},
            "practising": {"bg": "#d99a17", "fg": WHITE, "symbol": ""},
            "not_yet":    {"bg": "#b04a4a", "fg": WHITE, "symbol": ""},
        },
        "chip_bg": "#ffffff",
        "chip_fg": "#1f2937",
        "chip_border": "#e5e7eb",
        "group_colors": None,      # colour by progress state, not by group
        "group_untested_bg": "#f3f4f6",
        "group_untested_fg": "#9aa3af",
        "type": {
            "base": "1rem",
            "grapheme": "2.1rem",
            "grapheme_sm": "1.75rem",
            "meta": "0.78rem",
            "button": "0.95rem",
            "hero": "1.5rem",
            "hero_sm": "1.2rem",
            "tap_min": "44px",
        },
    },
}

DEFAULT_THEME = "vivid"


def resolve(name: str | None) -> str:
    return name if name in THEMES else DEFAULT_THEME


def _root_vars(t: dict) -> str:
    ty = t["type"]
    s = t["status"]
    return f"""
  :root {{
    --ink: {t['ink']};
    --ink-soft: {t['ink_soft']};
    --muted: {t['muted']};
    --panel: {t['panel_bg']};
    --border: {t['border']};
    --focus: {t['focus']};
    --hero-from: {t['hero_from']};
    --hero-to: {t['hero_to']};
    --accent: {t['accent']};
    --got-bg: {s['acquired']['bg']};
    --got-fg: {s['acquired']['fg']};
    --near-bg: {s['practising']['bg']};
    --near-fg: {s['practising']['fg']};
    --not-bg: {s['not_yet']['bg']};
    --not-fg: {s['not_yet']['fg']};
    --chip-bg: {t['chip_bg']};
    --chip-fg: {t['chip_fg']};
    --chip-border: {t['chip_border']};
    --fs-base: {ty['base']};
    --fs-grapheme: {ty['grapheme']};
    --fs-grapheme-sm: {ty['grapheme_sm']};
    --fs-meta: {ty['meta']};
    --fs-button: {ty['button']};
    --fs-hero: {ty['hero']};
    --fs-hero-sm: {ty['hero_sm']};
    --tap-min: {ty['tap_min']};
  }}
"""


def status_style(code: str, theme: str | None = None) -> dict:
    return THEMES[resolve(theme)]["status"][code]


def status_badge(code: str, label: str, theme: str | None = None) -> str:
    """A status as a filled pill carrying BOTH a shape and a colour.

    The shape is what makes these readable for someone who cannot rely on
    hue -- red/amber/green alone is the single most common accessibility
    mistake in a progress UI.
    """
    s = status_style(code, theme)
    sym = f"{s['symbol']} " if s["symbol"] else ""
    return (
        f"<span class='badge' style='background:{s['bg']};color:{s['fg']}'>"
        f"{sym}{label}</span>"
    )


def group_card_style(group_number: int, state: str, theme: str | None = None) -> tuple:
    """(background, text colour, border) for one of the seven group cards.

    state is 'done', 'started' or 'untested'.

    vivid gives each group its own colour and shows state through fill
    strength plus the mark inside the card; classic keeps the original
    green/amber/grey by state.
    """
    t = THEMES[resolve(theme)]
    if t["group_colors"]:
        if state == "untested":
            return t["group_untested_bg"], t["group_untested_fg"], "transparent"
        color = t["group_colors"][(group_number - 1) % len(t["group_colors"])]
        if state == "done":
            return color, WHITE, color
        # Started: the group's colour as a heavy outline on white, so a
        # part-finished group never reads as a finished one.
        return WHITE, color, color
    if state == "done":
        return "#e6f4ea", "#1e6b39", "transparent"
    if state == "started":
        return "#fdf3e0", "#8a6412", "transparent"
    return t["group_untested_bg"], t["group_untested_fg"], "transparent"


BASE_CSS = """
  html, body, [data-testid="stAppViewContainer"] { font-size: var(--fs-base); }
  body { color: var(--ink); }

  .hero {
    background: linear-gradient(135deg, var(--hero-from) 0%, var(--hero-to) 100%);
    color: #fff; padding: 1.1rem 1.4rem; border-radius: 14px; margin-bottom: 1.1rem;
  }
  .hero h1 { margin: 0; font-size: var(--fs-hero); color: #fff; }
  .hero p  { margin: .25rem 0 0; font-size: 1rem; color: #fff; }

  .sound-card { padding: .3rem 0 .1rem; }
  .sound-grapheme {
    font-size: var(--fs-grapheme); font-weight: 800; line-height: 1;
    color: var(--ink);
  }
  .sound-meta { font-size: var(--fs-meta); color: var(--ink-soft); display: block; }
  .sound-action { font-size: var(--fs-meta); color: var(--muted); font-style: italic; }
  .screen-help { font-size: 1rem; color: var(--ink-soft); margin: -.4rem 0 .6rem; }
  .test-head { font-size: 1rem; line-height: 1.4; color: var(--ink); }

  /* Streamlit renders captions at 0.6 opacity, which blends dark text
     toward white and drops it to roughly 3.6:1 -- under the 4.5:1 floor,
     at 14.7px. Captions carry real instructions here, so they get full
     opacity, a checked colour and a readable size. */
  [data-testid="stCaptionContainer"] { opacity: 1 !important; }
  [data-testid="stCaptionContainer"],
  [data-testid="stCaptionContainer"] p {
    color: var(--ink-soft) !important; font-size: 1rem !important;
  }

  /* The mark-all shortcuts are outlined in the colour they apply, so they
     read as "set everything to this" rather than as a second row of the
     per-sound buttons. */
  [class*="st-key-bulk_acquired"] button {
    border: 3px solid var(--got-bg) !important; color: var(--got-bg) !important;
    font-weight: 700;
  }
  [class*="st-key-bulk_practising"] button {
    border: 3px solid var(--near-bg) !important; color: var(--near-bg) !important;
    font-weight: 700;
  }
  [class*="st-key-bulk_not_yet"] button {
    border: 3px solid var(--not-bg) !important; color: var(--not-bg) !important;
    font-weight: 700;
  }

  /* Two lengths of the same sentence: the full wording on a laptop, a
     compact one on a phone where five wrapped lines push the sounds down. */
  .only-narrow { display: none; }

  .badge {
    display: inline-block; padding: .2rem .6rem; border-radius: 999px;
    font-size: .95rem; font-weight: 700; margin: .1rem .25rem .1rem 0;
    white-space: nowrap;
  }

  /* Touch targets. Streamlit's default segmented-control button is 32px
     tall; anything under ~44px is a miss-prone target on a phone, and this
     entire screen is tapping. The vivid theme goes further again. */
  [data-testid="stBaseButton-segmented_control"],
  [data-testid="stBaseButton-segmented_controlActive"] {
    min-height: var(--tap-min); font-size: var(--fs-button); font-weight: 700;
  }
  /* Unselected reads as an empty outline, selected as a solid fill: the
     difference is weight and fill, never hue alone. */
  [data-testid="stBaseButton-segmented_control"] {
    background: var(--chip-bg) !important; color: var(--chip-fg) !important;
    border: 2px solid var(--chip-border) !important;
  }
  [data-testid="stBaseButton-segmented_controlActive"] {
    border: 2px solid transparent !important;
  }
  /* Each status keeps its own colour when selected. */
  [class*="st-key-snd_"] [data-testid="stButtonGroup"] button:nth-child(1)[data-testid$="Active"] {
    background: var(--got-bg) !important; color: var(--got-fg) !important;
  }
  [class*="st-key-snd_"] [data-testid="stButtonGroup"] button:nth-child(2)[data-testid$="Active"] {
    background: var(--near-bg) !important; color: var(--near-fg) !important;
  }
  [class*="st-key-snd_"] [data-testid="stButtonGroup"] button:nth-child(3)[data-testid$="Active"] {
    background: var(--not-bg) !important; color: var(--not-fg) !important;
  }
  [class*="st-key-grp_"] [data-testid="stButtonGroup"] button[data-testid$="Active"] {
    background: var(--accent) !important; color: #fff !important;
  }

  /* A focus ring that is actually visible. */
  button:focus-visible, input:focus-visible, select:focus-visible,
  [role="radio"]:focus-visible {
    outline: 3px solid var(--focus) !important; outline-offset: 2px !important;
  }

  /* Keep each sound on ONE row on a phone. Streamlit stacks columns below
     ~640px, which turned six sounds into twelve rows of scrolling and put
     the Save button two screens down. */
  [data-testid="stHorizontalBlock"]:has(.sound-card) {
    flex-wrap: nowrap !important; align-items: center; gap: .5rem;
  }
  [data-testid="stHorizontalBlock"]:has(.sound-card) > [data-testid="stColumn"] {
    min-width: 0 !important;
  }
  [data-testid="stHorizontalBlock"]:has(.sound-card) > [data-testid="stColumn"]:first-child {
    flex: 0 0 5.5rem;
  }
  [data-testid="stHorizontalBlock"]:has(.sound-card) > [data-testid="stColumn"]:last-child {
    flex: 1 1 auto;
  }

  /* The element container around a segmented control is shrink-to-fit, so
     every width below it resolved against the buttons' own text rather than
     the column. Widening it here is what actually lets the buttons spread. */
  [class*="st-key-snd_"], [class*="st-key-grp_"] { width: 100%; }
  @media (min-width: 641px) {
    [class*="st-key-snd_"] { max-width: 30rem; }
  }
  /* Basis ~1/n rather than 0. flex-grow is not honoured inside this button
     group, so a zero basis leaves every button at its padding width. */
  [class*="st-key-snd_"] [data-testid="stButtonGroup"] button {
    flex: 1 1 30%; padding-left: .4rem; padding-right: .4rem;
  }
  [class*="st-key-grp_"] [data-testid="stButtonGroup"] button {
    flex: 1 1 12%; padding-left: .3rem; padding-right: .3rem;
  }

  /* Mark-all row stays three across rather than stacking into three rows. */
  [data-testid="stHorizontalBlock"]:has([class*="st-key-bulk_"]) {
    flex-wrap: nowrap !important; gap: .4rem;
  }
  [data-testid="stHorizontalBlock"]:has([class*="st-key-bulk_"]) > [data-testid="stColumn"] {
    min-width: 0 !important;
  }

  /* Child's name and the "Change child" button share one row on a phone. */
  [data-testid="stHorizontalBlock"]:has(.test-head) {
    flex-wrap: nowrap !important; align-items: center; gap: .5rem;
  }
  [data-testid="stHorizontalBlock"]:has(.test-head) > [data-testid="stColumn"] {
    min-width: 0 !important;
  }
  [data-testid="stHorizontalBlock"]:has(.test-head) > [data-testid="stColumn"]:last-child {
    flex: 0 0 8rem;
  }

  .group-card {
    border-radius: 10px; padding: .6rem .3rem; text-align: center;
    border: 3px solid transparent;
  }
  .group-card .gc-n { font-weight: 800; white-space: nowrap; font-size: 1rem; }
  .group-card .gc-m { font-size: 1.25rem; font-weight: 700; white-space: nowrap; }
  .group-card .gc-p { font-size: .8rem; opacity: .9; line-height: 1.25; }

  /* The seven groups are a progress strip, not seven stacked blocks -- left
     to stack they push the "practise at home" sounds off a parent's phone. */
  [data-testid="stHorizontalBlock"]:has(.group-card) {
    flex-wrap: nowrap !important; gap: .25rem;
  }
  [data-testid="stHorizontalBlock"]:has(.group-card) > [data-testid="stColumn"] {
    min-width: 0 !important;
  }

  /* Grid, not flex-wrap: with flex the single card on a final row grows to
     the full width and looks like a different kind of thing. */
  .practise-row {
    display: grid; gap: .5rem;
    grid-template-columns: repeat(auto-fit, minmax(6rem, 1fr));
  }
  .practise-card {
    border: 3px solid var(--border); border-radius: 12px; padding: .7rem .5rem;
    text-align: center; background: #fff;
  }
  .practise-card .g {
    font-size: 2.1rem; font-weight: 800; color: var(--accent); line-height: 1.1;
  }
  .practise-card .w { font-size: .95rem; color: var(--ink-soft); }

  @media (max-width: 640px) {
    /* Branding and first-run help do not earn their vertical space on a
       phone, where the point is to get the six sounds onto one screen. */
    .hero--app { display: none; }
    .screen-help { display: none; }
    .sound-action { display: none; }
    .sound-grapheme { font-size: var(--fs-grapheme-sm); }
    .hero { padding: .8rem 1rem; }
    .hero h1 { font-size: var(--fs-hero-sm); }
    /* At a seventh of a phone screen there is no room for the sound list. */
    .group-card .gc-p { display: none; }
    .group-card { padding: .5rem .15rem; }
    .group-card .gc-m { font-size: 1.1rem; }
    .only-wide { display: none; }
    .only-narrow { display: inline; }
  }
"""


def css(theme: str | None = None) -> str:
    return "<style>" + _root_vars(THEMES[resolve(theme)]) + BASE_CSS + "</style>"
