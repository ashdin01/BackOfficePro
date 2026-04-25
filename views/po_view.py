from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QMessageBox, QLabel,
    QDoubleSpinBox, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QAbstractItemView, QSplitter,
    QGroupBox, QScrollArea, QCheckBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor
import models.purchase_order as po_model
import models.po_lines as line_model
import models.product as prod_model
import models.supplier as sup_model
import models.stock_on_hand as soh_model
from config.constants import PO_STATUS_COLOURS
from views.widgets import (
    page_header, primary_btn, danger_btn, success_btn, warning_btn,
    make_table, table_item, money_item
)


class ItemLookupDialog(QDialog):
    """
    Modal item lookup — lists all products pre-sorted by supplier name.
    Double-click or press OK to select an item and populate the add-line fields.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Item Lookup")
        self.setMinimumSize(800, 520)
        self.selected = None          # dict set on accept

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Search bar ──────────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by supplier, barcode or description…")
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(500)
        self._filter_timer.timeout.connect(lambda: self._filter(self.search_input.text()))
        self.search_input.textChanged.connect(lambda _: self._filter_timer.start())
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        # ── Table ────────────────────────────────────────────────────────────
        self.table = make_table(
            ["Supplier", "Barcode", "Description", "Cost Price"],
            stretch_col=2
        )
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(3, 100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_products()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load_products(self):
        """Load all products joined with supplier, sorted by supplier name."""
        raw = prod_model.get_all()          # existing model call
        suppliers = {s["id"]: s["name"] for s in sup_model.get_all()}

        self._all_rows = sorted(
            [
                {
                    "supplier":    suppliers.get(p.get("supplier_id"), ""),
                    "barcode":     p.get("barcode", ""),
                    "description": p.get("description", ""),
                    "cost_price":  p.get("cost_price") or 0.0,
                }
                for p in raw
            ],
            key=lambda r: (r["supplier"].lower(), r["description"].lower())
        )
        self._populate(self._all_rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, table_item(r["supplier"]))
            self.table.setItem(row, 1, table_item(r["barcode"]))
            self.table.setItem(row, 2, table_item(r["description"]))
            self.table.setItem(row, 3, money_item(r["cost_price"]))

    def _filter(self, text):
        text = text.lower()
        filtered = [
            r for r in self._all_rows
            if (text in r["supplier"].lower()
                or text in r["barcode"].lower()
                or text in r["description"].lower())
        ]
        self._populate(filtered)

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _row_data(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return {
            "barcode":     self.table.item(row, 1).text(),
            "description": self.table.item(row, 2).text(),
            "cost_price":  float(self.table.item(row, 3).text().replace("$", "").replace(",", "") or 0),
        }

    def _on_accept(self):
        data = self._row_data()
        if data is None:
            QMessageBox.warning(self, "No selection", "Please select an item first.")
            return
        self.selected = data
        self.accept()

    def _on_double_click(self):
        self._on_accept()


class POView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        header_row.addWidget(page_header("Purchase Orders", "Create and manage orders to suppliers"))
        header_row.addStretch()
        new_btn = primary_btn("＋  New Purchase Order")
        new_btn.clicked.connect(self.new_po)
        header_row.addWidget(new_btn)
        layout.addLayout(header_row)

        # Status filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["ALL", "DRAFT", "SENT", "PARTIAL", "RECEIVED", "CANCELLED"])
        self.status_filter.currentIndexChanged.connect(self.load)
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Table
        self.table = make_table(
            ["PO Number", "Supplier", "Status", "Delivery Date", "Lines", "Total", "Created", "Actions"],
            stretch_col=1
        )
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 50)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 190)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

        self._po_list = []
        self.load()

    def load(self):
        status = self.status_filter.currentText()
        self._po_list = po_model.get_all(status if status != "ALL" else None)
        self.table.setRowCount(len(self._po_list))
        for row, po in enumerate(self._po_list):
            total = line_model.po_total(po["id"])
            status_colour = PO_STATUS_COLOURS.get(po["status"], "#888888")

            self.table.setItem(row, 0, table_item(po["po_number"]))
            self.table.setItem(row, 1, table_item(po.get("supplier_name", "")))

            status_item = QTableWidgetItem(po["status"])
            status_item.setForeground(QColor(status_colour))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 2, status_item)

            self.table.setItem(row, 3, table_item(po.get("delivery_date", "") or ""))
            self.table.setItem(row, 4, table_item(str(po.get("line_count", 0)), Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(row, 5, money_item(total))
            self.table.setItem(row, 6, table_item((po.get("created_at") or "")[:10]))

            btn_w = QWidget()
            btn_l = QHBoxLayout(btn_w)
            btn_l.setContentsMargins(4, 2, 4, 2)
            btn_l.setSpacing(4)

            view_btn = primary_btn("View")
            view_btn.setFixedWidth(55)
            view_btn.clicked.connect(lambda _, pid=po["id"]: self.view_po(pid))
            btn_l.addWidget(view_btn)

            if po["status"] == "DRAFT":
                send_btn = warning_btn("Send")
                send_btn.setFixedWidth(50)
                send_btn.clicked.connect(lambda _, pid=po["id"]: self.change_status(pid, "SENT"))
                btn_l.addWidget(send_btn)

                del_btn = danger_btn("Del")
                del_btn.setFixedWidth(40)
                del_btn.clicked.connect(lambda _, pid=po["id"]: self.delete_po(pid))
                btn_l.addWidget(del_btn)

            elif po["status"] in ("SENT", "PARTIAL"):
                recv_btn = success_btn("Receive")
                recv_btn.setFixedWidth(70)
                recv_btn.clicked.connect(lambda _, pid=po["id"]: self.receive_po(pid))
                btn_l.addWidget(recv_btn)

            self.table.setCellWidget(row, 7, btn_w)

    def _on_double_click(self, index):
        if index.row() < len(self._po_list):
            self.view_po(self._po_list[index.row()]["id"])

    def new_po(self):
        dlg = POCreateDialog(self)
        if dlg.exec():
            po_id, po_number = po_model.create(
                dlg.supplier.currentData(),
                dlg.delivery_date.date().toString("yyyy-MM-dd") if not dlg.no_date.isChecked() else None,
                dlg.notes.toPlainText().strip()
            )
            self.load()
            self.view_po(po_id)

    def view_po(self, po_id):
        dlg = PODetailDialog(self, po_id)
        dlg.exec()
        self.load()

    def receive_po(self, po_id):
        dlg = POReceiveDialog(self, po_id)
        if dlg.exec():
            self.load()

    def change_status(self, po_id, status):
        if QMessageBox.question(self, "Confirm", f"Mark this PO as {status}?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            po_model.update_status(po_id, status)
            self.load()

    def delete_po(self, po_id):
        if QMessageBox.question(self, "Confirm", "Delete this draft PO?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            po_model.delete_draft(po_id)
            self.load()


class POCreateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Purchase Order")
        self.setFixedWidth(400)
        layout = QFormLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        self.supplier = QComboBox()
        for s in sup_model.get_all():
            self.supplier.addItem(s["name"], s["id"])

        self.delivery_date = QDateEdit()
        self.delivery_date.setDate(QDate.currentDate().addDays(7))
        self.delivery_date.setCalendarPopup(True)
        self.no_date = QCheckBox("No expected date")
        self.no_date.toggled.connect(lambda c: self.delivery_date.setEnabled(not c))

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(70)

        layout.addRow("Supplier *", self.supplier)
        layout.addRow("Expected Delivery", self.delivery_date)
        layout.addRow("", self.no_date)
        layout.addRow("Notes", self.notes)

        btn_row = QHBoxLayout()
        cancel = primary_btn("Cancel")
        cancel.setProperty("class", "")
        cancel.clicked.connect(self.reject)
        create = primary_btn("Create PO")
        create.clicked.connect(self._validate)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(create)
        layout.addRow(btn_row)

    def _validate(self):
        if self.supplier.currentData() is None:
            QMessageBox.warning(self, "Required", "Please select a supplier.")
            return
        self.accept()


class PODetailDialog(QDialog):
    def __init__(self, parent, po_id):
        super().__init__(parent)
        self.po_id = po_id
        self.setWindowTitle("Purchase Order")
        self.setMinimumSize(820, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        po = po_model.get_by_id(po_id)
        if not po:
            return
        self._supplier_id = po['supplier_id']

        # PO header info
        info = QLabel(
            f"<b>{po['po_number']}</b> &nbsp;|&nbsp; "
            f"{po.get('supplier_name','')} &nbsp;|&nbsp; "
            f"<span style='color:{PO_STATUS_COLOURS.get(po['status'],'#888')}'>"
            f"{po['status']}</span>"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # Lines table
        self.lines_table = make_table(
            ["Barcode", "Description", "Ordered Qty", "Received", "Unit Cost", "Line Total", "Notes", ""],
            stretch_col=1
        )
        self.lines_table.setColumnWidth(0, 120)
        self.lines_table.setColumnWidth(2, 90)
        self.lines_table.setColumnWidth(3, 80)
        self.lines_table.setColumnWidth(4, 90)
        self.lines_table.setColumnWidth(5, 90)
        self.lines_table.setColumnWidth(7, 40)
        layout.addWidget(self.lines_table)

        # Add line section (only for DRAFT)
        if po["status"] == "DRAFT":
            add_group = QGroupBox("Add Line Item")
            add_layout = QHBoxLayout(add_group)
            self.prod_search = QLineEdit()
            self.prod_search.setPlaceholderText("Type barcode or product name…")
            self.prod_combo = QComboBox()
            self.prod_combo.setMinimumWidth(280)
            self._load_products()
            self._prod_filter_timer = QTimer()
            self._prod_filter_timer.setSingleShot(True)
            self._prod_filter_timer.setInterval(500)
            self._prod_filter_timer.timeout.connect(lambda: self._filter_products(self.prod_search.text()))
            self.prod_search.textChanged.connect(lambda _: self._prod_filter_timer.start())
            self.add_qty = QDoubleSpinBox()
            self.add_qty.setRange(0.1, 99999)
            self.add_qty.setValue(1)
            self.add_qty.setDecimals(1)
            self.add_cost = QDoubleSpinBox()
            self.add_cost.setPrefix("$ ")
            self.add_cost.setRange(0, 99999)
            self.add_cost.setDecimals(2)
            self.prod_combo.currentIndexChanged.connect(self._auto_fill_cost)
            add_line_btn = success_btn("Add")
            add_line_btn.clicked.connect(self._add_line)
            lookup_btn = primary_btn("🔍 Lookup")
            lookup_btn.setFixedWidth(90)
            lookup_btn.clicked.connect(self._open_lookup)
            add_layout.addWidget(QLabel("Product:"))
            add_layout.addWidget(self.prod_search)
            add_layout.addWidget(self.prod_combo)
            add_layout.addWidget(lookup_btn)
            add_layout.addWidget(QLabel("Qty:"))
            add_layout.addWidget(self.add_qty)
            add_layout.addWidget(QLabel("Cost:"))
            add_layout.addWidget(self.add_cost)
            add_layout.addWidget(add_line_btn)
            layout.addWidget(add_group)

        # Total label
        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        # Buttons
        btn_row = QHBoxLayout()
        close_btn = primary_btn("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._reload_lines()

    def _load_products(self):
        import models.product_suppliers as ps_model
        self._all_products = list(ps_model.get_by_supplier(self._supplier_id, default_only=True))
        self.prod_combo.clear()
        for p in self._all_products:
            self.prod_combo.addItem(f"{p['barcode']} — {p['description']}", p["barcode"])

    def _open_lookup(self):
        """Open the item lookup dialog and populate the add-line fields."""
        dlg = ItemLookupDialog(self)
        if dlg.exec() and dlg.selected:
            item = dlg.selected
            # Focus the search box and fill it so the combo filters to this item
            self.prod_search.setText(item["barcode"])
            # Find and select matching entry in combo
            for i in range(self.prod_combo.count()):
                if self.prod_combo.itemData(i) == item["barcode"]:
                    self.prod_combo.setCurrentIndex(i)
                    break
            self.add_cost.setValue(item["cost_price"])

    def _filter_products(self, text):
        self.prod_combo.clear()
        for p in self._all_products:
            if (text.lower() in p["description"].lower() or
                    text in p["barcode"]):
                self.prod_combo.addItem(f"{p['barcode']} — {p['description']}", p["barcode"])

    def _auto_fill_cost(self):
        barcode = self.prod_combo.currentData()
        if barcode:
            p = prod_model.get_by_barcode(barcode)
            if p:
                self.add_cost.setValue(p.get("cost_price") or 0)

    def _add_line(self):
        barcode = self.prod_combo.currentData()
        if not barcode:
            return
        p = prod_model.get_by_barcode(barcode)
        if not p:
            return
        line_model.add_line(
            self.po_id, barcode, p["description"],
            self.add_qty.value(), self.add_cost.value()
        )
        self._reload_lines()

    def _reload_lines(self):
        lines = line_model.get_lines(self.po_id)
        self.lines_table.setRowCount(len(lines))
        total = 0
        for row, ln in enumerate(lines):
            line_total = ln["ordered_qty"] * ln["unit_cost"]
            total += line_total
            self.lines_table.setItem(row, 0, table_item(ln["barcode"]))
            self.lines_table.setItem(row, 1, table_item(ln["description"]))
            self.lines_table.setItem(row, 2, table_item(f"{ln['ordered_qty']:.1f}", Qt.AlignmentFlag.AlignCenter))
            self.lines_table.setItem(row, 3, table_item(f"{ln['received_qty']:.1f}", Qt.AlignmentFlag.AlignCenter))
            self.lines_table.setItem(row, 4, money_item(ln["unit_cost"]))
            self.lines_table.setItem(row, 5, money_item(line_total))
            self.lines_table.setItem(row, 6, table_item(ln.get("notes", "")))

            del_btn = danger_btn("×")
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, lid=ln["id"]: self._delete_line(lid))
            self.lines_table.setCellWidget(row, 7, del_btn)

        self.total_label.setText(f"<b>Total: ${total:.2f}</b>")

    def _delete_line(self, line_id):
        line_model.delete_line(line_id)
        self._reload_lines()


class POReceiveDialog(QDialog):
    def __init__(self, parent, po_id):
        super().__init__(parent)
        self.po_id = po_id
        self.setWindowTitle("Receive Stock")
        self.setMinimumSize(700, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        po = po_model.get_by_id(po_id)
        layout.addWidget(QLabel(f"<b>Receiving: {po['po_number']}</b> — {po.get('supplier_name','')}"))
        layout.addWidget(QLabel("Enter received quantities for each line. Leave 0 if not received."))

        self.lines_table = make_table(
            ["Barcode", "Description", "Ordered", "Enter Received Qty"], stretch_col=1
        )
        self.lines_table.setColumnWidth(0, 120)
        self.lines_table.setColumnWidth(2, 80)
        self.lines_table.setColumnWidth(3, 160)
        layout.addWidget(self.lines_table)

        lines = line_model.get_lines(po_id)
        self.line_spinboxes = {}
        self.lines_table.setRowCount(len(lines))
        for row, ln in enumerate(lines):
            self.lines_table.setItem(row, 0, table_item(ln["barcode"]))
            self.lines_table.setItem(row, 1, table_item(ln["description"]))
            self.lines_table.setItem(row, 2, table_item(f"{ln['ordered_qty']:.1f}", Qt.AlignmentFlag.AlignCenter))
            spin = QDoubleSpinBox()
            spin.setRange(0, 99999)
            spin.setDecimals(1)
            spin.setValue(ln["ordered_qty"])
            self.lines_table.setCellWidget(row, 3, spin)
            self.line_spinboxes[ln["id"]] = (spin, ln["barcode"], ln["unit_cost"])

        btn_row = QHBoxLayout()
        cancel = primary_btn("Cancel")
        cancel.setProperty("class", "")
        cancel.clicked.connect(self.reject)
        confirm = success_btn("Confirm Receipt & Update Stock")
        confirm.clicked.connect(self._confirm)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(confirm)
        layout.addLayout(btn_row)

    def _confirm(self):
        po = po_model.get_by_id(self.po_id)
        all_received = True
        any_received = False
        for line_id, (spin, barcode, unit_cost) in self.line_spinboxes.items():
            qty = spin.value()
            if qty > 0:
                any_received = True
                line_model.receive_line(line_id, qty)
                soh_model.adjust(
                    barcode, qty, "RECEIPT",
                    reference=po["po_number"],
                    notes=f"Received via {po['po_number']}"
                )
                # Update cost price on product
                prod = prod_model.get_by_barcode(barcode)
                if prod:
                    data = dict(prod)
                    data["cost_price"] = unit_cost
                    prod_model.update(barcode, data)
            lines = line_model.get_lines(self.po_id)
            for ln in lines:
                if ln["received_qty"] < ln["ordered_qty"]:
                    all_received = False

        new_status = "RECEIVED" if all_received else "PARTIAL"
        po_model.update_status(self.po_id, new_status)
        QMessageBox.information(self, "Done", f"Stock updated. PO marked as {new_status}.")
        self.accept()
