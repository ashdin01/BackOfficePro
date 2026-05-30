"""Tests for utils/auto_plu_map.py — PLU auto-mapping logic."""
import pytest
from utils.auto_plu_map import auto_map_plu_barcodes


@pytest.fixture()
def _products(db_conn, dept_id, supplier_id):
    """Insert test products with specific PLU values."""
    rows = [
        ("9300100000001", "Unique PLU Product",  "100", 1),
        ("9300200000001", "Ambiguous PLU Product A", "200", 1),
        ("9300200000002", "Ambiguous PLU Product B", "200", 1),
        ("9300300000001", "Inactive PLU Product",  "300", 0),
    ]
    for barcode, desc, plu, active in rows:
        db_conn.execute(
            "INSERT INTO products (barcode, description, department_id, supplier_id, plu, active, unit) "
            "VALUES (?, ?, ?, ?, ?, ?, 'EA')",
            (barcode, desc, dept_id, supplier_id, plu, active),
        )
    db_conn.commit()


def _insert_sale(db_conn, plu, sale_date="2026-01-01"):
    db_conn.execute(
        "INSERT OR IGNORE INTO sales_daily (sale_date, plu, quantity) VALUES (?, ?, 1.0)",
        (sale_date, plu),
    )
    db_conn.commit()


# ── Empty-database baseline ───────────────────────────────────────────────────

class TestEmptyDatabase:
    def test_returns_dict_with_all_keys(self, test_db):
        result = auto_map_plu_barcodes()
        assert isinstance(result, dict)
        assert "mapped" in result
        assert "skipped" in result
        assert "unmapped" in result

    def test_all_lists_empty_on_empty_db(self, test_db):
        result = auto_map_plu_barcodes()
        assert result["mapped"] == []
        assert result["skipped"] == []
        assert result["unmapped"] == []


# ── Unambiguous match → mapped ────────────────────────────────────────────────

class TestUnambiguousMapping:
    def test_single_match_is_mapped(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        result = auto_map_plu_barcodes()
        mapped_plus = [row[0] for row in result["mapped"]]
        assert "100" in mapped_plus

    def test_mapped_entry_has_correct_barcode(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        result = auto_map_plu_barcodes()
        entry = next(r for r in result["mapped"] if r[0] == "100")
        assert entry[1] == "9300100000001"

    def test_mapped_entry_stored_in_plu_barcode_map(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        auto_map_plu_barcodes()
        row = db_conn.execute(
            "SELECT barcode FROM plu_barcode_map WHERE plu=100"
        ).fetchone()
        assert row is not None
        assert row["barcode"] == "9300100000001"

    def test_not_in_skipped_or_unmapped(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        result = auto_map_plu_barcodes()
        assert "100" not in [r[0] for r in result["skipped"]]
        assert "100" not in result["unmapped"]


# ── Multiple matches → skipped ────────────────────────────────────────────────

class TestAmbiguousMapping:
    def test_ambiguous_plu_is_skipped(self, _products, db_conn):
        _insert_sale(db_conn, "200")
        result = auto_map_plu_barcodes()
        skipped_plus = [r[0] for r in result["skipped"]]
        assert "200" in skipped_plus

    def test_skipped_entry_records_match_count(self, _products, db_conn):
        _insert_sale(db_conn, "200")
        result = auto_map_plu_barcodes()
        entry = next(r for r in result["skipped"] if r[0] == "200")
        assert entry[1] == 2

    def test_ambiguous_not_written_to_plu_barcode_map(self, _products, db_conn):
        _insert_sale(db_conn, "200")
        auto_map_plu_barcodes()
        row = db_conn.execute(
            "SELECT barcode FROM plu_barcode_map WHERE plu=200"
        ).fetchone()
        assert row is None


# ── No product match → unmapped ───────────────────────────────────────────────

class TestNoProductMatch:
    def test_unknown_plu_is_unmapped(self, test_db, db_conn):
        _insert_sale(db_conn, "999")
        result = auto_map_plu_barcodes()
        assert "999" in result["unmapped"]

    def test_unmapped_not_in_mapped_or_skipped(self, test_db, db_conn):
        _insert_sale(db_conn, "999")
        result = auto_map_plu_barcodes()
        assert "999" not in [r[0] for r in result["mapped"]]
        assert "999" not in [r[0] for r in result["skipped"]]


# ── Already-mapped PLU is not re-processed ───────────────────────────────────

class TestAlreadyMapped:
    def test_already_mapped_plu_not_in_results(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        db_conn.execute(
            "INSERT INTO plu_barcode_map (plu, barcode) VALUES (100, '9300100000001')"
        )
        db_conn.commit()
        result = auto_map_plu_barcodes()
        assert "100" not in [r[0] for r in result["mapped"]]
        assert "100" not in result["unmapped"]
        assert "100" not in [r[0] for r in result["skipped"]]

    def test_idempotent_second_call_maps_nothing_new(self, _products, db_conn):
        _insert_sale(db_conn, "100")
        auto_map_plu_barcodes()
        result2 = auto_map_plu_barcodes()
        assert result2["mapped"] == []


# ── Inactive products are not matched ────────────────────────────────────────

class TestInactiveProducts:
    def test_inactive_product_plu_treated_as_unmapped(self, _products, db_conn):
        _insert_sale(db_conn, "300")
        result = auto_map_plu_barcodes()
        # PLU 300 belongs to an inactive product — should appear in unmapped
        assert "300" in result["unmapped"]
