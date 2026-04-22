"""
Run this from ~/BackOfficePro:
    python3 fix_product_edit_layout.py
"""
import os, sys

path = 'views/products/product_edit.py'
content = open(path).read()

LABEL_STYLE = "color:#8b949e;font-size:12px;padding:10px 8px 10px 0;background:transparent;"
VALUE_STYLE = "color:#e6edf3;font-size:13px;padding:10px 0 10px 0;background:transparent;"

# ── 1. Window size ─────────────────────────────────────────────────────────
content = content.replace(
    'self.setMinimumWidth(860)\n        self.setMinimumHeight(920)',
    'self.setMinimumWidth(760)\n        self.setMinimumHeight(880)'
)

# ── 2. Check if already patched ────────────────────────────────────────────
if 'QScrollArea' in content and 'QGridLayout' in content:
    print("Already patched")
    sys.exit(0)

# ── 3. Replace form setup + ro_row ────────────────────────────────────────
old = (
    '    def _build_ui(self):\n'
    '        layout = QVBoxLayout(self)\n'
    '        form = QFormLayout()\n'
    '        form.setSpacing(0)\n'
    '        form.setContentsMargins(16, 8, 16, 8)\n'
    '        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)\n'
    '        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)\n'
    '        def ro_row(value, on_edit):\n'
    '            wrapper = QWidget()\n'
    '            wrapper.setStyleSheet(\n'
    '                "background: transparent; "\n'
    '                "border-bottom: 1px solid rgba(255,255,255,0.07);"\n'
    '            )\n'
    '            row = QHBoxLayout(wrapper)\n'
    '            row.setContentsMargins(0, 8, 0, 8)\n'
    '            row.setSpacing(8)\n'
    '            lbl = QLabel(str(value))\n'
    '            lbl.setMinimumWidth(400)\n'
    '            lbl.setStyleSheet("background: transparent; border: none;")\n'
    '            btn = QPushButton("\u270e")\n'
    '            btn.setFixedSize(28, 28)\n'
    '            btn.setStyleSheet("border: 1px solid #2a3a4a; border-radius: 4px; background: #1e2a38;")\n'
    '            btn.clicked.connect(on_edit)\n'
    '            row.addWidget(lbl)\n'
    '            row.addWidget(btn)\n'
    '            row.addStretch()\n'
    '            return wrapper, lbl'
)

