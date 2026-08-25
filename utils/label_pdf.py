"""
Shelf-edge label PDF generation.

Follows the same pattern as every other printed document in this app
(utils/po_pdf.py, utils/ar_pdf.py): build a PDF with reportlab, write it to
disk, hand it to the OS default viewer. The user prints it from there,
picking whichever printer is configured (e.g. a Zebra GK420D with its label
page size set in the printer driver) — BackOfficePro itself never talks to
a specific printer or command language, so it isn't tied to Zebra/ZPL and
needs no printer-name setting.

Two independently-configurable label sizes are supported — "standard" and
"large" — matching the two buttons on Product Detail (Settings > Label
Printing), since a shop commonly uses a small everyday shelf label plus a
bigger one for feature/promo placement. Defaults: standard 3" x 1"
(76 x 25.4mm), large 3" x 2" (76 x 51mm).
"""
import os
import tempfile
import uuid

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode import code128

import models.settings as settings_model

DEFAULT_WIDTH_MM  = 76.0   # 3"
DEFAULT_HEIGHT_MM = 25.4   # 1"

DEFAULT_LARGE_WIDTH_MM  = 76.0   # 3"
DEFAULT_LARGE_HEIGHT_MM = 51.0   # 2"

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def get_label_size_mm(large=False) -> tuple[float, float]:
    if large:
        width  = float(settings_model.get_setting('label_large_width_mm')  or DEFAULT_LARGE_WIDTH_MM)
        height = float(settings_model.get_setting('label_large_height_mm') or DEFAULT_LARGE_HEIGHT_MM)
    else:
        width  = float(settings_model.get_setting('label_width_mm')  or DEFAULT_WIDTH_MM)
        height = float(settings_model.get_setting('label_height_mm') or DEFAULT_HEIGHT_MM)
    return width, height


def generate_label_pdf(barcode, description, price_inc_gst, plu=None,
                        copies=1, path=None, large=False) -> str:
    """
    Build a shelf-edge label PDF: description, price (inc GST), a scannable
    Code128 barcode with human-readable digits, and PLU. One page per copy,
    each page sized to the configured label dimensions (the "large" profile
    when large=True, otherwise "standard" — see Settings > Label Printing).
    Returns the path written to (a temp file when path is not given — this
    is a throwaway print job, not a record to keep).
    """
    width_mm, height_mm = get_label_size_mm(large=large)
    page_w, page_h = width_mm * mm, height_mm * mm

    if path is None:
        safe_barcode = barcode or "label"
        path = os.path.join(
            tempfile.gettempdir(), f"label_{safe_barcode}_{uuid.uuid4().hex[:8]}.pdf"
        )

    c = pdfcanvas.Canvas(path, pagesize=(page_w, page_h))
    for _ in range(max(1, int(copies))):
        _draw_label(c, page_w, page_h, barcode, description, price_inc_gst, plu)
        c.showPage()
    c.save()
    return path


