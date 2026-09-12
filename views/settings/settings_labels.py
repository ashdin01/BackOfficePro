"""Label Printing settings — shelf-edge label page sizes, plus the Edikio
card printer.

Once a printer is selected below, Product Detail's "Print Label" / "Print
Large Label" buttons print straight to it — no dialog, no viewer — via
utils.label_print. With no printer selected, they fall back to generating
a PDF and opening it with the system default viewer for manual printing
(utils.label_pdf), so the feature still works before a printer is set up.

Two independent sizes are configurable — "standard" and "large" — matching
the two print buttons on Product Detail, since a shop commonly wants a
small everyday label plus a bigger one for feature/promo placement.

The Edikio card printer is a separate physical device with its own printer
setting (edikio_printer_name) — a shop running both prints shelf labels on
one and credit-card-size price cards on the other. Its size isn't
configurable: a credit card is a fixed physical standard (85.6 x 54mm), not
a label roll that varies by what stock is loaded.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QDoubleSpinBox, QComboBox, QMessageBox,
    QGroupBox, QSizePolicy,
)
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt
import config.styles as styles
import controllers.settings_controller as settings_ctrl
from utils.error_dialog import show_error
from utils.label_pdf import (
    DEFAULT_WIDTH_MM, DEFAULT_HEIGHT_MM,
    DEFAULT_LARGE_WIDTH_MM, DEFAULT_LARGE_HEIGHT_MM,
    EDIKIO_WIDTH_MM, EDIKIO_HEIGHT_MM,
    generate_label_pdf, generate_edikio_label_pdf,
)


class LabelPrintingScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Label Printing")
        self.setMinimumWidth(460)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._build_ui()
        self._load()

    def _build_size_group(self, title):
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        form = QFormLayout(group)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        width_spin = QDoubleSpinBox()
        width_spin.setRange(10.0, 300.0)
        width_spin.setDecimals(1)
        width_spin.setSuffix(" mm")
        form.addRow("Width", width_spin)

        height_spin = QDoubleSpinBox()
        height_spin.setRange(10.0, 300.0)
        height_spin.setDecimals(1)
        height_spin.setSuffix(" mm")
        form.addRow("Height", height_spin)

        btn_test = QPushButton("Print Test Label")
        btn_test.setFixedHeight(28)
        form.addRow("", btn_test)

        return group, width_spin, height_spin, btn_test

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Label Printing")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        printer_group = QGroupBox("Shelf Label Printer")
        printer_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        printer_form = QFormLayout(printer_group)
        printer_form.setContentsMargins(16, 16, 16, 16)
        printer_form.setSpacing(10)
        printer_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        printer_row = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.setMinimumWidth(260)
        printer_row.addWidget(self.printer_combo)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setFixedHeight(26)
        btn_refresh.clicked.connect(lambda: self._refresh_printer_combo(self.printer_combo))
        printer_row.addWidget(btn_refresh)
        printer_form.addRow("Printer", printer_row)

        printer_note = QLabel(
            "Selected: Product Detail's print buttons print straight to this printer, "
            "no dialog. None selected: they open a PDF for you to print manually instead."
        )
        printer_note.setStyleSheet("color: grey; font-size: 8pt;")
        printer_note.setWordWrap(True)
        printer_form.addRow("", printer_note)

        outer.addWidget(printer_group)

        note = QLabel(
            "Each label PDF is generated at exactly the size below, so it must match "
            "your printer's page/label size setting (set in the printer driver) for a "
            "1:1 print."
        )
        note.setStyleSheet("color: grey; font-size: 8pt;")
        note.setWordWrap(True)
        outer.addWidget(note)

        std_group, self.width_spin, self.height_spin, btn_std_test = \
            self._build_size_group('Standard Label  (Product Detail → "Print Label")')
        btn_std_test.clicked.connect(lambda: self._print_test_label(large=False))
        outer.addWidget(std_group)

        large_group, self.large_width_spin, self.large_height_spin, btn_large_test = \
            self._build_size_group('Large Label  (Product Detail → "Print Large Label")')
        btn_large_test.clicked.connect(lambda: self._print_test_label(large=True))
        outer.addWidget(large_group)

        edikio_group = QGroupBox('Edikio Card Printer  (Product Detail → "Print Edikio Card")')
        edikio_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        edikio_form = QFormLayout(edikio_group)
        edikio_form.setContentsMargins(16, 16, 16, 16)
        edikio_form.setSpacing(10)
        edikio_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        edikio_printer_row = QHBoxLayout()
        self.edikio_printer_combo = QComboBox()
        self.edikio_printer_combo.setMinimumWidth(260)
        edikio_printer_row.addWidget(self.edikio_printer_combo)
        btn_edikio_refresh = QPushButton("Refresh")
        btn_edikio_refresh.setFixedHeight(26)
        btn_edikio_refresh.clicked.connect(
            lambda: self._refresh_printer_combo(self.edikio_printer_combo))
        edikio_printer_row.addWidget(btn_edikio_refresh)
        edikio_form.addRow("Printer", edikio_printer_row)

        edikio_form.addRow(
            "Card Size", QLabel(f"{EDIKIO_WIDTH_MM:g} × {EDIKIO_HEIGHT_MM:g} mm  (fixed)"))

        edikio_note = QLabel(
            "A separate physical printer from the shelf label one above. Standard credit-card "
            "size (ISO/IEC 7810 ID-1) — not configurable, since it's a fixed card stock rather "
            "than a label roll."
        )
        edikio_note.setStyleSheet("color: grey; font-size: 8pt;")
        edikio_note.setWordWrap(True)
        edikio_form.addRow("", edikio_note)

        btn_edikio_test = QPushButton("Print Test Card")
        btn_edikio_test.setFixedHeight(28)
        btn_edikio_test.clicked.connect(self._print_test_edikio_card)
        edikio_form.addRow("", btn_edikio_test)

        outer.addWidget(edikio_group)

        outer.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.close)

        btn_save = QPushButton("Save  [Ctrl+S]")
        btn_save.setFixedHeight(34)
        btn_save.setStyleSheet(
            f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
            f"border-radius: 4px; padding: 0 18px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
        )
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    _NONE_PRINTER = "-- None (open a PDF to print manually) --"

    def _refresh_printer_combo(self, combo):
        from utils.label_print import get_printer_names
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._NONE_PRINTER)
        combo.addItems(get_printer_names())
        idx = combo.findText(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _load(self):
        settings = settings_ctrl.get_all_settings()
        self.width_spin.setValue(float(settings.get('label_width_mm') or DEFAULT_WIDTH_MM))
        self.height_spin.setValue(float(settings.get('label_height_mm') or DEFAULT_HEIGHT_MM))
        self.large_width_spin.setValue(
            float(settings.get('label_large_width_mm') or DEFAULT_LARGE_WIDTH_MM))
        self.large_height_spin.setValue(
            float(settings.get('label_large_height_mm') or DEFAULT_LARGE_HEIGHT_MM))

        self._refresh_printer_combo(self.printer_combo)
        saved_printer = settings.get('label_printer_name') or ''
        if saved_printer:
            idx = self.printer_combo.findText(saved_printer)
            if idx >= 0:
                self.printer_combo.setCurrentIndex(idx)

        self._refresh_printer_combo(self.edikio_printer_combo)
        saved_edikio_printer = settings.get('edikio_printer_name') or ''
        if saved_edikio_printer:
            idx = self.edikio_printer_combo.findText(saved_edikio_printer)
            if idx >= 0:
                self.edikio_printer_combo.setCurrentIndex(idx)

    def _selected_printer_name(self) -> str:
        text = self.printer_combo.currentText()
        return '' if text == self._NONE_PRINTER else text

    def _selected_edikio_printer_name(self) -> str:
        text = self.edikio_printer_combo.currentText()
        return '' if text == self._NONE_PRINTER else text

    def _save(self):
        settings_ctrl.set_setting('label_width_mm', str(self.width_spin.value()))
        settings_ctrl.set_setting('label_height_mm', str(self.height_spin.value()))
        settings_ctrl.set_setting('label_large_width_mm', str(self.large_width_spin.value()))
        settings_ctrl.set_setting('label_large_height_mm', str(self.large_height_spin.value()))
        settings_ctrl.set_setting('label_printer_name', self._selected_printer_name())
        settings_ctrl.set_setting('edikio_printer_name', self._selected_edikio_printer_name())
        QMessageBox.information(self, "Saved", "Label Printing settings saved successfully.")
        self.close()

    def _print_test_label(self, large):
        settings_ctrl.set_setting('label_width_mm', str(self.width_spin.value()))
        settings_ctrl.set_setting('label_height_mm', str(self.height_spin.value()))
        settings_ctrl.set_setting('label_large_width_mm', str(self.large_width_spin.value()))
        settings_ctrl.set_setting('label_large_height_mm', str(self.large_height_spin.value()))
        settings_ctrl.set_setting('label_printer_name', self._selected_printer_name())

        test_kwargs = dict(
            barcode="9300000000001",
            description="Sample Product Description",
            price_inc_gst=9.99,
            plu="1234",
        )
        if self._selected_printer_name():
            from utils.label_print import print_label_direct
            ok, msg = print_label_direct(**test_kwargs, large=large)
            if not ok:
                show_error(self, "Could not print the test label.", RuntimeError(msg))
            return

        try:
            from utils.open_file import open_with_default_app
            path = generate_label_pdf(**test_kwargs, copies=1, large=large)
            open_with_default_app(path)
        except Exception as e:
            show_error(self, "Could not generate the test label.", e)

    def _print_test_edikio_card(self):
        settings_ctrl.set_setting('edikio_printer_name', self._selected_edikio_printer_name())

        test_kwargs = dict(
            barcode="9300000000001",
            description="Sample Product Description",
            price_inc_gst=9.99,
            unit="EA",
        )
        if self._selected_edikio_printer_name():
            from utils.label_print import print_edikio_label_direct
            ok, msg = print_edikio_label_direct(**test_kwargs)
            if not ok:
                show_error(self, "Could not print the test card.", RuntimeError(msg))
            return

        try:
            from utils.open_file import open_with_default_app
            path = generate_edikio_label_pdf(**test_kwargs, copies=1)
            open_with_default_app(path)
        except Exception as e:
            show_error(self, "Could not generate the test card.", e)
