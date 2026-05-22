from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QMessageBox, QFrame,
    QFileDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QShortcut, QKeySequence
import csv, os
from utils.error_dialog import show_error
import controllers.purchase_order_controller as po_ctrl
import controllers.product_controller as product_ctrl
import controllers.supplier_controller as supplier_ctrl


_RIGHT  = Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter


def _item(text, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
          colour=None):
    i = QTableWidgetItem(str(text))
    i.setTextAlignment(align)
    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if colour:
        i.setForeground(QColor(colour))
    return i


class POHistory(QWidget):
    def __init__(self, po_id, on_close=None):
        super().__init__()
        self.po_id    = po_id
        self.on_close = on_close
        self.setMinimumSize(1400, 650)
        self.resize(1550, 780)
        self._build_ui()
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        po = po_ctrl.get_po_by_id(self.po_id)
        self.setWindowTitle(f"PO History: {po['po_number']}")

        status_colour = {
            'RECEIVED': '#4CAF50', 'CANCELLED': '#f44336',
            'REVERSED': '#9C27B0', 'PARTIAL':   '#FF9800',
        }.get(po['status'], '#8b949e')

        inv_num = po['supplier_invoice_number'] or '—'
        self.header = QLabel(
            f"<b>{po['po_number']}</b> &nbsp;—&nbsp; {po['supplier_name']} &nbsp;—&nbsp; "
            f"Status: <b style='color:{status_colour}'>{po['status']}</b>"
            f"&nbsp;&nbsp;&nbsp;"
            f"<span style='color:#8b949e;'>Supplier Invoice:</span> "
            f"<b style='color:#e6edf3'>{inv_num}</b>"
        )
        self.header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.header)

        # ── Bank details row ─────────────────────────────────────────────────
        supplier = supplier_ctrl.get_by_id(po['supplier_id'])
        bank_name   = (supplier['bank_account_name']   or '') if supplier else ''
        bank_bsb    = (supplier['bank_bsb']            or '') if supplier else ''
        bank_acct   = (supplier['bank_account_number'] or '') if supplier else ''
        if bank_name or bank_bsb or bank_acct:
            parts = []
            if bank_name:
                parts.append(f"<span style='color:#8b949e;'>Account Name:</span> "
                             f"<b style='color:#e6edf3'>{bank_name}</b>")
            if bank_bsb:
                parts.append(f"<span style='color:#8b949e;'>BSB:</span> "
                             f"<b style='color:#e6edf3'>{bank_bsb}</b>")
            if bank_acct:
                parts.append(f"<span style='color:#8b949e;'>Account:</span> "
                             f"<b style='color:#e6edf3'>{bank_acct}</b>")
            self.bank_lbl = QLabel("&nbsp;&nbsp;&nbsp;".join(parts))
            self.bank_lbl.setTextFormat(Qt.TextFormat.RichText)
            self.bank_lbl.setStyleSheet("font-size: 11px; margin-bottom: 2px;")
            layout.addWidget(self.bank_lbl)

        # ── Lines table ──────────────────────────────────────────────────────
        line_lbl = QLabel("Order Lines")
        line_lbl.setStyleSheet("font-weight: bold; color: #8b949e; font-size: 11px;"
                               " margin-top: 6px;")
        layout.addWidget(line_lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Description", "Pack Size",
            "Ordered", "Received",
            "Cost ex. GST", "Tax %", "Line ex. GST", "Line inc. GST",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for ci in [0, 2, 3, 4, 5, 6, 7, 8]:
            hdr.setSectionResizeMode(ci, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 120)   # Barcode
        self.table.setColumnWidth(2,  90)   # Pack Size
        self.table.setColumnWidth(3,  80)   # Ordered
        self.table.setColumnWidth(4,  80)   # Received
        self.table.setColumnWidth(5, 110)   # Cost ex. GST
        self.table.setColumnWidth(6,  65)   # Tax %
        self.table.setColumnWidth(7, 115)   # Line ex. GST
        self.table.setColumnWidth(8, 120)   # Line inc. GST
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # ── Charges table ────────────────────────────────────────────────────
        charges = po_ctrl.get_po_charges(self.po_id)
        if charges:
            chg_lbl = QLabel("Additional Charges")
            chg_lbl.setStyleSheet("font-weight: bold; color: #8b949e; font-size: 11px;"
                                  " margin-top: 4px;")
            layout.addWidget(chg_lbl)

            self.charges_table = QTableWidget()
            self.charges_table.setColumnCount(4)
            self.charges_table.setHorizontalHeaderLabels(
                ["Description", "Tax %", "Amount ex. GST", "Amount inc. GST"]
            )
            self.charges_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
            self.charges_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.charges_table.setAlternatingRowColors(True)
            self.charges_table.verticalHeader().setVisible(False)
            self.charges_table.setFixedHeight(
                min(len(charges), 5) * 30 + self.charges_table.horizontalHeader().height() + 4
            )
            layout.addWidget(self.charges_table)
        else:
            self.charges_table = None

        # ── Totals ───────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a3a4a;")
        layout.addWidget(sep)

        self.totals_lbl = QLabel()
        self.totals_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.totals_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.totals_lbl)

        self._load_lines(po)

        # ── Buttons ──────────────────────────────────────────────────────────
        btns = QHBoxLayout()
        if po['status'] in ('RECEIVED', 'PARTIAL'):
            btn_reverse = QPushButton("↩ Reverse PO")
            btn_reverse.setFixedHeight(35)
            btn_reverse.setStyleSheet(
                "QPushButton{background:#6a1b9a;color:white;font-weight:bold;"
                "border:none;border-radius:4px;padding:0 16px;}"
                "QPushButton:hover{background:#7b1fa2;}"
            )
            btn_reverse.setToolTip(
                "Reverse this PO — reduces stock on hand by all received quantities"
            )
            btn_reverse.clicked.connect(self._reverse)
            btns.addWidget(btn_reverse)

        btns.addStretch()
        btn_export = QPushButton("Export CSV")
        btn_export.setFixedHeight(35)
        btn_export.clicked.connect(self._export_csv)
        btns.addWidget(btn_export)

        btn_pdf = QPushButton("Export PDF")
        btn_pdf.setFixedHeight(35)
        btn_pdf.clicked.connect(self._export_pdf)
        btns.addWidget(btn_pdf)

        btn_close = QPushButton("Close  [Esc]")
        btn_close.setFixedHeight(35)
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _load_lines(self, po=None):
        if po is None:
            po = po_ctrl.get_po_by_id(self.po_id)

        lines   = po_ctrl.get_po_lines(self.po_id)
        charges = po_ctrl.get_po_charges(self.po_id)

        self.table.setRowCount(len(lines))
        total_ex  = 0.0
        total_gst = 0.0

        for r, line in enumerate(lines):
            product   = product_ctrl.get_product_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty'])  if product and product['pack_qty']  else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0
            pack_str  = f"{pack_qty} × {pack_unit}" if pack_qty > 1 else pack_unit

            cost          = float(line['actual_cost'] or line['unit_cost'] or 0)
            recv_cartons  = int(line['received_qty'] or 0)
            recv_units    = recv_cartons * pack_qty
            line_ex       = round(recv_units * cost, 2)
            line_gst      = round(line_ex * tax_rate / 100, 2)
            line_inc      = round(line_ex + line_gst, 2)
            total_ex     += line_ex
            total_gst    += line_gst

            recv_colour = '#4CAF50' if recv_cartons > 0 else None
            promo_colour = '#FFB300' if line['is_promo'] else None

            self.table.setItem(r, 0, _item(line['barcode'], _CENTER))
            desc = line['description']
            if line['is_promo']:
                desc += "  ★ promo"
            self.table.setItem(r, 1, _item(desc, colour=promo_colour))
            self.table.setItem(r, 2, _item(pack_str, _CENTER))
            self.table.setItem(r, 3, _item(str(int(line['ordered_qty'])), _CENTER))
            self.table.setItem(r, 4, _item(str(recv_cartons), _CENTER,
                                           colour=recv_colour))
            self.table.setItem(r, 5, _item(f"${cost:.4f}", _RIGHT))
            self.table.setItem(r, 6, _item(
                f"{tax_rate:.0f}%" if tax_rate > 0 else "Free", _CENTER,
                colour='#4CAF50' if tax_rate > 0 else '#555'))
            self.table.setItem(r, 7, _item(f"${line_ex:.2f}", _RIGHT))
            self.table.setItem(r, 8, _item(f"${line_inc:.2f}", _RIGHT,
                                           colour='#4CAF50' if tax_rate > 0 else None))

        # Charges
        charge_ex  = 0.0
        charge_gst = 0.0
        if self.charges_table is not None:
            self.charges_table.setRowCount(len(charges))
            for r, c in enumerate(charges):
                amt_inc = float(c['amount_inc_tax'])
                tax_r   = float(c['tax_rate'])
                amt_ex  = round(amt_inc / (1 + tax_r / 100), 2) if tax_r > 0 else amt_inc
                gst     = round(amt_inc - amt_ex, 2)
                charge_ex  += amt_ex
                charge_gst += gst

                self.charges_table.setItem(r, 0, _item(c['description']))
                self.charges_table.setItem(r, 1, _item(
                    f"{tax_r:.0f}%" if tax_r > 0 else "GST Free", _CENTER,
                    colour='#4CAF50' if tax_r > 0 else '#555'))
                self.charges_table.setItem(r, 2, _item(f"${amt_ex:.2f}", _RIGHT))
                self.charges_table.setItem(r, 3, _item(f"${amt_inc:.2f}", _RIGHT,
                                                        colour='#4CAF50' if tax_r > 0 else None))

        grand_ex  = round(total_ex  + charge_ex,  2)
        grand_gst = round(total_gst + charge_gst, 2)
        grand_inc = round(grand_ex  + grand_gst,  2)

        self.totals_lbl.setText(
            f"Subtotal ex. GST: <b>${grand_ex:.2f}</b>"
            f"&nbsp;&nbsp;&nbsp;GST: <b>${grand_gst:.2f}</b>"
            f"&nbsp;&nbsp;&nbsp;Invoice Total inc. GST: "
            f"<b style='color:#4CAF50; font-size:14px;'>${grand_inc:.2f}</b>"
        )

    def _export_csv(self):
        po = po_ctrl.get_po_by_id(self.po_id)
        default_name = f"{po['po_number'].replace('/', '-')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PO History",
            os.path.join(os.path.expanduser("~/Downloads"), default_name),
            "CSV (*.csv)",
        )
        if not path:
            return

        lines   = po_ctrl.get_po_lines(self.po_id)
        charges = po_ctrl.get_po_charges(self.po_id)

        total_ex  = 0.0
        total_gst = 0.0

        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)

            # Header block
            w.writerow(["PO Number",        po['po_number']])
            w.writerow(["Supplier",         po['supplier_name']])
            w.writerow(["Status",           po['status']])
            w.writerow(["Supplier Invoice", po['supplier_invoice_number'] or ''])
            w.writerow(["Received Date",    po['delivery_date'] or ''])
            sup = supplier_ctrl.get_by_id(po['supplier_id'])
            if sup:
                bk_name = sup['bank_account_name']   or ''
                bk_bsb  = sup['bank_bsb']            or ''
                bk_acct = sup['bank_account_number'] or ''
                if bk_name or bk_bsb or bk_acct:
                    w.writerow(["Bank Account Name", bk_name])
                    w.writerow(["BSB",               bk_bsb])
                    w.writerow(["Account Number",    bk_acct])
            w.writerow([])

            # Lines
            w.writerow([
                "Barcode", "Description", "Pack Size",
                "Ordered (cartons)", "Received (cartons)", "Received (units)",
                "Cost ex. GST", "Tax %", "Promo",
                "Line Total ex. GST", "Line Total inc. GST",
            ])

            for line in lines:
                product   = product_ctrl.get_product_by_barcode(line['barcode'])
                pack_qty  = int(product['pack_qty'])  if product and product['pack_qty']  else 1
                pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
                tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0
                pack_str  = f"{pack_qty} x {pack_unit}" if pack_qty > 1 else pack_unit

                cost         = float(line['actual_cost'] or line['unit_cost'] or 0)
                recv_cartons = int(line['received_qty'] or 0)
                recv_units   = recv_cartons * pack_qty
                line_ex      = round(recv_units * cost, 2)
                line_gst     = round(line_ex * tax_rate / 100, 2)
                line_inc     = round(line_ex + line_gst, 2)
                total_ex    += line_ex
                total_gst   += line_gst

                w.writerow([
                    line['barcode'],
                    line['description'],
                    pack_str,
                    int(line['ordered_qty']),
                    recv_cartons,
                    recv_units,
                    f"{cost:.4f}",
                    f"{tax_rate:.0f}",
                    "Yes" if line['is_promo'] else "No",
                    f"{line_ex:.2f}",
                    f"{line_inc:.2f}",
                ])

            # Charges
            charge_ex  = 0.0
            charge_gst = 0.0
            if charges:
                w.writerow([])
                w.writerow(["Additional Charges"])
                w.writerow(["Description", "Tax %", "Amount ex. GST", "Amount inc. GST"])
                for c in charges:
                    amt_inc = float(c['amount_inc_tax'])
                    tax_r   = float(c['tax_rate'])
                    amt_ex  = round(amt_inc / (1 + tax_r / 100), 2) if tax_r > 0 else amt_inc
                    gst     = round(amt_inc - amt_ex, 2)
                    charge_ex  += amt_ex
                    charge_gst += gst
                    w.writerow([
                        c['description'],
                        f"{tax_r:.0f}",
                        f"{amt_ex:.2f}",
                        f"{amt_inc:.2f}",
                    ])

            # Totals
            grand_ex  = round(total_ex  + charge_ex,  2)
            grand_gst = round(total_gst + charge_gst, 2)
            grand_inc = round(grand_ex  + grand_gst,  2)

            w.writerow([])
            w.writerow(["Subtotal ex. GST", f"{grand_ex:.2f}"])
            w.writerow(["GST",              f"{grand_gst:.2f}"])
            w.writerow(["Total inc. GST",   f"{grand_inc:.2f}"])

        import subprocess, sys
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

    def _export_pdf(self):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )

        po      = po_ctrl.get_po_by_id(self.po_id)
        lines   = po_ctrl.get_po_lines(self.po_id)
        charges = po_ctrl.get_po_charges(self.po_id)

        default_name = f"{po['po_number'].replace('/', '-')}_receipt.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PO Receipt PDF",
            os.path.join(os.path.expanduser("~/Downloads"), default_name),
            "PDF (*.pdf)",
        )
        if not path:
            return

        # ── Styles ───────────────────────────────────────────────────────────
        C_BLACK  = colors.HexColor("#111111")
        C_GREY   = colors.HexColor("#555555")
        C_LGREY  = colors.HexColor("#f2f2f2")
        C_BORDER = colors.HexColor("#aaaaaa")

        def _s(size=9, bold=False, align=TA_LEFT, colour=C_BLACK):
            return ParagraphStyle("_",
                fontSize=size,
                fontName="Helvetica-Bold" if bold else "Helvetica",
                textColor=colour, alignment=align, leading=size + 3)

        doc = SimpleDocTemplate(
            path, pagesize=landscape(A4),
            leftMargin=15*mm, rightMargin=15*mm,
            topMargin=15*mm, bottomMargin=15*mm,
        )
        story = []

        # ── Header ───────────────────────────────────────────────────────────
        story.append(Paragraph(f"Purchase Order Receipt", _s(16, bold=True)))
        story.append(Spacer(1, 4*mm))

        sup_pdf = supplier_ctrl.get_by_id(po['supplier_id'])
        bk_name_pdf = (sup_pdf['bank_account_name']   or '') if sup_pdf else ''
        bk_bsb_pdf  = (sup_pdf['bank_bsb']            or '') if sup_pdf else ''
        bk_acct_pdf = (sup_pdf['bank_account_number'] or '') if sup_pdf else ''

        inv_pdf = po['supplier_invoice_number'] or "—"

        # Pre-calculate totals so they can appear in the header block
        _t_ex = _t_gst = 0.0
        for _ln in lines:
            _prod  = product_ctrl.get_product_by_barcode(_ln['barcode'])
            _pack  = int(_prod['pack_qty']) if _prod and _prod['pack_qty'] else 1
            _tax   = float(_prod['tax_rate']) if _prod and _prod['tax_rate'] else 0.0
            _cost  = float(_ln['actual_cost'] or _ln['unit_cost'] or 0)
            _units = int(_ln['received_qty'] or 0) * _pack
            _t_ex  += round(_units * _cost, 2)
            _t_gst += round(_units * _cost * _tax / 100, 2)
        for _c in charges:
            _inc   = float(_c['amount_inc_tax'])
            _tr    = float(_c['tax_rate'])
            _ex    = round(_inc / (1 + _tr / 100), 2) if _tr > 0 else _inc
            _t_ex  += _ex
            _t_gst += round(_inc - _ex, 2)
        grand_ex  = round(_t_ex, 2)
        grand_gst = round(_t_gst, 2)
        grand_inc = round(grand_ex + grand_gst, 2)

        # Right column: Supplier → Received Date → Supplier Invoice → totals
        right_col = [
            ("Supplier:",         po['supplier_name']),
            ("Received Date:",    po['delivery_date'] or "—"),
            ("Supplier Invoice:", inv_pdf),
            ("Subtotal ex. GST:", f"${grand_ex:.2f}"),
            ("GST:",              f"${grand_gst:.2f}"),
            ("Total inc. GST:",   f"${grand_inc:.2f}"),
        ]
        # Left column: PO Number, Status, then bank details if present
        left_col = [
            ("PO Number:", po['po_number']),
            ("Status:",    po['status']),
        ]
        if bk_name_pdf or bk_bsb_pdf or bk_acct_pdf:
            left_col += [
                ("Bank Account:",   bk_name_pdf or "—"),
                ("BSB:",            bk_bsb_pdf or "—"),
                ("Account Number:", bk_acct_pdf or "—"),
            ]
        while len(left_col) < len(right_col):
            left_col.append(("", ""))

        meta = [[l[0], l[1], r[0], r[1]] for l, r in zip(left_col, right_col)]

        meta_tbl = Table(meta, colWidths=[35*mm, 70*mm, 35*mm, 70*mm])
        meta_tbl.setStyle(TableStyle([
            ("FONTNAME",      (0,0),(-1,-1), "Helvetica"),
            ("FONTNAME",      (0,0),(0,-1),  "Helvetica-Bold"),
            ("FONTNAME",      (2,0),(2,-1),  "Helvetica-Bold"),
            ("FONTNAME",      (3,3),(3,5),   "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("FONTSIZE",      (2,5),(3,5),   11),
            ("TEXTCOLOR",     (0,0),(-1,-1), C_BLACK),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2),
            ("ALIGN",         (3,3),(3,5),   "RIGHT"),
            ("LINEABOVE",     (2,5),(3,5),   0.5, C_BORDER),
        ]))
        story.append(meta_tbl)
        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
        story.append(Spacer(1, 3*mm))

        # ── Lines table ──────────────────────────────────────────────────────
        story.append(Paragraph("Order Lines", _s(10, bold=True)))
        story.append(Spacer(1, 2*mm))

        col_w = [28*mm, 70*mm, 18*mm, 16*mm, 16*mm, 18*mm, 22*mm, 12*mm, 12*mm, 25*mm, 25*mm]
        hdrs  = [
            "Barcode", "Description", "Pack Size",
            "Ordered", "Received", "Rcvd Units", "Cost ex. GST",
            "Tax %", "Promo", "Line ex. GST", "Line inc. GST",
        ]
        tbl_data = [[Paragraph(h, _s(8, bold=True, align=TA_CENTER)) for h in hdrs]]

        for i, line in enumerate(lines):
            product   = product_ctrl.get_product_by_barcode(line['barcode'])
            pack_qty  = int(product['pack_qty'])  if product and product['pack_qty']  else 1
            pack_unit = (product['pack_unit'] or 'EA') if product else 'EA'
            tax_rate  = float(product['tax_rate']) if product and product['tax_rate'] else 0.0
            pack_str  = f"{pack_qty}×{pack_unit}" if pack_qty > 1 else pack_unit

            cost         = float(line['actual_cost'] or line['unit_cost'] or 0)
            recv_cartons = int(line['received_qty'] or 0)
            recv_units   = recv_cartons * pack_qty
            line_ex      = round(recv_units * cost, 2)
            line_gst     = round(line_ex * tax_rate / 100, 2)
            line_inc     = round(line_ex + line_gst, 2)

            bg = C_LGREY if i % 2 == 1 else colors.white
            tbl_data.append([
                Paragraph(line['barcode'],              _s(8, align=TA_CENTER)),
                Paragraph(line['description'],          _s(8)),
                Paragraph(pack_str,                     _s(8, align=TA_CENTER)),
                Paragraph(str(int(line['ordered_qty'])),_s(8, align=TA_CENTER)),
                Paragraph(str(recv_cartons),            _s(8, align=TA_CENTER)),
                Paragraph(str(recv_units),              _s(8, align=TA_CENTER)),
                Paragraph(f"${cost:.4f}",               _s(8, align=TA_RIGHT)),
                Paragraph(f"{tax_rate:.0f}%",           _s(8, align=TA_CENTER)),
                Paragraph("Yes" if line['is_promo'] else "No", _s(8, align=TA_CENTER)),
                Paragraph(f"${line_ex:.2f}",            _s(8, align=TA_RIGHT)),
                Paragraph(f"${line_inc:.2f}",           _s(8, align=TA_RIGHT)),
            ])

        lines_style = TableStyle([
            ("BACKGROUND",   (0,0), (-1,0),  C_LGREY),
            ("GRID",         (0,0), (-1,-1), 0.3, C_BORDER),
            ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, C_LGREY]),
            ("TOPPADDING",   (0,0), (-1,-1), 2),
            ("BOTTOMPADDING",(0,0), (-1,-1), 2),
        ])
        story.append(Table(tbl_data, colWidths=col_w, style=lines_style, repeatRows=1))

        # ── Charges ──────────────────────────────────────────────────────────
        if charges:
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph("Additional Charges", _s(10, bold=True)))
            story.append(Spacer(1, 2*mm))

            chg_data = [[
                Paragraph(h, _s(8, bold=True))
                for h in ["Description", "Tax %", "Amount ex. GST", "Amount inc. GST"]
            ]]
            for i, c in enumerate(charges):
                amt_inc = float(c['amount_inc_tax'])
                tax_r   = float(c['tax_rate'])
                amt_ex  = round(amt_inc / (1 + tax_r / 100), 2) if tax_r > 0 else amt_inc
                gst     = round(amt_inc - amt_ex, 2)
                chg_data.append([
                    Paragraph(c['description'],          _s(8)),
                    Paragraph(f"{tax_r:.0f}%",           _s(8, align=TA_CENTER)),
                    Paragraph(f"${amt_ex:.2f}",          _s(8, align=TA_RIGHT)),
                    Paragraph(f"${amt_inc:.2f}",         _s(8, align=TA_RIGHT)),
                ])
            story.append(Table(
                chg_data,
                colWidths=[100*mm, 25*mm, 40*mm, 40*mm],
                style=TableStyle([
                    ("BACKGROUND",   (0,0),(-1,0),  C_LGREY),
                    ("GRID",         (0,0),(-1,-1), 0.3, C_BORDER),
                    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, C_LGREY]),
                    ("TOPPADDING",   (0,0),(-1,-1), 2),
                    ("BOTTOMPADDING",(0,0),(-1,-1), 2),
                ]),
            ))

        doc.build(story)

        import subprocess, sys
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

    def _reverse(self):
        po    = po_ctrl.get_po_by_id(self.po_id)
        lines = po_ctrl.get_po_lines(self.po_id)

        summary_lines = []
        for line in lines:
            received = int(line['received_qty'] or 0)
            if received > 0:
                product  = product_ctrl.get_product_by_barcode(line['barcode'])
                pack_qty = int(product['pack_qty']) if product and product['pack_qty'] else 1
                units    = received * pack_qty
                summary_lines.append(f"  • {line['description']}: -{units} units")

        if not summary_lines:
            QMessageBox.information(self, "Nothing to Reverse",
                                    "No received quantities found on this PO.")
            return

        summary = "\n".join(summary_lines[:10])
        if len(summary_lines) > 10:
            summary += f"\n  ... and {len(summary_lines) - 10} more lines"

        reply = QMessageBox.warning(
            self, "Confirm PO Reversal",
            f"This will REVERSE {po['po_number']} — {po['supplier_name']}.\n\n"
            f"The following stock will be REMOVED from inventory:\n\n"
            f"{summary}\n\n"
            f"This action cannot be undone. The PO will be marked REVERSED.\n\n"
            f"Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            po_ctrl.reverse_po(self.po_id)
            QMessageBox.information(
                self, "PO Reversed",
                f"{po['po_number']} has been reversed.\n"
                f"Stock on hand has been reduced accordingly.\n"
                f"Movement history has been updated."
            )
            if self.on_close:
                self.on_close()
            self.close()
        except Exception as e:
            show_error(self, "Could not reverse purchase order.", e, title="Reversal Failed")
