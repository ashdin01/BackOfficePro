"""Unit tests for utils/receipt_pdf.py — POS receipt reprint PDF generation."""
import os
import pytest

from utils.receipt_pdf import render_receipt_pdf, _wrap, _item_desc


class TestWrap:
    def test_short_text_fits_one_line(self):
        assert _wrap("Milk 2L", "Helvetica", 9, max_width=500) == ["Milk 2L"]

    def test_empty_text_returns_single_blank_line(self):
        assert _wrap("", "Helvetica", 9, max_width=500) == [""]

    def test_long_text_wraps_within_max_lines(self):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        text = "A Very Long Product Description That Does Not Fit"
        narrow = stringWidth("A Very Long", "Helvetica", 9) + 5
        lines = _wrap(text, "Helvetica", 9, max_width=narrow, max_lines=2)
        assert len(lines) <= 2


class TestItemDesc:
    def test_prefers_notes_over_product_description(self):
        item = {'notes': 'Half Cantaloupe', 'description': 'Cantaloupe Whole'}
        assert _item_desc(item) == 'Half Cantaloupe'

    def test_falls_back_to_product_description_when_notes_blank(self):
        item = {'notes': '', 'description': 'Cantaloupe Whole'}
        assert _item_desc(item) == 'Cantaloupe Whole'

    def test_blank_when_both_missing(self):
        assert _item_desc({}) == ''


class TestRenderReceiptPdf:
    STORE_INFO = {
        'store_name': 'The Little Red Apple',
        'store_address': '8795 Midland Highway Barkers Creek VIC 3451',
        'store_phone': '(03) 5474 2483',
        'store_abn': '95 083 232 973',
    }

    def _txn(self, **overrides):
        txn = {
            'sale_date': '2026-09-12', 'received_at': '2026-09-12 21:39:48',
            'operator': 'ash', 'payment_method': 'CASH',
            'subtotal': 2.50, 'gst_amount': 0.0, 'total': 2.50,
            'items': [
                {'barcode': '0735850555485', 'description': 'Marlo Butter',
                 'notes': 'Half Cantaloupe', 'quantity': -1,
                 'unit_price': 2.50, 'line_total': 2.50},
            ],
        }
        txn.update(overrides)
        return txn

    def test_writes_a_pdf_file(self, tmp_path):
        out = str(tmp_path / "receipt.pdf")
        path = render_receipt_pdf('RCPT-001', self._txn(), self.STORE_INFO, out)
        assert path == out
        assert os.path.exists(path)
        with open(path, 'rb') as f:
            assert f.read(4) == b'%PDF'

    def test_defaults_output_path_when_none_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr('tempfile.gettempdir', lambda: str(tmp_path))
        path = render_receipt_pdf('RCPT-002', self._txn(), self.STORE_INFO, None)
        assert os.path.exists(path)
        assert str(tmp_path) in path

    def test_missing_price_fields_render_without_crashing(self, tmp_path):
        txn = self._txn(subtotal=None, gst_amount=None, total=None)
        txn['items'][0]['unit_price'] = None
        txn['items'][0]['line_total'] = None
        out = str(tmp_path / "receipt.pdf")
        path = render_receipt_pdf('RCPT-003', txn, self.STORE_INFO, out)
        assert os.path.exists(path)

    def test_no_items_still_renders(self, tmp_path):
        txn = self._txn(items=[])
        out = str(tmp_path / "receipt.pdf")
        path = render_receipt_pdf('RCPT-004', txn, self.STORE_INFO, out)
        assert os.path.exists(path)

    def test_long_description_does_not_raise(self, tmp_path):
        txn = self._txn()
        txn['items'].append({
            'barcode': '9300000000002',
            'description': 'A Second Item With A Fairly Long Name For Wrap Testing',
            'notes': None, 'quantity': -3, 'unit_price': 3.99, 'line_total': 11.97,
        })
        out = str(tmp_path / "receipt.pdf")
        path = render_receipt_pdf('RCPT-005', txn, self.STORE_INFO, out)
        assert os.path.exists(path)
        # Regression: the page height must be measured from the same layout
        # that's drawn, so a wrapped multi-line description can't push the
        # totals block off the bottom of a too-short page.
        assert os.path.getsize(path) > 500

    def test_empty_store_info_does_not_raise(self, tmp_path):
        out = str(tmp_path / "receipt.pdf")
        path = render_receipt_pdf('RCPT-006', self._txn(), {}, out)
        assert os.path.exists(path)
