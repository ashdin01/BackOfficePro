"""Tests for controllers/dashboard_controller.py."""
import pytest
from datetime import date
from database.connection import get_connection
import controllers.dashboard_controller as dash_ctrl


def test_dashboard_stats_returns_required_keys(test_db):
    stats = dash_ctrl.get_dashboard_stats()
    assert 'store_name' in stats
    assert 'today_sales' in stats
    assert 'open_po_count' in stats
    assert 'low_stock_count' in stats
    assert 'active_product_count' in stats


def test_store_name_default(test_db):
    stats = dash_ctrl.get_dashboard_stats()
    assert isinstance(stats['store_name'], str)
    assert len(stats['store_name']) > 0


def test_store_name_from_settings(test_db, db_conn):
    db_conn.execute(
        "INSERT INTO settings (key, value) VALUES ('store_name', 'Apple Hill IGA') "
        "ON CONFLICT(key) DO UPDATE SET value='Apple Hill IGA'"
    )
    db_conn.commit()
    stats = dash_ctrl.get_dashboard_stats()
    assert stats['store_name'] == 'Apple Hill IGA'


def test_today_sales_zero_when_no_data(test_db):
    stats = dash_ctrl.get_dashboard_stats()
    assert stats['today_sales'] == 0.0


def test_today_sales_reflects_todays_data(test_db, db_conn):
    today = date.today().isoformat()
    db_conn.execute("""
        INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
        VALUES (?, '10001', 'MILK 2L', 5, 12.50)
    """, (today,))
    db_conn.execute("""
        INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
        VALUES (?, '10002', 'BREAD', 3, 7.50)
    """, (today,))
    db_conn.commit()
    stats = dash_ctrl.get_dashboard_stats()
    assert abs(stats['today_sales'] - 20.00) < 0.01


def test_open_po_count_counts_draft_and_sent(test_db, db_conn, supplier_id):
    db_conn.execute("""
        INSERT INTO purchase_orders (po_number, supplier_id, status)
        VALUES ('PO-001', ?, 'DRAFT'), ('PO-002', ?, 'SENT'), ('PO-003', ?, 'RECEIVED')
    """, (supplier_id, supplier_id, supplier_id))
    db_conn.commit()
    stats = dash_ctrl.get_dashboard_stats()
    assert stats['open_po_count'] == 2


def test_low_stock_count(test_db, db_conn, dept_id, supplier_id):
    # Product below reorder point
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, reorder_point, active, unit)
        VALUES ('BC001', 'Low Stock Item', ?, ?, 1.0, 0.5, 0, 10, 1, 'EA')
    """, (dept_id, supplier_id))
    db_conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity) VALUES ('BC001', 5)
    """)
    # Product above reorder point
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, reorder_point, active, unit)
        VALUES ('BC002', 'Fine Stock Item', ?, ?, 1.0, 0.5, 0, 10, 1, 'EA')
    """, (dept_id, supplier_id))
    db_conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity) VALUES ('BC002', 20)
    """)
    db_conn.commit()
    stats = dash_ctrl.get_dashboard_stats()
    assert stats['low_stock_count'] >= 1


def test_active_product_count(test_db, db_conn, dept_id, supplier_id):
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, active, unit)
        VALUES ('BC003', 'Active', ?, ?, 1.0, 0.5, 0, 1, 'EA')
    """, (dept_id, supplier_id))
    db_conn.execute("""
        INSERT INTO products (barcode, description, department_id, supplier_id,
            sell_price, cost_price, tax_rate, active, unit)
        VALUES ('BC004', 'Inactive', ?, ?, 1.0, 0.5, 0, 0, 'EA')
    """, (dept_id, supplier_id))
    db_conn.commit()
    stats = dash_ctrl.get_dashboard_stats()
    assert stats['active_product_count'] >= 1


# ── get_last_import_date ──────────────────────────────────────────────────────

def test_last_import_date_none_when_empty(test_db):
    assert dash_ctrl.get_last_import_date() is None


def test_last_import_date_returns_most_recent(test_db, db_conn):
    db_conn.execute("""
        INSERT INTO sales_daily (sale_date, plu, plu_name, quantity, sales_dollars)
        VALUES ('2026-05-01', '10001', 'ITEM', 1, 1.0),
               ('2026-05-03', '10002', 'ITEM', 1, 1.0),
               ('2026-05-02', '10003', 'ITEM', 1, 1.0)
    """)
    db_conn.commit()
    result = dash_ctrl.get_last_import_date()
    assert result == date(2026, 5, 3)
