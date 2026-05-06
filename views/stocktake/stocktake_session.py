from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QDialog, QFormLayout, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.error_dialog import show_error
import models.stocktake as stocktake_model
import models.product as product_model
import models.stock_on_hand as soh_model


class StocktakeSession(QWidget):
    def __init__(self, session_id, on_close=None):
        super().__init__()
        self.session_id = session_id
        self.on_close = on_close
        self.setMinimumSize(1000, 650)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        # Import bar
        import_row = QHBoxLayout()
        import_lbl = QLabel("Import counts:")
        import_lbl.setStyleSheet("color: grey;")
        import_row.addWidget(import_lbl)

        btn_csv = QPushButton("📂 Import CSV")
        btn_csv.setFixedHeight(30)
        btn_csv.setToolTip(
            "Import from CSV file.\n"
            "Required columns: barcode (or ean/code/upc) + qty (or quantity/count/counted)"
        )
        btn_csv.clicked.connect(self._import_csv)
        import_row.addWidget(btn_csv)

        btn_sqlite = QPushButton("🗄 Import SQLite")
        btn_sqlite.setFixedHeight(30)
        btn_sqlite.setToolTip(
            "Import from a SQLite database file (.db/.sqlite).\n"
            "Will auto-detect tables with barcode + qty columns."
        )
        btn_sqlite.clicked.connect(self._import_sqlite)
        import_row.addWidget(btn_sqlite)

        import_row.addStretch()

        self.import_status = QLabel("")
        self.import_status.setStyleSheet("color: steelblue;")
        import_row.addWidget(self.import_status)
        layout.addLayout(import_row)

        # Manual scan bar
        scan_row = QHBoxLayout()
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Scan barcode or type and press Enter to add manually...")
        self.scan_input.setFixedHeight(36)
        self.scan_input.returnPressed.connect(self._on_scan)
        scan_row.addWidget(self.scan_input)

        self.qty_input = QDoubleSpinBox()
        self.qty_input.setMinimum(0)
        self.qty_input.setMaximum(999999)
        self.qty_input.setDecimals(0)
        self.qty_input.setValue(1)
        self.qty_input.setFixedHeight(36)
        self.qty_input.setFixedWidth(100)
        scan_row.addWidget(QLabel("Qty:"))
        scan_row.addWidget(self.qty_input)

        btn_scan = QPushButton("Add  [Enter]")
        btn_scan.setFixedHeight(36)
        btn_scan.clicked.connect(self._on_scan)
        scan_row.addWidget(btn_scan)
        layout.addLayout(scan_row)

        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet("color: steelblue; padding: 2px;")
        layout.addWidget(self.scan_status)

        # Count table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department", "SOH", "Counted", "Variance", "Scanned At"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.summary_label = QLabel("")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.summary_label)

        # Buttons
        btns = QHBoxLayout()

        btn_edit = QPushButton("&Edit Count")
        btn_edit.setFixedHeight(34)
        btn_edit.clicked.connect(self._edit_count)

        btn_del = QPushButton("&Remove Line")
        btn_del.setFixedHeight(34)
        btn_del.clicked.connect(self._remove_line)

        btn_variance = QPushButton("📊 &Variance Report")
        btn_variance.setFixedHeight(34)
        btn_variance.setToolTip("Review full variance report before applying")
        btn_variance.clicked.connect(self._open_variance_report)

        btn_apply = QPushButton("✓ &Apply && Close Session")
        btn_apply.setFixedHeight(34)
        btn_apply.setStyleSheet("background-color: #2e7d32; color: white;")
        btn_apply.clicked.connect(self._apply_session)

        btn_close = QPushButton("Close [Esc]")
        btn_close.setFixedHeight(34)
        btn_close.clicked.connect(self.close)

        btns.addWidget(btn_edit)
        btns.addWidget(btn_del)
        btns.addWidget(btn_variance)
        btns.addStretch()
        btns.addWidget(btn_apply)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

        QShortcut(QKeySequence("Escape"), self, self.close)

    def _load(self):
        session = stocktake_model.get_session(self.session_id)
        self._session = session
        status = session['status']
        dept = session['dept_name'] or 'All Departments'
        self.setWindowTitle(f"Stocktake: {session['label']}")
        self.header.setText(
            f"<b>{session['label']}</b>  |  Department: {dept}  |  "
            f"Status: <b style='color:{'green' if status == 'OPEN' else 'grey'}'>{status}</b>"
        )

        is_open = (status == 'OPEN')
        self.scan_input.setEnabled(is_open)
        self.qty_input.setEnabled(is_open)

        counts = stocktake_model.get_counts(self.session_id)
        self.table.setRowCount(0)
        total_lines = 0
        total_variance = 0

        for c in counts:
            r = self.table.rowCount()
            self.table.insertRow(r)
            soh = float(c['soh_qty'])
            counted = float(c['counted_qty'])
            variance = counted - soh
            total_variance += variance
            total_lines += 1

            self.table.setItem(r, 0, QTableWidgetItem(c['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(c['description']))
            self.table.setItem(r, 2, QTableWidgetItem(c['dept_name'] or ''))

            soh_item = QTableWidgetItem(f"{soh:.0f}")
            soh_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, soh_item)

            counted_item = QTableWidgetItem(f"{counted:.0f}")
            counted_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, counted_item)

            var_item = QTableWidgetItem(f"{variance:+.0f}")
            var_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if variance > 0:
                var_item.setForeground(Qt.GlobalColor.green)
            elif variance < 0:
                var_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(r, 5, var_item)

            self.table.setItem(r, 6, QTableWidgetItem(str(c['scanned_at'])[:16]))
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, c['id'])

        sign = "+" if total_variance >= 0 else ""
        self.summary_label.setText(
            f"<b>Lines: {total_lines}  |  Total Variance: {sign}{total_variance:.0f} units</b>"
        )

        if is_open:
            self.scan_input.setFocus()

    # ── Import ────────────────────────────────────────────────────────────────

    def _import_csv(self):
        if self._session['status'] != 'OPEN':
            QMessageBox.information(self, "Closed", "This session is already closed.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import CSV", os.path.expanduser("~"),
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            imported, skipped, errors = stocktake_model.import_from_csv(
                self.session_id, path
            )
            self._show_import_result(imported, skipped, errors, path)
            self._load()
        except Exception as e:
            show_error(self, "Could not import stocktake from CSV.", e, title="Import Failed")

    def _import_sqlite(self):
        if self._session['status'] != 'OPEN':
            QMessageBox.information(self, "Closed", "This session is already closed.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SQLite Database", os.path.expanduser("~"),
            "SQLite Files (*.db *.sqlite *.sqlite3);;All Files (*)"
        )
        if not path:
            return
        try:
            imported, skipped, errors = stocktake_model.import_from_sqlite(
                self.session_id, path
            )
            self._show_import_result(imported, skipped, errors, path)
            self._load()
        except Exception as e:
            show_error(self, "Could not import stocktake from database file.", e, title="Import Failed")

    def _show_import_result(self, imported, skipped, errors, path):
        import os
        fname = os.path.basename(path)
        msg = f"Import complete from: {fname}\n\n"
        msg += f"  ✓ Imported:  {imported}\n"
        msg += f"  ⚠ Skipped:   {skipped}\n"
        if errors:
            msg += f"\nFirst {min(10, len(errors))} issues:\n"
            for e in errors[:10]:
                msg += f"  • {e}\n"
            if len(errors) > 10:
                msg += f"  ... and {len(errors) - 10} more."
        self.import_status.setText(f"Last import: {imported} in, {skipped} skipped")
        QMessageBox.information(self, "Import Result", msg)

    # ── Manual scan ───────────────────────────────────────────────────────────

    def _on_scan(self):
        barcode = self.scan_input.text().strip()
        if not barcode:
            return
        product = product_model.get_by_barcode(barcode)
        if not product:
            self.scan_status.setText(f"⚠  Barcode not found: {barcode}")
            self.scan_input.selectAll()
            return
        qty = int(self.qty_input.value())
        stocktake_model.upsert_count(self.session_id, barcode, qty)
        self.scan_status.setText(
            f"✓  {product['description']}  —  counted: {qty}"
        )
        self.scan_input.clear()
        self.qty_input.setValue(1)
        self._load()
        self.scan_input.setFocus()

    # ── Variance Report ───────────────────────────────────────────────────────

    def _open_variance_report(self):
        from views.stocktake.variance_report import VarianceReport
        self.variance_win = VarianceReport(
            session_id=self.session_id,
            session_label=self._session['label'],
            on_apply=self._on_applied,
        )
        self.variance_win.show()

    def _on_applied(self):
        self._load()
        if self.on_close:
            self.on_close()

    # ── Edit / Remove ─────────────────────────────────────────────────────────

    def _edit_count(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Edit", "Select a line first.")
            return
        barcode = self.table.item(row, 0).text()
        desc = self.table.item(row, 1).text()
        current_qty = float(self.table.item(row, 4).text())

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit Count — {desc}")
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        inp = QDoubleSpinBox()
        inp.setMinimum(0)
        inp.setMaximum(999999)
        inp.setDecimals(0)
        inp.setValue(current_qty)
        form.addRow("Counted Qty", inp)
        layout.addLayout(form)
        btns = QHBoxLayout()
        ok = QPushButton("Save  [Ctrl+S]")
        ok.setFixedHeight(32)
        cancel = QPushButton("Cancel  [Esc]")
        cancel.setFixedHeight(32)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        from PyQt6.QtGui import QShortcut, QKeySequence
        result = [False]
        def confirm():
            result[0] = True
            dlg.accept()
        ok.clicked.connect(confirm)
        cancel.clicked.connect(dlg.reject)
        QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
        QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
        inp.setFocus()
        if dlg.exec() and result[0]:
            stocktake_model.upsert_count(self.session_id, barcode, int(inp.value()))
            self._load()

    def _remove_line(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove", "Select a line first.")
            return
        count_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        desc = self.table.item(row, 1).text()
        reply = QMessageBox.question(self, "Confirm", f"Remove count for:\n{desc}?")
        if reply == QMessageBox.StandardButton.Yes:
            stocktake_model.delete_count(count_id)
            self._load()

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _apply_session(self):
        if self._session['status'] != 'OPEN':
            QMessageBox.information(self, "Closed", "This session is already closed.")
            return
        count = self.table.rowCount()
        if count == 0:
            QMessageBox.warning(self, "Empty", "No counts to apply.")
            return
        reply = QMessageBox.question(
            self, "Review First?",
            f"You have {count} count(s) ready.\n\n"
            "It is recommended to review the Variance Report before applying.\n"
            "Open Variance Report now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._open_variance_report()
        else:
            self._do_apply(count)

    def _do_apply(self, count):
        reply = QMessageBox.question(
            self, "Apply Stocktake",
            f"Apply {count} count(s) to stock on hand?\n\n"
            "This will update stock quantities to counted values "
            "and close the session. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                stocktake_model.apply_session(self.session_id)
                QMessageBox.information(
                    self, "Complete",
                    f"Stocktake applied. {count} product(s) updated."
                )
                self._load()
                if self.on_close:
                    self.on_close()
            except Exception as e:
                show_error(self, "Could not apply stocktake counts.", e)


import os
