"""Unit tests for utils/label_print.py — silent direct-to-printer label printing.

Never targets a real OS printer queue: print_label_direct's `printer` param
is used to inject a QPrinter configured for PdfFormat output instead, so
these tests exercise the full render+paint pipeline without sending an
actual print job to hardware.
"""
import os
import re
import pytest

pytest.importorskip("PyQt6.QtPdf")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtPrintSupport import QPrinter

import models.settings as settings_model
from utils.label_print import (
    get_printer_names, get_configured_printer_name,
    render_label_image, print_label_direct,
    get_configured_edikio_printer_name,
    render_edikio_label_image, print_edikio_label_direct,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pdf_output_printer(path) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    return printer


class TestGetConfiguredPrinterName:
    def test_empty_when_unset(self, test_db):
        assert get_configured_printer_name() == ""

    def test_reads_configured_value(self, test_db):
        settings_model.set_setting('label_printer_name', 'Zebra GK420d')
        assert get_configured_printer_name() == "Zebra GK420d"


class TestGetPrinterNames:
    def test_returns_a_list(self, test_db):
        assert isinstance(get_printer_names(), list)


class TestRenderLabelImage:
    def test_renders_non_null_image_at_standard_size(self, test_db):
        image = render_label_image("9311766000632", "Alba Mozzarella Block 500G",
                                    11.95, plu="537", large=False)
        assert image is not None
        assert not image.isNull()
        # 76mm at 300dpi ~= 898px, 25.4mm ~= 300px
        assert 890 <= image.width() <= 905
        assert 295 <= image.height() <= 305

    def test_renders_at_large_size(self, test_db):
        settings_model.set_setting('label_large_width_mm', '76')
        settings_model.set_setting('label_large_height_mm', '51')
        image = render_label_image("9311766000632", "Alba Mozzarella Block 500G",
                                    11.95, plu="537", large=True)
        assert image is not None
        assert 590 <= image.height() <= 610  # 51mm at 300dpi ~= 602px

    def test_cleans_up_temp_pdf(self, test_db, tmp_path, monkeypatch):
        seen_paths = []
        import utils.label_print as label_print_mod
        real_generate = label_print_mod.generate_label_pdf

        def spy(*args, **kwargs):
            path = real_generate(*args, **kwargs)
            seen_paths.append(path)
            return path

        monkeypatch.setattr(label_print_mod, "generate_label_pdf", spy)
        render_label_image("123", "Test", 1.00)
        assert seen_paths
        assert not os.path.exists(seen_paths[0])


class TestPrintLabelDirect:
    def test_fails_gracefully_with_no_printer_configured(self, test_db):
        ok, msg = print_label_direct("123", "Test", 1.00)
        assert ok is False
        assert "No printer configured" in msg

    def test_fails_gracefully_for_unknown_printer_name(self, test_db):
        settings_model.set_setting('label_printer_name', 'Definitely Not A Real Printer')
        ok, msg = print_label_direct("123", "Test", 1.00)
        assert ok is False
        assert "not available" in msg

    def test_prints_via_injected_printer(self, test_db, tmp_path):
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, msg = print_label_direct(
            "9311766000632", "Alba Mozzarella Block 500G", 11.95, plu="537",
            printer=printer,
        )
        assert ok is True
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0

    def test_multiple_copies_produce_multiple_pages(self, test_db, tmp_path):
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, _ = print_label_direct("123", "Test", 1.00, copies=3, printer=printer)
        assert ok is True
        content = open(out_path, 'rb').read()
        # Qt's PDF writer also emits one "/Type /Pages" (parent) node, which
        # a plain substring count would double-count against "/Type /Page".
        assert len(re.findall(rb'/Type\s*/Page(?!s)', content)) == 3

    def test_injected_printer_skips_settings_lookup(self, test_db, tmp_path):
        """No printer configured in Settings at all — injected printer must
        still work, since it bypasses the Settings-based lookup entirely."""
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, msg = print_label_direct("123", "Test", 1.00, printer=printer)
        assert ok is True, msg


class TestGetConfiguredEdikioPrinterName:
    def test_empty_when_unset(self, test_db):
        assert get_configured_edikio_printer_name() == ""

    def test_reads_configured_value(self, test_db):
        settings_model.set_setting('edikio_printer_name', 'Edikio Access')
        assert get_configured_edikio_printer_name() == "Edikio Access"

    def test_independent_of_shelf_label_printer_setting(self, test_db):
        """Regression: the two printer settings must not collide — a shop
        runs both devices at once, each selected independently in Settings."""
        settings_model.set_setting('label_printer_name', 'Zebra GK420d')
        settings_model.set_setting('edikio_printer_name', 'Edikio Access')
        assert get_configured_printer_name() == "Zebra GK420d"
        assert get_configured_edikio_printer_name() == "Edikio Access"


class TestRenderEdikioLabelImage:
    def test_renders_non_null_image_at_card_size(self, test_db):
        image = render_edikio_label_image("9311766000632", "Alba Mozzarella Block 500G",
                                           11.95, unit="EA")
        assert image is not None
        assert not image.isNull()
        # 85.6mm at 300dpi ~= 1011px, 54mm ~= 638px
        assert 1000 <= image.width() <= 1020
        assert 630 <= image.height() <= 645

    def test_cleans_up_temp_pdf(self, test_db, monkeypatch):
        seen_paths = []
        import utils.label_print as label_print_mod
        real_generate = label_print_mod.generate_edikio_label_pdf

        def spy(*args, **kwargs):
            path = real_generate(*args, **kwargs)
            seen_paths.append(path)
            return path

        monkeypatch.setattr(label_print_mod, "generate_edikio_label_pdf", spy)
        render_edikio_label_image("123", "Test", 1.00)
        assert seen_paths
        assert not os.path.exists(seen_paths[0])


class TestPrintEdikioLabelDirect:
    def test_fails_gracefully_with_no_printer_configured(self, test_db):
        ok, msg = print_edikio_label_direct("123", "Test", 1.00)
        assert ok is False
        assert "No Edikio printer configured" in msg

    def test_fails_gracefully_for_unknown_printer_name(self, test_db):
        settings_model.set_setting('edikio_printer_name', 'Definitely Not A Real Printer')
        ok, msg = print_edikio_label_direct("123", "Test", 1.00)
        assert ok is False
        assert "not available" in msg

    def test_prints_via_injected_printer(self, test_db, tmp_path):
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, msg = print_edikio_label_direct(
            "9311766000632", "Alba Mozzarella Block 500G", 11.95, unit="EA",
            printer=printer,
        )
        assert ok is True
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0

    def test_multiple_copies_produce_multiple_pages(self, test_db, tmp_path):
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, _ = print_edikio_label_direct("123", "Test", 1.00, copies=3, printer=printer)
        assert ok is True
        content = open(out_path, 'rb').read()
        assert len(re.findall(rb'/Type\s*/Page(?!s)', content)) == 3

    def test_injected_printer_skips_settings_lookup(self, test_db, tmp_path):
        out_path = str(tmp_path / "printed.pdf")
        printer = _pdf_output_printer(out_path)
        ok, msg = print_edikio_label_direct("123", "Test", 1.00, printer=printer)
        assert ok is True, msg
