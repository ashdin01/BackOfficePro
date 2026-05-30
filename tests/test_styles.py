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


# ── STYLE_* constant content ──────────────────────────────────────────────────

STYLE_CONSTANTS = [n for n in REQUIRED_CONSTANTS if n.startswith("STYLE_")]


def test_style_constants_are_strings():
    """STYLE_* values must be non-empty strings (not colour codes)."""
    for name in STYLE_CONSTANTS:
        val = getattr(styles, name)
        assert isinstance(val, str), f"styles.{name} is not a string"
        assert val.strip(), f"styles.{name} is blank"


def test_style_constants_contain_css_property():
    """Every STYLE_* constant must contain at least one CSS property (a colon)."""
    for name in STYLE_CONSTANTS:
        val = getattr(styles, name)
        assert ":" in val, (
            f"styles.{name} = {val!r} contains no CSS property (expected a colon)"
        )


def test_no_raw_palette_hex_in_styles_module():
    """styles.py itself must not contain raw hex literals for its own CLR_* values.

    All CLR_* constants should be defined once; STYLE_* should reference CLR_* by
    name via f-strings or string concatenation, not by re-inlining the hex code.
    """
    styles_file = Path(__file__).parent.parent / "config" / "styles.py"
    src = styles_file.read_text()
    lines = src.splitlines()

    # Build a set of hex values from CLR_* definitions
    # (the line that *defines* a CLR_* constant is allowed to contain that hex)
    clr_definition_lines = set()
    for i, line in enumerate(lines):
        if re.match(r'\s*CLR_\w+\s*=', line):
            clr_definition_lines.add(i)

    leaks = []
    for i, line in enumerate(lines):
        if i in clr_definition_lines:
            continue
        for match in _HEX_RE.finditer(line):
            found = match.group().lower()
            if found in PALETTE_HEX:
                leaks.append(f"styles.py:{i + 1}  {match.group()}")

    assert not leaks, (
        "Raw palette hex in styles.py outside CLR_* definitions — use CLR_* names:\n"
        + "\n".join(leaks)
    )


def test_clr_constants_are_unique():
    """No two CLR_* constants should share the same hex value (avoids palette confusion)."""
    seen: dict[str, str] = {}
    duplicates = []
    for name in REQUIRED_CONSTANTS:
        if not name.startswith("CLR_"):
            continue
        val = getattr(styles, name).lower()
        if not val.startswith("#"):
            continue
        if val in seen:
            duplicates.append(f"{name} == {seen[val]} ({val})")
        else:
            seen[val] = name
    assert not duplicates, (
        "Duplicate CLR_* hex values found:\n" + "\n".join(duplicates)
    )
