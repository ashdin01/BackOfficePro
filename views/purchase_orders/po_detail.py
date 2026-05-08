from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QDialog, QFormLayout, QSpinBox,
    QFileDialog, QAbstractItemView, QDialogButtonBox, QDateEdit, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QUrl, QDate
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
from utils.error_dialog import show_error
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product as product_model
import models.stock_on_hand as stock_model
import models.settings as settings_model
import controllers.purchase_order_controller as po_controller
from config.constants import PO_STATUS_SENT
from datetime import date, timedelta
import csv
import os
import math


def _week_bounds(offset=0):
    """offset=0 → last completed week; offset=1 → two weeks ago."""
    today = date.today()
    mon   = today - timedelta(days=today.weekday())
    start = mon - timedelta(weeks=(1 + offset))
    return start, start + timedelta(days=6)


def _fy_bounds(year=None):
    today = date.today()
    if year is None:
        year = today.year if today.month >= 7 else today.year - 1
    return date(year, 7, 1), date(year + 1, 6, 30)


def _cartons_needed(reorder_qty, pack_qty):
    return po_controller.cartons_needed(reorder_qty, pack_qty)


def _calc_order_units(reorder_max, reorder_qty, on_hand):
    return po_controller.calc_order_units(reorder_max, reorder_qty, on_hand)


def _carton_note(pack_qty, pack_unit, barcode):
    return po_controller.carton_note(pack_qty, pack_unit, barcode)


