"""Scale Labels settings — how to read EAN-13 barcodes printed by a
weigh-and-label machine (PLU plus weight or price embedded in the barcode).

Stored as scale_label_* settings; models.barcode.decode_scale_label reads
them, so product lookups by scanned label work in BackOfficePro and its API.
RetailPOSPro keeps its own copy of the same keys (Settings → Scale), so enter
the same layout in both.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QCheckBox, QGroupBox, QMessageBox, QSizePolicy,
)
from PyQt6.QtGui import QKeySequence, QShortcut
import controllers.settings_controller as settings_ctrl
from models.barcode import (
    SCALE_LABEL_DEFAULTS, SCALE_LABEL_PRESETS, decode_scale_label,
)

_FIELDS = (
    ('scale_label_prefixes',    "Starts with",     "e.g. 2 or 20,21"),
    ('scale_label_plu_start',   "PLU starts at",   "0-12"),
    ('scale_label_plu_len',     "PLU digits",      "e.g. 5"),
    ('scale_label_value_start', "Value starts at", "0-12"),
    ('scale_label_value_len',   "Value digits",    "e.g. 5"),
)


class ScaleLabelsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scale Labels")
        self.setMinimumWidth(480)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._build_ui()
        self._load()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        note = QLabel(
            "Barcodes printed by a weigh-and-label machine carry the item's PLU and "
            "either its weight (grams) or total price (cents). Digit positions count "
            "from 0 at the first digit. Enter the same layout in RetailPOSPro."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: grey;")
        outer.addWidget(note)

        group = QGroupBox("Label layout")
        form = QFormLayout(group)
        self.enabled_chk = QCheckBox("Recognise scale-label barcodes")
        form.addRow("", self.enabled_chk)

        self.preset_cb = QComboBox()
        self.preset_cb.addItem("Custom", None)
        for name in SCALE_LABEL_PRESETS:
            self.preset_cb.addItem(name, name)
        self.preset_cb.currentIndexChanged.connect(self._on_preset)
        form.addRow("Layout", self.preset_cb)

        self.type_cb = QComboBox()
        self.type_cb.addItem("Weight (grams)", 'weight')
        self.type_cb.addItem("Price (cents)", 'price')
        self.type_cb.currentIndexChanged.connect(self._test)
        form.addRow("Embedded value", self.type_cb)

        self.edits = {}
        for key, label, ph in _FIELDS:
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.textEdited.connect(self._on_field_edited)
            self.edits[key] = e
            form.addRow(label, e)

        self.check_chk = QCheckBox("Reject labels with a bad EAN-13 check digit")
        form.addRow("", self.check_chk)

        self.test_edit = QLineEdit()
        self.test_edit.setPlaceholderText("Scan or type a label barcode to test")
        self.test_edit.textChanged.connect(self._test)
        form.addRow("Test", self.test_edit)
        self.test_lbl = QLabel("")
        form.addRow("", self.test_lbl)
        outer.addWidget(group)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel  [Esc]")
        cancel.clicked.connect(self.close)
        save = QPushButton("Save  [Ctrl+S]")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _cfg(self) -> dict:
        cfg = {k: e.text().strip() for k, e in self.edits.items()}
        cfg['scale_label_enabled'] = '1' if self.enabled_chk.isChecked() else '0'
        cfg['scale_label_value_type'] = self.type_cb.currentData()
        cfg['scale_label_check'] = '1' if self.check_chk.isChecked() else '0'
        return cfg

    def _load(self):
        stored = settings_ctrl.get_all_settings()
        lv = {**SCALE_LABEL_DEFAULTS,
              **{k: v for k, v in stored.items() if k.startswith('scale_label_') and v}}
        self.enabled_chk.setChecked(lv['scale_label_enabled'] == '1')
        self.check_chk.setChecked(lv['scale_label_check'] == '1')
        for key, e in self.edits.items():
            e.setText(lv[key])
        self.type_cb.setCurrentIndex(max(self.type_cb.findData(lv['scale_label_value_type']), 0))
        current = tuple(lv[k] for k, _, _ in _FIELDS)
        self.preset_cb.blockSignals(True)
        self.preset_cb.setCurrentIndex(0)
        for name, (pf, ps, pl, vs, vl) in SCALE_LABEL_PRESETS.items():
            if current == (pf, str(ps), str(pl), str(vs), str(vl)):
                self.preset_cb.setCurrentIndex(self.preset_cb.findData(name))
                break
        self.preset_cb.blockSignals(False)

    def _on_preset(self, _i):
        name = self.preset_cb.currentData()
        if name is None:
            return
        for (key, _, _), val in zip(_FIELDS, SCALE_LABEL_PRESETS[name]):
            self.edits[key].setText(str(val))
        self._test()

    def _on_field_edited(self, _t):
        self.preset_cb.blockSignals(True)
        self.preset_cb.setCurrentIndex(0)
        self.preset_cb.blockSignals(False)
        self._test()

    def _test(self, *_):
        code = self.test_edit.text().strip()
        if not code:
            self.test_lbl.setText("")
            return
        cfg = self._cfg()
        cfg['scale_label_enabled'] = '1'
        r = decode_scale_label(code, cfg)
        if r is None:
            self.test_lbl.setText("Not recognised as a scale label")
        elif r['price'] is not None:
            self.test_lbl.setText(f"PLU {r['plu']}  ·  price ${r['price']:.2f}")
        else:
            self.test_lbl.setText(f"PLU {r['plu']}  ·  weight {r['weight_kg']:.3f} kg")

    def _save(self):
        for k, v in self._cfg().items():
            settings_ctrl.set_setting(k, v)
        QMessageBox.information(self, "Saved", "Scale label settings saved.")
        self.close()
