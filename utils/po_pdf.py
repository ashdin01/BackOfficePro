"""
Purchase Order PDF generator for BackOfficePro.
Uses reportlab Platypus for clean, professional output.
"""
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)


# ── Colour palette (matches BackOfficePro dark theme, adapted for print) ──
C_DARK    = colors.HexColor("#1a2332")
C_MID     = colors.HexColor("#1e2a38")
C_BLUE    = colors.HexColor("#1565c0")
C_GREEN   = colors.HexColor("#2e7d32")
C_TEXT    = colors.HexColor("#212121")
C_SUBTEXT = colors.HexColor("#555555")
C_BORDER  = colors.HexColor("#cccccc")
C_HDR_BG  = colors.HexColor("#1565c0")
C_ROW_ALT = colors.HexColor("#f5f7fa")
C_WHITE   = colors.white


def _get_settings():
    from database.connection import get_connection
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r[0]: (r[1] or "") for r in rows}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title",
            fontSize=20, fontName="Helvetica-Bold",
            textColor=C_DARK, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle",
            fontSize=10, fontName="Helvetica",
            textColor=C_SUBTEXT, spaceAfter=2),
        "section": ParagraphStyle("section",
            fontSize=9, fontName="Helvetica-Bold",
            textColor=C_SUBTEXT, spaceBefore=8, spaceAfter=4,
            borderPad=0),
        "body": ParagraphStyle("body",
            fontSize=9, fontName="Helvetica",
            textColor=C_TEXT, leading=13),
        "body_bold": ParagraphStyle("body_bold",
            fontSize=9, fontName="Helvetica-Bold",
            textColor=C_TEXT),
        "right": ParagraphStyle("right",
            fontSize=9, fontName="Helvetica",
            textColor=C_TEXT, alignment=TA_RIGHT),
        "right_bold": ParagraphStyle("right_bold",
            fontSize=9, fontName="Helvetica-Bold",
            textColor=C_TEXT, alignment=TA_RIGHT),
        "small": ParagraphStyle("small",
            fontSize=8, fontName="Helvetica",
            textColor=C_SUBTEXT),
        "total_label": ParagraphStyle("total_label",
            fontSize=10, fontName="Helvetica-Bold",
            textColor=C_TEXT, alignment=TA_RIGHT),
        "total_value": ParagraphStyle("total_value",
            fontSize=10, fontName="Helvetica-Bold",
            textColor=C_BLUE, alignment=TA_RIGHT),
    }


