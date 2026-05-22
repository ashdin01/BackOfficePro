"""
Tests for config/styles.py palette constants and view-file hygiene.

The palette-leak test catches regressions where a palette colour gets
re-inlined in a view instead of using the styles constant.
"""
import re
from pathlib import Path
import config.styles as styles


# ── Palette constant existence ────────────────────────────────────────────────

REQUIRED_CONSTANTS = [
    # Core palette
    "CLR_TEXT", "CLR_MUTED", "CLR_EXTRA_DIM",
    "CLR_BG", "CLR_BG_PANEL", "CLR_BG_DEEP", "CLR_BORDER",
    "CLR_SUCCESS", "CLR_SUCCESS_ALT", "CLR_SUCCESS_DARK", "CLR_SUCCESS_HOVER",
    "CLR_WARNING", "CLR_DANGER", "CLR_DANGER_ALT",
    "CLR_INFO", "CLR_ACCENT", "CLR_ACCENT_HOVER",
    "CLR_ORANGE", "CLR_AMBER",
    "CLR_BLUE", "CLR_BLUE_LIGHT",
    "CLR_PURPLE", "CLR_PURPLE_DARK", "CLR_PURPLE_HOVER",
    # Composite style strings
    "STYLE_LABEL_MUTED", "STYLE_LABEL_MUTED_SMALL", "STYLE_LABEL_EXTRA_DIM",
    "STYLE_LABEL_PRIMARY", "STYLE_LABEL_SUCCESS", "STYLE_LABEL_DANGER",
    "STYLE_LABEL_WARNING", "STYLE_SEPARATOR", "STYLE_TRANSPARENT",
    "STYLE_BTN_PRIMARY", "STYLE_BTN_SUCCESS", "STYLE_BTN_DANGER_LINK",
    "STYLE_BTN_INFO_LINK", "STYLE_BTN_PERIOD",
    "STYLE_PANEL_HEADER", "STYLE_PANEL_SIDEBAR", "STYLE_PANEL_FOOTER",
    "STYLE_WARNING_BANNER", "STYLE_INFO_BANNER",
]


def test_all_palette_constants_exist():
    for name in REQUIRED_CONSTANTS:
        assert hasattr(styles, name), f"styles.{name} is missing"
        assert getattr(styles, name), f"styles.{name} is empty"


def test_clr_constants_are_valid_css_colours():
    """CLR_* values must be hex strings or plain CSS colour names."""
    hex_re = re.compile(r'^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$')
    named_colours = {"green", "red", "orange", "grey", "white", "black"}
    for name in REQUIRED_CONSTANTS:
        if not name.startswith("CLR_"):
            continue
        val = getattr(styles, name)
        assert hex_re.match(val) or val in named_colours, (
            f"styles.{name} = {val!r} is not a valid hex or named CSS colour"
        )


# ── Palette-leak guard ────────────────────────────────────────────────────────

# Hex literals that belong in styles.py — if these appear raw in a view file,
# someone bypassed the palette and the test will flag it.
PALETTE_HEX = {
    getattr(styles, n).lower()
    for n in dir(styles)
    if n.startswith("CLR_") and getattr(styles, n).startswith("#")
}

_VIEWS_DIR = Path(__file__).parent.parent / "views"
_HEX_RE = re.compile(r'#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}(?![0-9a-fA-F])',
                     re.IGNORECASE)


def _view_files():
    return [p for p in _VIEWS_DIR.rglob("*.py") if "__pycache__" not in str(p)]


def test_no_raw_palette_hex_in_views():
    """No view file should contain a bare hex literal that matches a palette colour."""
    leaks = []
    for path in _view_files():
        src = path.read_text()
        for match in _HEX_RE.finditer(src):
            found = match.group().lower()
            if found in PALETTE_HEX:
                line_no = src[:match.start()].count("\n") + 1
                leaks.append(f"{path.relative_to(_VIEWS_DIR)}:{line_no}  {match.group()}")
    assert not leaks, (
        "Raw palette hex literals found in views — use styles.CLR_* instead:\n"
        + "\n".join(leaks)
    )