def _draw_label(c, page_w, page_h, barcode, description, price_inc_gst, plu):
    """
    Two horizontal bands:
      - Top two-thirds: description (left column, smaller font, up to two
        lines) + sell price inc GST (right column, large and prominent).
      - Bottom third: PLU (left column) + barcode (right column, sized to
        fill the band for a bigger, easier-to-scan symbol).
    """
    margin = 2 * mm
    small_label = page_h < 20 * mm

    band_split_y  = page_h / 3.0   # top-third/bottom-two-thirds boundary
    top_band_h    = page_h - band_split_y
    bottom_band_h = band_split_y

    # ── Top two-thirds: description (left) + price (right) ────────────────
    desc_col_w  = (page_w - 2 * margin) * 0.55
    price_col_x = margin + desc_col_w + 2 * mm
    price_col_w = page_w - margin - price_col_x

    desc_size = 8 if small_label else 11
    line_gap  = desc_size * 0.3
    c.setFont(_FONT_BOLD, desc_size)
    lines = _wrap_text(description or "", _FONT_BOLD, desc_size, desc_col_w, max_lines=2)
    block_h = len(lines) * desc_size + max(0, len(lines) - 1) * line_gap
    first_baseline = band_split_y + (top_band_h + block_h) / 2 - desc_size * 0.85
    for i, line in enumerate(lines):
        c.drawString(margin, first_baseline - i * (desc_size + line_gap), line)

    price_text = f"${price_inc_gst:.2f}"
    price_size = _fit_font_size(price_text, _FONT_BOLD, price_col_w, top_band_h * 0.8,
                                 max_size=top_band_h, min_size=12)
    c.setFont(_FONT_BOLD, price_size)
    price_y = band_split_y + (top_band_h - price_size * 0.72) / 2
    c.drawString(price_col_x, price_y, price_text)

    # ── Bottom third: PLU (left) + barcode (right, large & scannable) ─────
    if plu:
        plu_col_w = (page_w - 2 * margin) * 0.28
        barcode_x = margin + plu_col_w + 2 * mm
        barcode_w = page_w - margin - barcode_x

        plu_size = 9 if small_label else 12
        c.setFont(_FONT, plu_size)
        c.drawString(margin, (bottom_band_h - plu_size * 0.7) / 2, f"PLU {plu}")
    else:
        # No PLU on this product — give the barcode the full width instead
        # of leaving a blank column, since a bigger symbol scans easier.
        barcode_x = margin
        barcode_w = page_w - 2 * margin

    if barcode:
        c.saveState()
        try:
            _draw_fitted_barcode(c, barcode, barcode_x, margin * 0.5, barcode_w,
                                  bottom_band_h - margin * 0.5, small_label=small_label)
        finally:
            c.restoreState()


def _wrap_text(text, font, size, max_width, max_lines=2) -> list[str]:
    """Greedy word-wrap into at most max_lines, truncating the last line
    with an ellipsis only if words were actually left over (not just
    because the wrap happened to land exactly at max_lines)."""
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    consumed = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
            consumed += 1
        else:
            if current:
                lines.append(current)
            current = word
            consumed += 1
            if len(lines) == max_lines:
                consumed -= 1  # this word was never actually placed
                break
    else:
        if current:
            lines.append(current)

    truncated = consumed < len(words)
    if truncated:
        last = lines[-1] if lines else ""
        while stringWidth(last + "…", font, size) > max_width and len(last) > 1:
            last = last[:-1]
        lines = (lines[:-1] if lines else []) + [last + "…"]

    return lines or [""]


def _fit_font_size(text, font, max_width, max_height, max_size=200, min_size=6) -> float:
    """Largest font size (points) that keeps text within max_width and
    max_height, starting from min(max_size, max_height) and shrinking."""
    size = min(max_size, max_height)
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return max(min_size, size)


def _draw_fitted_barcode(c, data, x, y, target_width, target_height, small_label=False):
    """Draw a Code128 barcode (bars + human-readable digits) scaled to fit
    within target_width x target_height, clamped to a minimum bar width so
    bars stay scannable on small labels.

    Code128's own `.height` only covers the bars — the human-readable text
    reportlab draws beneath them is NOT included, so that text's height must
    be reserved here explicitly or it prints past the bottom of the label.
    """
    text_size = 5 if small_label else 7
    text_gap  = 0.5 * mm
    text_h    = text_size * 0.3528 * mm  # points -> mm
    bar_h     = max(2 * mm, target_height - text_h - text_gap)

    # 0.33mm (~13 mil) is a widely-used minimum module width for reliable
    # scanning — bars are never thinner than this even on a tight label,
    # per "barcode larger and easier to scan than previously".
    min_bar_width  = 0.33 * mm
    base_bar_width = 0.5 * mm
    probe = code128.Code128(data, barHeight=bar_h, barWidth=base_bar_width,
                             humanReadable=True, fontSize=text_size)
    if probe.width > target_width:
        scale = target_width / probe.width
        bar_width = max(min_bar_width, base_bar_width * scale)
    else:
        bar_width = base_bar_width

    barcode_obj = code128.Code128(data, barHeight=bar_h, barWidth=bar_width,
                                   humanReadable=True, fontSize=text_size)
    offset_x = x + max(0, (target_width - barcode_obj.width) / 2)
    # Bars sit above the reserved text band, i.e. at the top of target_height.
    barcode_obj.drawOn(c, offset_x, y + text_h + text_gap)
