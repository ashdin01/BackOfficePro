"""Widget regression tests for settings_labels.py — Label Printing settings.

Covers the Edikio card printer addition: a printer setting independent of
the existing Zebra shelf-label one, with a fixed (non-configurable) card
size.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication

import controllers.settings_controller as settings_ctrl
from utils.label_pdf import EDIKIO_WIDTH_MM, EDIKIO_HEIGHT_MM


@pytest.fixture()
def labels_screen(qtbot, test_db):
    from views.settings.settings_labels import LabelPrintingScreen
    w = LabelPrintingScreen()
    qtbot.addWidget(w)
    w.show()
    QApplication.processEvents()
    return w


class TestEdikioPrinterSelection:
    def test_none_selected_by_default(self, labels_screen):
        assert labels_screen._selected_edikio_printer_name() == ""

    def test_combo_is_separate_widget_from_shelf_label_combo(self, labels_screen):
        assert labels_screen.edikio_printer_combo is not labels_screen.printer_combo

    def test_save_persists_edikio_printer_name(self, labels_screen):
        labels_screen.edikio_printer_combo.addItem("Edikio Access")
        labels_screen.edikio_printer_combo.setCurrentText("Edikio Access")
        with patch('views.settings.settings_labels.QMessageBox'):
            labels_screen._save()
        assert settings_ctrl.get_all_settings()['edikio_printer_name'] == "Edikio Access"

    def test_save_does_not_affect_shelf_label_printer_setting(self, labels_screen):
        labels_screen.printer_combo.addItem("Zebra GK420d")
        labels_screen.printer_combo.setCurrentText("Zebra GK420d")
        labels_screen.edikio_printer_combo.addItem("Edikio Access")
        labels_screen.edikio_printer_combo.setCurrentText("Edikio Access")
        with patch('views.settings.settings_labels.QMessageBox'):
            labels_screen._save()
        settings = settings_ctrl.get_all_settings()
        assert settings['label_printer_name'] == "Zebra GK420d"
        assert settings['edikio_printer_name'] == "Edikio Access"

    def test_load_restores_previously_saved_selection(self, qtbot, test_db, monkeypatch):
        settings_ctrl.set_setting('edikio_printer_name', 'Edikio Access')
        monkeypatch.setattr(
            'utils.label_print.get_printer_names', lambda: ['Edikio Access', 'Other Printer'])
        from views.settings.settings_labels import LabelPrintingScreen
        w = LabelPrintingScreen()
        qtbot.addWidget(w)
        assert w._selected_edikio_printer_name() == "Edikio Access"


class TestEdikioCardSizeIsFixed:
    def test_card_size_shown_is_the_fixed_constant(self, labels_screen):
        from PyQt6.QtWidgets import QLabel
        texts = [lbl.text() for lbl in labels_screen.findChildren(QLabel)]
        assert any(f"{EDIKIO_WIDTH_MM:g}" in t and f"{EDIKIO_HEIGHT_MM:g}" in t for t in texts)

    def test_no_width_height_spinboxes_for_edikio(self, labels_screen):
        """Regression: only two size groups (standard/large) should be
        editable — Edikio must not gain its own width/height spinboxes,
        since a credit card is a fixed physical size."""
        assert not hasattr(labels_screen, 'edikio_width_spin')
        assert not hasattr(labels_screen, 'edikio_height_spin')


class TestPrintTestEdikioCard:
    def test_no_printer_falls_back_to_pdf(self, labels_screen, monkeypatch):
        opened = []
        with patch('utils.open_file.open_with_default_app', lambda p: opened.append(p)):
            labels_screen._print_test_edikio_card()
        assert len(opened) == 1

    def test_printer_configured_prints_direct(self, labels_screen):
        labels_screen.edikio_printer_combo.addItem("Edikio Access")
        labels_screen.edikio_printer_combo.setCurrentText("Edikio Access")
        with patch('utils.label_print.print_edikio_label_direct',
                    return_value=(True, "Printed")) as mock_print:
            labels_screen._print_test_edikio_card()
        mock_print.assert_called_once()

    def test_direct_print_failure_shows_error(self, labels_screen):
        labels_screen.edikio_printer_combo.addItem("Edikio Access")
        labels_screen.edikio_printer_combo.setCurrentText("Edikio Access")
        with patch('utils.label_print.print_edikio_label_direct',
                    return_value=(False, "Printer offline")), \
             patch('views.settings.settings_labels.show_error') as mock_show_error:
            labels_screen._print_test_edikio_card()
        mock_show_error.assert_called_once()
