"""Accounts Receivable business logic."""
import os
import math
from datetime import date, timedelta
from calendar import monthrange

from database.connection import get_connection
import models.customer as customer_model
import models.ar_invoice as invoice_model
import models.ar_payment as payment_model
import models.settings as settings_model


# ── Invoice / credit note numbering ──────────────────────────────────────────

def _next_invoice_number():
    conn = get_connection()
    try:
        prefix = 'INV'
        row = conn.execute(
            "SELECT value FROM settings WHERE key='ar_next_invoice_number'"
        ).fetchone()
        seq = int(row['value']) if row else 1
        conn.execute(
            "UPDATE settings SET value=? WHERE key='ar_next_invoice_number'",
            (str(seq + 1),)
        )
        conn.commit()
        return f"{prefix}-{seq:05d}"
    finally:
        conn.close()


def _next_credit_number():
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='ar_next_credit_number'"
        ).fetchone()
        seq = int(row['value']) if row else 1
        conn.execute(
            "UPDATE settings SET value=? WHERE key='ar_next_credit_number'",
            (str(seq + 1),)
        )
        conn.commit()
        return f"CN-{seq:05d}"
    finally:
        conn.close()


# ── Due date (EOM + N days) ───────────────────────────────────────────────────

def calc_due_date(invoice_date, payment_terms_days=37):
    """
    Calculate due date as: end of invoice month + payment_terms_days.
    Default 37 = EOM + 7 days.
    invoice_date: date object or ISO string.
    """
    if isinstance(invoice_date, str):
        invoice_date = date.fromisoformat(invoice_date)
    last_day = monthrange(invoice_date.year, invoice_date.month)[1]
    eom = invoice_date.replace(day=last_day)
    return eom + timedelta(days=payment_terms_days - 30)


# ── Create invoice ────────────────────────────────────────────────────────────

def create_invoice(customer_id, invoice_date=None, notes='', created_by=''):
    if invoice_date is None:
        invoice_date = date.today()
    if isinstance(invoice_date, str):
        invoice_date = date.fromisoformat(invoice_date)

    customer = customer_model.get_by_id(customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    terms     = customer.get('payment_terms_days', 37)
    due_date  = calc_due_date(invoice_date, terms)
    inv_num   = _next_invoice_number()

    invoice_id = invoice_model.create(
        invoice_number=inv_num,
        customer_id=customer_id,
        invoice_date=invoice_date.isoformat(),
        due_date=due_date.isoformat(),
        notes=notes,
        created_by=created_by,
    )
    return invoice_id, inv_num


# ── Record payment ────────────────────────────────────────────────────────────

def record_payment(invoice_id, amount, payment_date=None,
                   method='EFT', reference='', notes=''):
    if payment_date is None:
        payment_date = date.today().isoformat()
    if isinstance(payment_date, date):
        payment_date = payment_date.isoformat()

    inv = invoice_model.get_by_id(invoice_id)
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")

    payment_model.add(
        invoice_id=invoice_id,
        customer_id=inv['customer_id'],
        payment_date=payment_date,
        amount=amount,
        method=method,
        reference=reference,
        notes=notes,
    )

    total_paid = payment_model.total_paid(invoice_id)
    invoice_model.update_amount_paid(invoice_id, total_paid)

    inv_total = float(inv['total'])
    if total_paid >= inv_total:
        invoice_model.update_status(invoice_id, 'PAID')
    elif total_paid > 0:
        invoice_model.update_status(invoice_id, 'PARTIAL')


# ── Create credit note ────────────────────────────────────────────────────────

def create_credit_note(customer_id, reason='', invoice_id=None, cn_date=None):
    if cn_date is None:
        cn_date = date.today().isoformat()
    if isinstance(cn_date, date):
        cn_date = cn_date.isoformat()

    cn_num = _next_credit_number()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO ar_credit_notes
                (credit_note_number, customer_id, invoice_id, date, reason)
            VALUES (?,?,?,?,?)
        """, (cn_num, customer_id, invoice_id, cn_date, reason))
        conn.commit()
        row = conn.execute(
            "SELECT id FROM ar_credit_notes WHERE credit_note_number=?", (cn_num,)
        ).fetchone()
        return row['id'], cn_num
    finally:
        conn.close()


# ── Aged debtors ──────────────────────────────────────────────────────────────

def get_aged_debtors(as_of_date=None):
    """
    Returns list of dicts per customer with outstanding balance split into
    current, 30, 60, 90+ day buckets.
    """
    if as_of_date is None:
        as_of_date = date.today()
    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT i.id, i.invoice_number, i.invoice_date, i.due_date,
                   i.total, i.amount_paid, i.status,
                   c.id AS customer_id, c.name AS customer_name, c.code
            FROM ar_invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.status NOT IN ('PAID', 'VOID')
            ORDER BY c.name, i.due_date
        """).fetchall()
    finally:
        conn.close()

    by_customer = {}
    for r in rows:
        outstanding = round(float(r['total']) - float(r['amount_paid']), 2)
        if outstanding <= 0:
            continue
        due = date.fromisoformat(r['due_date'])
        days_overdue = (as_of_date - due).days

        cid = r['customer_id']
        if cid not in by_customer:
            by_customer[cid] = {
                'customer_id':   cid,
                'customer_name': r['customer_name'],
                'code':          r['code'],
                'current':       0.0,
                'days_30':       0.0,
                'days_60':       0.0,
                'days_90plus':   0.0,
                'total':         0.0,
                'invoices':      [],
            }
        bucket = by_customer[cid]
        bucket['total'] = round(bucket['total'] + outstanding, 2)
        bucket['invoices'].append({
            'invoice_number': r['invoice_number'],
            'due_date':       r['due_date'],
            'outstanding':    outstanding,
            'days_overdue':   days_overdue,
        })
        if days_overdue <= 0:
            bucket['current']    = round(bucket['current']  + outstanding, 2)
        elif days_overdue <= 30:
            bucket['days_30']    = round(bucket['days_30']   + outstanding, 2)
        elif days_overdue <= 60:
            bucket['days_60']    = round(bucket['days_60']   + outstanding, 2)
        else:
            bucket['days_90plus'] = round(bucket['days_90plus'] + outstanding, 2)

    return sorted(by_customer.values(), key=lambda x: x['customer_name'])


