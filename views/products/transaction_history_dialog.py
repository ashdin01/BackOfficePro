"""Movement history and full-receipt viewer dialogs for Product Detail.

show_movement_history_dialog lists every stock movement for a barcode;
double-clicking a SALE or RETURN row calls `on_view_receipt(dialog,
reference)` so the caller decides how to open the full receipt (ProductEdit
wires this straight to show_receipt_dialog via its own
_view_transaction_popup wrapper). A RETURN row's reference is the refund's
own reference (not the original sale's) — show_receipt_dialog resolves
either kind via product_controller.get_transaction() and, for a refund,
also shows the original sale it refunds.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence, QColor
import config.styles as styles
import controllers.product_controller as product_controller
from utils.error_dialog import show_error


def show_movement_history_dialog(parent, barcode, on_view_receipt):
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Movement History — {barcode}")
    dlg.setMinimumSize(820, 500)
    layout = QVBoxLayout(dlg)

    filter_row = QHBoxLayout()
    filter_row.addWidget(QLabel("Type:"))
    type_cb = QComboBox()
    type_cb.addItems(["ALL", "RECEIPT", "SALE", "ADJUSTMENT", "ADJUSTMENT_IN",
                      "ADJUSTMENT_OUT", "WASTAGE", "SHRINKAGE", "RETURN", "STOCKTAKE",
                      "REVALUE"])
    filter_row.addWidget(type_cb)
    filter_row.addStretch()
    hint_lbl = QLabel("Double-click a SALE or RETURN row to view the full receipt")
    hint_lbl.setStyleSheet(f"color: {styles.CLR_MUTED};")
    filter_row.addWidget(hint_lbl)
    status_lbl = QLabel()
    filter_row.addWidget(status_lbl)
    layout.addLayout(filter_row)

    tbl = QTableWidget()
    tbl.setColumnCount(6)
    tbl.setHorizontalHeaderLabels(["Date/Time", "Type", "Qty", "Balance", "Reference", "Notes"])
    hdr = tbl.horizontalHeader()
    for ci in range(5):
        hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
    hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
    tbl.setColumnWidth(0, 135)
    tbl.setColumnWidth(1, 110)
    tbl.setColumnWidth(2, 60)
    tbl.setColumnWidth(3, 70)
    tbl.setColumnWidth(4, 110)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setSortingEnabled(False)
    layout.addWidget(tbl)

    def on_row_double_clicked(r, _col):
        type_item = tbl.item(r, 1)
        ref_item = tbl.item(r, 4)
        if type_item is None or ref_item is None:
            return
        if type_item.text() not in ("SALE", "RETURN") or not ref_item.text():
            return
        on_view_receipt(dlg, ref_item.text())

    tbl.cellDoubleClicked.connect(on_row_double_clicked)

    def load(move_type=None):
        rows = product_controller.get_movement_history(barcode, move_type)
        tbl.setRowCount(0)
        balance = 0.0
        display_rows = []
        for row in reversed(rows):  # oldest first so balance builds correctly
            balance += row["quantity"]
            display_rows.append((row, balance))
        display_rows.reverse()  # newest first for display, balances already computed

        for row, bal in display_rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(str(row["created_at"])[:16]))

            type_item = QTableWidgetItem(row["movement_type"])
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty = row["quantity"]
            if row["movement_type"] in ("RECEIPT", "ADJUSTMENT_IN", "RETURN"):
                type_item.setForeground(QColor(styles.CLR_SUCCESS_ALT))
            elif row["movement_type"] in ("SALE", "WASTAGE", "ADJUSTMENT_OUT", "SHRINKAGE"):
                type_item.setForeground(QColor(styles.CLR_DANGER))
            elif row["movement_type"] == "REVALUE":
                type_item.setForeground(QColor(styles.CLR_PURPLE))
            else:
                type_item.setForeground(QColor("steelblue"))
            tbl.setItem(r, 1, type_item)

            qty_item = QTableWidgetItem(f"{'+' if qty > 0 else ''}{qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setForeground(
                QColor(styles.CLR_SUCCESS_ALT) if qty > 0 else
                QColor(styles.CLR_DANGER) if qty < 0 else
                QColor(styles.CLR_MUTED)
            )
            tbl.setItem(r, 2, qty_item)

            bal_item = QTableWidgetItem(f"{bal:.0f}")
            bal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bal_item.setForeground(
                QColor(styles.CLR_SUCCESS_ALT) if bal > 0 else
                QColor(styles.CLR_ORANGE) if bal == 0 else
                QColor(styles.CLR_DANGER)
            )
            tbl.setItem(r, 3, bal_item)
            tbl.setItem(r, 4, QTableWidgetItem(row["reference"] or ""))
            tbl.setItem(r, 5, QTableWidgetItem(row["notes"] or ""))

        status_lbl.setText(f"{tbl.rowCount()} movements")

    type_cb.currentTextChanged.connect(load)
    load()

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    close_btn = QPushButton("Close  [Esc]")
    close_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
    dlg.exec()


def show_receipt_dialog(parent, reference: str):
    """Show the full POS receipt (all line items across all products, plus
    receipt number and totals) for a SALE row's reference, or the equivalent
    view — including the original sale it refunds — for a RETURN row's
    reference."""
    txn = product_controller.get_transaction(reference)
    if txn is None:
        QMessageBox.information(
            parent, "Receipt Not Found",
            f"No transaction record found for reference {reference}."
        )
        return
    is_refund = txn.get('transaction_type') == 'REFUND'

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Refund Receipt — {reference}" if is_refund else f"Receipt — {reference}")
    dlg.setMinimumSize(640, 480)
    layout = QVBoxLayout(dlg)

    header = QFormLayout()
    header.addRow("Receipt #", QLabel(reference))
    if is_refund and txn.get('original_reference'):
        header.addRow("Original Sale", QLabel(txn['original_reference']))
    header.addRow("Date/Time", QLabel(str(txn.get('received_at') or txn.get('sale_date') or '')))
    header.addRow("Operator", QLabel(txn.get('operator') or ''))
    if txn.get('payment_method'):
        header.addRow("Payment", QLabel(txn['payment_method']))
    layout.addLayout(header)

    tbl = QTableWidget()
    tbl.setColumnCount(5)
    tbl.setHorizontalHeaderLabels(["Barcode", "Description", "Qty", "Unit Price", "Line Total"])
    hdr = tbl.horizontalHeader()
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for ci in (2, 3, 4):
        hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
    tbl.setColumnWidth(0, 130)
    tbl.setColumnWidth(2, 60)
    tbl.setColumnWidth(3, 90)
    tbl.setColumnWidth(4, 90)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    items = txn.get('items') or []
    tbl.setRowCount(len(items))
    for r, item in enumerate(items):
        qty = item['quantity']
        desc = item['notes'] or item['description'] or ''
        unit_price = item['unit_price']
        line_total = item['line_total']
        tbl.setItem(r, 0, QTableWidgetItem(item['barcode']))
        tbl.setItem(r, 1, QTableWidgetItem(desc))
        # SALE movements store quantity negative (stock decreased); RETURN
        # movements store it positive (stock increased) — display always
        # wants the positive "how many" count either way.
        qty_val = qty if is_refund else (-qty if qty is not None else None)
        qty_text = "" if qty_val is None else (
            f"{qty_val:g}" if qty_val != int(qty_val) else f"{qty_val:.0f}"
        )
        qty_item = QTableWidgetItem(qty_text)
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.setItem(r, 2, qty_item)
        price_item = QTableWidgetItem(f"${unit_price:.2f}" if unit_price is not None else "—")
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tbl.setItem(r, 3, price_item)
        total_item = QTableWidgetItem(f"${line_total:.2f}" if line_total is not None else "—")
        total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tbl.setItem(r, 4, total_item)
    layout.addWidget(tbl)

    totals = QFormLayout()
    if txn.get('subtotal') is not None:
        totals.addRow("Subtotal", QLabel(f"${txn['subtotal']:.2f}"))
    if txn.get('gst_amount') is not None:
        totals.addRow("GST", QLabel(f"${txn['gst_amount']:.2f}"))
    if txn.get('total') is not None:
        totals.addRow("Total", QLabel(f"${txn['total']:.2f}"))
    layout.addLayout(totals)

    def print_receipt():
        from utils.open_file import open_with_default_app
        try:
            path = product_controller.generate_receipt_pdf(reference)
            open_with_default_app(path)
        except Exception as e:
            show_error(dlg, "Could not generate the receipt PDF.", e)

    btn_row = QHBoxLayout()
    print_btn = QPushButton("Print Receipt  [Ctrl+P]")
    print_btn.clicked.connect(print_receipt)
    btn_row.addWidget(print_btn)
    btn_row.addStretch()
    close_btn = QPushButton("Close  [Esc]")
    close_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    QShortcut(QKeySequence("Ctrl+P"), dlg, print_receipt)
    QShortcut(QKeySequence("Escape"), dlg, dlg.accept)
    dlg.exec()
