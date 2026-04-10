from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QDoubleSpinBox, QDialog, QFormLayout, QSpinBox,
    QFileDialog, QAbstractItemView, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QColor
import models.purchase_order as po_model
import models.po_lines as lines_model
import models.product as product_model
import models.stock_on_hand as stock_model
from config.constants import PO_STATUS_SENT
from database.connection import get_connection
import csv
import os
import math


def get_recommendations(supplier_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.barcode, p.description, p.reorder_point,
               COALESCE(p.reorder_max, 0) as reorder_max,
               p.cost_price, COALESCE(s.quantity, 0) as on_hand,
               COALESCE(p.pack_qty, 1) as pack_qty,
               COALESCE(p.pack_unit, 'EA') as pack_unit,
               p.supplier_sku
        FROM products p
        LEFT JOIN stock_on_hand s ON p.barcode = s.barcode
        WHERE p.supplier_id = ?
          AND p.active = 1
          AND COALESCE(s.quantity, 0) <= p.reorder_point
          AND p.reorder_point > 0
        ORDER BY p.description
    """, (supplier_id,)).fetchall()
    conn.close()
    return rows


def _cartons_needed(reorder_qty, pack_qty):
    """Convert unit reorder qty to number of cartons, rounding up."""
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    import math
    return max(1, math.ceil(reorder_qty / pack_qty))


def _calc_order_units(reorder_max, reorder_qty, on_hand):
    """
    If reorder_max > 0: order = max - on_hand (min 1 unit).
    Otherwise fall back to reorder_qty (legacy).
    """
    reorder_max = reorder_max or 0
    on_hand     = on_hand or 0
    if reorder_max > 0:
        needed = reorder_max - on_hand
        return max(1, int(needed))
    return max(1, int(reorder_qty or 1))


def _carton_note(pack_qty, pack_unit, barcode):
    """Build the per-line note string."""
    pack_qty = pack_qty if pack_qty and pack_qty > 0 else 1
    return f"{pack_qty} × {pack_unit}  |  barcode: {barcode}"


class ItemLookupDialog(QDialog):
    """
    Modal item lookup — all products sorted by supplier name then description.
    Double-click or OK to select; populates AddLineDialog barcode field.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Item Lookup")
        self.setMinimumSize(860, 540)
        self.selected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Search bar
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by supplier, barcode or description…")
        self.search_input.textChanged.connect(self._filter)
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        # Table
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

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_products()

    def _load_products(self):
        conn = get_connection()
        rows = conn.execute("""
            SELECT
                COALESCE(s.name, '') AS supplier_name,
                p.barcode,
                p.description,
                COALESCE(p.pack_qty, 1) AS pack_qty,
                COALESCE(p.pack_unit, 'EA') AS pack_unit,
                COALESCE(p.cost_price, 0.0) AS cost_price
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.active = 1
            ORDER BY supplier_name ASC, p.description ASC
        """).fetchall()
        conn.close()
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
            "barcode":    self.table.item(row, 1).text(),
            "cost_price": float(self.table.item(row, 4).text().replace("$", "") or 0),
        }
        self.accept()