class ItemLookupDialog(QDialog):
    def __init__(self, parent=None, supplier_id=None):
        super().__init__(parent)
        self.supplier_id = supplier_id
        self.setWindowTitle("Item Lookup — This Supplier" if supplier_id else "Item Lookup")
        self.setMinimumSize(860, 540)
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by supplier, barcode or description...")
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(500)
        self._filter_timer.timeout.connect(lambda: self._filter(self.search_input.text()))
        self.search_input.textChanged.connect(lambda _: self._filter_timer.start())
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Supplier", "Barcode", "Description", "Pack Size", "Cost Price"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self.table)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_products()

    def _load_products(self):
        rows = po_controller.get_items_for_supplier(self.supplier_id)
        self._all_rows = [dict(r) for r in rows]
        self._populate(self._all_rows)
    def _populate(self, rows):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            pack_str = f"{r['pack_qty']} × {r['pack_unit']}"
            self.table.setItem(row, 0, QTableWidgetItem(r['supplier_name']))
            self.table.setItem(row, 1, QTableWidgetItem(r['barcode']))
            self.table.setItem(row, 2, QTableWidgetItem(r['description']))
            self.table.setItem(row, 3, QTableWidgetItem(pack_str))
            cost_item = QTableWidgetItem(f"${r['cost_price']:.2f}")
            cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, cost_item)

    def _filter(self, text):
        text = text.lower()
        filtered = [
            r for r in self._all_rows
            if (text in r['supplier_name'].lower()
                or text in r['barcode'].lower()
                or text in r['description'].lower())
        ]
        self._populate(filtered)

    def _on_accept(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No selection", "Please select an item first.")
            return
        self.selected = {
            "barcode": self.table.item(row, 1).text(),
            "cost_price": float(self.table.item(row, 4).text().replace("$", "") or 0),
        }
        self.accept()




class PODetail(QWidget):
    def __init__(self, po_id, on_save=None, blank=False):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self._blank = blank
        self._line_ids = []
        self._line_pack_info = []
        self._line_tax_rates = []
        self.setMinimumSize(1400, 800)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        self.rec_banner = QLabel("")
        self.rec_banner.setStyleSheet("color: steelblue; padding: 4px;")
        layout.addWidget(self.rec_banner)

        self.supplier_notes_banner = QLabel("")
        self.supplier_notes_banner.setWordWrap(True)
        self.supplier_notes_banner.setStyleSheet(
            "color: #e6c84e; background: #2a2200; border: 1px solid #6b5500;"
            "border-radius: 4px; padding: 6px 10px;"
        )
        self.supplier_notes_banner.hide()
        layout.addWidget(self.supplier_notes_banner)

        # ── Sales period selector ─────────────────────────────────────────
        period_row = QHBoxLayout()
        period_row.setSpacing(6)
        period_row.addWidget(QLabel("Sales period:"))

        _btn_style = (
            "QPushButton{background:#1e2a38;color:#e6edf3;border:1px solid #2a3a4a;"
            "border-radius:3px;padding:0 8px;font-size:11px;height:26px;}"
            "QPushButton:hover{background:#2a3a4a;}"
        )
        for label, fn in [
            ("This Wk",    self._set_this_week),
            ("Last Wk",    self._set_last_week),
            ("2 Wks Ago",  self._set_two_weeks_ago),
            ("This Month", self._set_this_month),
            ("Last Month", self._set_last_month),
            ("This FY",    self._set_this_fy),
            ("Last FY",    self._set_last_fy),
            ("All Time",   self._set_all_time),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(_btn_style)
            btn.setFixedHeight(26)
            btn.clicked.connect(fn)
            period_row.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#2a3a4a;")
        period_row.addWidget(sep)

        period_row.addWidget(QLabel("From:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("dd/MM/yyyy")
        self._date_from.setDate(QDate.currentDate().addDays(-7))
        self._date_from.setFixedHeight(26)
        period_row.addWidget(self._date_from)

        period_row.addWidget(QLabel("To:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("dd/MM/yyyy")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedHeight(26)
        period_row.addWidget(self._date_to)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(26)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:3px;padding:0 10px;font-size:11px;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        apply_btn.clicked.connect(self._refresh_sales_column)
        period_row.addWidget(apply_btn)
        period_row.addStretch()
        layout.addLayout(period_row)

        self._sales_period_label = "Last Week"

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Supplier Ctn Qty", "Supplier SKU", "On Hand", "Reorder Pt",
            "Order Qty", "Unit Cost $ (ex. GST)", "Line Total $ (ex. GST)",
            "Sales: Last Week",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setMinimumSectionSize(60)
        for _ci in range(10):
            hdr.setSectionResizeMode(_ci, QHeaderView.ResizeMode.Interactive)
        # Description (col 1) absorbs leftover space; Supplier cols (2, 3) are next priority
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Fit all non-stretch headers once the widget has rendered and fonts are resolved
        QTimer.singleShot(0, self._fit_header_widths)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(self._open_product)
        self.table.setToolTip("Double-click any row to open product details")
        layout.addWidget(self.table)

        totals_row = QHBoxLayout()
        totals_row.addStretch()
        self.subtotal_label = QLabel()
        self.subtotal_label.setStyleSheet("font-size:12px; color:#aaa;")
        self.gst_label = QLabel()
        self.gst_label.setStyleSheet("font-size:12px; color:#aaa;")
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-size:13px; font-weight:bold; color:#4CAF50;")
        totals_row.addWidget(self.subtotal_label)
        totals_row.addSpacing(24)
        totals_row.addWidget(self.gst_label)
        totals_row.addSpacing(24)
        totals_row.addWidget(self.total_label)
        layout.addLayout(totals_row)

        btns = QHBoxLayout()

        btn_add = QPushButton("&Add Line  [A]")
        btn_add.setFixedHeight(35)
        btn_add.clicked.connect(self._add_line)

        btn_del = QPushButton("Remove Line  [Del]")
        btn_del.setFixedHeight(35)
        btn_del.clicked.connect(self._remove_line)

        btn_reload = QPushButton("&Reload Recommendations  [R]")
        btn_reload.setFixedHeight(35)
        btn_reload.clicked.connect(self._reload_recommendations)

        btn_export = QPushButton("⬇ Export CSV")
        btn_export.setFixedHeight(35)
        btn_export.clicked.connect(self._export_csv)

        btn_pdf = QPushButton("📄 Export PDF")
        btn_pdf.setFixedHeight(35)
        btn_pdf.setStyleSheet(
            "QPushButton{background:#6a1b9a;color:white;border:none;"
            "border-radius:4px;padding:0 10px;font-weight:bold;}"
            "QPushButton:hover{background:#7b1fa2;}"
        )
        btn_pdf.clicked.connect(self._export_pdf)

        btn_email = QPushButton("📧 Email PO")
        btn_email.setFixedHeight(35)
        btn_email.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:0 10px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        btn_email.clicked.connect(self._email_po)

        btn_send = QPushButton("&Mark as Sent ✓  [M]")
        btn_send.setFixedHeight(35)
        btn_send.clicked.connect(self._mark_sent)

        btn_cancel = QPushButton("&Cancel PO")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;"
            "border-radius:4px;padding:0 10px;}"
            "QPushButton:hover{background:#991b1b;}"
        )
        btn_cancel.clicked.connect(self._cancel_po)

        btn_close = QPushButton("Close  [Esc]")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)

        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addWidget(btn_reload)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_export)
        btns.addWidget(btn_pdf)
        btns.addWidget(btn_email)
        btns.addStretch()
        btns.addWidget(btn_send)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

        QShortcut(QKeySequence("A"), self, self._add_line)
        QShortcut(QKeySequence("M"), self, self._mark_sent)
        QShortcut(QKeySequence("C"), self, self._cancel_po)
        QShortcut(QKeySequence("R"), self, self._reload_recommendations)
        QShortcut(QKeySequence("E"), self, self._export_csv)
        QShortcut(QKeySequence("Delete"), self, self._remove_line)
        QShortcut(QKeySequence("Backspace"), self, self._remove_line)
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _open_product(self, index):
        row = index.row()
        if row < 0 or row >= self.table.rowCount():
            return
        barcode_item = self.table.item(row, 0)
        if not barcode_item:
            return
        barcode = barcode_item.text().strip()
        if not barcode:
            return
        from views.products.product_edit import ProductEdit
        self._product_edit_win = ProductEdit(
            barcode=barcode,
            on_save=lambda: self._load()
        )
        self._product_edit_win.show()
        self._product_edit_win.raise_()
        self._product_edit_win.activateWindow()

    def _export_pdf(self):
        import os
        import logging
        po = self._po

        if po['status'] == 'DRAFT':
            try:
                po_model.update_status(self.po_id, 'DRAFT')
                logging.info(f"Auto-saved {po['po_number']} as DRAFT before PDF export")
            except Exception as e:
                logging.warning(f"Auto-save before PDF export failed: {e}")

        pdf_folder = settings_model.get_setting('po_pdf_path').strip()
        if not pdf_folder:
            pdf_folder = os.path.join(
                os.path.expanduser("~"), "Documents", "BackOfficePro", "PurchaseOrders"
            )
        os.makedirs(pdf_folder, exist_ok=True)

        filename = f"{po['po_number']}_{po['supplier_name'].replace(' ', '_')}.pdf"
        path = os.path.join(pdf_folder, filename)

        try:
            from utils.po_pdf import generate_po_pdf
            generate_po_pdf(self.po_id, path)
            if self.on_save:
                self.on_save()
            logging.info(f"PDF exported: {path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            QMessageBox.information(self, "PDF Exported", f"✓ Saved to:\n{path}")
        except Exception as e:
            logging.critical(f"PDF export failed: {e}", exc_info=True)
            QMessageBox.critical(self, "PDF Export Failed", f"Could not generate the PDF.\n\nDetail: {e}")

    def _email_po(self):
        import os
        import logging
        from PyQt6.QtWidgets import QInputDialog

        po = self._po
        supplier = getattr(self, '_supplier', None)

        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "Cannot Send", "Add at least one line before emailing the PO.")
            return

        # ── Online ordering portal warning ────────────────────────────
        if supplier and supplier['online_order']:
            note = (supplier['online_order_note'] or '').strip()
            msg = QMessageBox(self)
            msg.setWindowTitle("Online Ordering Required")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                f"<b>{po['supplier_name']}</b> requires ordering via an online portal."
            )
            msg.setInformativeText(note if note else "Do not email this PO — place the order manually via the supplier's portal.")
            msg.setStandardButtons(
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ignore
            )
            msg.button(QMessageBox.StandardButton.Ignore).setText("Send Email Anyway")
            msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if msg.exec() != QMessageBox.StandardButton.Ignore:
                return

        supplier_email = (supplier['email_orders'] or '').strip() if supplier else ''
        if not supplier_email:
            email, ok = QInputDialog.getText(
                self, "Supplier Email",
                f"No email address found for {po['supplier_name']}.\nEnter supplier email address:"
            )
            if not ok or not email.strip():
                return
            supplier_email = email.strip()

        from config.constants import PO_DOC_TITLES
        _doc_title = PO_DOC_TITLES.get(po['po_type'] or 'PO', 'PURCHASE ORDER').title()
        reply = QMessageBox.question(
            self, "Confirm Email",
            f"Email {_doc_title} {po['po_number']} to:\n\n{po['supplier_name']}\n{supplier_email}"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            pdf_folder = settings_model.get_setting('po_pdf_path').strip()
            if not pdf_folder:
                pdf_folder = os.path.join(os.path.expanduser('~'), 'Documents', 'BackOfficePro', 'PurchaseOrders')
            os.makedirs(pdf_folder, exist_ok=True)

            filename = f"{po['po_number']}_{po['supplier_name'].replace(' ', '_')}.pdf"
            pdf_path = os.path.join(pdf_folder, filename)

            from utils.po_pdf import generate_po_pdf
            generate_po_pdf(self.po_id, pdf_path)

            from utils.email_graph import send_purchase_order
            send_purchase_order(po_id=self.po_id, to_address=supplier_email, pdf_path=pdf_path)

            po_model.update_status(self.po_id, PO_STATUS_SENT)
            self._load()
            if self.on_save:
                self.on_save()

            QMessageBox.information(self, "Email Sent", f"✓ {_doc_title} {po['po_number']} sent to:\n{supplier_email}")
        except Exception as e:
            logging.error(f"Email send failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Email Failed", f"Could not send the email.\n\nDetail: {e}")

    def _export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, 'Export', 'No lines to export.')
            return
        po = self._po
        supplier = getattr(self, '_supplier', None)
        sup_name = po['supplier_name'] or ''
        sup_email = (supplier['email_orders'] or '') if supplier and supplier['email_orders'] else ''

        default_name = f"{po['po_number']}_{sup_name.replace(' ', '_')}.csv"
        default_path = os.path.join(os.path.expanduser("~/Downloads"), default_name)
        path, _ = QFileDialog.getSaveFileName(self, 'Export PO to CSV', default_path, 'CSV Files (*.csv)')
        if not path:
            return
        try:
            lines = lines_model.get_by_po(self.po_id)

            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Supplier', sup_name])
                writer.writerow(['Email', sup_email])
                writer.writerow(['PO Number', po['po_number']])
                writer.writerow(['Status', po['status']])
                writer.writerow([])
                writer.writerow(['Barcode', 'Description', 'Units per Carton', 'Total Units',
                                'SOH (Actual)', 'SOH (System)', 'Variance (Actual less System)'])

                rows_written = 0
                for line in lines:
                    product = product_model.get_by_barcode(line['barcode'])
                    pack_qty = int(product['pack_qty']) if product and product['pack_qty'] else 1
                    pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'

                    soh = stock_model.get_by_barcode(line['barcode'])
                    on_hand = int(soh['quantity']) if soh else 0

                    total_units = int(line['ordered_qty']) * pack_qty

                    writer.writerow([f'="{line["barcode"]}"', line['description'],
                                    f'{pack_qty} x {pack_unit}', total_units, '', on_hand, ''])
                    rows_written += 1

            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            show_error(self, "Could not export CSV.", e, title="Export Failed")

    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self._po = po
        from config.constants import PO_DOC_TITLES, PO_TYPES
        _po_type   = po['po_type'] or 'PO'
        _doc_title = PO_DOC_TITLES.get(_po_type, 'PURCHASE ORDER')
        self.setWindowTitle(f"{_doc_title}: {po['po_number']}")
        from models.supplier import get_by_id as get_supplier
        supplier = get_supplier(po['supplier_id'])
        self._supplier = supplier
        self._order_minimum = float(supplier['order_minimum']) if supplier and supplier['order_minimum'] else 0
        min_str = f"  |  Order Min: <b>${self._order_minimum:.2f}</b>" if self._order_minimum else ""

        sup_notes = (supplier['notes'] or '').strip() if supplier else ''
        if sup_notes:
            self.supplier_notes_banner.setText(f"⚠️  Supplier notes: {sup_notes}")
            self.supplier_notes_banner.show()
        else:
            self.supplier_notes_banner.hide()

        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b>{po['status']}</b> — "
            f"Delivery: {po['delivery_date'] or 'TBC'}{min_str}"
        )
        lines = lines_model.get_by_po(self.po_id)

        _po_type = po['po_type'] or 'PO'
        if len(lines) == 0 and not self._blank and _po_type == 'PO':
            self._auto_load_recommendations()
            lines = lines_model.get_by_po(self.po_id)
        elif len(lines) == 0:
            from config.constants import PO_TYPES
            type_label = PO_TYPES.get(_po_type, 'Order')
            self.rec_banner.setText(
                f"{type_label} — use Add Line [A] or F2 lookup to add products."
            )

        self._populate_table(lines)

    def _auto_load_recommendations(self):
        recs = po_controller.get_reorder_recommendations(self._po['supplier_id'])
        if not recs:
            self.rec_banner.setText("✓ All stock levels are above reorder points for this supplier.")
            return
        for r in recs:
            pack_qty = int(r['pack_qty']) if r['pack_qty'] else 1
            pack_unit = r['pack_unit'] or 'EA'
            order_units = _calc_order_units(r['reorder_max'], 0, r['on_hand'])
            cartons = _cartons_needed(order_units, pack_qty)
            note = _carton_note(pack_qty, pack_unit, r['barcode'])
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=cartons,
                unit_cost=r['cost_price'],
                notes=note,
                pack_qty=pack_qty,
            )
        # ── Also add any auto_reorder products not already on PO ─────
        auto_rows = po_controller.get_auto_reorder_items(self._po['supplier_id'])
        existing_barcodes = {l['barcode'] for l in lines_model.get_by_po(self.po_id)}
        auto_added = 0
        for ar in auto_rows:
            if ar['barcode'] in existing_barcodes:
                continue
            auto_pack_qty = int(ar['pack_qty']) if ar['pack_qty'] else 1
            note = _carton_note(auto_pack_qty, ar['pack_unit'], ar['barcode'])
            lines_model.add(
                po_id=self.po_id,
                barcode=ar['barcode'],
                description=ar['description'],
                ordered_qty=1,
                unit_cost=ar['cost_price'],
                notes=note,
                pack_qty=auto_pack_qty,
            )
            auto_added += 1
        _banner = f"💡 {len(recs)} line(s) auto-loaded from reorder points."
        if auto_added:
            _banner += f"  |  {auto_added} on-reorder item(s) added at 1 carton."
        self.rec_banner.setText(_banner)

    def _reload_recommendations(self):
        recs = po_controller.get_reorder_recommendations(self._po['supplier_id'])
        if not recs:
            QMessageBox.information(self, "Recommendations", "All products are above reorder points.")
            return
        existing = {l['barcode'] for l in lines_model.get_by_po(self.po_id)}
        new_recs = [r for r in recs if r['barcode'] not in existing]
        if not new_recs:
            QMessageBox.information(self, "Recommendations", "All recommended products are already on this PO.")
            return
        for r in new_recs:
            pack_qty = int(r['pack_qty']) if r['pack_qty'] else 1
            pack_unit = r['pack_unit'] or 'EA'
            order_units = _calc_order_units(r['reorder_max'], 0, r['on_hand'])
            cartons = _cartons_needed(order_units, pack_qty)
            note = _carton_note(pack_qty, pack_unit, r['barcode'])
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=cartons,
                unit_cost=r['cost_price'],
                notes=note,
                pack_qty=pack_qty,
            )
        self.rec_banner.setText(f"✓ {len(new_recs)} additional line(s) added.")
        lines = lines_model.get_by_po(self.po_id)
        self._populate_table(lines)
        if self.on_save:
            self.on_save()

    def _populate_table(self, lines):
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self._line_ids = []
            self._line_pack_info = []
            self._line_tax_rates = []

            barcodes = [line['barcode'] for line in lines]
            d_from = self._date_from.date().toPyDate()
            d_to   = self._date_to.date().toPyDate()

            product_map = product_model.get_by_barcodes(barcodes)
            soh_map     = stock_model.get_by_barcodes(barcodes)
            sales_map   = po_controller.get_sales_for_barcodes_range(barcodes, d_from, d_to)

            for line in lines:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self._line_ids.append(line['id'])

                product  = product_map.get(line['barcode'])
                pack_qty  = int(product['pack_qty']) if product and product['pack_qty'] else 1
                pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
                tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0
                self._line_pack_info.append((pack_qty, pack_unit))
                self._line_tax_rates.append(tax_rate)

                barcode_item = QTableWidgetItem(line['barcode'])
                barcode_item.setFlags(barcode_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 0, barcode_item)

                desc_item = QTableWidgetItem(line['description'])
                desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 1, desc_item)

                ctn_item = QTableWidgetItem(f"{pack_qty} × {pack_unit}")
                ctn_item.setFlags(ctn_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                ctn_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, 2, ctn_item)

                sup_sku = (product['supplier_sku'] or '') if product else ''
                sup_sku_item = QTableWidgetItem(sup_sku)
                sup_sku_item.setFlags(sup_sku_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 3, sup_sku_item)

                on_hand = int(soh_map.get(line['barcode'], 0) or 0)
                soh_item = QTableWidgetItem(str(on_hand))
                soh_item.setFlags(soh_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                soh_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, 4, soh_item)

                reorder_pt = int(product['reorder_point']) if product else 0
                rp_item = QTableWidgetItem(str(reorder_pt))
                rp_item.setFlags(rp_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                rp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, 5, rp_item)

                cartons     = int(line['ordered_qty'])
                total_units = cartons * pack_qty
                qty_item = QTableWidgetItem(str(total_units))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setToolTip(f"{cartons} carton(s) × {pack_qty} {pack_unit} = {total_units} units total")
                self.table.setItem(r, 6, qty_item)

                cost_item = QTableWidgetItem(f"{line['unit_cost']:.2f}")
                cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cost_item.setFlags(cost_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 7, cost_item)

                if product and product['variable_weight']:
                    total_item = QTableWidgetItem("— variable weight")
                    total_item.setForeground(QColor("#FFA500"))
                else:
                    total_item = QTableWidgetItem(f"${total_units * line['unit_cost']:.2f}")
                    total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 8, total_item)

                sales_val = sales_map.get(line['barcode'])
                if sales_val is None:
                    sales_cell = QTableWidgetItem("—")
                    sales_cell.setForeground(QColor("#666666"))
                else:
                    sales_cell = QTableWidgetItem(str(sales_val) if sales_val > 0 else "0")
                    sales_cell.setForeground(QColor("#4CAF50" if sales_val > 0 else "#666666"))
                sales_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                sales_cell.setFlags(sales_cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 9, sales_cell)
        finally:
            self.table.blockSignals(False)
        self._update_total()

    def _fit_header_widths(self):
        """Expand any non-stretch column that is too narrow to show its header text."""
        hdr = self.table.horizontalHeader()
        fm  = hdr.fontMetrics()
        # 44px covers: 8px left pad + 8px right pad + ~20px sort indicator + 8px safety margin
        PADDING = 44
        for col in range(self.table.columnCount()):
            if hdr.sectionResizeMode(col) == QHeaderView.ResizeMode.Stretch:
                continue
            item = self.table.horizontalHeaderItem(col)
            text = item.text() if item else ""
            needed = fm.horizontalAdvance(text) + PADDING
            if self.table.columnWidth(col) < needed:
                self.table.setColumnWidth(col, needed)

    def _set_period(self, label, d_from, d_to):
        self._date_from.setDate(QDate(d_from.year, d_from.month, d_from.day))
        self._date_to.setDate(QDate(d_to.year, d_to.month, d_to.day))
        self._sales_period_label = label
        self._refresh_sales_column()

    def _set_this_week(self):
        t = date.today()
        self._set_period("This Week", t - timedelta(days=t.weekday()), t)

    def _set_last_week(self):
        s, e = _week_bounds(0)
        self._set_period("Last Week", s, e)

    def _set_two_weeks_ago(self):
        s, e = _week_bounds(1)
        self._set_period("2 Wks Ago", s, e)

    def _set_this_month(self):
        t = date.today()
        self._set_period("This Month", t.replace(day=1), t)

    def _set_last_month(self):
        t = date.today()
        last_day = t.replace(day=1) - timedelta(days=1)
        self._set_period("Last Month", last_day.replace(day=1), last_day)

    def _set_this_fy(self):
        s, e = _fy_bounds()
        self._set_period("This FY", s, min(e, date.today()))

    def _set_last_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        s, e = _fy_bounds(y - 1)
        self._set_period("Last FY", s, e)

    def _set_all_time(self):
        self._set_period("All Time", date(2000, 1, 1), date.today())

    def _refresh_sales_column(self):
        label = getattr(self, '_sales_period_label', 'Selected Period')
        d_from = self._date_from.date().toPyDate()
        d_to   = self._date_to.date().toPyDate()
        self.table.setHorizontalHeaderItem(9, QTableWidgetItem(f"Sales: {label}"))
        self._fit_header_widths()

        barcodes = [
            self.table.item(r, 0).text().strip()
            for r in range(self.table.rowCount())
            if self.table.item(r, 0)
        ]
        sales_map = po_controller.get_sales_for_barcodes_range(barcodes, d_from, d_to)

        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                barcode_item = self.table.item(r, 0)
                if not barcode_item:
                    continue
                sales_val = sales_map.get(barcode_item.text().strip())
                if sales_val is None:
                    cell = QTableWidgetItem("—")
                    cell.setForeground(QColor("#666666"))
                else:
                    cell = QTableWidgetItem(str(sales_val) if sales_val > 0 else "0")
                    cell.setForeground(QColor("#4CAF50" if sales_val > 0 else "#666666"))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 9, cell)
        finally:
            self.table.blockSignals(False)

    def _on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if col not in (6, 7):
            return
        if row >= len(self._line_ids):
            return
        if self._line_ids[row] is None:
            return

        line_id = self._line_ids[row]
        pack_qty, pack_unit = self._line_pack_info[row]

        try:
            if col == 6:
                total_units = max(1, int(float(item.text())))
                cartons = max(1, math.ceil(total_units / pack_qty))
                snapped_units = cartons * pack_qty
                self.table.blockSignals(True)
                item.setText(str(snapped_units))
                self.table.blockSignals(False)
                lines_model.update(
                    line_id,
                    ordered_qty=cartons,
                    unit_cost=float(self.table.item(row, 7).text().replace("$", "").strip()),
                    notes=_carton_note(pack_qty, pack_unit, self.table.item(row, 0).text()),
                )
                item.setToolTip(f"{cartons} carton(s) × {pack_qty} {pack_unit} = {snapped_units} units total")
                self.rec_banner.setText("")

            elif col == 7:
                cost = max(0.0, float(item.text().replace("$", "").strip()))
                total_units_col = int(float(self.table.item(row, 6).text()))
                cartons = max(1, math.ceil(total_units_col / pack_qty))
                lines_model.update(
                    line_id,
                    ordered_qty=cartons,
                    unit_cost=cost,
                    notes=_carton_note(pack_qty, pack_unit, self.table.item(row, 0).text())
                )

            try:
                total_units_now = int(float(self.table.item(row, 6).text()))
                cost_now = float(self.table.item(row, 7).text().replace("$", "").strip())
                line_total = total_units_now * cost_now
                lt_item = self.table.item(row, 8)
                if lt_item and not lt_item.text().startswith("—"):
                    lt_item.setFlags(lt_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.table.blockSignals(True)
                    lt_item.setText(f"${line_total:.2f}")
                    self.table.blockSignals(False)
                    lt_item.setFlags(lt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            except (ValueError, AttributeError):
                pass

        except (ValueError, TypeError):
            pass

        self._update_total()

    def _update_total(self):
        subtotal = 0.0   # ex. GST
        gst_total = 0.0
        var_lines = 0
        for r in range(self.table.rowCount()):
            if r >= len(self._line_ids) or self._line_ids[r] is None:
                continue
            try:
                lt_item = self.table.item(r, 8)
                if not lt_item:
                    continue
                if lt_item.text().startswith("—"):
                    var_lines += 1
                    continue
                line_total_ex = float(lt_item.text().replace("$", "").replace(",", "").strip())
                subtotal += line_total_ex
                tax_rate = 0.0
                if r < len(self._line_tax_rates) and self._line_tax_rates[r] is not None:
                    tax_rate = float(self._line_tax_rates[r])
                if tax_rate > 0:
                    gst_total += line_total_ex * (tax_rate / 100)
            except (ValueError, AttributeError):
                pass

        subtotal   = round(subtotal, 2)
        gst        = round(gst_total, 2)
        order_total = round(subtotal + gst, 2)

        self.subtotal_label.setText(f"Subtotal (ex GST): ${subtotal:.2f}")
        self.gst_label.setText(f"GST: ${gst:.2f}")

        if var_lines:
            self.total_label.setText(
                f"Order Total (inc. GST): ${order_total:.2f}"
                f"  +  {var_lines} variable weight line(s) invoiced at delivery"
            )
        else:
            self.total_label.setText(f"Order Total (inc. GST): ${order_total:.2f}")

    def _add_line(self):
        po = po_model.get_by_id(self.po_id)
        dlg = AddLineDialog(self.po_id, supplier_id=po["supplier_id"], parent=self)
        if dlg.exec():
            lines = lines_model.get_by_po(self.po_id)
            self._populate_table(lines)
            if self.on_save:
                self.on_save()

    def _remove_line(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove Line", "Select a line first.")
            return
        while row >= 0 and (row >= len(self._line_ids) or self._line_ids[row] is None):
            row -= 1
        if row < 0 or self._line_ids[row] is None:
            QMessageBox.information(self, "Remove Line", "Could not identify line. Please click a product row.")
            return
        line_id = self._line_ids[row]
        desc = self.table.item(row, 1).text() if self.table.item(row, 1) else "this line"
        reply = QMessageBox.question(
            self, "Confirm Remove",
            f"Remove this line?\n\n{desc}"
        )
        if reply == QMessageBox.StandardButton.Yes:
            lines_model.delete(line_id)
            lines = lines_model.get_by_po(self.po_id)
            self._populate_table(lines)
            if self.on_save:
                self.on_save()

    def _mark_sent(self):
        lines = lines_model.get_by_po(self.po_id)
        if not lines:
            QMessageBox.warning(self, "Cannot Send", "Add at least one line before sending.")
            return
        total = 0
        for r in range(self.table.rowCount()):
            if r >= len(self._line_ids) or self._line_ids[r] is None:
                continue
            try:
                qty  = float(self.table.item(r, 6).text())
                cost = float(self.table.item(r, 7).text().replace("$", "").strip())
                tax_rate = float(self._line_tax_rates[r]) if r < len(self._line_tax_rates) else 0.0
                line_ex  = qty * cost
                total   += line_ex * (1 + tax_rate / 100)
            except (ValueError, AttributeError):
                pass
        if self._order_minimum > 0 and total < self._order_minimum:
            reply = QMessageBox.warning(
                self, "Order Minimum Not Met",
                f"This order total is ${total:.2f}, which is below the supplier's "
                f"order minimum of ${self._order_minimum:.2f}.\n\nSend anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        reply = QMessageBox.question(self, "Confirm", "Mark this PO as Sent?")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.update_status(self.po_id, PO_STATUS_SENT)
            self._load()
            if self.on_save:
                self.on_save()

    def _cancel_po(self):
        reply = QMessageBox.question(
            self, "Confirm", "Cancel this PO? This cannot be undone.")
        if reply == QMessageBox.StandardButton.Yes:
            po_model.cancel(self.po_id)
            if self.on_save:
                self.on_save()
            self.close()



class AddLineDialog(QDialog):
    def __init__(self, po_id, supplier_id=None, parent=None):
        super().__init__(parent)
        self.po_id = po_id
        self.supplier_id = supplier_id
        self.setWindowTitle("Add Line")
        self.setMinimumWidth(440)
        self._reorder_max = 0
        self._pack_qty = 1
        self._pack_unit = 'EA'
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        barcode_row = QHBoxLayout()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.barcode.returnPressed.connect(self._on_barcode_enter)
        lookup_btn = QPushButton("🔍 F2")
        lookup_btn.setFixedWidth(70)
        lookup_btn.setFixedHeight(28)
        lookup_btn.setToolTip("Press F2 to open item lookup")
        lookup_btn.setAutoDefault(False)
        lookup_btn.setDefault(False)
        lookup_btn.clicked.connect(self._open_lookup)
        from PyQt6.QtGui import QShortcut, QKeySequence
        f2 = QShortcut(QKeySequence("F2"), self)
        f2.setContext(Qt.ShortcutContext.WindowShortcut)
        f2.activated.connect(self._open_lookup)
        barcode_row.addWidget(self.barcode)
        barcode_row.addWidget(lookup_btn)

        self.description = QLineEdit()
        self.description.setPlaceholderText("Auto-filled on barcode lookup")

        self.on_hand_label = QLabel("")
        self.on_hand_label.setStyleSheet("color: grey;")

        self.pack_label = QLabel("")
        self.pack_label.setStyleSheet("color: steelblue; font-style: italic;")

        self.qty = QDoubleSpinBox()
        self.qty.setMinimum(1)
        self.qty.setMaximum(99999)
        self.qty.setDecimals(0)
        self.qty.setValue(1)
        self.qty.setSuffix(" carton(s)")
        self.qty.valueChanged.connect(self._update_unit_preview)
        self.qty.installEventFilter(self)

        self.unit_preview = QLabel("")
        self.unit_preview.setStyleSheet("color: #555; font-style: italic;")

        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setMaximum(99999)
        self.unit_cost.setPrefix("$")
        self.unit_cost.setDecimals(2)
        self.unit_cost.installEventFilter(self)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional")

        form.addRow("Barcode *",       barcode_row)
        form.addRow("Description",     self.description)
        form.addRow("Stock on Hand",   self.on_hand_label)
        form.addRow("Pack Size",       self.pack_label)
        form.addRow("Qty (Cartons) *", self.qty)
        form.addRow("",                self.unit_preview)
        form.addRow("Unit Cost",       self.unit_cost)
        form.addRow("Notes",           self.notes)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add to PO")
        ok_btn.setFixedHeight(35)
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self._add)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self._add)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if obj == self.qty:
                    self.unit_cost.setFocus()
                    self.unit_cost.selectAll()
                    return True
                elif obj == self.unit_cost:
                    self._add()
                    return True
        return super().eventFilter(obj, event)

    def _on_barcode_enter(self):
        self._lookup()
        self.qty.setFocus()
        self.qty.selectAll()

    def _open_lookup(self):
        dlg = ItemLookupDialog(parent=self, supplier_id=self.supplier_id)
        if dlg.exec() and dlg.selected:
            self.barcode.setText(dlg.selected["barcode"])
            self.unit_cost.setValue(dlg.selected["cost_price"])
            self._lookup()

    def _lookup(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            return
        existing_lines = lines_model.get_by_po(self.po_id)
        for line_num, existing in enumerate(existing_lines, start=1):
            if existing['barcode'] == barcode:
                QMessageBox.warning(
                    self, "Item Already on PO",
                    f"This item is already on this PO at line {line_num}:\n\n"
                    f"{existing['description']}\n\n"
                    f"Edit the existing line instead."
                )
                self.barcode.clear()
                self.barcode.setFocus()
                return
        product = product_model.get_by_barcode(barcode)
        if product:
            if self.supplier_id and product['supplier_id'] != self.supplier_id:
                import models.supplier as _sup_model
                po_sup   = _sup_model.get_by_id(self.supplier_id)
                prod_sup = _sup_model.get_by_id(product['supplier_id']) if product['supplier_id'] else None
                po_name   = po_sup['name'] if po_sup else "Unknown"
                prod_name = prod_sup['name'] if prod_sup else "No supplier set"
                QMessageBox.warning(
                    self, "Wrong Supplier",
                    f"This product belongs to: {prod_name}\n"
                    f"This PO is for: {po_name}\n\n"
                    f"Only {po_name} products can be added to this order."
                )
                self.barcode.clear()
                self.barcode.setFocus()
                return
            self.description.setText(product['description'])
            self.unit_cost.setValue(product['cost_price'])
            self._reorder_max = int(product['reorder_max']) if product['reorder_max'] else 0
            self._pack_qty    = int(product['pack_qty']) if product['pack_qty'] else 1
            self._pack_unit   = product['pack_unit'] or 'EA'
            soh = stock_model.get_by_barcode(barcode)
            on_hand = int(soh['quantity']) if soh else 0
            reorder = int(product['reorder_point'])
            color   = "red" if on_hand <= reorder else "green"
            self.on_hand_label.setText(
                f"<span style='color:{color}'>{on_hand}</span> "
                f"(reorder at {reorder})"
            )
            self.pack_label.setText(f"{self._pack_qty} × {self._pack_unit} per carton")
            soh_qty = int(soh['quantity']) if soh else 0
            order_units = max(1, self._reorder_max - soh_qty) if self._reorder_max > 0 else self._pack_qty
            suggested_cartons = max(1, math.ceil(order_units / self._pack_qty))
            self.qty.setValue(suggested_cartons)
            self._update_unit_preview()
        else:
            self.description.clear()
            self.pack_label.setText("")
            self.on_hand_label.setText("<span style='color:red'>Product not found</span>")

    def _update_unit_preview(self):
        cartons     = int(self.qty.value())
        total_units = cartons * self._pack_qty
        self.unit_preview.setText(
            f"= {total_units} units  ({cartons} × {self._pack_qty} {self._pack_unit})"
        )

    def _add(self):
        barcode     = self.barcode.text().strip()
        description = self.description.text().strip()
        if not barcode or not description:
            QMessageBox.warning(self, "Validation", "Barcode and Description are required.")
            return
        cartons = int(self.qty.value())
        note    = _carton_note(self._pack_qty, self._pack_unit, barcode)
        lines_model.add(
            po_id=self.po_id,
            barcode=barcode,
            description=description,
            ordered_qty=cartons,
            unit_cost=self.unit_cost.value(),
            notes=note,
            pack_qty=self._pack_qty,
        )
        self.accept()
