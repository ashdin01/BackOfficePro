"""
Centralised UI style constants for BackOfficePro views.

Import with:
    import config.styles as styles
or:
    from config.styles import CLR_TEXT, STYLE_LABEL_MUTED, ...
"""

# ── Colour palette ──────────────────────────────────────────────────────────

CLR_TEXT        = "#e6edf3"   # primary foreground
CLR_MUTED       = "#8b949e"   # secondary / dim text
CLR_EXTRA_DIM   = "#6e7681"   # tertiary text
CLR_BG          = "#1a2332"   # main background
CLR_BG_PANEL    = "#1e2a38"   # panel / sidebar background
CLR_BORDER      = "#2a3a4a"   # borders and separators
CLR_SUCCESS     = "#3fb950"   # green (active, ok)
CLR_SUCCESS_ALT = "#4CAF50"   # green variant (GP, price ok)
CLR_WARNING     = "#e6c84e"   # amber warning
CLR_DANGER      = "#f85149"   # red (error, low stock)
CLR_DANGER_ALT  = "#f44336"   # red variant
CLR_INFO        = "#4fc3f7"   # light blue info
CLR_ACCENT      = "#1565c0"   # blue accent (primary action)
CLR_GP_OK       = "green"     # GP % good
CLR_GP_WARN     = "orange"    # GP % marginal
CLR_GP_BAD      = "red"       # GP % bad
CLR_GP_NONE     = "grey"      # GP % unavailable

# Extended palette (used in reports / status badges / nav)
CLR_ACCENT_HOVER  = "#1976d2"  # hover state for primary-blue buttons
CLR_BLUE          = "#2196F3"  # medium blue (stat cards, info highlights)
CLR_BLUE_LIGHT    = "#5c9de8"  # light blue (Admin write-off category)
CLR_ORANGE        = "#FF9800"  # orange (partial, caution, low-stock)
CLR_AMBER         = "#FFB300"  # amber/gold (promo lines, report totals)
CLR_SUCCESS_DARK  = "#2e7d32"  # dark green button background
CLR_SUCCESS_HOVER = "#388e3c"  # green button hover
CLR_PURPLE        = "#9C27B0"  # purple accent (top-seller, active-products)
CLR_PURPLE_DARK   = "#6a1b9a"  # dark purple (Reports nav button, reversed PO)
CLR_PURPLE_HOVER  = "#7b1fa2"  # purple hover
CLR_BG_DEEP       = "#0d1a24"  # very-dark row bg (grand-total rows in reports)

# ── Widget stylesheet constants ─────────────────────────────────────────────

STYLE_LABEL_MUTED       = f"color: {CLR_MUTED}; font-size: 11px;"
STYLE_LABEL_MUTED_SMALL = f"color: {CLR_MUTED}; font-size: 10px;"
STYLE_LABEL_EXTRA_DIM   = f"color: {CLR_EXTRA_DIM}; font-size: 11px;"
STYLE_LABEL_DIM_BG_NONE = f"color: {CLR_MUTED}; font-size: 11px; background: transparent;"
STYLE_LABEL_PRIMARY     = f"color: {CLR_TEXT};"
STYLE_LABEL_SUCCESS     = f"color: {CLR_SUCCESS};"
STYLE_LABEL_DANGER      = f"color: {CLR_DANGER};"
STYLE_LABEL_WARNING     = f"color: {CLR_WARNING};"
STYLE_SEPARATOR         = f"color: {CLR_BORDER};"
STYLE_TRANSPARENT       = "background: transparent;"
STYLE_TRANSPARENT_NOBORDER = "background: transparent; border: none;"

STYLE_BTN_PRIMARY = (
    f"QPushButton{{background:{CLR_ACCENT};color:white;font-weight:bold;padding:0 16px;}}"
)
STYLE_BTN_SUCCESS = (
    f"QPushButton{{background:{CLR_SUCCESS_DARK};color:white;font-weight:bold;padding:0 16px;}}"
)
STYLE_BTN_DANGER_LINK = (
    f"color: {CLR_DANGER}; font-weight: bold; border: none; background: transparent;"
)
STYLE_BTN_INFO_LINK = (
    f"color: {CLR_INFO}; font-weight: bold; border: none; background: transparent;"
)
STYLE_BTN_PERIOD = (
    f"QPushButton{{background:{CLR_BG_PANEL};color:{CLR_TEXT};border:1px solid {CLR_BORDER};"
    "border-radius:3px;padding:0 8px;font-size:11px;height:26px;}}"
    f"QPushButton:hover{{background:{CLR_BORDER};}}"
)
STYLE_PANEL_HEADER = (
    f"background:{CLR_BG_PANEL}; border-bottom:1px solid {CLR_BORDER};"
)
STYLE_PANEL_SIDEBAR = (
    f"background:{CLR_BG_PANEL}; border-right:1px solid {CLR_BORDER};"
)
STYLE_PANEL_FOOTER = (
    f"background:{CLR_BG_PANEL}; border-top:1px solid {CLR_BORDER};"
)
STYLE_WARNING_BANNER = (
    f"color: {CLR_WARNING}; background: #2a2200; border: 1px solid #6b5500;"
    "border-radius: 4px; padding: 6px 10px;"
)
STYLE_INFO_BANNER = (
    f"color: {CLR_INFO}; padding: 4px;"
)

# ── HTML rich-text helpers ──────────────────────────────────────────────────

def html_span(text, color):
    """Return <span style='color:{color}'>{text}</span>."""
    return f"<span style='color:{color}'>{text}</span>"


def html_bold(text, color):
    """Return <b style='color:{color}'>{text}</b>."""
    return f"<b style='color:{color}'>{text}</b>"


def html_colored_label(value, reorder, on_order=0):
    """Stock-on-hand coloured label: red if below the reorder minimum, green otherwise."""
    color = CLR_DANGER if value < reorder else CLR_SUCCESS
    return f"<span style='color:{color}'>{value}</span> (reorder below {reorder})"
