"""Accounts Receivable business logic."""
import os
import math
from datetime import date, timedelta
from calendar import monthrange

import models.customer as customer_model
import models.ar_invoice as invoice_model
import models.ar_payment as payment_model
import models.settings as settings_model
import models.bank_recon as recon_model
import models.ar_credit_note as ar_credit_note_model


# ── Invoice / credit note numbering ──────────────────────────────────────────

def _next_invoice_number() -> str:
    return settings_model.next_sequence('ar_next_invoice_number', 'INV')


def _next_credit_number() -> str:
    return settings_model.next_sequence('ar_next_credit_number', 'CN')


# ── Due date (EOM + N days) ───────────────────────────────────────────────────

def calc_due_date(invoice_date, payment_terms_days=37) -> date:
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

def create_invoice(customer_id, invoice_date=None, notes='', created_by='') -> tuple[int, str]:
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
                   method='EFT', reference='', notes='') -> int:
    from utils.validators import positive_number
    if payment_date is None:
        payment_date = date.today().isoformat()
    if isinstance(payment_date, date):
        payment_date = payment_date.isoformat()

    try:
        if float(amount) <= 0:
            raise ValueError("Payment amount must be greater than zero")
    except (TypeError, ValueError) as e:
        raise ValueError("Payment amount must be greater than zero") from e

    inv = invoice_model.get_by_id(invoice_id)
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")

    payment_id, _total_paid, _new_status = invoice_model.apply_payment(
        invoice_id=invoice_id,
        customer_id=inv['customer_id'],
        payment_date=payment_date,
        amount=amount,
        method=method,
        reference=reference,
        notes=notes,
    )
    return payment_id


# ── Create credit note ────────────────────────────────────────────────────────

def create_credit_note(customer_id, reason='', invoice_id=None, cn_date=None) -> int:
    if cn_date is None:
        cn_date = date.today().isoformat()
    if isinstance(cn_date, date):
        cn_date = cn_date.isoformat()

    cn_num = _next_credit_number()
    return ar_credit_note_model.create(cn_num, customer_id, invoice_id, cn_date, reason)


# ── Aged debtors ──────────────────────────────────────────────────────────────

def get_aged_debtors(as_of_date=None) -> list[dict]:
    """
    Returns list of dicts per customer with outstanding balance split into
    current, 30, 60, 90+ day buckets.
    """
    if as_of_date is None:
        as_of_date = date.today()
    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)

    rows = invoice_model.get_unpaid_for_aged_debtors()

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


def refresh_overdue_statuses() -> None:
    """Mark SENT/PARTIAL invoices past due date as OVERDUE."""
    invoice_model.refresh_overdue(date.today().isoformat())


# ── Statement data ────────────────────────────────────────────────────────────

def get_statement_data(customer_id, date_from, date_to) -> dict:
    """
    Returns invoices and payments for a customer within a date range,
    plus opening balance (outstanding before date_from).
    """
    return invoice_model.get_statement_rows(customer_id, date_from, date_to)


# ── MYOB provision ────────────────────────────────────────────────────────────

def push_invoice_to_myob(invoice_id) -> tuple[bool, str]:
    """Push an AR invoice to MYOB AccountRight as a bill.
    Returns (False, message) until OAuth registration is complete.
    """
    return False, (
        "MYOB export is not yet active.\n\n"
        "To enable: register the app at developer.myob.com and "
        "complete the OAuth credentials in Settings."
    )


# ── PDF generation ────────────────────────────────────────────────────────────

def generate_invoice_pdf(invoice_id, output_path=None) -> str:
    """
    Generate a two-page PDF:
      Page 1 — ATO-compliant tax invoice (with pricing)
      Page 2 — Delivery docket (no pricing, signature block)
    Returns the file path written.
    """
    from utils.ar_pdf import render_invoice_pdf

    inv   = invoice_model.get_by_id(invoice_id)
    lines = invoice_model.get_lines(invoice_id)
    if not inv:
        raise ValueError(f"Invoice {invoice_id} not found")

    store_info = {
        'store_name':    settings_model.get_setting('store_name',    'My Store'),
        'store_address': settings_model.get_setting('store_address', ''),
        'store_phone':   settings_model.get_setting('store_phone',   ''),
        'store_abn':     settings_model.get_setting('store_abn',     ''),
    }

    if output_path is None:
        pdf_dir = settings_model.get_setting('ar_invoice_pdf_path', '')
        if not pdf_dir or not os.path.isdir(pdf_dir):
            pdf_dir = os.path.expanduser('~')
        output_path = os.path.join(pdf_dir, f"{inv['invoice_number']}.pdf")

    return render_invoice_pdf(inv, lines, store_info, output_path)


