from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QMessageBox, QFrame,
    QFileDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QShortcut, QKeySequence
import csv, os
from utils.error_dialog import show_error
from utils.po_type_helpers import fmt_money
from views.purchase_orders.po_history_data import compute_po_history_data
import config.styles as styles
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
            'RECEIVED': styles.CLR_SUCCESS_ALT, 'CANCELLED': styles.CLR_DANGER_ALT,
            'REVERSED': styles.CLR_PURPLE, 'PARTIAL':   styles.CLR_ORANGE,
        }.get(po['status'], styles.CLR_MUTED)

        inv_num = po['supplier_invoice_number'] or '—'
        self.header = QLabel(
            f"<b>{po['po_number']}</b> &nbsp;—&nbsp; {po['supplier_name']} &nbsp;—&nbsp; "
            f"Status: <b style='color:{status_colour}'>{po['status']}</b>"
            f"&nbsp;&nbsp;&nbsp;"
            f"{styles.html_span('Supplier Invoice:', styles.CLR_MUTED)} "
            f"{styles.html_bold(inv_num, styles.CLR_TEXT)}"
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
                parts.append(f"{styles.html_span('Account Name:', styles.CLR_MUTED)} "
                             f"{styles.html_bold(bank_name, styles.CLR_TEXT)}")
            if bank_bsb:
                parts.append(f"{styles.html_span('BSB:', styles.CLR_MUTED)} "
                             f"{styles.html_bold(bank_bsb, styles.CLR_TEXT)}")
            if bank_acct:
                parts.append(f"{styles.html_span('Account:', styles.CLR_MUTED)} "
                             f"{styles.html_bold(bank_acct, styles.CLR_TEXT)}")
            self.bank_lbl = QLabel("&nbsp;&nbsp;&nbsp;".join(parts))
            self.bank_lbl.setTextFormat(Qt.TextFormat.RichText)
            self.bank_lbl.setStyleSheet("font-size: 11px; margin-bottom: 2px;")
            layout.addWidget(self.bank_lbl)

        # ── Lines table ──────────────────────────────────────────────────────
        line_lbl = QLabel("Order Lines")
        line_lbl.setStyleSheet(f"font-weight: bold; color: {styles.CLR_MUTED}; font-size: 11px;"
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
            chg_lbl.setStyleSheet(f"font-weight: bold; color: {styles.CLR_MUTED}; font-size: 11px;"
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
        sep.setStyleSheet(styles.STYLE_SEPARATOR)
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
                f"QPushButton{{background:{styles.CLR_PURPLE_DARK};color:white;font-weight:bold;"
                "border:none;border-radius:4px;padding:0 16px;}"
                f"QPushButton:hover{{background:{styles.CLR_PURPLE_HOVER};}}"
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
        data = compute_po_history_data(self.po_id, po=po)

        self.table.setRowCount(len(data.lines))
        for r, ld in enumerate(data.lines):
            recv_colour  = styles.CLR_SUCCESS_ALT if ld.recv_units != 0 else None
            promo_colour = styles.CLR_AMBER if ld.is_promo else None
            desc = ld.description + ("  ★ promo" if ld.is_promo else "")

            self.table.setItem(r, 0, _item(ld.barcode, _CENTER))
            self.table.setItem(r, 1, _item(desc, colour=promo_colour))
            self.table.setItem(r, 2, _item(ld.pack_str, _CENTER))
            self.table.setItem(r, 3, _item(str(ld.ordered_disp), _CENTER))
            self.table.setItem(r, 4, _item(str(ld.recv_units), _CENTER, colour=recv_colour))
            self.table.setItem(r, 5, _item(f"${ld.cost:.4f}", _RIGHT))
            self.table.setItem(r, 6, _item(
                f"{ld.tax_rate:.0f}%" if ld.tax_rate > 0 else "Free", _CENTER,
                colour=styles.CLR_SUCCESS_ALT if ld.tax_rate > 0 else '#555'))
            self.table.setItem(r, 7, _item(fmt_money(ld.line_ex), _RIGHT))
            self.table.setItem(r, 8, _item(fmt_money(ld.line_inc), _RIGHT,
                                           colour=styles.CLR_SUCCESS_ALT if ld.tax_rate > 0 else None))

        if self.charges_table is not None:
            self.charges_table.setRowCount(len(data.charges))
            for r, cd in enumerate(data.charges):
                self.charges_table.setItem(r, 0, _item(cd.description))
                self.charges_table.setItem(r, 1, _item(
                    f"{cd.tax_r:.0f}%" if cd.tax_r > 0 else "GST Free", _CENTER,
                    colour=styles.CLR_SUCCESS_ALT if cd.tax_r > 0 else '#555'))
                self.charges_table.setItem(r, 2, _item(f"${cd.amt_ex:.2f}", _RIGHT))
                self.charges_table.setItem(r, 3, _item(f"${cd.amt_inc:.2f}", _RIGHT,
                                                        colour=styles.CLR_SUCCESS_ALT if cd.tax_r > 0 else None))

        total_label = "Credit Total" if data.is_return else "Invoice Total"
        self.totals_lbl.setText(
            f"Subtotal ex. GST: <b>{fmt_money(data.grand_ex)}</b>"
            f"&nbsp;&nbsp;&nbsp;GST: <b>{fmt_money(data.grand_gst)}</b>"
            f"&nbsp;&nbsp;&nbsp;{total_label} inc. GST: "
            f"<b style='color:{styles.CLR_SUCCESS_ALT}; font-size:14px;'>{fmt_money(data.grand_inc)}</b>"
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

        data = compute_po_history_data(self.po_id, po=po)

        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)

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

            w.writerow([
                "Barcode", "Description", "Pack Size",
                "Ordered (units)", "Received (units)",
                "Cost ex. GST", "Tax %", "Promo",
                "Line Total ex. GST", "Line Total inc. GST",
            ] if data.unit_mode else [
                "Barcode", "Description", "Pack Size",
                "Ordered (cartons)", "Received (cartons)", "Received (units)",
                "Cost ex. GST", "Tax %", "Promo",
                "Line Total ex. GST", "Line Total inc. GST",
            ])

            for ld in data.lines:
                if data.unit_mode:
                    w.writerow([
                        ld.barcode, ld.description, ld.pack_str,
                        ld.ordered_disp, ld.recv_units,
                        f"{ld.cost:.4f}", f"{ld.tax_rate:.0f}",
                        "Yes" if ld.is_promo else "No",
                        f"{ld.line_ex:.2f}", f"{ld.line_inc:.2f}",
                    ])
                else:
                    w.writerow([
                        ld.barcode, ld.description, ld.pack_str,
                        ld.ordered_qty_raw, ld.recv_raw, ld.recv_units,
                        f"{ld.cost:.4f}", f"{ld.tax_rate:.0f}",
                        "Yes" if ld.is_promo else "No",
                        f"{ld.line_ex:.2f}", f"{ld.line_inc:.2f}",
                    ])

            if data.charges:
                w.writerow([])
                w.writerow(["Additional Charges"])
                w.writerow(["Description", "Tax %", "Amount ex. GST", "Amount inc. GST"])
                for cd in data.charges:
                    w.writerow([
                        cd.description,
                        f"{cd.tax_r:.0f}",
                        f"{cd.amt_ex:.2f}",
                        f"{cd.amt_inc:.2f}",
                    ])

            total_label = "Credit Total inc. GST" if data.is_return else "Total inc. GST"
            w.writerow([])
            w.writerow(["Subtotal ex. GST", f"{data.grand_ex:.2f}"])
            w.writerow(["GST",              f"{data.grand_gst:.2f}"])
            w.writerow([total_label,        f"{data.grand_inc:.2f}"])

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

        po   = po_ctrl.get_po_by_id(self.po_id)
        data = compute_po_history_data(self.po_id, po=po)

        default_name = f"{po['po_number'].replace('/', '-')}_receipt.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PO Receipt PDF",
            os.path.join(os.path.expanduser("~/Downloads"), default_name),
            "PDF (*.pdf)",
        )
        if not path:
            return

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

        from config.constants import PO_DOC_TITLES
        _doc_title = PO_DOC_TITLES.get(data.po_type, 'PURCHASE ORDER').title()
        story.append(Paragraph(f"{_doc_title} Receipt", _s(16, bold=True)))
        story.append(Spacer(1, 4*mm))

        sup_pdf = supplier_ctrl.get_by_id(po['supplier_id'])
        bk_name_pdf = (sup_pdf['bank_account_name']   or '') if sup_pdf else ''
        bk_bsb_pdf  = (sup_pdf['bank_bsb']            or '') if sup_pdf else ''
        bk_acct_pdf = (sup_pdf['bank_account_number'] or '') if sup_pdf else ''
        inv_pdf     = po['supplier_invoice_number'] or "—"

        total_label = "Credit Total inc. GST:" if data.is_return else "Total inc. GST:"
        right_col = [
            ("Supplier:",         po['supplier_name']),
            ("Received Date:",    po['delivery_date'] or "—"),
            ("Supplier Invoice:", inv_pdf),
            ("Subtotal ex. GST:", fmt_money(data.grand_ex)),
            ("GST:",              fmt_money(data.grand_gst)),
            (total_label,         fmt_money(data.grand_inc)),
        ]
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

        story.append(Paragraph("Order Lines", _s(10, bold=True)))
        story.append(Spacer(1, 2*mm))

        col_w = [28*mm, 70*mm, 18*mm, 16*mm, 16*mm, 18*mm, 22*mm, 12*mm, 12*mm, 25*mm, 25*mm]
        hdrs  = [
            "Barcode", "Description", "Pack Size",
            "Ordered", "Received", "Rcvd Units", "Cost ex. GST",
            "Tax %", "Promo", "Line ex. GST", "Line inc. GST",
        ]
        tbl_data = [[Paragraph(h, _s(8, bold=True, align=TA_CENTER)) for h in hdrs]]

        for ld in data.lines:
            tbl_data.append([
                Paragraph(ld.barcode,                          _s(8, align=TA_CENTER)),
                Paragraph(ld.description,                      _s(8)),
                Paragraph(ld.pack_str,                         _s(8, align=TA_CENTER)),
                Paragraph(str(ld.ordered_disp),                _s(8, align=TA_CENTER)),
                Paragraph(str(ld.recv_raw),                    _s(8, align=TA_CENTER)),
                Paragraph(str(ld.recv_units),                  _s(8, align=TA_CENTER)),
                Paragraph(f"${ld.cost:.4f}",                   _s(8, align=TA_RIGHT)),
                Paragraph(f"{ld.tax_rate:.0f}%",               _s(8, align=TA_CENTER)),
                Paragraph("Yes" if ld.is_promo else "No",      _s(8, align=TA_CENTER)),
                Paragraph(fmt_money(ld.line_ex),               _s(8, align=TA_RIGHT)),
                Paragraph(fmt_money(ld.line_inc),              _s(8, align=TA_RIGHT)),
            ])

        story.append(Table(tbl_data, colWidths=col_w, repeatRows=1, style=TableStyle([
            ("BACKGROUND",     (0,0), (-1,0),  C_LGREY),
            ("GRID",           (0,0), (-1,-1), 0.3, C_BORDER),
            ("FONTNAME",       (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, C_LGREY]),
            ("TOPPADDING",     (0,0), (-1,-1), 2),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 2),
        ])))

        if data.charges:
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph("Additional Charges", _s(10, bold=True)))
            story.append(Spacer(1, 2*mm))
            chg_data = [[
                Paragraph(h, _s(8, bold=True))
                for h in ["Description", "Tax %", "Amount ex. GST", "Amount inc. GST"]
            ]]
            for cd in data.charges:
                chg_data.append([
                    Paragraph(cd.description,      _s(8)),
                    Paragraph(f"{cd.tax_r:.0f}%",  _s(8, align=TA_CENTER)),
                    Paragraph(f"${cd.amt_ex:.2f}", _s(8, align=TA_RIGHT)),
                    Paragraph(f"${cd.amt_inc:.2f}", _s(8, align=TA_RIGHT)),
                ])
            story.append(Table(
                chg_data,
                colWidths=[100*mm, 25*mm, 40*mm, 40*mm],
                style=TableStyle([
                    ("BACKGROUND",    (0,0),(-1,0),  C_LGREY),
                    ("GRID",          (0,0),(-1,-1), 0.3, C_BORDER),
                    ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, C_LGREY]),
                    ("TOPPADDING",    (0,0),(-1,-1), 2),
                    ("BOTTOMPADDING", (0,0),(-1,-1), 2),
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
