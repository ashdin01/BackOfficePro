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
import config.styles as styles
import controllers.purchase_order_controller as po_controller
import controllers.product_controller as product_ctrl
import controllers.supplier_controller as supplier_ctrl
from config.constants import PO_STATUS_SENT
from datetime import date, timedelta
import csv
import os
import math
from utils.po_type_helpers import po_unit_mode, po_is_return, fmt_money
from utils.calculations import week_bounds, fy_bounds
from views.base_view import BaseView
from views.purchase_orders.item_lookup_dialog import ItemLookupDialog
from views.purchase_orders.add_line_dialog import AddLineDialog


class PODetail(BaseView):
    def __init__(self, po_id, on_save=None, blank=False):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self._blank = blank
        self._unit_mode = False   # True for IO/RO — qty means individual units, not cartons
        self._line_ids = []
        self._line_pack_info = []
        self._line_tax_rates = []
        self.setMinimumSize(1400, 800)
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        self.rec_banner = QLabel("")
        self.rec_banner.setStyleSheet("color: steelblue; padding: 4px;")
        layout.addWidget(self.rec_banner)

        self.supplier_notes_banner = QLabel("")
        self.supplier_notes_banner.setWordWrap(True)
        self.supplier_notes_banner.setStyleSheet(styles.STYLE_WARNING_BANNER)
        self.supplier_notes_banner.hide()
        layout.addWidget(self.supplier_notes_banner)

        # ── Sales period selector ─────────────────────────────────────────
        period_row = QHBoxLayout()
        period_row.setSpacing(6)
        period_row.addWidget(QLabel("Sales period:"))

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
            btn.setStyleSheet(styles.STYLE_BTN_PERIOD)
            btn.setFixedHeight(26)
            btn.clicked.connect(fn)
            period_row.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
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
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:3px;padding:0 10px;font-size:11px;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
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
        self.total_label.setStyleSheet(f"font-size:13px; font-weight:bold; color:{styles.CLR_SUCCESS_ALT};")
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

        btn_note = QPushButton("Add Note  [N]")
        btn_note.setFixedHeight(35)
        btn_note.clicked.connect(self._add_note)

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
            f"QPushButton{{background:{styles.CLR_PURPLE_DARK};color:white;border:none;"
            "border-radius:4px;padding:0 10px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_PURPLE_HOVER};}}"
        )
        btn_pdf.clicked.connect(self._export_pdf)

        btn_email = QPushButton("📧 Email PO")
        btn_email.setFixedHeight(35)
        btn_email.setStyleSheet(
            f"QPushButton{{background:{styles.CLR_ACCENT};color:white;border:none;"
            "border-radius:4px;padding:0 10px;font-weight:bold;}"
            f"QPushButton:hover{{background:{styles.CLR_ACCENT_HOVER};}}"
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
        btns.addWidget(btn_note)
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
        QShortcut(QKeySequence("N"), self, self._add_note)
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
            on_save=lambda: self.load()
        )
        self._product_edit_win.show()
        self._product_edit_win.raise_()
        self._product_edit_win.activateWindow()

    def _export_pdf(self):
        import logging
        if self._po['status'] == 'DRAFT':
            try:
                po_controller.update_po_status(self.po_id, 'DRAFT')
            except Exception as e:
                logging.warning(f"Auto-save before PDF export failed: {e}")
        try:
            path = po_controller.generate_po_pdf_to_disk(self.po_id)
            if self.on_save:
                self.on_save()
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
            po_controller.send_po_email(self.po_id, supplier_email)
            self.load()
            if self.on_save:
                self.on_save()
            QMessageBox.information(self, "Email Sent", f"✓ {_doc_title} {po['po_number']} sent to:\n{supplier_email}")
        except Exception as e:
            import logging
            logging.error(f"Email send failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Email Failed", f"Could not send the email.\n\nDetail: {e}")

    def _export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, 'Export', 'No lines to export.')
            return
        po = self._po
        default_name = f"{po['po_number']}_{(po['supplier_name'] or '').replace(' ', '_')}.csv"
        default_path = os.path.join(os.path.expanduser("~/Downloads"), default_name)
        path, _ = QFileDialog.getSaveFileName(self, 'Export PO to CSV', default_path, 'CSV Files (*.csv)')
        if not path:
            return
        try:
            po_controller.write_po_csv(self.po_id, path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            show_error(self, "Could not export CSV.", e, title="Export Failed")

    def _load(self):
        po = po_controller.get_po_by_id(self.po_id)
        self._po = po
        from config.constants import PO_DOC_TITLES, PO_TYPES
        _po_type   = po['po_type'] or 'PO'
        _doc_title = PO_DOC_TITLES.get(_po_type, 'PURCHASE ORDER')
        self._unit_mode  = po_unit_mode(_po_type)
        self._is_return  = po_is_return(_po_type)
        # Column 6 label reflects whether we're ordering in cartons or individual units
        self.table.setHorizontalHeaderItem(6, QTableWidgetItem(
            "Qty (Units)" if self._unit_mode else "Order Qty"
        ))
        self.setWindowTitle(f"{_doc_title}: {po['po_number']}")
        supplier = supplier_ctrl.get_by_id(po['supplier_id'])
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
        lines = po_controller.get_po_lines(self.po_id)

        _po_type = po['po_type'] or 'PO'
        if len(lines) == 0 and not self._blank and _po_type == 'PO':
            self._auto_load_recommendations()
            lines = po_controller.get_po_lines(self.po_id)
        elif len(lines) == 0:
            from config.constants import PO_TYPES
            type_label = PO_TYPES.get(_po_type, 'Order')
            self.rec_banner.setText(
                f"{type_label} — use Add Line [A] or F2 lookup to add products."
            )

        self._populate_table(lines)

    def _auto_load_recommendations(self):
        banner = po_controller.auto_populate_po_lines(self.po_id, self._po['supplier_id'])
        self.rec_banner.setText(banner)

    def _reload_recommendations(self):
        count = po_controller.reload_reorder_recommendations(self.po_id, self._po['supplier_id'])
        if count is None:
            QMessageBox.information(self, "Recommendations", "All products are above reorder points.")
            return
        if count == 0:
            QMessageBox.information(self, "Recommendations", "All recommended products are already on this PO.")
            return
        self.rec_banner.setText(f"✓ {count} additional line(s) added.")
        self._populate_table(po_controller.get_po_lines(self.po_id))
        if self.on_save:
            self.on_save()

    def _populate_table(self, lines):
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self._line_ids = []
            self._line_pack_info = []
            self._line_tax_rates = []

            barcodes = [line['barcode'] for line in lines if not line['is_note']]
            d_from = self._date_from.date().toPyDate()
            d_to   = self._date_to.date().toPyDate()

            product_map = product_ctrl.get_products_by_barcodes(barcodes)
            soh_map     = product_ctrl.get_soh_by_barcodes(barcodes)
            sales_map   = po_controller.get_sales_for_barcodes_range(barcodes, d_from, d_to)

            for line in lines:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self._line_ids.append(line['id'])

                # ── Note line ─────────────────────────────────────────────
                if line['is_note']:
                    note_colour = QColor(styles.CLR_MUTED)
                    note_bg     = QColor(styles.CLR_BG_PANEL)
                    note_item   = QTableWidgetItem(f"📝  {line['description']}")
                    note_item.setForeground(note_colour)
                    note_item.setBackground(note_bg)
                    note_item.setFlags(note_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    font = note_item.font(); font.setItalic(True); note_item.setFont(font)
                    self.table.setItem(r, 1, note_item)
                    for col in [0, 2, 3, 4, 5, 6, 7, 8, 9]:
                        blank = QTableWidgetItem('')
                        blank.setBackground(note_bg)
                        blank.setFlags(blank.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(r, col, blank)
                    self._line_pack_info.append((1, 'EA'))
                    self._line_tax_rates.append(0.0)
                    continue

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

                if self._unit_mode:
                    stored_units  = int(line['ordered_qty'])
                    total_units   = -stored_units if self._is_return else stored_units
                    qty_item = QTableWidgetItem(str(total_units))
                    qty_item.setToolTip(f"{total_units} unit(s)")
                else:
                    cartons     = int(line['ordered_qty'])
                    total_units = cartons * pack_qty
                    qty_item = QTableWidgetItem(str(total_units))
                    qty_item.setToolTip(f"{cartons} carton(s) × {pack_qty} {pack_unit} = {total_units} units total")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, 6, qty_item)

                cost_item = QTableWidgetItem(f"{line['unit_cost']:.2f}")
                cost_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cost_item.setFlags(cost_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 7, cost_item)

                line_val = total_units * line['unit_cost']
                if product and product['variable_weight']:
                    total_item = QTableWidgetItem("— variable weight")
                    total_item.setForeground(QColor("#FFA500"))
                else:
                    line_str = fmt_money(line_val)
                    total_item = QTableWidgetItem(line_str)
                    total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, 8, total_item)

                sales_val = sales_map.get(line['barcode'])
                if sales_val is None:
                    sales_cell = QTableWidgetItem("—")
                    sales_cell.setForeground(QColor("#666666"))
                else:
                    sales_cell = QTableWidgetItem(str(sales_val) if sales_val > 0 else "0")
                    sales_cell.setForeground(QColor(styles.CLR_SUCCESS_ALT if sales_val > 0 else "#666666"))
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
        s, e = week_bounds(0)
        self._set_period("Last Week", s, e)

    def _set_two_weeks_ago(self):
        s, e = week_bounds(1)
        self._set_period("2 Wks Ago", s, e)

    def _set_this_month(self):
        t = date.today()
        self._set_period("This Month", t.replace(day=1), t)

    def _set_last_month(self):
        t = date.today()
        last_day = t.replace(day=1) - timedelta(days=1)
        self._set_period("Last Month", last_day.replace(day=1), last_day)

    def _set_this_fy(self):
        s, e = fy_bounds()
        self._set_period("This FY", s, min(e, date.today()))

    def _set_last_fy(self):
        t = date.today()
        y = t.year if t.month >= 7 else t.year - 1
        s, e = fy_bounds(y - 1)
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
                    cell.setForeground(QColor(styles.CLR_SUCCESS_ALT if sales_val > 0 else "#666666"))
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
                if self._unit_mode:
                    # IO/RO: store exact unit quantity — no carton snapping
                    raw = int(float(item.text()))
                    stored_units = max(1, abs(raw))
                    display_units = -stored_units if self._is_return else stored_units
                    po_controller.update_po_line(
                        line_id,
                        ordered_qty=stored_units,
                        unit_cost=float(self.table.item(row, 7).text().replace("$", "").strip()),
                        notes='',
                    )
                    if display_units != raw:
                        self.table.blockSignals(True)
                        item.setText(str(display_units))
                        self.table.blockSignals(False)
                    item.setToolTip(f"{display_units} unit(s)")
                else:
                    total_units = max(1, int(float(item.text())))
                    cartons = max(1, math.ceil(total_units / pack_qty))
                    snapped_units = cartons * pack_qty
                    self.table.blockSignals(True)
                    item.setText(str(snapped_units))
                    self.table.blockSignals(False)
                    po_controller.update_po_line(
                        line_id,
                        ordered_qty=cartons,
                        unit_cost=float(self.table.item(row, 7).text().replace("$", "").strip()),
                        notes=po_controller.carton_note(pack_qty, pack_unit, self.table.item(row, 0).text()),
                    )
                    item.setToolTip(f"{cartons} carton(s) × {pack_qty} {pack_unit} = {snapped_units} units total")
                self.rec_banner.setText("")

            elif col == 7:
                cost = max(0.0, float(item.text().replace("$", "").strip()))
                display_qty = int(float(self.table.item(row, 6).text()))
                if self._unit_mode:
                    stored_qty = abs(display_qty) if self._is_return else display_qty
                    po_controller.update_po_line(
                        line_id,
                        ordered_qty=stored_qty,
                        unit_cost=cost,
                        notes=''
                    )
                else:
                    cartons = max(1, math.ceil(display_qty / pack_qty))
                    po_controller.update_po_line(
                        line_id,
                        ordered_qty=cartons,
                        unit_cost=cost,
                        notes=po_controller.carton_note(pack_qty, pack_unit, self.table.item(row, 0).text())
                    )

            try:
                total_units_now = int(float(self.table.item(row, 6).text()))
                cost_now = float(self.table.item(row, 7).text().replace("$", "").strip())
                line_total = total_units_now * cost_now
                lt_item = self.table.item(row, 8)
                if lt_item and not lt_item.text().startswith("—"):
                    lt_str = fmt_money(line_total)
                    lt_item.setFlags(lt_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    self.table.blockSignals(True)
                    lt_item.setText(lt_str)
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
        po = po_controller.get_po_by_id(self.po_id)
        dlg = AddLineDialog(self.po_id, supplier_id=po["supplier_id"],
                            po_type=po["po_type"] or 'PO', parent=self)
        if dlg.exec():
            lines = po_controller.get_po_lines(self.po_id)
            self._populate_table(lines)
            last = self.table.rowCount() - 1
            if last >= 0:
                self.table.selectRow(last)
            if self.on_save:
                self.on_save()

    def _add_note(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add Note", "Note text:")
        if not ok or not text.strip():
            return

        row = self.table.currentRow()
        note_id = po_controller.add_po_note_line(self.po_id, text.strip())

        # Build new order: insert note after selected row (or at end)
        ids = list(self._line_ids)
        if row >= 0 and row < len(ids):
            ids.insert(row + 1, note_id)
        else:
            ids.append(note_id)

        po_controller.renumber_po_lines(self.po_id, ids)
        lines = po_controller.get_po_lines(self.po_id)
        self._populate_table(lines)
        target = (row + 1) if row >= 0 else (self.table.rowCount() - 1)
        target = min(target, self.table.rowCount() - 1)
        if target >= 0:
            self.table.selectRow(target)
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
            po_controller.delete_po_line(line_id)
            lines = po_controller.get_po_lines(self.po_id)
            self._populate_table(lines)
            target = min(row, self.table.rowCount() - 1)
            if target >= 0:
                self.table.selectRow(target)
            if self.on_save:
                self.on_save()

    def _mark_sent(self):
        lines = po_controller.get_po_lines(self.po_id)
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
            po_controller.update_po_status(self.po_id, PO_STATUS_SENT)
            self.load()
            if self.on_save:
                self.on_save()

    def _cancel_po(self):
        reply = QMessageBox.question(
            self, "Confirm", "Cancel this PO? This cannot be undone.")
        if reply == QMessageBox.StandardButton.Yes:
            po_controller.cancel_po(self.po_id)
            if self.on_save:
                self.on_save()
            self.close()