def generate_statement_pdf(customer_id, date_from, date_to, output_path=None) -> str:
    """Generate a customer statement PDF for the given date range."""
    from utils.ar_pdf import render_statement_pdf

    customer = customer_model.get_by_id(customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")

    stmt_data = get_statement_data(customer_id, date_from, date_to)
    stmt_data['date_from'] = date_from
    stmt_data['date_to']   = date_to

    store_info = {
        'store_name': settings_model.get_setting('store_name', 'My Store'),
        'store_abn':  settings_model.get_setting('store_abn',  ''),
    }

    if output_path is None:
        pdf_dir = settings_model.get_setting('ar_invoice_pdf_path', '')
        if not pdf_dir or not os.path.isdir(pdf_dir):
            pdf_dir = os.path.expanduser('~')
        output_path = os.path.join(
            pdf_dir, f"STMT-{customer['code']}-{date_to}.pdf"
        )

    return render_statement_pdf(customer, stmt_data, store_info, output_path)


# ── Invoice model wrappers ────────────────────────────────────────────────────

def get_invoice_by_id(invoice_id) -> dict | None:
    return invoice_model.get_by_id(invoice_id)


def get_all_invoices(customer_id=None, status=None,
                     limit=None, offset=0) -> list[dict]:
    return invoice_model.get_all(customer_id=customer_id, status=status,
                                 limit=limit, offset=offset)


def count_invoices(customer_id=None, status=None) -> int:
    return invoice_model.count(customer_id=customer_id, status=status)


def get_invoice_lines(invoice_id) -> list[dict]:
    return invoice_model.get_lines(invoice_id)


def _validate_invoice_line(description, quantity, unit_price, discount_pct, gst_rate):
    from utils.validators import positive_number, percentage
    if not str(description).strip():
        raise ValueError("Line description is required.")
    try:
        if float(quantity) <= 0:
            raise ValueError("Quantity must be greater than zero")
    except (TypeError, ValueError) as e:
        raise ValueError("Quantity must be greater than zero") from e
    positive_number(unit_price,  "Unit price")
    percentage(discount_pct,     "Discount %")
    percentage(gst_rate,         "GST rate")


def add_invoice_line(invoice_id, description, quantity, unit_price,
                     discount_pct=0.0, gst_rate=10.0, barcode='') -> None:
    _validate_invoice_line(description, quantity, unit_price, discount_pct, gst_rate)
    invoice_model.add_line(invoice_id, description, quantity, unit_price,
                           discount_pct=discount_pct, gst_rate=gst_rate, barcode=barcode)


def update_invoice_line(line_id, description, quantity, unit_price,
                        discount_pct=0.0, gst_rate=10.0, barcode='') -> None:
    _validate_invoice_line(description, quantity, unit_price, discount_pct, gst_rate)
    invoice_model.update_line(line_id, description, quantity, unit_price,
                              discount_pct=discount_pct, gst_rate=gst_rate, barcode=barcode)


def delete_invoice_line(line_id) -> None:
    invoice_model.delete_line(line_id)


def update_invoice_status(invoice_id, status) -> None:
    invoice_model.update_status(invoice_id, status)


def update_invoice_notes(invoice_id, notes) -> None:
    invoice_model.update_notes(invoice_id, notes)


# ── Customer model wrappers ───────────────────────────────────────────────────

def get_all_customers(active_only=True, limit=None, offset=0) -> list[dict]:
    return customer_model.get_all(active_only=active_only, limit=limit, offset=offset)


def count_customers(active_only=True) -> int:
    return customer_model.count(active_only=active_only)


def get_customer_by_id(customer_id) -> dict | None:
    return customer_model.get_by_id(customer_id)


def create_customer(code, name, abn='', address_line1='', address_line2='',
                    suburb='', state='', postcode='', email='', phone='',
                    contact_name='', payment_terms_days=37, credit_limit=0.0,
                    active=1, notes='') -> int:
    return customer_model.create(code, name, abn=abn, address_line1=address_line1,
                               address_line2=address_line2, suburb=suburb, state=state,
                               postcode=postcode, email=email, phone=phone,
                               contact_name=contact_name,
                               payment_terms_days=payment_terms_days,
                               credit_limit=credit_limit, active=active, notes=notes)


def update_customer(customer_id, code, name, abn='', address_line1='',
                    address_line2='', suburb='', state='', postcode='',
                    email='', phone='', contact_name='',
                    payment_terms_days=37, credit_limit=0.0, active=1, notes='') -> None:
    customer_model.update(customer_id, code, name, abn=abn,
                          address_line1=address_line1, address_line2=address_line2,
                          suburb=suburb, state=state, postcode=postcode,
                          email=email, phone=phone, contact_name=contact_name,
                          payment_terms_days=payment_terms_days,
                          credit_limit=credit_limit, active=active, notes=notes)


# ── Payment model wrappers ────────────────────────────────────────────────────

def get_payments_by_invoice(invoice_id) -> list[dict]:
    return payment_model.get_by_invoice(invoice_id)


# ── Bank recon model wrappers ─────────────────────────────────────────────────

def get_all_recon_profiles() -> list[dict]:
    return recon_model.get_all_profiles()


def get_recon_profile(profile_id) -> dict | None:
    return recon_model.get_profile(profile_id)


def delete_recon_profile(profile_id) -> None:
    recon_model.delete_profile(profile_id)


def save_recon_profile(name, delimiter, has_header, skip_rows, date_format,
                       amount_type, col_date=None, col_amount=None,
                       col_debit=None, col_credit=None, col_description=None,
                       col_reference=None, col_balance=None) -> int:
    return recon_model.save_profile(name, delimiter, has_header, skip_rows,
                                    date_format, amount_type,
                                    col_date=col_date, col_amount=col_amount,
                                    col_debit=col_debit, col_credit=col_credit,
                                    col_description=col_description,
                                    col_reference=col_reference,
                                    col_balance=col_balance)


def get_recon_transactions(batch) -> list[dict]:
    return recon_model.get_transactions(batch)


def insert_recon_transactions(profile_id, batch, rows) -> None:
    recon_model.insert_transactions(profile_id, batch, rows)


def set_recon_matched(txn_id, invoice_id, payment_id) -> None:
    recon_model.set_matched(txn_id, invoice_id, payment_id)


def set_recon_ignored(txn_id) -> None:
    recon_model.set_ignored(txn_id)


def unmatch_recon_transaction(txn_id) -> None:
    recon_model.unmatch_transaction(txn_id)


def get_credit_note_by_id(cn_id) -> dict | None:
    return ar_credit_note_model.get_by_id(cn_id)