def generate_po_pdf(po_id: int, output_path: str) -> str:
    """
    Generate a PDF for the given PO and save to output_path.
    Returns the output_path on success.
    """
    from database.connection import get_connection
    import models.po_lines as lines_model
    import models.product as product_model
    import models.stock_on_hand as stock_model

    conn = get_connection()

    # Load PO + supplier
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

    # ── Document setup ────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm,
    )
    W = A4[0] - 36*mm   # usable width

    story = []

    # ── Header: Store name + PO number ───────────────────────────────────
    store_name = settings.get("store_name", "My Supermarket")
    store_abn  = settings.get("store_abn", "")
    store_addr = settings.get("store_address", "")
    store_ph   = settings.get("store_phone", "")

    header_data = [[
        Paragraph(store_name, st["title"]),
        Paragraph(
            f'<b>PURCHASE ORDER</b><br/>'
            f'<font size="14" color="#1565c0">{po["po_number"]}</font>',
            ParagraphStyle("po_num", fontSize=9, fontName="Helvetica-Bold",
                           alignment=TA_RIGHT, textColor=C_TEXT)
        )
    ]]
    header_tbl = Table(header_data, colWidths=[W*0.6, W*0.4])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(header_tbl)

    # Store details line
    store_details = []
    if store_addr: store_details.append(store_addr)
    if store_ph:   store_details.append(f"Ph: {store_ph}")
    if store_abn:  store_details.append(f"ABN: {store_abn}")
    if store_details:
        story.append(Paragraph(" | ".join(store_details), st["small"]))

    story.append(HRFlowable(width="100%", thickness=2,
                            color=C_BLUE, spaceAfter=8))

    # ── Two-column info block: Supplier | PO Details ──────────────────────
    sup_lines = [f'<b>{po["supplier_name"]}</b>']
    if po["contact_name"]: sup_lines.append(po["contact_name"])
    if po["address"]:      sup_lines.append(po["address"])
    if po["phone"]:        sup_lines.append(f'Ph: {po["phone"]}')
    if po["email"]:        sup_lines.append(f'Email: {po["email"]}')
    if po["account_number"]: sup_lines.append(f'Account: {po["account_number"]}')

    po_details = [
        f'<b>Status:</b> {po["status"]}',
        f'<b>Date:</b> {datetime.today().strftime("%d/%m/%Y")}',
        f'<b>Delivery:</b> {po["delivery_date"] or "TBC"}',
    ]
    if po["payment_terms"]:
        po_details.append(f'<b>Terms:</b> {po["payment_terms"]}')

    info_data = [[
        Paragraph("<br/>".join(sup_lines), st["body"]),
        Paragraph("<br/>".join(po_details), st["body"]),
    ]]
    info_tbl = Table(info_data, colWidths=[W*0.55, W*0.45])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BACKGROUND", (0,0), (-1,-1), C_ROW_ALT),
        ("BOX", (0,0), (-1,-1), 0.5, C_BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.5, C_BORDER),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 10))

    # ── PO Notes ─────────────────────────────────────────────────────────
    if po["notes"]:
        story.append(Paragraph(f'<b>Notes:</b> {po["notes"]}', st["small"]))
        story.append(Spacer(1, 6))

    # ── Line items table ──────────────────────────────────────────────────
    col_widths = [
        W*0.14,   # Barcode
        W*0.35,   # Description
        W*0.10,   # Pack Size
        W*0.10,   # SKU
        W*0.10,   # Qty (units)
        W*0.11,   # Unit Cost
        W*0.10,   # Line Total
    ]

    tbl_data = [[
        Paragraph("Barcode",     st["body_bold"]),
        Paragraph("Description", st["body_bold"]),
        Paragraph("Pack",        st["body_bold"]),
        Paragraph("SKU",         st["body_bold"]),
        Paragraph("Qty\n(Units)",st["body_bold"]),
        Paragraph("Unit\nCost",  st["body_bold"]),
        Paragraph("Line\nTotal", st["right_bold"]),
    ]]

    fixed_total = 0.0
    gst_total   = 0.0

    for idx, line in enumerate(lines):
        product   = product_model.get_by_barcode(line["barcode"])
        pack_qty  = int(product["pack_qty"])  if product and product["pack_qty"]  else 1
        pack_unit = (product["pack_unit"] or "EA") if product else "EA"
        sup_sku   = (product["supplier_sku"] or "") if product else ""
        tax_rate  = float(product["tax_rate"]) if product and product["tax_rate"] else 0.0

        cartons     = int(line["ordered_qty"])
        total_units = cartons * pack_qty
        unit_cost   = float(line["unit_cost"])
        line_total  = total_units * unit_cost

        fixed_total += line_total
        if tax_rate > 0:
            gst_total += line_total - (line_total / (1 + tax_rate / 100))

        pack_str = f"{pack_qty}x{pack_unit}"
        row_bg = C_WHITE if idx % 2 == 0 else C_ROW_ALT

        tbl_data.append([
            Paragraph(line["barcode"],    st["small"]),
            Paragraph(line["description"], st["body"]),
            Paragraph(pack_str,           st["small"]),
            Paragraph(sup_sku,            st["small"]),
            Paragraph(str(total_units),
                ParagraphStyle("ctr", fontSize=9, fontName="Helvetica",
                               alignment=TA_CENTER, textColor=C_TEXT)),
            Paragraph(f"${unit_cost:.4f}", st["right"]),
            Paragraph(f"${line_total:.2f}", st["right"]),
        ])

    lines_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)

    # Build row styles
    row_styles = [
        # Header row
        ("BACKGROUND",    (0,0), (-1,0), C_HDR_BG),
        ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 8),
        ("TOPPADDING",    (0,0), (-1,0), 6),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        # All rows
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("TOPPADDING",    (0,1), (-1,-1), 4),
        ("BOTTOMPADDING", (0,1), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("GRID",          (0,0), (-1,-1), 0.4, C_BORDER),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_ROW_ALT]),
    ]
    lines_tbl.setStyle(TableStyle(row_styles))
    story.append(lines_tbl)
    story.append(Spacer(1, 8))

    # ── Totals block ──────────────────────────────────────────────────────
    subtotal = round(fixed_total - gst_total, 2)
    gst      = round(gst_total, 2)

    totals_data = [
        [Paragraph("Subtotal (ex GST):", st["total_label"]),
         Paragraph(f"${subtotal:.2f}", st["total_value"])],
        [Paragraph("GST (10%):", st["total_label"]),
         Paragraph(f"${gst:.2f}", st["total_value"])],
        [Paragraph("ORDER TOTAL:", ParagraphStyle("ot",
            fontSize=12, fontName="Helvetica-Bold",
            alignment=TA_RIGHT, textColor=C_DARK)),
         Paragraph(f"${fixed_total:.2f}", ParagraphStyle("otv",
            fontSize=12, fontName="Helvetica-Bold",
            alignment=TA_RIGHT, textColor=C_GREEN))],
    ]
    totals_tbl = Table(totals_data,
                       colWidths=[W*0.82, W*0.18])
    totals_tbl.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LINEABOVE",     (0,2), (-1,2), 1, C_DARK),
        ("TOPPADDING",    (0,2), (-1,2), 6),
    ]))
    story.append(totals_tbl)

    # ── Supplier notes footer ─────────────────────────────────────────────
    if po["supplier_notes"]:
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=C_BORDER, spaceAfter=4))
        story.append(Paragraph(
            f'<b>Supplier Notes:</b> {po["supplier_notes"]}', st["small"]))

    # ── Footer ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=C_BORDER, spaceAfter=4))
    story.append(Paragraph(
        f'Generated by BackOfficePro  |  {datetime.now().strftime("%d/%m/%Y %H:%M")}  |  {po["po_number"]}',
        ParagraphStyle("footer", fontSize=7, fontName="Helvetica",
                       textColor=C_SUBTEXT, alignment=TA_CENTER)
    ))

    doc.build(story)
    return output_path
