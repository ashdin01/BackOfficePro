"""Step 1 of bank reconciliation: upload CSV and map columns."""
import csv
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QFileDialog,
    QSpinBox, QCheckBox, QLineEdit, QGroupBox, QFormLayout,
    QMessageBox, QDialogButtonBox, QRadioButton, QButtonGroup,
    QHeaderView, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt
import models.bank_recon as recon_model

FIELD_OPTIONS = ['— ignore —', 'Date', 'Amount', 'Debit', 'Credit',
                 'Description', 'Reference', 'Balance']

DATE_PRESETS = [
    ('%d/%m/%Y', 'DD/MM/YYYY  (e.g. 30/04/2026)'),
    ('%d/%m/%y', 'DD/MM/YY  (e.g. 30/04/26)'),
    ('%d %b %Y', 'D Mon YYYY  (e.g. 30 Apr 2026)'),
    ('%d %b %y', 'D Mon YY  (e.g. 30 Apr 26)'),
    ('%Y-%m-%d', 'YYYY-MM-DD  (ISO)'),
    ('%m/%d/%Y', 'MM/DD/YYYY'),
    ('custom',   'Custom…'),
]

DELIMITERS = [(',', 'Comma  (,)'), ('\t', 'Tab'), (';', 'Semicolon  (;)'), ('|', 'Pipe  (|)')]


class ReconImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bank Reconciliation — Import CSV")
        self.setMinimumSize(940, 660)
        self._csv_path       = None
        self._raw_rows       = []
        self._headers        = []
        self._col_combos     = []
        self._pending_profile = None
        self._result         = None
        self._build_ui()
        self._refresh_profiles()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Saved profile bar
        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Saved profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.currentIndexChanged.connect(self._load_profile)
        prof_row.addWidget(self.profile_combo)
        btn_del = QPushButton("Delete Profile")
        btn_del.clicked.connect(self._delete_profile)
        prof_row.addWidget(btn_del)
        prof_row.addStretch()
        root.addLayout(prof_row)

        # File picker
        file_row = QHBoxLayout()
        btn_pick = QPushButton("📂  Choose CSV File…")
        btn_pick.clicked.connect(self._pick_file)
        self.lbl_file = QLabel("No file selected")
        self.lbl_file.setStyleSheet("color: grey;")
        file_row.addWidget(btn_pick)
        file_row.addWidget(self.lbl_file, 1)
        root.addLayout(file_row)

        # Parse options
        opts_grp = QGroupBox("Parse Options")
        opts_row = QHBoxLayout(opts_grp)
        self.chk_header = QCheckBox("First row is header")
        self.chk_header.setChecked(True)
        self.chk_header.stateChanged.connect(self._reparse)
        opts_row.addWidget(self.chk_header)

        opts_row.addWidget(QLabel("   Skip rows:"))
        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(0, 10)
        self.skip_spin.valueChanged.connect(self._reparse)
        opts_row.addWidget(self.skip_spin)

        opts_row.addWidget(QLabel("   Delimiter:"))
        self.delim_combo = QComboBox()
        for _, label in DELIMITERS:
            self.delim_combo.addItem(label)
        self.delim_combo.currentIndexChanged.connect(self._reparse)
        opts_row.addWidget(self.delim_combo)
        opts_row.addStretch()
        root.addWidget(opts_grp)

        # Column assignment preview
        root.addWidget(QLabel(
            "<b>Column Assignment</b> — use the dropdowns in row 1 to assign a role to each column:"
        ))
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.preview_table.setMinimumHeight(200)
        root.addWidget(self.preview_table)

        # Format settings
        fmt_grp = QGroupBox("Format Settings")
        fmt_form = QFormLayout(fmt_grp)

        self.date_preset = QComboBox()
        for fmt, label in DATE_PRESETS:
            self.date_preset.addItem(label, fmt)
        self.date_preset.currentIndexChanged.connect(self._on_date_preset)
        fmt_form.addRow("Date format:", self.date_preset)

        self.date_custom = QLineEdit()
        self.date_custom.setPlaceholderText("Python strptime format, e.g. %d-%m-%Y")
        self.date_custom.setVisible(False)
        fmt_form.addRow("Custom format:", self.date_custom)

        self.rb_signed = QRadioButton(
            "Single signed column  (positive = credit in, negative = debit out)"
        )
        self.rb_split  = QRadioButton("Separate Debit / Credit columns")
        self.rb_signed.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_signed)
        grp.addButton(self.rb_split)
        fmt_form.addRow("Amount type:", self.rb_signed)
        fmt_form.addRow("",             self.rb_split)
        root.addWidget(fmt_grp)

        # Save profile row
        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("Profile name:"))
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("e.g.  NAB Business Cheque")
        save_row.addWidget(self.profile_name, 1)
        btn_save = QPushButton("💾  Save Profile")
        btn_save.clicked.connect(self._save_profile)
        save_row.addWidget(btn_save)
        root.addLayout(save_row)

        # Dialog buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Import →")
        btns.accepted.connect(self._import)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ── Profile management ────────────────────────────────────────────

    def _refresh_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("— new mapping —", None)
        for p in recon_model.get_all_profiles():
            self.profile_combo.addItem(p['name'], p['id'])
        self.profile_combo.blockSignals(False)

    def _load_profile(self):
        pid = self.profile_combo.currentData()
        if not pid:
            return
        p = recon_model.get_profile(pid)
        if not p:
            return
        self.chk_header.setChecked(bool(p['has_header']))
        self.skip_spin.setValue(int(p['skip_rows'] or 0))
        delim_chars = [d for d, _ in DELIMITERS]
        di = delim_chars.index(p['delimiter']) if p['delimiter'] in delim_chars else 0
        self.delim_combo.setCurrentIndex(di)
        fmt = p['date_format'] or '%d/%m/%Y'
        for i, (f, _) in enumerate(DATE_PRESETS):
            if f == fmt:
                self.date_preset.setCurrentIndex(i)
                break
        else:
            self.date_preset.setCurrentIndex(len(DATE_PRESETS) - 1)
            self.date_custom.setText(fmt)
        if p['amount_type'] == 'split':
            self.rb_split.setChecked(True)
        else:
            self.rb_signed.setChecked(True)
        self.profile_name.setText(p['name'])
        self._pending_profile = p
        self._reparse()

    def _delete_profile(self):
        pid = self.profile_combo.currentData()
        if not pid:
            return
        name = self.profile_combo.currentText()
        if QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            recon_model.delete_profile(pid)
            self._refresh_profiles()

    def _save_profile(self):
        name = self.profile_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Enter a profile name first.")
            return
        pid = recon_model.save_profile(**self._profile_kwargs(name))
        self._refresh_profiles()
        for i in range(self.profile_combo.count()):
            if self.profile_combo.itemData(i) == pid:
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentIndex(i)
                self.profile_combo.blockSignals(False)
                break
        QMessageBox.information(self, "Saved", f"Profile '{name}' saved.")

    def _profile_kwargs(self, name):
        a = self._get_assignments()
        return dict(
            name          = name,
            delimiter     = self._delimiter(),
            has_header    = 1 if self.chk_header.isChecked() else 0,
            skip_rows     = self.skip_spin.value(),
            date_format   = self._date_format(),
            amount_type   = 'split' if self.rb_split.isChecked() else 'signed',
            col_date        = a.get('Date'),
            col_amount      = a.get('Amount'),
            col_debit       = a.get('Debit'),
            col_credit      = a.get('Credit'),
            col_description = a.get('Description'),
            col_reference   = a.get('Reference'),
            col_balance     = a.get('Balance'),
        )

    # ── File parsing ──────────────────────────────────────────────────

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Bank CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self._csv_path = path
            self.lbl_file.setText(os.path.basename(path))
            self.lbl_file.setStyleSheet("")
            self._reparse()

    def _delimiter(self):
        return DELIMITERS[self.delim_combo.currentIndex()][0]

    def _date_format(self):
        data = self.date_preset.currentData()
        if data == 'custom':
            return self.date_custom.text().strip() or '%d/%m/%Y'
        return data

    def _on_date_preset(self):
        self.date_custom.setVisible(self.date_preset.currentData() == 'custom')

    def _reparse(self):
        if not self._csv_path:
            return
        try:
            with open(self._csv_path, newline='', encoding='utf-8-sig') as f:
                all_rows = list(csv.reader(f, delimiter=self._delimiter()))
        except Exception as e:
            QMessageBox.critical(self, "Read Error", str(e))
            return

        skip = self.skip_spin.value()
        all_rows = all_rows[skip:]
        if not all_rows:
            return

        if self.chk_header.isChecked():
            self._headers  = [h.strip() for h in all_rows[0]]
            self._raw_rows = all_rows[1:9]
        else:
            self._headers  = [f"Col {i}" for i in range(len(all_rows[0]))]
            self._raw_rows = all_rows[:9]

        self._build_preview()

    def _build_preview(self):
        n_cols = len(self._headers)
        n_rows = len(self._raw_rows)

        # save previous assignments before rebuilding
        prev = {}
        for i, cb in enumerate(self._col_combos):
            if cb.currentIndex() > 0:
                prev[i] = cb.currentText()

        self.preview_table.setRowCount(n_rows + 1)
        self.preview_table.setColumnCount(n_cols)
        self.preview_table.setHorizontalHeaderLabels(self._headers)

        self._col_combos = []
        for c in range(n_cols):
            cb = QComboBox()
            cb.addItems(FIELD_OPTIONS)
            if c in prev and prev[c] in FIELD_OPTIONS:
                cb.setCurrentIndex(FIELD_OPTIONS.index(prev[c]))
            self._col_combos.append(cb)
            self.preview_table.setCellWidget(0, c, cb)

        for r, row in enumerate(self._raw_rows):
            for c in range(n_cols):
                val = row[c].strip() if c < len(row) else ''
                self.preview_table.setItem(r + 1, c, QTableWidgetItem(val))

        self.preview_table.resizeColumnsToContents()

        # apply column assignments from a loaded profile
        if self._pending_profile:
            p = self._pending_profile
            mapping = {
                p.get('col_date'):        'Date',
                p.get('col_amount'):      'Amount',
                p.get('col_debit'):       'Debit',
                p.get('col_credit'):      'Credit',
                p.get('col_description'): 'Description',
                p.get('col_reference'):   'Reference',
                p.get('col_balance'):     'Balance',
            }
            for col_idx, field in mapping.items():
                if col_idx is not None and field in FIELD_OPTIONS:
                    idx = FIELD_OPTIONS.index(field)
                    if 0 <= col_idx < len(self._col_combos):
                        self._col_combos[col_idx].setCurrentIndex(idx)
            self._pending_profile = None

    def _get_assignments(self):
        """Returns {field_name: col_index} for all non-ignored columns."""
        result = {}
        for i, cb in enumerate(self._col_combos):
            field = cb.currentText()
            if field != '— ignore —':
                # last assignment wins if user duplicated a field
                result[field] = i
        return result

    # ── Import ────────────────────────────────────────────────────────

    def _import(self):
        if not self._csv_path:
            QMessageBox.warning(self, "No File", "Choose a CSV file first.")
            return

        assignments = self._get_assignments()
        amount_type = 'split' if self.rb_split.isChecked() else 'signed'

        # Validate required fields
        missing = []
        if 'Date' not in assignments:
            missing.append('Date')
        if 'Description' not in assignments:
            missing.append('Description')
        if amount_type == 'signed' and 'Amount' not in assignments:
            missing.append('Amount')
        if amount_type == 'split' and 'Credit' not in assignments and 'Debit' not in assignments:
            missing.append('Credit or Debit')
        if missing:
            QMessageBox.warning(self, "Missing Columns",
                                f"Please assign: {', '.join(missing)}")
            return

        date_fmt = self._date_format()
        skip     = self.skip_spin.value()
        has_hdr  = self.chk_header.isChecked()

        try:
            with open(self._csv_path, newline='', encoding='utf-8-sig') as f:
                all_rows = list(csv.reader(f, delimiter=self._delimiter()))
        except Exception as e:
            QMessageBox.critical(self, "Read Error", str(e))
            return

        all_rows = all_rows[skip:]
        if has_hdr:
            all_rows = all_rows[1:]

        parsed, errors = [], []
        for i, row in enumerate(all_rows):
            if not any(c.strip() for c in row):
                continue
            try:
                txn = _parse_row(row, assignments, date_fmt, amount_type)
                if txn:
                    parsed.append(txn)
            except Exception as e:
                errors.append(f"Row {skip + (2 if has_hdr else 1) + i}: {e}")

        if errors:
            sample = '\n'.join(errors[:5])
            if len(errors) > 5:
                sample += f'\n… and {len(errors) - 5} more'
            reply = QMessageBox.warning(
                self, "Parse Warnings",
                f"{len(errors)} row(s) could not be parsed:\n\n{sample}\n\n"
                f"Import the {len(parsed)} valid rows anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if not parsed:
            QMessageBox.warning(self, "No Data", "No valid transactions found in the file.")
            return

        name = self.profile_name.text().strip() or "Unnamed"
        profile_id = recon_model.save_profile(**self._profile_kwargs(name))
        batch = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        recon_model.insert_transactions(profile_id, batch, parsed)

        self._result = {'batch': batch, 'count': len(parsed), 'errors': len(errors)}
        self.accept()

    def import_result(self):
        return self._result


# ── Row parser (module-level) ─────────────────────────────────────────────────

def _parse_row(row, assignments, date_fmt, amount_type):
    def cell(field):
        idx = assignments.get(field)
        return row[idx].strip() if idx is not None and idx < len(row) else ''

    raw_date = cell('Date')
    if not raw_date:
        return None

    # Try the specified format first, then common fallbacks
    txn_date = None
    for fmt in (date_fmt, '%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d', '%d %b %Y', '%d %b %y'):
        try:
            txn_date = datetime.strptime(raw_date, fmt).strftime('%Y-%m-%d')
            break
        except ValueError:
            pass
    if not txn_date:
        raise ValueError(f"Cannot parse date '{raw_date}' with format '{date_fmt}'")

    if amount_type == 'split':
        raw_d = cell('Debit').replace(',', '').replace('$', '').replace('−', '-')
        raw_c = cell('Credit').replace(',', '').replace('$', '').replace('−', '-')
        debit  = float(raw_d) if raw_d else 0.0
        credit = float(raw_c) if raw_c else 0.0
        amount = round(credit - debit, 2)
    else:
        raw = cell('Amount').replace(',', '').replace('$', '').replace('−', '-')
        if not raw:
            return None
        amount = round(float(raw), 2)

    description = cell('Description')
    reference   = cell('Reference')
    raw_bal     = cell('Balance').replace(',', '').replace('$', '')
    balance     = float(raw_bal) if raw_bal else None

    return {
        'txn_date':    txn_date,
        'amount':      amount,
        'description': description,
        'reference':   reference,
        'balance':     balance,
    }
