"""Tests for bank details in PO History CSV export.

Requires a running Qt application (pytest-qt / DISPLAY=:0).
"""
import csv
import pytest
from unittest.mock import patch, MagicMock
import models.purchase_order as po_model
import models.supplier as supplier_model


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def supplier_with_bank(db_conn):
    """Supplier that has all three bank fields populated."""
    supplier_model.add(
        'BNK', 'Bank Supplier',
        bank_account_name='Harcourt Apples Pty Ltd',
        bank_bsb='063-000',
        bank_account_number='12345678',
    )
    row = db_conn.execute("SELECT id FROM suppliers WHERE code='BNK'").fetchone()
    return row['id']


@pytest.fixture()
def po_with_bank(supplier_with_bank):
    """RECEIVED PO for a supplier that has bank details."""
    po_id = po_model.create(supplier_with_bank, '2026-06-01', '', 'admin')
    po_model.update_status(po_id, 'RECEIVED')
    return po_id


@pytest.fixture()
def supplier_no_bank(db_conn):
    """Supplier with no bank details at all."""
    supplier_model.add('NBK', 'No Bank Supplier')
    row = db_conn.execute("SELECT id FROM suppliers WHERE code='NBK'").fetchone()
    return row['id']


@pytest.fixture()
def po_no_bank(supplier_no_bank):
    """RECEIVED PO for a supplier with no bank details."""
    po_id = po_model.create(supplier_no_bank, '2026-06-01', '', 'admin')
    po_model.update_status(po_id, 'RECEIVED')
    return po_id


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.reader(f))


def _find_value(rows, label):
    """Return column-1 value for the first row whose column-0 matches label."""
    for row in rows:
        if row and row[0] == label:
            return row[1] if len(row) > 1 else ''
    return None


def _all_labels(rows):
    return [row[0] for row in rows if row]


def _make_widget(qtbot, po_id):
    import views.purchase_orders.po_history as _mod
    widget = _mod.POHistory(po_id)
    qtbot.addWidget(widget)
    return widget, _mod


def _export_csv(widget, _mod, out_path):
    mock_fd = MagicMock()
    mock_fd.getSaveFileName.return_value = (out_path, '')
    with patch.object(_mod, 'QFileDialog', mock_fd):
        with patch('subprocess.Popen'):
            widget._export_csv()


# ── CSV bank-details tests ────────────────────────────────────────────────────

class TestPoHistoryCSVBankDetails:
    def test_bank_account_name_in_csv(self, qtbot, test_db, po_with_bank, tmp_path):
        widget, _mod = _make_widget(qtbot, po_with_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        assert _find_value(_read_csv(out), 'Bank Account Name') == 'Harcourt Apples Pty Ltd'

    def test_bsb_in_csv(self, qtbot, test_db, po_with_bank, tmp_path):
        widget, _mod = _make_widget(qtbot, po_with_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        assert _find_value(_read_csv(out), 'BSB') == '063-000'

    def test_account_number_in_csv(self, qtbot, test_db, po_with_bank, tmp_path):
        widget, _mod = _make_widget(qtbot, po_with_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        assert _find_value(_read_csv(out), 'Account Number') == '12345678'

    def test_bank_rows_omitted_when_no_details(self, qtbot, test_db, po_no_bank, tmp_path):
        widget, _mod = _make_widget(qtbot, po_no_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        labels = _all_labels(_read_csv(out))
        assert 'Bank Account Name' not in labels
        assert 'BSB' not in labels
        assert 'Account Number' not in labels

    def test_bank_rows_appear_before_line_items(self, qtbot, test_db, po_with_bank, tmp_path):
        """Bank detail rows must be in the header block, before the lines table."""
        widget, _mod = _make_widget(qtbot, po_with_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        labels = _all_labels(_read_csv(out))
        bank_idx  = labels.index('Bank Account Name')
        lines_idx = labels.index('Barcode')
        assert bank_idx < lines_idx

    def test_standard_header_rows_still_present(self, qtbot, test_db, po_with_bank, tmp_path):
        """Adding bank rows must not remove the existing PO header rows."""
        widget, _mod = _make_widget(qtbot, po_with_bank)
        out = str(tmp_path / 'out.csv')
        _export_csv(widget, _mod, out)
        labels = _all_labels(_read_csv(out))
        for expected in ('PO Number', 'Supplier', 'Status', 'Received Date'):
            assert expected in labels
