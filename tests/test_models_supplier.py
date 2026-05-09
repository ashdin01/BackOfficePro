"""Tests for models/supplier.py."""
import pytest
from datetime import date, timedelta
from database.connection import get_connection
import models.supplier as supplier_model


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add(db_conn, code='SUP1', name='Supplier One', **kwargs):
    supplier_model.add(code, name, **kwargs)
    row = db_conn.execute("SELECT id FROM suppliers WHERE code=?", (code.upper(),)).fetchone()
    return row['id']


def _make_po(db_conn, supplier_id, status='DRAFT', days_ago=0):
    """Insert a minimal purchase order for suppression tests."""
    ts = f"datetime('now', '-{days_ago} day')" if days_ago else "CURRENT_TIMESTAMP"
    db_conn.execute(f"""
        INSERT INTO purchase_orders (po_number, supplier_id, status, created_at, updated_at)
        VALUES ('TST-00001', ?, ?, {ts}, {ts})
    """, (supplier_id, status))
    db_conn.commit()


# ── add / get_by_id ───────────────────────────────────────────────────────────

def test_add_code_uppercased(test_db):
    supplier_model.add('abc', 'Lower Code Supplier')
    conn = get_connection()
    row = conn.execute("SELECT code FROM suppliers WHERE name='Lower Code Supplier'").fetchone()
    conn.close()
    assert row['code'] == 'ABC'


def test_add_and_get_by_id(test_db):
    supplier_model.add('S1', 'Test Supplier', phone='0300000000', abn='12 345 678 901')
    conn = get_connection()
    sid = conn.execute("SELECT id FROM suppliers WHERE code='S1'").fetchone()['id']
    conn.close()
    s = supplier_model.get_by_id(sid)
    assert s['name'] == 'Test Supplier'
    assert s['phone'] == '0300000000'
    assert s['abn'] == '12 345 678 901'


def test_get_by_id_missing_returns_none(test_db):
    assert supplier_model.get_by_id(99999) is None


def test_add_all_schedule_fields(test_db):
    supplier_model.add(
        'SCH', 'Schedule Supplier',
        order_days='MON,FRI',
        order_first_monday=1,
        order_fortnightly_start='2026-05-01',
        delivery_days='TUE,THU',
    )
    conn = get_connection()
    s = conn.execute("SELECT * FROM suppliers WHERE code='SCH'").fetchone()
    conn.close()
    assert s['order_days'] == 'MON,FRI'
    assert s['order_first_monday'] == 1
    assert s['order_fortnightly_start'] == '2026-05-01'
    assert s['delivery_days'] == 'TUE,THU'


# ── get_all ───────────────────────────────────────────────────────────────────

def test_get_all_active_only(test_db, db_conn):
    sid = _add(db_conn, 'ACT', 'Active Supplier')
    _add(db_conn, 'INA', 'Inactive Supplier')
    db_conn.execute("UPDATE suppliers SET active=0 WHERE code='INA'")
    db_conn.commit()

    rows = supplier_model.get_all(active_only=True)
    names = [r['name'] for r in rows]
    assert 'Active Supplier' in names
    assert 'Inactive Supplier' not in names


def test_get_all_includes_inactive(test_db, db_conn):
    _add(db_conn, 'ACT2', 'Active 2')
    _add(db_conn, 'INA2', 'Inactive 2')
    db_conn.execute("UPDATE suppliers SET active=0 WHERE code='INA2'")
    db_conn.commit()

    rows = supplier_model.get_all(active_only=False)
    names = [r['name'] for r in rows]
    assert 'Active 2' in names
    assert 'Inactive 2' in names


def test_get_all_ordered_by_name(test_db, db_conn):
    _add(db_conn, 'ZZZ', 'Zebra Supplier')
    _add(db_conn, 'AAA', 'Aardvark Supplier')
    rows = supplier_model.get_all(active_only=False)
    names = [r['name'] for r in rows]
    assert names == sorted(names)


# ── update ────────────────────────────────────────────────────────────────────

