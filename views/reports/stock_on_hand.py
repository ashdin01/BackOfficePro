from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QLineEdit, QComboBox, QDialog, QFormLayout, QDoubleSpinBox,
    QMessageBox, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
from utils.keyboard_mixin import KeyboardMixin
from database.connection import get_connection
import models.stock_on_hand as stock_model
from config.constants import MOVE_TYPES


def get_stock_levels(search="", dept_id=None, filter_mode="all"):
    conn = get_connection()
    sql = """
        SELECT p.barcode, p.description, d.name as dept_name,
               COALESCE(s.quantity, 0) as quantity,
               p.reorder_point, p.reorder_qty, p.unit, p.cost_price,
               COALESCE(s.quantity, 0) * p.cost_price as stock_value
        FROM products p
        LEFT JOIN departments d ON p.department_id = d.id
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        WHERE p.active = 1
    """
    params = []
    if search:
        sql += " AND (p.description LIKE ? OR p.barcode LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if dept_id:
        sql += " AND p.department_id = ?"
        params.append(dept_id)
    if filter_mode == "low":
        sql += " AND COALESCE(s.quantity, 0) <= p.reorder_point"
    elif filter_mode == "zero":
        sql += " AND COALESCE(s.quantity, 0) = 0"
    sql += " ORDER BY d.name, p.description"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_departments():
    conn = get_connection()
    rows = conn.execute("SELECT id, name FROM departments WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return rows


class StockOnHandReport(KeyboardMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Filters row
        filter_row = QHBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search description or barcode...")
        self.search.textChanged.connect(self._load)
        filter_row.addWidget(self.search)

        self.dept_filter = QComboBox()
        self.dept_filter.addItem("All Departments", None)
        for d in get_departments():
            self.dept_filter.addItem(d['name'], d['id'])
        self.dept_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.dept_filter)

        self.mode_filter = QComboBox()
        self.mode_filter.addItem("All Products", "all")
        self.mode_filter.addItem("⚠ Low / At Reorder Point", "low")
        self.mode_filter.addItem("✕ Zero Stock", "zero")
        self.mode_filter.currentIndexChanged.connect(self._load)
        filter_row.addWidget(self.mode_filter)

        btn_adjust = QPushButton("&Adjust Stock")
        btn_adjust.setFixedHeight(32)
        btn_adjust.setToolTip("Adjust selected product [A]")
        btn_adjust.clicked.connect(self._adjust)
        filter_row.addWidget(btn_adjust)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.setFixedHeight(32)
        btn_refresh.clicked.connect(self._load)
        filter_row.addWidget(btn_refresh)

        layout.addLayout(filter_row)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Department", "Unit",
            "On Hand", "Reorder Pt", "Reorder Qty", "Stock Value"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._adjust)
        layout.addWidget(self.table)

        # Summary footer
        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.value_label = QLabel("")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer.addWidget(self.status_label)
        footer.addWidget(self.value_label)
        layout.addLayout(footer)

        QShortcut(QKeySequence("A"), self, self._adjust)
        QShortcut(QKeySequence("/"), self, lambda: self.search.setFocus())
        self.setup_keyboard(table=self.table, on_enter=self._adjust)

    def _load(self):
        search = self.search.text().strip()
        dept_id = self.dept_filter.currentData()
        mode = self.mode_filter.currentData()
        rows = get_stock_levels(search=search, dept_id=dept_id, filter_mode=mode)

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        total_value = 0

        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            qty = row['quantity']
            reorder = row['reorder_point']
            value = row['stock_value']
            total_value += value

            self.table.setItem(r, 0, QTableWidgetItem(row['barcode']))
            self.table.setItem(r, 1, QTableWidgetItem(row['description']))
            self.table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or ''))
            self.table.setItem(r, 3, QTableWidgetItem(row['unit'] or ''))

            qty_item = QTableWidgetItem(str(int(qty)))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Colour code by stock level
            if qty == 0:
                qty_item.setForeground(QColor("red"))
            elif qty <= reorder:
                qty_item.setForeground(QColor("orange"))
            else:
                qty_item.setForeground(QColor("green"))
            self.table.setItem(r, 4, qty_item)

            rp_item = QTableWidgetItem(str(int(reorder)))
            rp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 5, rp_item)

            rq_item = QTableWidgetItem(str(int(row['reorder_qty'])))
            rq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 6, rq_item)

            val_item = QTableWidgetItem(f"${value:.2f}")
            val_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 7, val_item)

            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['barcode'])

        self.table.blockSignals(False)

        low_count = sum(1 for r in rows if r['quantity'] <= r['reorder_point'])
        self.status_label.setText(
            f"{len(rows)} products  |  "
            f"<span style='color:orange'>{low_count} at/below reorder</span>"
        )
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.value_label.setText(f"<b>Total Stock Value: ${total_value:,.2f}</b>")
        self.value_label.setTextFormat(Qt.TextFormat.RichText)

    def _adjust(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Adjust Stock", "Select a product first.")
            return
        barcode = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        description = self.table.item(row, 1).text()
        current_qty = int(self.table.item(row, 4).text())
        dlg = StockAdjustDialog(
            barcode=barcode,
            description=description,
            current_qty=current_qty,
            parent=self
        )
        if dlg.exec():
            self._load()


class StockAdjustDialog(QDialog):
    def __init__(self, barcode, description, current_qty, parent=None):
        super().__init__(parent)
        self.barcode = barcode
        self.setWindowTitle(f"Adjust Stock — {description}")
        self.setMinimumWidth(400)
        self._current_qty = current_qty
        self._build_ui(description, current_qty)

    def _build_ui(self, description, current_qty):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        form.addRow("Product", QLabel(description))
        form.addRow("Current Qty", QLabel(f"<b>{current_qty}</b>"))

        self.move_type = QComboBox()
        for move in MOVE_TYPES:
            self.move_type.addItem(move, move)
        self.move_type.currentIndexChanged.connect(self._update_preview)
        form.addRow("Reason", self.move_type)

        self.qty = QDoubleSpinBox()
        self.qty.setMinimum(0)
        self.qty.setMaximum(99999)
        self.qty.setDecimals(0)
        self.qty.setValue(0)
        self.qty.valueChanged.connect(self._update_preview)
        form.addRow("Adjustment Qty", self.qty)

        self.set_to = QDoubleSpinBox()
        self.set_to.setMinimum(0)
        self.set_to.setMaximum(99999)
        self.set_to.setDecimals(0)
        self.set_to.setValue(current_qty)
        self.set_to.valueChanged.connect(self._update_from_set)
        form.addRow("— or Set to —", self.set_to)

        self.preview = QLabel("")
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        form.addRow("New Qty will be", self.preview)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional note")
        form.addRow("Notes", self.notes)

        layout.addLayout(form)
        layout.addSpacing(10)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Save Adjustment  [Ctrl+S]")
        ok_btn.setFixedHeight(35)
        ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)

        self._update_preview()

    def _update_preview(self):
        move = self.move_type.currentData()
        adj = int(self.qty.value())
        if move in ("RECEIPT", "RETURN", "ADJUSTMENT_IN"):
            new_qty = self._current_qty + adj
            sign = "+"
            color = "green"
        elif move in ("SALE", "WASTAGE", "ADJUSTMENT_OUT", "SHRINKAGE"):
            new_qty = max(0, self._current_qty - adj)
            sign = "-"
            color = "red"
        else:
            new_qty = self._current_qty
            sign = ""
            color = "grey"
        self._new_qty = new_qty
        self.preview.setText(
            f"<b style='color:{color}'>{new_qty}</b>  "
            f"<span style='color:grey'>({sign}{adj})</span>"
        )

    def _update_from_set(self):
        # When "set to" changes, update the adj qty to match
        set_val = int(self.set_to.value())
        diff = abs(set_val - self._current_qty)
        self.qty.blockSignals(True)
        self.qty.setValue(diff)
        self.qty.blockSignals(False)
        self._new_qty = set_val
        color = "green" if set_val >= self._current_qty else "red"
        self.preview.setText(f"<b style='color:{color}'>{set_val}</b>")

    def _save(self):
        adj = int(self.qty.value())
        set_val = int(self.set_to.value())
        move = self.move_type.currentData()

        # Use set_to if it differs from current, otherwise use adj
        if set_val != self._current_qty:
            final_qty = set_val
            actual_adj = set_val - self._current_qty
        elif adj == 0:
            QMessageBox.warning(self, "Validation", "Enter an adjustment quantity or set a new total.")
            return
        else:
            if move in ("RECEIPT", "RETURN", "ADJUSTMENT_IN"):
                actual_adj = adj
            else:
                actual_adj = -adj
            final_qty = self._current_qty + actual_adj

        try:
            stock_model.adjust(
                barcode=self.barcode,
                quantity=actual_adj,
                movement_type=move,
                reference=self.notes.text() or move,
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
