"""ReportLab layout functions for AR invoice and statement PDFs.

Both functions accept plain data (dicts/lists) and write a PDF to
output_path.  No DB access — callers are responsible for fetching all
required data before calling here.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER


def render_invoice_pdf(inv: dict, lines: list, store_info: dict, output_path: str) -> str:
    """
    Write a two-page A4 PDF to output_path.
      Page 1 — ATO-compliant tax invoice (with pricing)
      Page 2 — Delivery docket (no pricing, signature block)

    inv        — invoice row dict (invoice_number, invoice_date, due_date,
                 customer_name, address_line1, suburb, state, postcode,
                 customer_abn, subtotal, gst_amount, total, notes)
    lines      — list of line dicts (description, quantity, unit_price,
                 discount_pct, line_gst, line_total)
    store_info — dict with keys: store_name, store_address, store_phone, store_abn
    """
    store_name    = store_info.get('store_name', '')
    store_address = store_info.get('store_address', '')
    store_phone   = store_info.get('store_phone', '')
    store_abn     = store_info.get('store_abn', '')

    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small  = ParagraphStyle('small',  parent=normal, fontSize=8)
    right  = ParagraphStyle('right',  parent=normal, alignment=TA_RIGHT)  # noqa: F841

    def _header_block(title):
        data = [[
            Paragraph(f"<b>{store_name}</b><br/>{store_address}<br/>Ph: {store_phone}<br/>ABN: {store_abn}", normal),
            Paragraph(f"<b>{title}</b>", ParagraphStyle('title', parent=normal, fontSize=18, fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        ]]
        t = Table(data, colWidths=[110*mm, 70*mm])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        return t

    def _customer_invoice_info():
        data = [[
            Paragraph(
                f"<b>Bill To:</b><br/>{inv['customer_name']}<br/>"
                f"{inv.get('address_line1','')}<br/>"
                f"{inv.get('suburb','')} {inv.get('state','')} {inv.get('postcode','')}<br/>"
                f"ABN: {inv.get('customer_abn','')}",
                normal
            ),
            Table([
                ['Invoice No:', inv['invoice_number']],
                ['Invoice Date:', inv['invoice_date']],
                ['Due Date:', inv['due_date']],
            ], colWidths=[35*mm, 45*mm], style=TableStyle([
                ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ])),
        ]]
        t = Table(data, colWidths=[110*mm, 80*mm])
        t.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        return t

    def _lines_table(show_prices):
        if show_prices:
            headers = ['Description', 'Qty', 'Unit Price', 'Disc %', 'GST', 'Total']
            col_w   = [80*mm, 15*mm, 25*mm, 15*mm, 20*mm, 25*mm]
        else:
            headers = ['Description', 'Qty', 'Unit']
            col_w   = [120*mm, 20*mm, 40*mm]

        rows = [headers]
        for ln in lines:
            if show_prices:
                rows.append([
                    ln['description'],
                    f"{ln['quantity']:g}",
                    f"${ln['unit_price']:.2f}",
                    f"{ln['discount_pct']:g}%" if ln['discount_pct'] else '',
                    f"${ln['line_gst']:.2f}",
                    f"${ln['line_total']:.2f}",
                ])
            else:
                rows.append([
                    ln['description'],
                    f"{ln['quantity']:g}",
                    '',
                ])

        style = TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), colors.HexColor('#2d5a27')),
            ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('GRID',          (0,0), (-1,-1), 0.25, colors.HexColor('#cccccc')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('ALIGN',         (1,1), (-1,-1), 'RIGHT'),
            ('ALIGN',         (1,0), (-1,0), 'CENTER'),
        ])
        return Table(rows, colWidths=col_w, style=style, repeatRows=1)

    def _totals_table():
        data = [
            ['Subtotal', f"${inv['subtotal']:.2f}"],
            ['GST (10%)',  f"${inv['gst_amount']:.2f}"],
            ['TOTAL DUE', f"${inv['total']:.2f}"],
        ]
        t = Table(data, colWidths=[130*mm, 30*mm], hAlign='RIGHT')
        t.setStyle(TableStyle([
            ('FONTNAME',      (0,2), (-1,2), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 10),
            ('ALIGN',         (1,0), (1,-1), 'RIGHT'),
            ('LINEABOVE',     (0,2), (-1,2), 1, colors.black),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        return t

    def _signature_block():
        data = [[
            Paragraph("Received in good order by: ______________________________", normal),
            Paragraph("Date: _______________", normal),
        ]]
        t = Table(data, colWidths=[120*mm, 60*mm])
        t.setStyle(TableStyle([('BOTTOMPADDING', (0,0), (-1,-1), 20)]))
        return t

    story = []

    # ── Page 1: Tax Invoice ───────────────────────────────────────────────────
    story.append(_header_block("TAX INVOICE"))
    story.append(Spacer(1, 6*mm))
    story.append(_customer_invoice_info())
    story.append(Spacer(1, 6*mm))
    story.append(_lines_table(show_prices=True))
    story.append(Spacer(1, 4*mm))
    story.append(_totals_table())
    if inv.get('notes'):
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(f"<b>Notes:</b> {inv['notes']}", small))
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        f"Payment due: {inv['due_date']}  |  EFT / Cheque payable to {store_name}",
        ParagraphStyle('payment', parent=small, alignment=TA_CENTER)
    ))

    story.append(PageBreak())

    # ── Page 2: Delivery Docket ───────────────────────────────────────────────
    story.append(_header_block("DELIVERY DOCKET"))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        f"<b>Deliver To:</b> {inv['customer_name']}  |  "
        f"<b>Date:</b> {inv['invoice_date']}  |  "
        f"<b>Ref:</b> {inv['invoice_number']}",
        normal
    ))
    story.append(Spacer(1, 6*mm))
    story.append(_lines_table(show_prices=False))
    story.append(Spacer(1, 12*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 6*mm))
    story.append(_signature_block())
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Please sign and return this docket as confirmation of delivery.",
        ParagraphStyle('docket_footer', parent=small, alignment=TA_CENTER)
    ))

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    doc.build(story)
    return output_path


def render_statement_pdf(customer: dict, data: dict, store_info: dict, output_path: str) -> str:
    """
    Write a customer account statement PDF to output_path.

    customer   — customer row dict (name, code)
    data       — dict with keys: opening_balance, invoices, payments, date_from, date_to
    store_info — dict with keys: store_name, store_abn
    """
    store_name = store_info.get('store_name', '')
    store_abn  = store_info.get('store_abn', '')
    date_from  = data['date_from']
    date_to    = data['date_to']

    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small  = ParagraphStyle('small', parent=normal, fontSize=8)  # noqa: F841

    rows = [['Date', 'Reference', 'Description', 'Amount', 'Balance']]
    balance = data['opening_balance']
    if balance != 0:
        rows.append([date_from, '', 'Opening Balance', '', f"${balance:.2f}"])

    events = []
    for inv in data['invoices']:
        events.append((inv['invoice_date'], 'inv', inv))
    for pmt in data['payments']:
        events.append((pmt['payment_date'], 'pmt', pmt))
    events.sort(key=lambda x: x[0])

    for ev_date, ev_type, ev in events:
        if ev_type == 'inv':
            balance = round(balance + float(ev['total']), 2)
            rows.append([ev['invoice_date'], ev['invoice_number'], 'Invoice', f"${ev['total']:.2f}", f"${balance:.2f}"])
        else:
            balance = round(balance - float(ev['amount']), 2)
            rows.append([ev['payment_date'], ev['invoice_number'], f"Payment ({ev['method']})", f"-${ev['amount']:.2f}", f"${balance:.2f}"])

    tbl = Table(rows, colWidths=[25*mm, 30*mm, 70*mm, 25*mm, 25*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), colors.HexColor('#2d5a27')),
        ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('GRID',          (0,0), (-1,-1), 0.25, colors.HexColor('#cccccc')),
        ('ALIGN',         (3,1), (-1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('FONTNAME',      (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))

    story = [
        Paragraph(f"<b>{store_name}</b>  |  ABN: {store_abn}", normal),
        Spacer(1, 4*mm),
        Paragraph(f"<b>ACCOUNT STATEMENT</b>", ParagraphStyle('stmtTitle', parent=normal, fontSize=14, fontName='Helvetica-Bold')),
        Spacer(1, 2*mm),
        Paragraph(
            f"Customer: <b>{customer['name']}</b>  |  "
            f"Period: {date_from} to {date_to}",
            normal
        ),
        Spacer(1, 6*mm),
        tbl,
        Spacer(1, 4*mm),
        Paragraph(f"<b>Closing Balance: ${balance:.2f}</b>",
                  ParagraphStyle('closing', parent=normal, fontSize=11, fontName='Helvetica-Bold', alignment=TA_RIGHT)),
    ]

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    doc.build(story)
    return output_path
