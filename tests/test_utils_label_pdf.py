"""Unit tests for utils/label_pdf.py — shelf-edge label PDF generation."""
import os
import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from utils.label_pdf import (
    generate_label_pdf, get_label_size_mm, _wrap_text,
    DEFAULT_WIDTH_MM, DEFAULT_HEIGHT_MM,
    DEFAULT_LARGE_WIDTH_MM, DEFAULT_LARGE_HEIGHT_MM,
)
import models.settings as settings_model


class TestWrapText:
    def test_short_text_fits_one_line(self):
        lines = _wrap_text("Milk 2L", "Helvetica-Bold", 8, max_width=200, max_lines=2)
        assert lines == ["Milk 2L"]

    def test_empty_text_returns_single_blank_line(self):
        assert _wrap_text("", "Helvetica-Bold", 8, max_width=200, max_lines=2) == [""]

    def test_long_text_wraps_within_max_lines(self):
        text = "A Very Long Product Description That Does Not Fit On One Line At All"
        narrow_width = stringWidth("A Very Long", "Helvetica-Bold", 8) + 5
        lines = _wrap_text(text, "Helvetica-Bold", 8, max_width=narrow_width, max_lines=2)
        assert len(lines) <= 2
        for line in lines:
            assert stringWidth(line, "Helvetica-Bold", 8) <= narrow_width + 1  # ellipsis tolerance

    def test_text_that_exactly_fills_max_lines_gets_no_ellipsis(self):
        """Regression: "Alba Mozzarella Block 500G" wraps to exactly two full
        lines with every word placed — must NOT be truncated with '…' just
        because it happened to land exactly at max_lines."""
        text = "Alba Mozzarella Block 500G"
        width = stringWidth("Alba Mozzarella", "Helvetica-Bold", 11) + 2
        lines = _wrap_text(text, "Helvetica-Bold", 11, max_width=width, max_lines=2)
        assert lines == ["Alba Mozzarella", "Block 500G"]
        assert not lines[-1].endswith("…")

    def test_overflow_last_line_gets_ellipsis(self):
        text = "A Very Long Product Description That Does Not Fit On One Line At All"
        narrow_width = stringWidth("A Very Long", "Helvetica-Bold", 8) + 5
        lines = _wrap_text(text, "Helvetica-Bold", 8, max_width=narrow_width, max_lines=2)
        assert lines[-1].endswith("…")


class TestGetLabelSizeMm:
    def test_defaults_when_unset(self, test_db):
        assert get_label_size_mm() == (DEFAULT_WIDTH_MM, DEFAULT_HEIGHT_MM)

    def test_reads_configured_size(self, test_db):
        settings_model.set_setting('label_width_mm', '76')
        settings_model.set_setting('label_height_mm', '51')
        assert get_label_size_mm() == (76.0, 51.0)

    def test_large_defaults_when_unset(self, test_db):
        assert get_label_size_mm(large=True) == (DEFAULT_LARGE_WIDTH_MM, DEFAULT_LARGE_HEIGHT_MM)

    def test_large_reads_its_own_configured_size_independently(self, test_db):
        settings_model.set_setting('label_width_mm', '76')
        settings_model.set_setting('label_height_mm', '25.4')
        settings_model.set_setting('label_large_width_mm', '100')
        settings_model.set_setting('label_large_height_mm', '150')
        assert get_label_size_mm(large=False) == (76.0, 25.4)
        assert get_label_size_mm(large=True) == (100.0, 150.0)


class TestGenerateLabelPdf:
    def test_creates_file_at_given_path(self, test_db, tmp_path):
        path = str(tmp_path / "label.pdf")
        result = generate_label_pdf(
            "9335388000092", "Nu Spring Water 600ml", 3.50, plu="1459", path=path
        )
        assert result == path
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_defaults_to_temp_file_when_no_path_given(self, test_db):
        path = generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50)
        try:
            assert os.path.exists(path)
        finally:
            os.remove(path)

    def test_multiple_copies_produce_multi_page_pdf(self, test_db, tmp_path):
        path = str(tmp_path / "label.pdf")
        generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50, copies=3, path=path)
        content = open(path, 'rb').read()
        # reportlab emits one "/Type /Page\n" object per page.
        assert content.count(b'/Type /Page\n') == 3

    def test_works_with_no_plu(self, test_db, tmp_path):
        path = str(tmp_path / "label.pdf")
        generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50, plu=None, path=path)
        assert os.path.exists(path)

    def test_works_with_long_description_and_small_label(self, test_db, tmp_path):
        settings_model.set_setting('label_width_mm', '76')
        settings_model.set_setting('label_height_mm', '25.4')
        path = str(tmp_path / "label.pdf")
        generate_label_pdf(
            "9335388000092",
            "A Very Long Product Description That Should Wrap Across Two Lines Of Text",
            12.99, plu="2201", path=path,
        )
        assert os.path.exists(path)

    def test_works_with_tall_label(self, test_db, tmp_path):
        settings_model.set_setting('label_width_mm', '76')
        settings_model.set_setting('label_height_mm', '51')
        path = str(tmp_path / "label.pdf")
        generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50, plu="1459", path=path)
        assert os.path.exists(path)

    def test_barcode_starting_with_2_variable_weight_style(self, test_db, tmp_path):
        """Variable-weight barcodes (start with '2', 13 digits, weight encoded in the
        digits) must still render fine as raw Code128 data — no EAN-13 recalculation."""
        path = str(tmp_path / "label.pdf")
        generate_label_pdf("2012345000456", "Weighed Cheese", 8.20, path=path)
        assert os.path.exists(path)

    def test_large_flag_uses_the_large_size_profile_independently(self, test_db, tmp_path):
        settings_model.set_setting('label_width_mm', '76')
        settings_model.set_setting('label_height_mm', '25.4')
        settings_model.set_setting('label_large_width_mm', '76')
        settings_model.set_setting('label_large_height_mm', '51')

        standard_path = str(tmp_path / "standard.pdf")
        large_path = str(tmp_path / "large.pdf")
        generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50, path=standard_path, large=False)
        generate_label_pdf("9335388000092", "Nu Spring Water 600ml", 3.50, path=large_path, large=True)

        # PDF page geometry is stated explicitly in /MediaBox (points); confirm
        # each call actually rendered at its own configured height, not the same one twice.
        assert b'0 215.4331 72 ]'  in open(standard_path, 'rb').read()
        assert b'0 215.4331 144.5669 ]' in open(large_path, 'rb').read()
