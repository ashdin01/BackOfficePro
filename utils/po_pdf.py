"""
Purchase Order PDF generator for BackOfficePro.
Black-and-white, print-safe layout. No coloured backgrounds or text.
"""
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from utils.calculations import gst_on_ex
from utils.po_type_helpers import po_unit_mode, po_is_return, po_display_qty, fmt_money
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

C_BLACK  = colors.HexColor("#111111")
C_GREY   = colors.HexColor("#555555")
C_LGREY  = colors.HexColor("#f2f2f2")   # alternate row
C_BORDER = colors.HexColor("#aaaaaa")
C_WHITE  = colors.white


def _get_settings():
    from database.connection import get_connection
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.release()
    return {r[0]: (r[1] or "") for r in rows}


def _styles():
    return {
        "title": ParagraphStyle("title",
            fontSize=20, fontName="Helvetica-Bold", textColor=C_BLACK, spaceAfter=2),
        "body": ParagraphStyle("body",
            fontSize=9, fontName="Helvetica", textColor=C_BLACK, leading=13),
        "body_bold": ParagraphStyle("body_bold",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK),
        "right": ParagraphStyle("right",
            fontSize=9, fontName="Helvetica", textColor=C_BLACK, alignment=TA_RIGHT),
        "right_bold": ParagraphStyle("right_bold",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "small": ParagraphStyle("small",
            fontSize=8, fontName="Helvetica", textColor=C_GREY),
        "ctr": ParagraphStyle("ctr",
            fontSize=9, fontName="Helvetica", textColor=C_BLACK, alignment=TA_CENTER),
        "hdr": ParagraphStyle("hdr",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK),
        "hdr_plain": ParagraphStyle("hdr_plain",
            fontSize=9, fontName="Helvetica", textColor=C_BLACK),
        "hdr_plain_right": ParagraphStyle("hdr_plain_right",
            fontSize=9, fontName="Helvetica", textColor=C_BLACK, alignment=TA_RIGHT),
        "hdr_ctr": ParagraphStyle("hdr_ctr",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_CENTER),
        "hdr_right": ParagraphStyle("hdr_right",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "total_label": ParagraphStyle("total_label",
            fontSize=10, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "total_value": ParagraphStyle("total_value",
            fontSize=10, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "grand_label": ParagraphStyle("grand_label",
            fontSize=12, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "grand_value": ParagraphStyle("grand_value",
            fontSize=12, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "po_label": ParagraphStyle("po_label",
            fontSize=9, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "po_number": ParagraphStyle("po_number",
            fontSize=16, fontName="Helvetica-Bold", textColor=C_BLACK, alignment=TA_RIGHT),
        "footer": ParagraphStyle("footer",
            fontSize=7, fontName="Helvetica", textColor=C_GREY, alignment=TA_CENTER),
    }


def _po_date(po) -> str:
    """PO creation date (not today's), so reprints keep the original date."""
    raw = str(po["created_at"] or "")[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return datetime.today().strftime("%d/%m/%Y")


def _numbered_canvas_cls(po_number):
    from reportlab.pdfgen import canvas as _canvas

    class _NumberedCanvas(_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self.setFont("Helvetica", 7)
                self.setFillColor(C_GREY)
                w, _ = self._pagesize
                self.drawCentredString(
                    w / 2, 8 * mm,
                    f"{po_number}  |  Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    return _NumberedCanvas


def generate_po_pdf(po_id: int, output_path: str) -> str:
    """Generate a B&W PDF for the given PO. Returns output_path on success."""
    from database.connection import get_connection
    import models.po_lines as lines_model
    import models.product as product_model
    import models.product_suppliers as product_suppliers_model

    conn = get_connection()
    po = conn.execute("""
        SELECT po.*, s.name as supplier_name, s.email, s.phone,
               s.contact_name, s.account_number, s.address,
               s.payment_terms, s.notes as supplier_notes, s.abn
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = ?
    """, (po_id,)).fetchone()
    conn.release()

    if not po:
        raise ValueError(f"PO {po_id} not found")

    settings  = _get_settings()
    st        = _styles()
    lines     = lines_model.get_by_po(po_id)
    _po_type  = po["po_type"] or "PO"
    unit_mode = po_unit_mode(_po_type)
    is_return = po_is_return(_po_type)

    # Per-supplier SKU/pack size overrides — a product can be linked to
    # multiple suppliers with different codes/pack sizes, so this PO must
    # show what *this* supplier actually uses, not the product's default.
    supplier_overrides = product_suppliers_model.get_map_for_barcodes(
        [l["barcode"] for l in lines if not l["is_note"]], po["supplier_id"]
    )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=20*mm,
    )
    W = landscape(A4)[0] - 36*mm
    story = []

    # ── Header: store name left, PO number right ──────────────────────────────
    store_name = settings.get("store_name", "My Supermarket")
    store_abn  = settings.get("store_abn",  "")
    store_addr = settings.get("store_address", "")
    store_ph   = settings.get("store_phone", "")

    from config.constants import PO_DOC_TITLES
    doc_title = PO_DOC_TITLES.get(po["po_type"] or "PO", "PURCHASE ORDER")

    header_data = [[
        Paragraph(store_name, st["title"]),
        [Paragraph(doc_title,        st["po_label"]),
         Paragraph(po["po_number"],  st["po_number"])],
    ]]
    header_tbl = Table(header_data, colWidths=[W * 0.6, W * 0.4])
    header_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_tbl)

    details = []
    if store_addr: details.append(store_addr)
    if store_ph:   details.append(f"Ph: {store_ph}")
    if store_abn:  details.append(f"ABN: {store_abn}")
    if details:
        story.append(Paragraph(" | ".join(details), st["small"]))

    story.append(HRFlowable(width="100%", thickness=1.5,
                            color=C_BLACK, spaceAfter=8))

    # ── Info block: Supplier left, PO details right ───────────────────────────
    sup_lines = [f'<b>{po["supplier_name"]}</b>']
    if po["contact_name"]:   sup_lines.append(po["contact_name"])
    if po["address"]:        sup_lines.append(po["address"])
    if po["phone"]:          sup_lines.append(f'Ph: {po["phone"]}')
    if po["email"]:          sup_lines.append(f'Email: {po["email"]}')
    if po["account_number"]: sup_lines.append(f'Account: {po["account_number"]}')

    po_details = [
        f'<b>PO Number:</b> {po["po_number"]}',
        f'<b>Status:</b> {po["status"]}',
        f'<b>Date:</b> {_po_date(po)}',
        '<b>Currency:</b> AUD',
        f'<b>Total lines:</b> {sum(1 for l in lines if not l["is_note"])}',
    ]
    if po["payment_terms"]:
        po_details.append(f'<b>Terms:</b> {po["payment_terms"]}')

    info_tbl = Table(
        [[Paragraph("<br/>".join(sup_lines),  st["body"]),
          Paragraph("<br/>".join(po_details), st["body"])]],
        colWidths=[W * 0.55, W * 0.45]
    )
    info_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BOX",           (0, 0), (-1, -1), 0.75, C_BLACK),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5,  C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 10))

    if po["notes"]:
        story.append(Paragraph(f'<b>Notes:</b> {po["notes"]}', st["small"]))
        story.append(Spacer(1, 6))

    # ── Line items table ──────────────────────────────────────────────────────
    col_widths = [W*0.04, W*0.15, W*0.12, W*0.26, W*0.08,
                  W*0.08, W*0.07, W*0.10, W*0.10]

    tbl_data = [[
        Paragraph("#",            st["hdr_plain"]),
        Paragraph("Supplier SKU", st["hdr_plain"]),
        Paragraph("Barcode",      st["hdr_plain"]),
        Paragraph("Description",  st["hdr_plain"]),
        Paragraph("Pack",         st["hdr_plain"]),
        Paragraph("Cartons",      st["hdr_right"]),   # only bold heading: guards carton vs unit mix-ups
        Paragraph("Units",        st["hdr_plain_right"]),
        Paragraph("Unit Cost (ex GST)", st["hdr_plain_right"]),
        Paragraph("Line Total",   st["hdr_plain_right"]),
    ]]
    line_no = 0
    line_rates = set()   # non-zero GST rates seen on lines
    tot_cartons = 0
    tot_units   = 0
    notes_out = []   # (line number it follows, text)

    fixed_total = 0.0
    gst_total   = 0.0

    for line in lines:
        # ── Note line — span description column, skip numeric columns ────
        if line["is_note"]:
            notes_out.append((line_no, line["description"]))
            continue
        line_no += 1

        product  = product_model.get_by_barcode(line["barcode"])
        override = supplier_overrides.get(line["barcode"])
        if override:
            pack_qty  = int(override["pack_qty"]) or 1
            pack_unit = override["pack_unit"] or "EA"
            sup_sku   = override["supplier_sku"] or ""
        else:
            pack_qty  = int(product["pack_qty"])        if product and product["pack_qty"]  else 1
            pack_unit = (product["pack_unit"] or "EA")  if product else "EA"
            sup_sku   = (product["supplier_sku"] or "") if product else ""
        tax_rate  = float(product["tax_rate"])      if product and product["tax_rate"]  else 0.0
        if tax_rate:
            line_rates.add(tax_rate)

        total_units = po_display_qty(_po_type, int(line["ordered_qty"]), pack_qty)
        cartons     = int(line["ordered_qty"])

        raw_cost = line["unit_cost"]
        try:
            unit_cost      = float(raw_cost)
            line_total     = total_units * unit_cost
            fixed_total   += line_total
            gst_total     += gst_on_ex(abs(line_total), tax_rate) * (-1 if is_return else 1)
            cost_str       = f"${unit_cost:.2f}"
            total_str      = fmt_money(line_total)
        except (TypeError, ValueError):
            cost_str  = str(raw_cost) if raw_cost else "-"
            total_str = "-"

        pack_str = f"{pack_qty} x {pack_unit}" if pack_qty > 1 else pack_unit
        # Cartons only mean something when the line is ordered in cartons
        by_carton = not unit_mode and pack_qty > 1
        ctn_str = f"{cartons} ctn" if by_carton else "-"
        tot_cartons += cartons if by_carton else 0
        tot_units   += total_units

        tbl_data.append([
            Paragraph(str(line_no),   st["body"]),
            Paragraph(sup_sku or "-", st["body"]),
            Paragraph(str(line["barcode"]), st["body"]),
            Paragraph(line["description"],  st["body"]),
            Paragraph(pack_str,       st["body"]),
            Paragraph(ctn_str,        st["right_bold"]),
            Paragraph(str(total_units), st["right"]),
            Paragraph(cost_str,       st["right"]),
            Paragraph(total_str,      st["right"]),
        ])

    # Group heading over Cartons / Units (cols 5-6)
    tbl_data.insert(0, ["", "", "", "", "",
                        Paragraph("ORDER", st["hdr_ctr"]), "", "", ""])

    lines_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=2)
    lines_tbl.setStyle(TableStyle([
        ("SPAN",          (5, 0), (6, 0)),
        ("BOX",           (5, 0), (6, 0), 1.0, C_BLACK),
        ("TOPPADDING",    (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        # Header — light grey background
        ("BACKGROUND",    (0, 1), (-1, 1), C_LGREY),
        ("TOPPADDING",    (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
        # Data rows
        ("FONTSIZE",      (0, 2), (-1, -1), 8),
        ("TOPPADDING",    (0, 2), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 2), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 1), (-1, -1), 0.25, C_BORDER),
        ("BOX",           (5, 1), (5, -1), 1.0, C_BLACK),
        ("BOX",           (0, 1), (-1, -1), 0.75, C_BLACK),
    ]))
    story.append(lines_tbl)
    story.append(Spacer(1, 8))

    if notes_out:
        story.append(Paragraph("<b>Line notes</b>", st["body"]))
        for after, text in notes_out:
            where = f"After line {after}" if after else "Before line 1"
            story.append(Paragraph(f"{where}: {text}", st["body"]))
        story.append(Spacer(1, 8))

    # ── Totals ────────────────────────────────────────────────────────────────
    subtotal    = round(fixed_total, 2)
    gst         = round(gst_total, 2)
    grand_total = round(fixed_total + gst_total, 2)

    grand_label = "CREDIT TOTAL:" if is_return else "ORDER TOTAL:"
    if abs(gst) < 0.005:
        gst_label = "GST (none - GST-free):"
    elif len(line_rates) == 1:
        gst_label = f"GST ({line_rates.pop():g}%):"
    else:
        gst_label = "GST (mixed rates):"
    qty_label = "ORDER QTY:" if not is_return else "RETURN QTY:"
    totals_tbl = Table([
        [Paragraph(qty_label, st["total_label"]),
         Paragraph(f"{tot_cartons} ctn / {tot_units} units", st["total_value"])],
        [Paragraph("Subtotal (ex GST):", st["total_label"]),
         Paragraph(fmt_money(subtotal),       st["total_value"])],
        [Paragraph(gst_label,            st["total_label"]),
         Paragraph(fmt_money(gst),            st["total_value"])],
        [Paragraph(grand_label,          st["grand_label"]),
         Paragraph(fmt_money(grand_total),    st["grand_value"])],
    ], colWidths=[W * 0.76, W * 0.24])
    totals_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE",     (0, 3), (-1, 3), 1,   C_BLACK),
        ("LINEBELOW",     (0, 3), (-1, 3), 0.75, C_BLACK),
        ("TOPPADDING",    (0, 3), (-1, 3), 6),
        ("BOTTOMPADDING", (0, 3), (-1, 3), 6),
        ("BACKGROUND",    (0, 3), (-1, 3), C_LGREY),
    ]))
    story.append(totals_tbl)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=C_BORDER, spaceAfter=4))
    story.append(Paragraph(
        f'Generated by BackOfficePro  |  {datetime.now().strftime("%d/%m/%Y %H:%M")}  |  {po["po_number"]}',
        st["footer"]
    ))

    doc.build(story, canvasmaker=_numbered_canvas_cls(po["po_number"]))
    return output_path
