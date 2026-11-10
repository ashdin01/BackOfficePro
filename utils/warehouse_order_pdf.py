"""Print-friendly PDF for a Warehouse Order (warehouse -> shop transfer)."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def _fmt_qty(q) -> str:
    return str(int(q)) if float(q) == int(q) else f"{q:g}"


def build_warehouse_order_pdf(path: str, lines: list, created_at, store_name: str = "",
                              notes: str = "") -> None:
    """lines: [{barcode, description, qty}] -> PDF at path (A4 portrait)."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Warehouse Order")
    story = [Paragraph("Warehouse Order", styles["Title"])]
    sub = created_at.strftime("%A %d %B %Y, %H:%M")
    if store_name:
        sub = f"{store_name} &nbsp;|&nbsp; {sub}"
    story.append(Paragraph(sub, styles["Normal"]))
    if notes:
        story += [Spacer(1, 3 * mm), Paragraph(f"Notes: {notes}", styles["Normal"])]
    story.append(Spacer(1, 6 * mm))

    desc_style = styles["BodyText"]
    data = [["Barcode", "Product Description", "Order Qty", "Picked"]]
    for ln in lines:
        data.append([ln["barcode"], Paragraph(ln["description"], desc_style),
                     _fmt_qty(ln["qty"]), ""])
    total = sum(float(ln["qty"]) for ln in lines)
    data.append(["", "Total units", _fmt_qty(total), ""])

    tbl = Table(data, colWidths=[38 * mm, 90 * mm, 28 * mm, 24 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 11),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    story.append(tbl)
    doc.build(story)