def _get_sales_for_barcode(barcode):
    """
    Return sales quantities for a barcode across key periods.
    Joins via plu_barcode_map to find the PLU for this barcode.
    Returns dict with keys: last_week, two_weeks, this_month, ytd
    """
    from datetime import date, timedelta
    today = date.today()

    # Week boundaries (Mon-Sun)
    days_since_monday = today.weekday()
    this_week_start   = today - timedelta(days=days_since_monday)
    last_week_start   = this_week_start - timedelta(days=7)
    last_week_end     = this_week_start - timedelta(days=1)
    two_weeks_start   = last_week_start - timedelta(days=7)
    two_weeks_end     = last_week_start - timedelta(days=1)
    month_start       = today.replace(day=1)
    year_start        = today.replace(month=1, day=1)

    try:
        from database.connection import get_connection
        conn = get_connection()

        # Find PLU for this barcode via plu_barcode_map
        plu_row = conn.execute(
            "SELECT plu FROM plu_barcode_map WHERE barcode=?", (barcode,)
        ).fetchone()

        if not plu_row:
            conn.close()
            return None   # Not matched — show "—"

        plu = str(plu_row[0])

        def qty(d_from, d_to):
            row = conn.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM sales_daily
                WHERE plu=? AND sale_date BETWEEN ? AND ?
            """, (plu, str(d_from), str(d_to))).fetchone()
            return int(row[0]) if row else 0

        result = {
            "last_week":  qty(last_week_start,  last_week_end),
            "two_weeks":  qty(two_weeks_start,  two_weeks_end),
            "this_month": qty(month_start,       today),
            "ytd":        qty(year_start,        today),
        }
        conn.close()
        return result
    except Exception:
        return None


class PODetail(QWidget):
    def __init__(self, po_id, on_save=None, blank=False):
        super().__init__()
        self.po_id = po_id
        self.on_save = on_save
        self._blank = blank
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

        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Supplier Ctn Qty", "Supplier SKU", "On Hand", "Reorder Pt",
            "Order Qty", "Unit Cost $", "Line Total $",
            "Last Week", "Two Weeks Ago", "This Month", "Year to Date"
        ])
        hdr = self.table.horizontalHeader()
        for _ci in range(13):
            hdr.setSectionResizeMode(_ci, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 110)   # Barcode
        # col 1 Description stretches
        self.table.setColumnWidth(2, 110)   # Supplier Ctn Qty
        self.table.setColumnWidth(3, 110)   # Supplier SKU
        self.table.setColumnWidth(4, 75)    # On Hand
        self.table.setColumnWidth(5, 80)    # Reorder Pt
        self.table.setColumnWidth(6, 90)    # Order Qty
        self.table.setColumnWidth(7, 85)    # Unit Cost $
        self.table.setColumnWidth(8, 95)    # Line Total $
        self.table.setColumnWidth(9, 80)    # Last Week
        self.table.setColumnWidth(10, 95)   # Two Weeks Ago
        self.table.setColumnWidth(11, 85)   # This Month
        self.table.setColumnWidth(12, 85)   # Year to Date
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
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
        btns.addStretch()
        btns.addWidget(btn_send)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

        QShortcut(QKeySequence("A"),          self, self._add_line)
        QShortcut(QKeySequence("M"),          self, self._mark_sent)
        QShortcut(QKeySequence("C"),          self, self._cancel_po)
        QShortcut(QKeySequence("R"),          self, self._reload_recommendations)
        QShortcut(QKeySequence("E"),          self, self._export_csv)
        QShortcut(QKeySequence("Delete"),     self, self._remove_line)
        QShortcut(QKeySequence("Backspace"),  self, self._remove_line)
        QShortcut(QKeySequence("Escape"),     self, self.close)

    def _export_pdf(self):
        import os
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        po = self._po
        default_name = f"{po['po_number']}_{po['supplier_name'].replace(' ', '_')}.pdf"
        default_path = os.path.join(os.path.expanduser("~/Downloads"), default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PO to PDF", default_path,
            "PDF Files (*.pdf);;All Files (*)"
        )
        if not path:
            return
        try:
            from utils.po_pdf import generate_po_pdf
            generate_po_pdf(self.po_id, path)
            QMessageBox.information(self, "PDF Exported", f"Saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "PDF Export Failed", str(e))

    def _export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, 'Export', 'No lines to export.')
            return
        po       = self._po
        supplier = getattr(self, '_supplier', None)
        sup_name  = po['supplier_name'] or ''
        sup_email = (supplier['email'] or '') if supplier and supplier['email'] else ''
        sup_notes = (supplier['notes'] or '') if supplier and supplier['notes'] else ''

        default_name = f"{po['po_number']}_{sup_name.replace(' ', '_')}.csv"
        default_path = os.path.join(os.path.expanduser("~/Downloads"), default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export PO to CSV', default_path,
            'CSV Files (*.csv);;All Files (*)'
        )
        if not path:
            return
        try:
            lines = lines_model.get_by_po(self.po_id)
            fixed_total = 0.0
            gst_total   = 0.0

            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Header block
                writer.writerow(['Supplier',      sup_name])
                writer.writerow(['Email',         sup_email])
                writer.writerow(['PO Number',     po['po_number']])
                writer.writerow(['Status',        po['status']])
                writer.writerow(['Delivery Date', po['delivery_date'] or ''])
                writer.writerow([])

                # Column headers
                writer.writerow([
                    'Barcode', 'Description', 'Supplier SKU',
                    'Order Qty (Cartons)', 'Units per Carton',
                    'Total Units', 'On Hand', 'Unit Cost', 'Line Total'
                ])

                # Line rows
                rows_written = 0
                for line in lines:
                    product   = product_model.get_by_barcode(line['barcode'])
                    pack_qty  = int(product['pack_qty'])  if product and product['pack_qty']  else 1
                    pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
                    sup_sku   = (product['supplier_sku'] or '') if product else ''
                    tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0

                    soh     = stock_model.get_by_barcode(line['barcode'])
                    on_hand = int(soh['quantity']) if soh else 0

                    cartons     = int(line['ordered_qty'])
                    total_units = cartons * pack_qty
                    unit_cost   = float(line['unit_cost'])
                    line_total  = total_units * unit_cost

                    fixed_total += line_total
                    if tax_rate > 0:
                        gst_total += line_total - (line_total / (1 + tax_rate / 100))

                    writer.writerow([
                        line['barcode'],
                        line['description'],
                        sup_sku,
                        cartons,
                        f'{pack_qty} x {pack_unit}',
                        total_units,
                        on_hand,
                        f'{unit_cost:.4f}',
                        f'{line_total:.2f}',
                    ])
                    rows_written += 1

                # Totals
                subtotal = round(fixed_total - gst_total, 2)
                gst      = round(gst_total, 2)
                writer.writerow([])
                writer.writerow(['', '', '', '', '', '', '', 'Subtotal (ex GST)', f'{subtotal:.2f}'])
                writer.writerow(['', '', '', '', '', '', '', 'GST',               f'{gst:.2f}'])
                writer.writerow(['', '', '', '', '', '', '', 'Order Total',       f'{fixed_total:.2f}'])

                # Supplier notes footer
                if sup_notes:
                    writer.writerow([])
                    writer.writerow(['Supplier Notes', sup_notes])

            QMessageBox.information(
                self, 'Export Complete',
                f'Exported {rows_written} lines to:\n{path}'
            )
        except Exception as e:
            QMessageBox.critical(self, 'Export Failed', str(e))
    def _load(self):
        po = po_model.get_by_id(self.po_id)
        self._po = po
        self.setWindowTitle(f"PO: {po['po_number']}")
        from models.supplier import get_by_id as get_supplier
        supplier = get_supplier(po['supplier_id'])
        self._supplier = supplier   # stored for CSV export
        self._order_minimum = float(supplier['order_minimum']) if supplier and 'order_minimum' in supplier.keys() and supplier['order_minimum'] else 0
        min_str = f"  |  Order Min: <b>${self._order_minimum:.2f}</b>" if self._order_minimum else ""
        self.header.setText(
            f"<b>{po['po_number']}</b> — {po['supplier_name']} — "
            f"Status: <b>{po['status']}</b> — "
            f"Delivery: {po['delivery_date'] or 'TBC'}{min_str}"
        )
        lines = lines_model.get_by_po(self.po_id)

        if len(lines) == 0 and not getattr(self, '_blank', False):
            self._auto_load_recommendations()
            lines = lines_model.get_by_po(self.po_id)
        elif len(lines) == 0 and getattr(self, '_blank', False):
            self.rec_banner.setText(
                "Blank PO — use Add Line [A] or F2 lookup to add products.")

        self._populate_table(lines)

    def _auto_load_recommendations(self):
        recs = get_recommendations(self._po['supplier_id'])
        if not recs:
            self.rec_banner.setText("✓ All stock levels are above reorder points for this supplier.")
            return
        for r in recs:
            pack_qty  = int(r['pack_qty']) if r['pack_qty'] else 1
            pack_unit = r['pack_unit'] or 'EA'
            order_units = _calc_order_units(r['reorder_max'], 0, r['on_hand'])
            cartons   = _cartons_needed(order_units, pack_qty)
            note      = _carton_note(pack_qty, pack_unit, r['barcode'])
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=cartons,
                unit_cost=r['cost_price'],
                notes=note,
            )
        self.rec_banner.setText(
            f"💡 {len(recs)} line(s) auto-loaded from reorder points. "
            f"Qty shown in cartons. Edit directly in the table."
        )

    def _reload_recommendations(self):
        recs = get_recommendations(self._po['supplier_id'])
        if not recs:
            QMessageBox.information(self, "Recommendations",
                "All products for this supplier are above reorder points.")
            return
        existing = {l['barcode'] for l in lines_model.get_by_po(self.po_id)}
        new_recs = [r for r in recs if r['barcode'] not in existing]
        if not new_recs:
            QMessageBox.information(self, "Recommendations",
                "All recommended products are already on this PO.")
            return
        for r in new_recs:
            pack_qty  = int(r['pack_qty']) if r['pack_qty'] else 1
            pack_unit = r['pack_unit'] or 'EA'
            order_units = _calc_order_units(r['reorder_max'], 0, r['on_hand'])
            cartons   = _cartons_needed(order_units, pack_qty)
            note      = _carton_note(pack_qty, pack_unit, r['barcode'])
            lines_model.add(
                po_id=self.po_id,
                barcode=r['barcode'],
                description=r['description'],
                ordered_qty=cartons,
                unit_cost=r['cost_price'],
                notes=note,
            )
        self.rec_banner.setText(f"✓ {len(new_recs)} additional line(s) added.")
        lines = lines_model.get_by_po(self.po_id)
        self._populate_table(lines)
        if self.on_save:
            self.on_save()

    def _populate_table(self, lines):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._line_ids = []
        self._line_pack_info = []
        self._line_tax_rates = []

        for line in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._line_ids.append(line['id'])

            product = product_model.get_by_barcode(line['barcode'])
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

            # col 2 — Supplier Ctn Qty
            ctn_str = f"{pack_qty} × {pack_unit}"
            ctn_item = QTableWidgetItem(ctn_str)
            ctn_item.setFlags(ctn_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ctn_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, ctn_item)

            sup_sku = (product['supplier_sku'] or '') if product else ''
            sup_sku_item = QTableWidgetItem(sup_sku)
            sup_sku_item.setFlags(sup_sku_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 3, sup_sku_item)

            soh = stock_model.get_by_barcode(line['barcode'])
            on_hand = int(soh['quantity']) if soh else 0
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

            product_vw = product_model.get_by_barcode(line['barcode'])
            is_var_wt = product_vw and product_vw['variable_weight']
            if is_var_wt:
                total_item = QTableWidgetItem("— variable weight")
                total_item.setForeground(QColor("#FFA500"))
            else:
                line_total = total_units * line['unit_cost']
                total_item = QTableWidgetItem(f"${line_total:.2f}")
                total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 8, total_item)

            # ── Sales history columns ─────────────────────────────────
            sales = _get_sales_for_barcode(line['barcode'])
            for col_idx, key in enumerate(['last_week', 'two_weeks', 'this_month', 'ytd'], start=9):
                if sales is None:
                    cell = QTableWidgetItem("—")
                    cell.setForeground(QColor("#666666"))
                else:
                    val = sales[key]
                    cell = QTableWidgetItem(str(val) if val > 0 else "0")
                    if val == 0:
                        cell.setForeground(QColor("#666666"))
                    elif key == 'last_week' and val > 0:
                        cell.setForeground(QColor("#4CAF50"))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, col_idx, cell)


        self.table.blockSignals(False)
        self._update_total()

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
                # col 6 displays total units — convert back to cartons for storage
                total_units = max(1, int(float(item.text())))
                cartons = max(1, math.ceil(total_units / pack_qty))
                # Snap display to exact carton multiple
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
                # col 6 shows total units — convert to cartons for storage
                total_units_col = int(float(self.table.item(row, 6).text()))
                cartons = max(1, math.ceil(total_units_col / pack_qty))
                lines_model.update(line_id, ordered_qty=cartons, unit_cost=cost,
                                   notes=_carton_note(pack_qty, pack_unit, self.table.item(row, 0).text()))

            # Refresh line total — col 6 now shows total units directly
            try:
                total_units_now = int(float(self.table.item(row, 6).text()))
                cost_now        = float(self.table.item(row, 7).text().replace("$","").strip())
                line_total      = total_units_now * cost_now
                lt_item = self.table.item(row, 8)
                if lt_item and not lt_item.text().startswith("—"):
                    # Temporarily make editable to update text
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
        fixed_total = 0.0
        gst_total   = 0.0
        var_lines   = 0
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
                line_total = float(lt_item.text().replace("$","").replace(",","").strip())
                fixed_total += line_total
                # Per-line GST using stored tax rate
                tax_rate = 0.0
                if r < len(self._line_tax_rates) and self._line_tax_rates[r] is not None:
                    tax_rate = float(self._line_tax_rates[r])
                if tax_rate > 0:
                    gst_total += line_total - (line_total / (1 + tax_rate / 100))
            except (ValueError, AttributeError):
                pass

        subtotal = round(fixed_total - gst_total, 2)
        gst      = round(gst_total, 2)

        self.subtotal_label.setText(f"Subtotal (ex GST): ${subtotal:.2f}")
        self.gst_label.setText(f"GST: ${gst:.2f}")

        if var_lines:
            self.total_label.setText(
                f"Order Total: ${fixed_total:.2f}"
                f"  +  {var_lines} variable weight line(s) invoiced at delivery"
            )
        else:
            self.total_label.setText(f"Order Total: ${fixed_total:.2f}")


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
        # Walk upward to find the nearest real line (skip note rows)
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
            if self._line_ids[r] is None:
                continue
            try:
                qty  = float(self.table.item(r, 6).text())
                cost = float(self.table.item(r, 7).text().replace("$", "").strip())
                total += qty * cost
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

        # Barcode row with Lookup button
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
        from PyQt6.QtGui import QKeyEvent
        if obj == self.qty and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._add()
                return True
        return super().eventFilter(obj, event)

    def _on_barcode_enter(self):
        """On Enter in barcode field: run lookup then move focus to qty."""
        self._lookup()
        self.qty.setFocus()
        self.qty.selectAll()

    def _open_lookup(self):
        """Open the item lookup dialog sorted by supplier, fill barcode on selection."""
        dlg = ItemLookupDialog(self)
        if dlg.exec() and dlg.selected:
            self.barcode.setText(dlg.selected["barcode"])
            self.unit_cost.setValue(dlg.selected["cost_price"])
            self._lookup()   # trigger the full product fill

    def _lookup(self):
        barcode = self.barcode.text().strip()
        if not barcode:
            return
        # ── Duplicate line check ─────────────────────────────────────
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
        # ─────────────────────────────────────────────────────────────
        product = product_model.get_by_barcode(barcode)
        if product:
            # Check supplier matches PO supplier
            if self.supplier_id and product['supplier_id'] != self.supplier_id:
                from database.connection import get_connection
                conn = get_connection()
                po_sup = conn.execute(
                    "SELECT name FROM suppliers WHERE id=?", (self.supplier_id,)
                ).fetchone()
                prod_sup = conn.execute(
                    "SELECT name FROM suppliers WHERE id=?", (product['supplier_id'],)
                ).fetchone() if product['supplier_id'] else None
                conn.close()
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
            on_hand   = int(soh['quantity']) if soh else 0
            reorder   = int(product['reorder_point'])
            color     = "red" if on_hand <= reorder else "green"
            self.on_hand_label.setText(
                f"<span style='color:{color}'>{on_hand}</span> "
                f"(reorder at {reorder})"
            )
            self.pack_label.setText(
                f"{self._pack_qty} × {self._pack_unit} per carton"
            )
            import math
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
        cartons    = int(self.qty.value())
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
        )
        self.accept()