def refresh_overdue_statuses():
    """Mark SENT/PARTIAL invoices past due date as OVERDUE."""
    today = date.today().isoformat()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE ar_invoices
            SET status='OVERDUE', updated_at=datetime('now','localtime')
            WHERE status IN ('SENT', 'PARTIAL')
              AND due_date < ?
        """, (today,))
        conn.commit()
    finally:
        conn.close()


# ── Statement data ────────────────────────────────────────────────────────────

def get_statement_data(customer_id, date_from, date_to):
    """
    Returns invoices and payments for a customer within a date range,
    plus opening balance (outstanding before date_from).
    """
    conn = get_connection()
    try:
        opening_rows = conn.execute("""
            SELECT COALESCE(SUM(total - amount_paid), 0) AS balance
            FROM ar_invoices
            WHERE customer_id=? AND invoice_date < ? AND status NOT IN ('PAID','VOID')
        """, (customer_id, date_from)).fetchone()
        opening_balance = float(opening_rows['balance']) if opening_rows else 0.0

        invoices = [dict(r) for r in conn.execute("""
            SELECT invoice_number, invoice_date, due_date, total, amount_paid, status
            FROM ar_invoices
            WHERE customer_id=? AND invoice_date BETWEEN ? AND ?
              AND status != 'VOID'
            ORDER BY invoice_date
        """, (customer_id, date_from, date_to)).fetchall()]

        payments = [dict(r) for r in conn.execute("""
            SELECT p.payment_date, p.amount, p.method, p.reference,
                   i.invoice_number
            FROM ar_payments p
            JOIN ar_invoices i ON i.id = p.invoice_id
            WHERE p.customer_id=? AND p.payment_date BETWEEN ? AND ?
            ORDER BY p.payment_date
        """, (customer_id, date_from, date_to)).fetchall()]

        return {
            'opening_balance': opening_balance,
            'invoices':        invoices,
            'payments':        payments,
        }
    finally:
        conn.close()


# ── MYOB provision ────────────────────────────────────────────────────────────

def push_invoice_to_myob(invoice_id):
    raise NotImplementedError("MYOB AR export not yet implemented")


# ── PDF generation ────────────────────────────────────────────────────────────

def generate_invoice_pdf(invoice_id, output_path=None):
    """
    Generate a two-page PDF:
      Page 1 — ATO-compliant tax invoice (with pricing)
      Page 2 — Delivery docket (no pricing, signature block)
    Returns the file path written.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable, PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    inv   = invoice_model.get_by_id(invoice_id)
    lines = invoice_model.get_lines(invoice_id)
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")

    store_name    = settings_model.get_setting('store_name',    'My Store')
    store_address = settings_model.get_setting('store_address', '')
    store_phone   = settings_model.get_setting('store_phone',   '')
    store_abn     = settings_model.get_setting('store_abn',     '')

    if output_path is None:
        pdf_dir = settings_model.get_setting('ar_invoice_pdf_path', '')
        if not pdf_dir or not os.path.isdir(pdf_dir):
            pdf_dir = os.path.expanduser('~')
        output_path = os.path.join(pdf_dir, f"{inv['invoice_number']}.pdf")

    styles = getSampleStyleSheet()
    h1     = styles['Heading1']
    normal = styles['Normal']
    small  = ParagraphStyle('small',  parent=normal, fontSize=8)
    right  = ParagraphStyle('right',  parent=normal, alignment=TA_RIGHT)
    bold   = ParagraphStyle('bold',   parent=normal, fontName='Helvetica-Bold')
    centre = ParagraphStyle('centre', parent=normal, alignment=TA_CENTER)

    W, H = A4

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
        due  = inv['due_date']
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
                ['Due Date:', due],
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


def generate_statement_pdf(customer_id, date_from, date_to, output_path=None):
    """Generate a customer statement PDF for the given date range."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT

    customer = customer_model.get_by_id(customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    data     = get_statement_data(customer_id, date_from, date_to)
    store_name = settings_model.get_setting('store_name', 'My Store')
    store_abn  = settings_model.get_setting('store_abn', '')

    if output_path is None:
        pdf_dir = settings_model.get_setting('ar_invoice_pdf_path', '')
        if not pdf_dir or not os.path.isdir(pdf_dir):
            pdf_dir = os.path.expanduser('~')
        output_path = os.path.join(
            pdf_dir, f"STMT-{customer['code']}-{date_to}.pdf"
        )

    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small  = ParagraphStyle('small', parent=normal, fontSize=8)
    right  = ParagraphStyle('right', parent=normal, alignment=TA_RIGHT)

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
