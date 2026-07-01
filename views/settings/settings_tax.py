"""Tax Rates settings screen — store-wide default GST rate."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QDoubleSpinBox, QGroupBox, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import config.styles as styles
import controllers.settings_controller as settings_ctrl


class TaxRatesScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tax Rates")
        self.setMinimumWidth(460)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("Tax Rates")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        outer.addWidget(title)

        tax_group = QGroupBox("GST")
        tax_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        tax_form = QFormLayout(tax_group)
        tax_form.setContentsMargins(16, 16, 16, 16)
        tax_form.setSpacing(10)
        tax_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._gst_rate = QDoubleSpinBox()
        self._gst_rate.setRange(0, 100)
        self._gst_rate.setDecimals(1)
        self._gst_rate.setSuffix("%")
        self._gst_rate.setMinimumWidth(120)
        tax_form.addRow("Default GST Rate", self._gst_rate)

        note = QLabel(
            "💡 This is the store-wide default GST rate, applied when a product or\n"
            "    AR invoice line doesn't specify its own rate. Individual products and\n"
            "    invoice lines can still override it (e.g. GST-free items at 0%)."
        )
        note.setStyleSheet("color: grey; font-size: 8pt;")
        note.setWordWrap(True)
        tax_form.addRow("", note)

        outer.addWidget(tax_group)
        outer.addStretch()

        # ── Buttons ────────────────────────────────────────────────────
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

    def _load(self):
        rate = settings_ctrl.get_setting("gst_rate", "10.0")
        try:
            self._gst_rate.setValue(float(rate))
        except (TypeError, ValueError):
            self._gst_rate.setValue(10.0)

    def _save(self):
        settings_ctrl.set_setting("gst_rate", str(self._gst_rate.value()))
        QMessageBox.information(self, "Saved", "Tax Rates saved successfully.")
        self.close()