new = (
    '    def _build_ui(self):\n'
    '        from PyQt6.QtWidgets import QScrollArea, QGridLayout\n'
    '\n'
    '        LABEL_STYLE = "color:#8b949e;font-size:12px;padding:10px 8px 10px 0;background:transparent;"\n'
    '        VALUE_STYLE = "color:#e6edf3;font-size:13px;padding:10px 0 10px 0;background:transparent;"\n'
    '        SEP_STYLE   = "background:rgba(255,255,255,0.07);max-height:1px;min-height:1px;"\n'
    '        BTN_STYLE   = ("QPushButton{background:#1e2a38;color:#8b949e;border:1px solid #2a3a4a;"\n'
    '                       "border-radius:4px;font-size:14px;}"\n'
    '                       "QPushButton:hover{background:#2a3a4a;color:#e6edf3;}")\n'
    '\n'
    '        outer = QVBoxLayout(self)\n'
    '        outer.setContentsMargins(0, 0, 0, 0)\n'
    '        outer.setSpacing(0)\n'
    '\n'
    '        scroll = QScrollArea()\n'
    '        scroll.setWidgetResizable(True)\n'
    '        scroll.setFrameShape(QScrollArea.Shape.NoFrame)\n'
    '        form_container = QWidget()\n'
    '        form_container.setStyleSheet("background:transparent;")\n'
    '        fc_layout = QVBoxLayout(form_container)\n'
    '        fc_layout.setContentsMargins(24, 8, 24, 8)\n'
    '        fc_layout.setSpacing(0)\n'
    '        scroll.setWidget(form_container)\n'
    '        outer.addWidget(scroll, stretch=1)\n'
    '\n'
    '        grid_widget = QWidget()\n'
    '        grid_widget.setStyleSheet("background:transparent;")\n'
    '        grid = QGridLayout(grid_widget)\n'
    '        grid.setContentsMargins(0, 0, 0, 0)\n'
    '        grid.setVerticalSpacing(0)\n'
    '        grid.setHorizontalSpacing(16)\n'
    '        grid.setColumnMinimumWidth(0, 160)\n'
    '        grid.setColumnMinimumWidth(1, 300)\n'
    '        grid.setColumnStretch(1, 1)\n'
    '        fc_layout.addWidget(grid_widget)\n'
    '        self._grid = grid\n'
    '        self._grid_row = 0\n'
    '        layout = fc_layout\n'
    '\n'
    '        def _add_sep():\n'
    '            sep = QFrame()\n'
    '            sep.setFrameShape(QFrame.Shape.HLine)\n'
    '            sep.setStyleSheet(SEP_STYLE)\n'
    '            self._grid.addWidget(sep, self._grid_row, 0, 1, 3)\n'
    '            self._grid_row += 1\n'
    '\n'
    '        def ro_row(value, on_edit):\n'
    '            lbl_key = QLabel()\n'
    '            lbl_key.setStyleSheet(LABEL_STYLE)\n'
    '            lbl_val = QLabel(str(value))\n'
    '            lbl_val.setStyleSheet(VALUE_STYLE)\n'
    '            lbl_val.setWordWrap(True)\n'
    '            btn = QPushButton("\u270e")\n'
    '            btn.setFixedSize(26, 26)\n'
    '            btn.setStyleSheet(BTN_STYLE)\n'
    '            btn.clicked.connect(on_edit)\n'
    '            _add_sep()\n'
    '            self._grid.addWidget(lbl_key, self._grid_row, 0,\n'
    '                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)\n'
    '            self._grid.addWidget(lbl_val, self._grid_row, 1,\n'
    '                Qt.AlignmentFlag.AlignVCenter)\n'
    '            self._grid.addWidget(btn, self._grid_row, 2,\n'
    '                Qt.AlignmentFlag.AlignVCenter)\n'
    '            self._grid_row += 1\n'
    '            dummy = QHBoxLayout()\n'
    '            dummy._lbl_key = lbl_key\n'
    '            return dummy, lbl_val'
)

if old in content:
    content = content.replace(old, new)
    print("ro_row replaced OK")
else:
    print("ERROR: ro_row block not found")
    sys.exit(1)

# ── 4. Insert addRow helper before field definitions ──────────────────────
old2 = (
    '        # ── Field order per spec ──────────────────────────────────────\n'
    "        r, self.lbl_barcode = ro_row(self.product['barcode'], self._edit_barcode)\n"
    '        form.addRow("Barcode", r)'
)
new2 = (
    '        def addRow(label_text, row_or_widget):\n'
    '            if hasattr(row_or_widget, \'_lbl_key\'):\n'
    '                row_or_widget._lbl_key.setText(label_text)\n'
    '            elif isinstance(row_or_widget, QWidget):\n'
    '                key_lbl = QLabel(label_text)\n'
    '                key_lbl.setStyleSheet(LABEL_STYLE)\n'
    '                _add_sep()\n'
    '                self._grid.addWidget(key_lbl, self._grid_row, 0,\n'
    '                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)\n'
    '                self._grid.addWidget(row_or_widget, self._grid_row, 1, 1, 2,\n'
    '                    Qt.AlignmentFlag.AlignVCenter)\n'
    '                self._grid_row += 1\n'
    '\n'
    "        form = type('FakeForm', (), {'addRow': staticmethod(addRow)})()\n"
    '\n'
    '        # ── Field order per spec ──────────────────────────────────────\n'
    "        r, self.lbl_barcode = ro_row(self.product['barcode'], self._edit_barcode)\n"
    '        form.addRow("Barcode", r)'
)

if old2 in content:
    content = content.replace(old2, new2)
    print("addRow helper OK")
else:
    print("ERROR: field order block not found")
    sys.exit(1)

# ── 5. Redirect bottom widgets ────────────────────────────────────────────
content = content.replace('        layout.addLayout(form)\n', '        _add_sep()\n')
content = content.replace(
    '        hist_row.addStretch()\n        layout.addLayout(hist_row)',
    '        hist_row.addStretch()\n        outer.addLayout(hist_row)'
)
content = content.replace('        layout.addWidget(alias_group)', '        outer.addWidget(alias_group)')
content = content.replace('        layout.addLayout(btns)',        '        outer.addLayout(btns)')

open(path, 'w').write(content)
print("Saved OK")