def test_update_fields(test_db, db_conn):
    sid = _add(db_conn, 'UPD', 'Original Name')
    supplier_model.update(
        sid, 'UPD', 'Updated Name', 'Jane', '0411000000',
        'ACC123', '30 days', '1 Main St', 'Some notes', 1,
        abn='98 765 432 109', delivery_days='WED',
    )
    s = supplier_model.get_by_id(sid)
    assert s['name'] == 'Updated Name'
    assert s['contact_name'] == 'Jane'
    assert s['abn'] == '98 765 432 109'
    assert s['delivery_days'] == 'WED'


def test_update_code_uppercased(test_db, db_conn):
    sid = _add(db_conn, 'ORI', 'Original')
    supplier_model.update(sid, 'new', 'Original', '', '', '', '', '', '', 1)
    s = supplier_model.get_by_id(sid)
    assert s['code'] == 'NEW'


# ── deactivate ────────────────────────────────────────────────────────────────

def test_deactivate(test_db, db_conn):
    sid = _add(db_conn, 'DEA', 'To Deactivate')
    supplier_model.deactivate(sid)
    s = supplier_model.get_by_id(sid)
    assert s['active'] == 0


# ── get_order_due_today ───────────────────────────────────────────────────────

def test_order_due_weekly_all_days(test_db, db_conn):
    """Supplier with all 7 order days always appears."""
    sid = _add(db_conn, 'WK7', 'All Days', order_days='MON,TUE,WED,THU,FRI,SAT,SUN')
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid in due_ids


def test_order_not_due_wrong_day(test_db, db_conn):
    """Supplier with no matching order day never appears."""
    _add(db_conn, 'NOD', 'No Order Days', order_days='')
    due_names = [r['name'] for r in supplier_model.get_order_due_today()]
    assert 'No Order Days' not in due_names


def test_order_due_fortnightly_on_exact_interval(test_db, db_conn):
    """Fortnightly supplier appears when today is exactly 14 days from start."""
    start = (date.today() - timedelta(days=14)).isoformat()
    sid = _add(db_conn, 'FRT', 'Fortnightly', order_fortnightly_start=start)
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid in due_ids


def test_order_not_due_fortnightly_off_cycle(test_db, db_conn):
    """Fortnightly supplier does not appear on wrong day in cycle."""
    start = (date.today() - timedelta(days=7)).isoformat()  # mid-cycle
    sid = _add(db_conn, 'FR2', 'Fortnightly Off', order_fortnightly_start=start)
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid not in due_ids


def test_order_suppressed_by_draft_po_today(test_db, db_conn):
    """Supplier with all order days is suppressed when a DRAFT PO exists today."""
    sid = _add(db_conn, 'SUP', 'Suppressed', order_days='MON,TUE,WED,THU,FRI,SAT,SUN')
    _make_po(db_conn, sid, status='DRAFT', days_ago=0)
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid not in due_ids


def test_order_suppressed_by_sent_po_yesterday(test_db, db_conn):
    """Supplier suppressed when a SENT PO was created yesterday."""
    sid = _add(db_conn, 'SNT', 'Sent Yesterday', order_days='MON,TUE,WED,THU,FRI,SAT,SUN')
    _make_po(db_conn, sid, status='SENT', days_ago=1)
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid not in due_ids


def test_order_not_suppressed_by_old_po(test_db, db_conn):
    """Supplier not suppressed when the only PO is 3+ days old."""
    sid = _add(db_conn, 'OLD', 'Old PO', order_days='MON,TUE,WED,THU,FRI,SAT,SUN')
    _make_po(db_conn, sid, status='SENT', days_ago=3)
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid in due_ids


def test_inactive_supplier_never_due(test_db, db_conn):
    """Inactive suppliers never appear in due list."""
    sid = _add(db_conn, 'INC', 'Inactive', order_days='MON,TUE,WED,THU,FRI,SAT,SUN')
    db_conn.execute("UPDATE suppliers SET active=0 WHERE id=?", (sid,))
    db_conn.commit()
    due_ids = [r['id'] for r in supplier_model.get_order_due_today()]
    assert sid not in due_ids
