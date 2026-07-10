import os
import subprocess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QLineEdit, QMessageBox, QDialog, QFormLayout, QDoubleSpinBox,
    QSpinBox, QDialogButtonBox, QTextEdit, QFrame, QSplitter,
    QAbstractItemView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import controllers.ar_controller as ar_ctrl
import controllers.product_controller as product_ctrl
import config.styles as styles
from utils.error_dialog import show_error
from utils.text_search import matches_all_words
from views.base_view import BaseView, BaseDialog
from views.widgets.search_bar import SearchBar


class _CustomerLookup(QDialog):
    """F3-style popup for actively picking a customer.

    No dropdown, no default selection — mirrors
    views.purchase_orders.po_create._SupplierLookup so an invoice can't be
    raised against whichever customer happens to sort first.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Customer")
        self.setModal(True)
        self.setFixedSize(420, 460)
        self.setStyleSheet(
            f"QDialog{{background:{styles.CLR_BG};color:{styles.CLR_TEXT};}}"
            f"QTableWidget{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};"
            f"gridline-color:{styles.CLR_BORDER};border:1px solid {styles.CLR_BORDER};}}"
            f"QTableWidget::item:selected{{background:{styles.CLR_ACCENT};}}"
            f"QHeaderView::section{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_MUTED};"
            "border:none;padding:4px 8px;font-weight:bold;}"
        )
        self.selected_id = None
        self.selected_name = None
        self._all_customers = ar_ctrl.get_all_customers(active_only=True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lbl = QLabel("Type to search, then double-click or press Enter:")
        lbl.setStyleSheet(styles.STYLE_LABEL_MUTED)
        lay.addWidget(lbl)

        self.search = SearchBar("Search customers by name or code…", interval=150)
        self.search.search_changed.connect(self._filter)
        lay.addWidget(self.search)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Code", "Name"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._pick)
        self._render(self._all_customers)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Select  [Enter]")
        btn_ok.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:6px 16px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}")
        btn_cancel = QPushButton("Cancel  [Esc]")
        btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{styles.CLR_MUTED};"
            f"border:1px solid {styles.CLR_BORDER};border-radius:4px;padding:6px 14px;}}"
            f"QPushButton:hover{{background:{styles.CLR_BG_PANEL};color:{styles.CLR_TEXT};}}")
        btn_ok.clicked.connect(self._pick)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        QShortcut(QKeySequence("Return"), self, self._pick)
        QShortcut(QKeySequence("Enter"),  self, self._pick)
        QShortcut(QKeySequence("Escape"), self, self.reject)

        self.search.setFocus()

    def _filter(self):
        term = self.search.text()
        rows = [c for c in self._all_customers
                if matches_all_words(term, c['name'], c['code'])]
        self._render(rows)

    def _render(self, rows):
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            code_item = QTableWidgetItem(c['code'])
            code_item.setData(Qt.ItemDataRole.UserRole, c['id'])
            self.table.setItem(r, 0, code_item)
            self.table.setItem(r, 1, QTableWidgetItem(c['name']))
        if rows:
            self.table.selectRow(0)

    def _pick(self):
        row = self.table.currentRow()
        if row >= 0:
            self.selected_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.selected_name = self.table.item(row, 1).text()
            self.accept()


class InvoiceDetail(BaseView):
    def __init__(self, invoice_id=None, on_saved=None):
        super().__init__()
        self._id       = invoice_id
        self._on_saved = on_saved
        self._inv      = None
        self.setWindowFlags(Qt.WindowType.Window)
        self.setMinimumSize(1000, 700)
        self._build_ui()
        if invoice_id:
            self.load()
        else:
            self._new_invoice_dialog()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        self.lbl_title = QLabel("Invoice")
        self.lbl_title.setStyleSheet("font-size:14px; font-weight:bold;")
        toolbar.addWidget(self.lbl_title)
        toolbar.addStretch()

        self.btn_add_line = QPushButton("&Add Line")
        self.btn_add_line.clicked.connect(self._add_line)
        toolbar.addWidget(self.btn_add_line)

        self.btn_payment = QPushButton("Record &Payment")
        self.btn_payment.clicked.connect(self._record_payment)
        toolbar.addWidget(self.btn_payment)

        self.btn_credit = QPushButton("Credit Note")
        self.btn_credit.clicked.connect(self._credit_note)
        toolbar.addWidget(self.btn_credit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(['DRAFT', 'SENT', 'PARTIAL', 'PAID', 'VOID'])
        self.status_combo.currentTextChanged.connect(self._status_changed)
        toolbar.addWidget(QLabel("Status:"))
        toolbar.addWidget(self.status_combo)

        self.btn_pdf = QPushButton("Print / PDF")
        self.btn_pdf.clicked.connect(self._export_pdf)
        toolbar.addWidget(self.btn_pdf)

        root.addLayout(toolbar)

        # ── Invoice header info ───────────────────────────────────────
        info = QHBoxLayout()
        self.lbl_customer  = QLabel("Customer: —")
        self.lbl_dates     = QLabel("")
        self.lbl_due       = QLabel("")
        self.lbl_balance   = QLabel("")
        for lbl in (self.lbl_customer, self.lbl_dates, self.lbl_due, self.lbl_balance):
            lbl.setStyleSheet(f"color: {styles.CLR_MUTED}; font-size: 11px;")
            info.addWidget(lbl)
        info.addStretch()
        root.addLayout(info)

        # ── Notes ─────────────────────────────────────────────────────
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Invoice notes…")
        self.notes_edit.editingFinished.connect(self._save_notes)
        root.addWidget(self.notes_edit)

        # ── Lines table ───────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Description", "Qty", "Unit Price", "Disc %",
            "GST Rate", "Subtotal", "GST", "Total",
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_line)
        root.addWidget(self.table)

        # ── Totals ────────────────────────────────────────────────────
        totals = QHBoxLayout()
        totals.addStretch()
        self.lbl_subtotal  = QLabel("Subtotal: $0.00")
        self.lbl_gst       = QLabel("GST: $0.00")
        self.lbl_total     = QLabel("TOTAL: $0.00")
        self.lbl_paid      = QLabel("Paid: $0.00")
        self.lbl_owing     = QLabel("OWING: $0.00")
        self.lbl_total.setStyleSheet("font-weight:bold; font-size:13px;")
        self.lbl_owing.setStyleSheet("font-weight:bold; font-size:13px; color:#e65100;")
        for w in (self.lbl_subtotal, self.lbl_gst, self.lbl_total,
                  self.lbl_paid, self.lbl_owing):
            totals.addWidget(w)
            totals.addSpacing(16)
        root.addLayout(totals)

        # ── Payments list ─────────────────────────────────────────────
        self.payments_tbl = QTableWidget()
        self.payments_tbl.setColumnCount(5)
        self.payments_tbl.setHorizontalHeaderLabels(
            ["Date", "Amount", "Method", "Reference", "Notes"]
        )
        self.payments_tbl.setMaximumHeight(130)
        self.payments_tbl.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(QLabel("Payments:"))
        root.addWidget(self.payments_tbl)

        # ── Shortcuts ─────────────────────────────────────────────────
        QShortcut(QKeySequence("Ctrl+Return"), self, self._add_line)
        QShortcut(QKeySequence("Delete"),      self, self._delete_line)

    def _new_invoice_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("New Invoice")
        dlg.setMinimumWidth(360)
        form = QFormLayout(dlg)

        self._new_inv_customer_id = None

        cust_row = QHBoxLayout()
        cust_lbl = QLabel("⚠  No customer selected")
        cust_lbl.setStyleSheet(f"color:{styles.CLR_DANGER};font-weight:bold;")
        cust_row.addWidget(cust_lbl, 1)
        cust_btn = QPushButton("Select…")
        cust_row.addWidget(cust_btn)
        cust_container = QWidget()
        cust_container.setLayout(cust_row)
        form.addRow("Customer *", cust_container)

        notes_edit = QLineEdit()
        form.addRow("Notes", notes_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(False)  # stays disabled until a customer is actively picked

        def _pick_customer():
            pick_dlg = _CustomerLookup(dlg)
            if pick_dlg.exec() == QDialog.DialogCode.Accepted and pick_dlg.selected_id:
                self._new_inv_customer_id = pick_dlg.selected_id
                cust_lbl.setText(f"✓  {pick_dlg.selected_name}")
                cust_lbl.setStyleSheet(f"color:{styles.CLR_TEXT};font-weight:bold;")
                ok_btn.setEnabled(True)

        cust_btn.clicked.connect(_pick_customer)

        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.close()
            return

        if not self._new_inv_customer_id:
            # Defensive only — OK is disabled until a customer is picked,
            # so this path shouldn't be reachable, but a billing record is
            # not something to create on an unproven assumption.
            self.close()
            return

        try:
            inv_id, inv_num = ar_ctrl.create_invoice(
                customer_id=self._new_inv_customer_id,
                notes=notes_edit.text().strip(),
            )
        except Exception as e:
            show_error(self, "Could not create invoice.", e)
            self.close()
            return

        self._id = inv_id
        self.load()
        if self._on_saved:
            self._on_saved()

    def _load(self):
        self._inv = ar_ctrl.get_invoice_by_id(self._id)
        if not self._inv:
            return
        inv = self._inv
        self.setWindowTitle(f"Invoice {inv['invoice_number']}")
        self.lbl_title.setText(f"Invoice {inv['invoice_number']}")
        self.lbl_customer.setText(f"Customer: {inv['customer_name']}")
        self.lbl_dates.setText(f"Date: {inv['invoice_date']}")
        self.lbl_due.setText(f"Due: {inv['due_date']}")
        self.notes_edit.setText(inv.get('notes', '') or '')

        self.status_combo.blockSignals(True)
        self.status_combo.setCurrentText(inv['status'])
        self.status_combo.blockSignals(False)

        editable = inv['status'] in ('DRAFT',)
        self.btn_add_line.setEnabled(editable)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self._load_lines()
        self._load_payments()
        self._refresh_totals()

    def _load_lines(self):
        lines = ar_ctrl.get_invoice_lines(self._id)
        self.table.setRowCount(len(lines))
        for i, ln in enumerate(lines):
            vals = [
                ln['description'],
                f"{ln['quantity']:g}",
                f"${ln['unit_price']:.2f}",
                f"{ln['discount_pct']:g}%" if ln['discount_pct'] else '—',
                f"{ln['gst_rate']:g}%",
                f"${ln['line_subtotal']:.2f}",
                f"${ln['line_gst']:.2f}",
                f"${ln['line_total']:.2f}",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, ln['id'])
                self.table.setItem(i, j, item)

    def _load_payments(self):
        payments = ar_ctrl.get_payments_by_invoice(self._id)
        self.payments_tbl.setRowCount(len(payments))
        for i, p in enumerate(payments):
            for j, v in enumerate([
                p['payment_date'], f"${p['amount']:.2f}",
                p['method'], p['reference'] or '', p['notes'] or ''
            ]):
                self.payments_tbl.setItem(i, j, QTableWidgetItem(str(v)))

    def _refresh_totals(self):
        if not self._inv:
            return
        inv     = ar_ctrl.get_invoice_by_id(self._id)
        total   = float(inv['total'])
        paid    = float(inv['amount_paid'])
        balance = round(total - paid, 2)
        self.lbl_subtotal.setText(f"Subtotal: ${float(inv['subtotal']):.2f}")
        self.lbl_gst.setText(f"GST: ${float(inv['gst_amount']):.2f}")
        self.lbl_total.setText(f"TOTAL: ${total:.2f}")
        self.lbl_paid.setText(f"Paid: ${paid:.2f}")
        self.lbl_owing.setText(f"OWING: ${balance:.2f}")
        colour = styles.CLR_SUCCESS_DARK if balance <= 0 else "#e65100"
        self.lbl_owing.setStyleSheet(f"font-weight:bold; font-size:13px; color:{colour};")
        self.lbl_balance.setText(f"Balance: ${balance:.2f}")

    def _add_line(self):
        if not self._id:
            return
        dlg = _LineDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.data()
            ar_ctrl.add_invoice_line(
                invoice_id=self._id,
                description=d['description'],
                quantity=d['quantity'],
                unit_price=d['unit_price'],
                discount_pct=d['discount_pct'],
                gst_rate=d['gst_rate'],
                barcode=d['barcode'],
            )
            self._load_lines()
            self._refresh_totals()
            if self._on_saved:
                self._on_saved()

    def _edit_line(self):
        if not self._inv or self._inv['status'] != 'DRAFT':
            return
        row = self.table.currentRow()
        if row < 0:
            return
        line_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        lines   = ar_ctrl.get_invoice_lines(self._id)
        ln      = next((l for l in lines if l['id'] == line_id), None)
        if not ln:
            return
        dlg = _LineDialog(parent=self, line=ln)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.data()
            ar_ctrl.update_invoice_line(
                line_id=line_id,
                description=d['description'],
                quantity=d['quantity'],
                unit_price=d['unit_price'],
                discount_pct=d['discount_pct'],
                gst_rate=d['gst_rate'],
                barcode=d['barcode'],
            )
            self._load_lines()
            self._refresh_totals()
            if self._on_saved:
                self._on_saved()

    def _delete_line(self):
        if not self._inv or self._inv['status'] != 'DRAFT':
            return
        row = self.table.currentRow()
        if row < 0:
            return
        line_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(
            self, "Delete Line", "Remove this line?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            ar_ctrl.delete_invoice_line(line_id)
            self._load_lines()
            self._refresh_totals()
            if self._on_saved:
                self._on_saved()

    def _status_changed(self, status):
        if not self._id:
            return
        ar_ctrl.update_invoice_status(self._id, status)
        self.load()
        if self._on_saved:
            self._on_saved()

    def _save_notes(self):
        if self._id:
            ar_ctrl.update_invoice_notes(self._id, self.notes_edit.text().strip())

    def _record_payment(self):
        if not self._inv:
            return
        from views.ar.payment_dialog import PaymentDialog
        dlg = PaymentDialog(invoice=self._inv, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.data()
            ar_ctrl.record_payment(
                invoice_id=self._id,
                amount=d['amount'],
                payment_date=d['date'],
                method=d['method'],
                reference=d['reference'],
                notes=d['notes'],
            )
            self.load()
            if self._on_saved:
                self._on_saved()

    def _credit_note(self):
        if not self._inv:
            return
        from views.ar.credit_note_detail import CreditNoteDetail
        w = CreditNoteDetail(
            customer_id=self._inv['customer_id'],
            linked_invoice_id=self._id,
        )
        w.show()

    def _export_pdf(self):
        if not self._id:
            return
        try:
            path = ar_ctrl.generate_invoice_pdf(self._id)
            QMessageBox.information(self, "PDF Saved", f"Saved to:\n{path}")
            os.startfile(path) if os.name == 'nt' else subprocess.Popen(['xdg-open', path])
        except Exception as e:
            show_error(self, "Could not generate PDF.", e, title="PDF Error")


class _LineDialog(QDialog):
    def __init__(self, parent=None, line=None):
        super().__init__(parent)
        self.setWindowTitle("Add Line" if line is None else "Edit Line")
        self.setMinimumWidth(460)
        self._line = line
        self._build_ui()
        if line:
            self._populate(line)

    def _build_ui(self):
        form = QFormLayout(self)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode — Enter to lookup, F2 to browse")
        self.barcode.returnPressed.connect(self._lookup_barcode)

        lookup_btn = QPushButton("🔍")
        lookup_btn.setFixedWidth(32)
        lookup_btn.setToolTip("Browse all products  [F2]")
        lookup_btn.clicked.connect(self._open_picker)

        bc_row = QWidget()
        bc_layout = QHBoxLayout(bc_row)
        bc_layout.setContentsMargins(0, 0, 0, 0)
        bc_layout.setSpacing(4)
        bc_layout.addWidget(self.barcode)
        bc_layout.addWidget(lookup_btn)
        form.addRow("Barcode", bc_row)

        QShortcut(QKeySequence("F2"), self, self._open_picker)

        self.description = QLineEdit()
        form.addRow("Description *", self.description)

        self.qty = QDoubleSpinBox()
        self.qty.setRange(0.001, 99999)
        self.qty.setDecimals(3)
        self.qty.setValue(1.0)
        form.addRow("Quantity *", self.qty)

        self.unit_price = QDoubleSpinBox()
        self.unit_price.setRange(0, 9999999)
        self.unit_price.setDecimals(4)
        self.unit_price.setPrefix("$")
        form.addRow("Unit Price *", self.unit_price)

        self.discount = QDoubleSpinBox()
        self.discount.setRange(0, 100)
        self.discount.setDecimals(2)
        self.discount.setSuffix("%")
        form.addRow("Discount", self.discount)

        self.gst_rate = QDoubleSpinBox()
        self.gst_rate.setRange(0, 100)
        self.gst_rate.setDecimals(1)
        self.gst_rate.setValue(10.0)
        self.gst_rate.setSuffix("%")
        form.addRow("GST Rate", self.gst_rate)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _populate(self, ln):
        self.barcode.setText(ln.get('barcode', '') or '')
        self.description.setText(ln['description'])
        self.qty.setValue(float(ln['quantity']))
        self.unit_price.setValue(float(ln['unit_price']))
        self.discount.setValue(float(ln['discount_pct']))
        self.gst_rate.setValue(float(ln['gst_rate']))

    def _lookup_barcode(self):
        bc = self.barcode.text().strip()
        if not bc:
            return
        p = product_ctrl.get_product_by_barcode(bc)
        if p:
            self.description.setText(p['description'])
            self.unit_price.setValue(float(p['sell_price'] or 0))
            self.gst_rate.setValue(float(p['tax_rate']) if p['tax_rate'] is not None else 10.0)

    def _open_picker(self):
        dlg = _ProductPickerDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            p = dlg.selected_product()
            if p:
                self.barcode.setText(p['barcode'] or '')
                self.description.setText(p['description'])
                self.unit_price.setValue(float(p['sell_price'] or 0))
                self.gst_rate.setValue(float(p['tax_rate']) if p['tax_rate'] is not None else 10.0)

    def _accept(self):
        if not self.description.text().strip():
            QMessageBox.warning(self, "Validation", "Description is required.")
            return
        self.accept()

    def data(self):
        return {
            'barcode':     self.barcode.text().strip(),
            'description': self.description.text().strip(),
            'quantity':    self.qty.value(),
            'unit_price':  self.unit_price.value(),
            'discount_pct': self.discount.value(),
            'gst_rate':    self.gst_rate.value(),
        }


class _ProductPickerDialog(BaseDialog):
    """Searchable product browser — opened via 🔍 button or F2."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Product Lookup  [F2]")
        self.setMinimumSize(740, 520)
        self._selected  = None
        self._all_rows  = []
        self._build_ui()
        self.load()

    def _build_ui(self):
        from PyQt6.QtCore import QTimer
        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search description or barcode…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda _: self._timer.start())

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Barcode", "Description", "Sell Price", "GST"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._pick)
        layout.addWidget(self.table)

        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color: grey; font-size: 10px;")
        layout.addWidget(self.lbl_count)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._pick)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        QShortcut(QKeySequence("Return"), self, self._pick)

    def _load(self):
        self._all_rows = [
            {'barcode': p['barcode'], 'description': p['description'],
             'sell_price': p['sell_price'], 'tax_rate': p['tax_rate']}
            for p in product_ctrl.get_all_products(active_only=True)
        ]
        self._render(self._all_rows)
        self.search.setFocus()

    def _filter(self):
        term = self.search.text().strip().lower()
        if not term:
            self._render(self._all_rows)
            return
        rows = [p for p in self._all_rows
                if term in p['description'].lower()
                or term in (p['barcode'] or '').lower()]
        self._render(rows)

    def _render(self, rows):
        self.table.setRowCount(len(rows))
        for i, p in enumerate(rows):
            vals = [
                p['barcode'] or '',
                p['description'],
                f"${float(p['sell_price'] or 0):.2f}",
                f"{float(p['tax_rate'] or 0):g}%",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.table.setItem(i, j, item)
        self.lbl_count.setText(f"{len(rows)} product(s)")
        if rows:
            self.table.selectRow(0)

    def _pick(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self._selected = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_product(self):
        return self._selected
