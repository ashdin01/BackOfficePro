"""
Receipt reprint PDF generation.

Follows the same pattern as utils/label_pdf.py: build a PDF with reportlab
straight onto a canvas (no platypus flow needed for something this simple),
write it to disk, hand it to the OS default viewer for the user to print
from whatever printer they choose.

Sized like a thermal receipt (80mm wide, height grows with the item count)
rather than A4, since this is a reprint of what the customer's register
receipt looked like — not a formal accounts-receivable document like
utils/ar_pdf.py.

Page height can't be known before the item list is laid out (descriptions
wrap to a variable number of lines), so layout happens in two passes over
the same list of draw commands: first to sum up the height they need (to
size the page), then to actually draw them onto the canvas. Passes share
one command list so the measured height can never drift from what's drawn.
"""
import logging
import os
import sys
import tempfile
import uuid

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE_WIDTH_MM = 80.0
MARGIN_MM     = 4.0
LINE_H_MM     = 4.2

_FONT = "Sora"
_FONT_BOLD = "Sora-Bold"

_fonts_dir = os.path.join(_BASE_DIR, 'assets', 'fonts', 'Sora')
try:
    pdfmetrics.registerFont(TTFont(_FONT, os.path.join(_fonts_dir, 'Sora-Regular.ttf')))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, os.path.join(_fonts_dir, 'Sora-Bold.ttf')))
except Exception:
    # Missing/unreadable font files must not take down receipt reprinting
    # with a hard crash at import time — fall back to a built-in font.
    logging.warning(
        "Sora font files not found at %s — falling back to Helvetica for "
        "reprinted receipts.", _fonts_dir
    )
    _FONT = "Helvetica"
    _FONT_BOLD = "Helvetica-Bold"


def render_receipt_pdf(reference: str, txn: dict, store_info: dict, output_path: str) -> str:
    """
    Write a single-page, receipt-width PDF reprinting a POS transaction.

    txn        — dict from product_controller.get_transaction(): sale_date,
                 operator, payment_method, subtotal, gst_amount, total, and
                 items (list of {barcode, description, notes, quantity,
                 unit_price, line_total}). Any of the pricing fields may be
                 None for a sale recorded before unit_price/line_total/totals
                 were tracked — printed as blank rather than "$0.00" so an
                 old reprint doesn't claim a false total.
    store_info — dict with store_name, store_address, store_phone, store_abn.
    """
    page_w = PAGE_WIDTH_MM * mm
    margin = MARGIN_MM * mm
    line_h = LINE_H_MM * mm
    content_w = page_w - 2 * margin

    ops = _build_layout(reference, txn, store_info, content_w)
    total_h = sum(op[-1] for op in ops)
    page_h = total_h + 2 * margin

    if output_path is None:
        output_path = os.path.join(
            tempfile.gettempdir(), f"receipt_{reference}_{uuid.uuid4().hex[:8]}.pdf"
        )

    c = pdfcanvas.Canvas(output_path, pagesize=(page_w, page_h))
    y = page_h - margin
    for op in ops:
        kind = op[0]
        if kind == 'text':
            _, text, font, size, align, dy = op
            c.setFont(font, size)
            baseline = y - size * 0.8
            if align == 'center':
                c.drawCentredString(page_w / 2, baseline, text)
            elif align == 'right':
                c.drawRightString(page_w - margin, baseline, text)
            else:
                c.drawString(margin, baseline, text)
            y -= dy
        elif kind == 'text_pair':
            # left-aligned text with a right-aligned total on the same baseline
            _, left_text, right_text, font, size, dy = op
            c.setFont(font, size)
            baseline = y - size * 0.8
            c.drawString(margin, baseline, left_text)
            c.drawRightString(page_w - margin, baseline, right_text)
            y -= dy
        elif kind == 'rule':
            _, dy = op
            c.setLineWidth(0.5)
            c.line(margin, y - 1, page_w - margin, y - 1)
            y -= dy
        elif kind == 'gap':
            _, dy = op
            y -= dy

    c.showPage()
    c.save()
    return output_path


def _build_layout(reference, txn, store_info, content_w):
    """Return the ordered list of draw commands for the receipt body, each
    tagged with the vertical space (in points) it consumes. Building this
    once and sharing it between the measuring and drawing passes is what
    keeps the two from drifting out of sync."""
    line_h = LINE_H_MM * mm
    ops = []

    def text(s, font=_FONT, size=9, align='left', dy=line_h):
        ops.append(('text', s, font, size, align, dy))

    def text_pair(left, right, font=_FONT, size=9, dy=line_h):
        ops.append(('text_pair', left, right, font, size, dy))

    def rule(dy=line_h * 0.6):
        ops.append(('rule', dy))

    def gap(dy=line_h * 0.3):
        ops.append(('gap', dy))

    store_name = store_info.get('store_name') or ''
    if store_name:
        text(store_name, font=_FONT_BOLD, size=12, align='center')
    if store_info.get('store_address'):
        text(store_info['store_address'], size=8, align='center')
    if store_info.get('store_phone'):
        text(f"Ph: {store_info['store_phone']}", size=8, align='center')
    if store_info.get('store_abn'):
        text(f"ABN: {store_info['store_abn']}", size=8, align='center')
    gap()
    text("RECEIPT REPRINT", font=_FONT_BOLD, size=9, align='center')
    rule()

    text(f"Receipt #: {reference}", size=8)
    when = txn.get('received_at') or txn.get('sale_date') or ''
    text(f"Date: {when}", size=8)
    if txn.get('operator'):
        text(f"Operator: {txn['operator']}", size=8)
    if txn.get('payment_method'):
        text(f"Payment: {txn['payment_method']}", size=8)
    rule()

    detail_width = content_w - 20 * mm
    for it in txn.get('items') or []:
        desc = _item_desc(it)
        line_total = it.get('line_total')
        total_text = f"${line_total:.2f}" if line_total is not None else "—"
        wrapped = _wrap(desc, _FONT, 9, detail_width) or [""]
        for i, wline in enumerate(wrapped):
            if i == 0:
                text_pair(wline, total_text, size=9)
            else:
                text(wline, size=9)

        qty = it.get('quantity')
        qty_val = -qty if qty is not None else None
        qty_text = "" if qty_val is None else (
            f"{qty_val:g}" if qty_val != int(qty_val) else f"{qty_val:.0f}"
        )
        unit_price = it.get('unit_price')
        price_text = f"${unit_price:.2f}" if unit_price is not None else "—"
        text(f"  {qty_text} x {price_text}", size=7.5)

    rule()
    if txn.get('subtotal') is not None:
        text(f"Subtotal: ${txn['subtotal']:.2f}", size=8, align='right')
    if txn.get('gst_amount') is not None:
        text(f"GST: ${txn['gst_amount']:.2f}", size=8, align='right')
    if txn.get('total') is not None:
        text(f"TOTAL: ${txn['total']:.2f}", font=_FONT_BOLD, size=11, align='right')
    gap(dy=line_h * 0.5)
    text("Thank you", size=8, align='center')

    return ops


def _item_desc(item) -> str:
    return item.get('notes') or item.get('description') or ''


def _wrap(text, font, size, max_width, max_lines=2):
    words = (text or "").split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines - 1:
                break
    if cur:
        lines.append(cur)
    return lines[:max_lines]
