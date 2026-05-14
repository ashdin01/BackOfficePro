"""
Purchase Order PDF generator for BackOfficePro.
Black-and-white, print-safe layout. No coloured backgrounds or text.
"""
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from utils.calculations import gst_on_ex
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
    conn.close()
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


def generate_po_pdf(po_id: int, output_path: str) -> str:
    """Generate a B&W PDF for the given PO. Returns output_path on success."""
    from database.connection import get_connection
    import models.po_lines as lines_model
    import models.product as product_model

    conn = get_connection()
    po = conn.execute("""
        SELECT po.*, s.name as supplier_name, s.email, s.phone,
               s.contact_name, s.account_number, s.address,
               s.payment_terms, s.notes as supplier_notes, s.abn
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = ?
    """, (po_id,)).fetchone()
    conn.close()

    if not po:
        raise ValueError(f"PO {po_id} not found")

    settings = _get_settings()
    st = _styles()
    lines = lines_model.get_by_po(po_id)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm,
    )
    W = A4[0] - 36*mm
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
        f'<b>Status:</b> {po["status"]}',
        f'<b>Date:</b> {datetime.today().strftime("%d/%m/%Y")}',
        f'<b>Delivery:</b> {po["delivery_date"] or "TBC"}',
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
    col_widths = [W*0.36, W*0.14, W*0.10, W*0.16, W*0.12, W*0.12]

    tbl_data = [[
        Paragraph("Description",  st["hdr"]),
        Paragraph("Supplier SKU", st["hdr"]),
        Paragraph("Pack",         st["hdr"]),
        Paragraph("Order Qty",    st["hdr_ctr"]),
        Paragraph("Unit Cost",    st["hdr_right"]),
        Paragraph("Line Total",   st["hdr_right"]),
    ]]

    fixed_total = 0.0
    gst_total   = 0.0

    for line in lines:
        product   = product_model.get_by_barcode(line["barcode"])
        pack_qty  = int(product["pack_qty"])        if product and product["pack_qty"]  else 1
        pack_unit = (product["pack_unit"] or "EA")  if product else "EA"
        sup_sku   = (product["supplier_sku"] or "") if product else ""
        tax_rate  = float(product["tax_rate"])      if product and product["tax_rate"]  else 0.0

        cartons     = int(line["ordered_qty"])
        total_units = cartons * pack_qty

        raw_cost = line["unit_cost"]
        try:
            unit_cost      = float(raw_cost)
            line_total     = total_units * unit_cost
            fixed_total   += line_total
            gst_total     += gst_on_ex(line_total, tax_rate)
            cost_str       = f"${unit_cost:.2f}"
            total_str      = f"${line_total:.2f}"
        except (TypeError, ValueError):
            cost_str  = str(raw_cost) if raw_cost else "—"
            total_str = "—"

        desc_para = Paragraph(
            f'{line["description"]}<br/>'
            f'<font size="7" color="#888888">{line["barcode"]}</font>',
            st["body"]
        )
        pack_str = f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit
        if pack_qty > 1:
            qty_str = f"{cartons} {'ctn' if cartons == 1 else 'ctns'}\n({total_units} units)"
        else:
            qty_str = f"{total_units} units"

        tbl_data.append([
            desc_para,
            Paragraph(sup_sku or "—", st["small"]),
            Paragraph(pack_str,       st["small"]),
            Paragraph(qty_str,        st["ctr"]),
            Paragraph(cost_str,       st["right"]),
            Paragraph(total_str,      st["right"]),
        ])

    lines_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    lines_tbl.setStyle(TableStyle([
        # Header — light grey background, bold black text
        ("BACKGROUND",    (0, 0), (-1, 0), C_LGREY),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        # Data rows
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 0), (-1, -1), 0.4, C_BORDER),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_LGREY]),
        ("BOX",           (0, 0), (-1, -1), 0.75, C_BLACK),
    ]))
    story.append(lines_tbl)
    story.append(Spacer(1, 8))

    # ── Totals ────────────────────────────────────────────────────────────────
    subtotal    = round(fixed_total, 2)
    gst         = round(gst_total, 2)
    grand_total = round(fixed_total + gst_total, 2)

    totals_tbl = Table([
        [Paragraph("Subtotal (ex GST):", st["total_label"]),
         Paragraph(f"${subtotal:.2f}",   st["total_value"])],
        [Paragraph("GST (10%):",         st["total_label"]),
         Paragraph(f"${gst:.2f}",        st["total_value"])],
        [Paragraph("ORDER TOTAL:",       st["grand_label"]),
         Paragraph(f"${grand_total:.2f}", st["grand_value"])],
    ], colWidths=[W * 0.82, W * 0.18])
    totals_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE",     (0, 2), (-1, 2), 1,   C_BLACK),
        ("LINEBELOW",     (0, 2), (-1, 2), 0.75, C_BLACK),
        ("TOPPADDING",    (0, 2), (-1, 2), 6),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 6),
        ("BACKGROUND",    (0, 2), (-1, 2), C_LGREY),
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

    doc.build(story)
    return output_path
