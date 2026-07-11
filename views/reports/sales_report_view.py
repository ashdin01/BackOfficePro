from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDateEdit, QFileDialog, QMessageBox, QTabWidget, QFrame,
    QMenu, QDialog, QLineEdit, QAbstractItemView, QScrollArea,
    QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QTextEdit,
    QApplication,
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QAction, QKeySequence, QShortcut
import csv, os, logging
import config.styles as styles
import controllers.sales_report_controller as sales_ctrl
from views.base_view import BaseView
from views.widgets.table_items import NumItem, item as _item, RIGHT, CENTER
from views.widgets.table_utils import make_table as _make_table
from views.reports.sales_plu_dialogs import (
    _AddProductDialog, _MatchItemDialog,
    _ensure_plu_map_table, _save_plu_map, _backfill_sale_movements, _load_plu_map,
    _get_all_products, _fuzzy_score, _plu_score,
)


def _stat_card(label, value, color=None):
    if color is None:
        color = styles.CLR_BLUE
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background: {styles.CLR_BG_PANEL};
            border-radius: 8px;
            border-left: 4px solid {color};
        }}
    """)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")
    lbl_lbl = QLabel(label)
    lbl_lbl.setStyleSheet(f"font-size: 11px; color: {styles.CLR_MUTED};")
    layout.addWidget(val_lbl)
    layout.addWidget(lbl_lbl)
    return frame, val_lbl, lbl_lbl


# ─────────────────────────────────────────────────────────────────────────────
# Main Sales Report View
# ─────────────────────────────────────────────────────────────────────────────
class SalesReportView(BaseView):
    def __init__(self):
        super().__init__()
        _ensure_plu_map_table()   # create plu_barcode_map if not exists
        self._build_ui()
        self.load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Sales Report")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setMinimumHeight(34)
        filter_row.addWidget(self.date_from)

        filter_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setMinimumHeight(34)
        filter_row.addWidget(self.date_to)

        filter_row.addWidget(QLabel("Group:"))
        self.group_filter = QComboBox()
        self.group_filter.addItem("All Groups", None)
        self.group_filter.setMinimumHeight(34)
        filter_row.addWidget(self.group_filter)

        load_btn = QPushButton("Apply")
        load_btn.setMinimumHeight(34)
        load_btn.setStyleSheet(f"background:{styles.CLR_ACCENT};color:white;font-weight:bold;padding:0 16px;")
        load_btn.clicked.connect(self._load)
        filter_row.addWidget(load_btn)

        import_btn = QPushButton("⬆  Import Sales")
        import_btn.setMinimumHeight(34)
        import_btn.setStyleSheet(styles.STYLE_BTN_SUCCESS)
        import_btn.clicked.connect(self._import_sales)
        filter_row.addWidget(import_btn)

        export_btn = QPushButton("⬇  Export CSV")
        export_btn.setMinimumHeight(34)
        export_btn.clicked.connect(self._export)
        filter_row.addWidget(export_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Stat cards
        cards_row = QHBoxLayout()
        self._card_revenue, self._val_revenue, _ = _stat_card("Net Revenue",      "$0.00", styles.CLR_SUCCESS_ALT)
        self._card_qty,     self._val_qty,     _ = _stat_card("Total Items Sold", "0",     styles.CLR_BLUE)
        self._card_days,    self._val_days,    _ = _stat_card("Days of Data",     "0",     styles.CLR_ORANGE)
        self._card_top,     self._val_top, self._lbl_top = _stat_card("Top Seller", "—",  styles.CLR_PURPLE)
        for c in [self._card_revenue, self._card_qty, self._card_days, self._card_top]:
            cards_row.addWidget(c)
        layout.addLayout(cards_row)

        # Unmatched-PLU banner — hidden when there's nothing to flag. A PLU
        # with no barcode match never had its sales deducted from stock on
        # hand, so this is the proactive alternative to noticing a wrong
        # SOH somewhere else and hunting for the cause.
        self.unmatched_banner = QLabel("")
        self.unmatched_banner.setStyleSheet(
            f"color:{styles.CLR_DANGER};font-weight:bold;font-size:12px;"
            f"background:{styles.CLR_BG_PANEL};border:1px solid {styles.CLR_DANGER};"
            "border-radius:4px;padding:8px 12px;"
        )
        self.unmatched_banner.setVisible(False)
        layout.addWidget(self.unmatched_banner)

        # Tabs
        tabs = QTabWidget()

        # Col: 0=Barcode 1=PLU 2=Description 3=Department
        #      4=On Hand 5=Total Qty 6=Total Sales$ 7=Avg/Day$ 8=%Sales
        self.product_table = _make_table(
            ["Barcode", "PLU", "Description", "Department",
             "On Hand", "Total Qty", "Total Sales $", "Avg/Day $", "% of Sales"],
            stretch_col=2   # Description stretches
        )
        # All columns interactively resizable; Description fills remaining space
        _hdr = self.product_table.horizontalHeader()
        for _c in range(9):
            _hdr.setSectionResizeMode(_c, QHeaderView.ResizeMode.Interactive)
        _hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.product_table.setColumnWidth(0, 110)  # Barcode
        self.product_table.setColumnWidth(1, 55)   # PLU
        # col 2 Description stretches
        self.product_table.setColumnWidth(3, 120)  # Department
        self.product_table.setColumnWidth(4, 70)   # On Hand
        self.product_table.setColumnWidth(5, 80)   # Total Qty
        self.product_table.setColumnWidth(6, 110)  # Total Sales $
        self.product_table.setColumnWidth(7, 95)   # Avg/Day $
        self.product_table.setColumnWidth(8, 85)   # % of Sales

        # Right-click context menu
        self.product_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.product_table.customContextMenuRequested.connect(self._show_context_menu)
        self.product_table.doubleClicked.connect(
            lambda idx: self._open_match(self._get_row_data(idx.row())))

        tabs.addTab(self.product_table, "By Product")

        # Tab 2: By Day
        self.day_table = _make_table(
            ["Date", "Items Sold", "Total Sales $", "Discount $", "Net Sales $"],
            stretch_col=0)
        self.day_table.setColumnWidth(0, 120)
        tabs.addTab(self.day_table, "By Day")

        # Tab 3: By Sub Group
        self.group_table = _make_table(
            ["Sub Group", "Total Qty", "Total Sales $", "% of Sales"],
            stretch_col=0)
        tabs.addTab(self.group_table, "By Sub Group")

        layout.addWidget(tabs)

        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet(f"color:{styles.CLR_MUTED};font-size:11px;")
        layout.addWidget(self.footer_label)

    # ── Data loading ──────────────────────────────────────────────────────────
    def _get_dates(self):
        return (self.date_from.date().toString("yyyy-MM-dd"),
                self.date_to.date().toString("yyyy-MM-dd"))

    def _load_groups(self):
        try:
            groups = sales_ctrl.get_sales_groups()
            current = self.group_filter.currentData()
            self.group_filter.blockSignals(True)
            self.group_filter.clear()
            self.group_filter.addItem("All Groups", None)
            for g in groups:
                self.group_filter.addItem(g, g)
            idx = self.group_filter.findData(current)
            if idx >= 0:
                self.group_filter.setCurrentIndex(idx)
            self.group_filter.blockSignals(False)
        except Exception:
            logging.exception("sales_report_view: group filter reload failed")

    def _load(self):
        if not sales_ctrl.sales_table_exists():
            self.footer_label.setText(
                "No sales data yet — import a CSV using the ⬆ Import Sales button.")
            self.unmatched_banner.setVisible(False)
            return

        d_from, d_to = self._get_dates()
        group = self.group_filter.currentData()

        stats      = sales_ctrl.get_sales_stats(d_from, d_to, group)
        total_rev  = stats['total_rev']
        total_qty  = stats['total_qty']
        total_days = stats['total_days']

        self._val_revenue.setText(f"${total_rev:,.2f}")
        self._val_qty.setText(f"{int(total_qty):,}")
        self._val_days.setText(str(total_days))
        self._val_top.setText(f"${stats['top_sales']:,.2f}" if stats['top_sales'] is not None else "—")
        self._lbl_top.setText(stats['top_name'] if stats['top_name'] else "Top Seller")

        # ── By Product ────────────────────────────────────────────────────────
        all_prods = sales_ctrl.get_products_with_stock()

        # Build lookup: plu_int → product dict
        # Barcode format in this store is zero-padded PLU, e.g. PLU 39 → barcode "0200039"
        plu_to_prod = {}
        bc_to_prod  = {}
        for p in all_prods:
            bc = p["barcode"] or ""
            bc_to_prod[bc] = p
            # Strip leading zeros to get PLU integer
            stripped = bc.lstrip("0")
            if stripped.isdigit():
                plu_to_prod[int(stripped)] = p
            # Also index by plu if numeric
            sku = p.get("plu") or ""
            if sku.isdigit():
                plu_to_prod[int(sku)] = p
            # Store-specific: barcode format is "02" + zero-padded PLU
            # e.g. PLU 598 → barcode "0200598" → strip "02" prefix → "00598" → 598
            if bc.startswith("02") and len(bc) == 7:
                inner = bc[2:].lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p
            # Also handle 7-digit barcodes starting with 0 (pure zero-padded PLU)
            if len(bc) == 7 and bc.startswith("0") and not bc.startswith("02"):
                inner = bc.lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p

        # Priority-0: persistent PLU→barcode map (set by operator via Match Item)
        saved_plu_map = _load_plu_map()   # {plu_int: barcode}

        # Sales aggregates per PLU
        products = sales_ctrl.get_sales_by_product(d_from, d_to, group)

        self.product_table.setSortingEnabled(False)
        self.product_table.setRowCount(0)

        unmatched_count = 0
        for row in products:
            plu      = row['plu']       or ""
            plu_name = row['plu_name']  or ""
            sub_grp  = row['sub_group'] or ""
            qty      = row['qty']       or 0
            sales    = row['sales']     or 0
            avg_day  = row['avg_day']   or 0
            pct      = (sales / total_rev * 100) if total_rev else 0

            # ── Product lookup (priority order) ──────────────────────────
            # 0. Persistent PLU map (operator-confirmed matches)
            prod = None
            try:
                plu_int = int(str(plu).strip())
                saved_bc = saved_plu_map.get(plu_int)
                if saved_bc:
                    prod = bc_to_prod.get(saved_bc)
            except (ValueError, TypeError):
                plu_int = None
            # 1. PLU integer → zero-padded barcode lookup
            if prod is None and plu_int is not None:
                prod = plu_to_prod.get(plu_int)
            # 2. PLU itself is a barcode
            if prod is None:
                prod = bc_to_prod.get(str(plu).strip())
            # 3. Auto-assign: PLU exactly matches product plu field
            if prod is None and plu_int is not None:
                for p in all_prods:
                    try:
                        if int(str(p.get("plu") or "").strip()) == plu_int:
                            prod = p
                            _save_plu_map(plu_int, p["barcode"])
                            break
                    except (ValueError, TypeError):
                        pass
            # 3. No match → prod stays None; row still shown with empty product fields

            barcode      = prod["barcode"]       if prod else ""
            # If matched: use DB description only.
            # If unmatched: combine plu_name + sub_group (PDF parser splits the name across both)
            if prod:
                description = prod["description"]
            else:
                # sub_group often contains the rest of the product name truncated by PDF parser
                # e.g. plu_name="QUINCEY", sub_group="JONES REAL TOMATO SAUCE GROCERY ALL"
                # Strip trailing dept/category words that aren't part of the name
                raw = plu_name.strip()
                description = raw
            dept_name    = prod["dept_name"]     if prod else ""
            sell_price   = prod["sell_price"]    if prod else 0
            cost_price   = prod["cost_price"]    if prod else 0
            on_hand      = prod["on_hand"]       if prod else ""

            if not barcode:
                unmatched_count += 1

            r = self.product_table.rowCount()
            self.product_table.insertRow(r)

            bc_item = _item(barcode, CENTER)
            if not barcode:
                bc_item.setForeground(QColor(styles.CLR_DANGER))   # red = unmatched

            desc_item = _item(description)
            desc_item.setData(Qt.ItemDataRole.UserRole, {
                "plu":         plu,
                "plu_name":    plu_name,
                "sub_group":   sub_grp,
                "barcode":     barcode,
                "total_qty":   qty,
                "total_sales": sales,
                "sell_price":  sell_price,
                "dept_name":   dept_name,
            })

            pct_item = _item(f"{pct:.1f}%", RIGHT, numeric=True)
            if pct > 5:
                pct_item.setForeground(QColor(styles.CLR_SUCCESS_ALT))

            on_hand_item = _item(
                f"{on_hand:.0f}" if on_hand != "" else "—", RIGHT, numeric=bool(on_hand)
            )
            if isinstance(on_hand, (int, float)) and on_hand < 0:
                on_hand_item.setForeground(QColor(styles.CLR_DANGER))

            self.product_table.setItem(r, 0, bc_item)
            self.product_table.setItem(r, 1, _item(str(plu), CENTER))
            self.product_table.setItem(r, 2, desc_item)
            self.product_table.setItem(r, 3, _item(dept_name))
            self.product_table.setItem(r, 4, on_hand_item)
            self.product_table.setItem(r, 5, _item(f"{qty:.0f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 6, _item(f"${sales:.2f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 7, _item(f"${avg_day:.2f}", RIGHT, numeric=True))
            self.product_table.setItem(r, 8, pct_item)

        self.product_table.setSortingEnabled(True)

        if unmatched_count:
            self.unmatched_banner.setText(
                f"⚠  {unmatched_count} unmatched PLU{'s' if unmatched_count != 1 else ''} in this "
                "date range — sales were recorded but stock on hand was NOT adjusted for them. "
                "Double-click a row with a red barcode in By Product to match it."
            )
            self.unmatched_banner.setVisible(True)
        else:
            self.unmatched_banner.setVisible(False)

        # By Day
        days = sales_ctrl.get_sales_by_day(d_from, d_to, group)
        self.day_table.setSortingEnabled(False)
        self.day_table.setRowCount(0)
        for row in days:
            r = self.day_table.rowCount(); self.day_table.insertRow(r)
            self.day_table.setItem(r, 0, _item(row['sale_date'] or ""))
            self.day_table.setItem(r, 1, _item(f"{row['quantity']:.0f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 2, _item(f"${row['sales_dollars']:.2f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 3, _item(f"${abs(row['discount']):.2f}", RIGHT, numeric=True))
            self.day_table.setItem(r, 4, _item(f"${row['net_sales']:.2f}", RIGHT, numeric=True))
        self.day_table.setSortingEnabled(True)

        # By Group
        groups = sales_ctrl.get_sales_by_group(d_from, d_to, group)
        self.group_table.setSortingEnabled(False)
        self.group_table.setRowCount(0)
        for row in groups:
            r = self.group_table.rowCount(); self.group_table.insertRow(r)
            pct = (row['sales_dollars'] / total_rev * 100) if total_rev else 0
            self.group_table.setItem(r, 0, _item(row['sub_group'] or ""))
            self.group_table.setItem(r, 1, _item(f"{row['quantity']:.0f}", RIGHT, numeric=True))
            self.group_table.setItem(r, 2, _item(f"${row['sales_dollars']:.2f}", RIGHT, numeric=True))
            self.group_table.setItem(r, 3, _item(f"{pct:.1f}%", RIGHT, numeric=True))
        self.group_table.setSortingEnabled(True)

        self._load_groups()
        self.footer_label.setText(
            f"Showing data from {d_from} to {d_to}  |  "
            f"{len(products)} products  |  {total_days} days  "
            f"  ·  Right-click any row to match or add a product"
        )

    # ── Right-click ───────────────────────────────────────────────────────────
    def _get_row_data(self, row_idx: int) -> dict:
        item = self.product_table.item(row_idx, 2)   # Name column holds UserRole data
        return item.data(Qt.ItemDataRole.UserRole) if item else {}

    def _show_context_menu(self, pos):
        row_idx = self.product_table.rowAt(pos.y())
        if row_idx < 0: return
        row_data = self._get_row_data(row_idx)
        if not row_data: return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu{{background:{styles.CLR_BG_PANEL};border:1px solid {styles.CLR_BORDER};
                  color:{styles.CLR_TEXT};font-size:12px;padding:4px;}}
            QMenu::item{{padding:7px 20px;border-radius:4px;}}
            QMenu::item:selected{{background:{styles.CLR_ACCENT};}}
            QMenu::separator{{height:1px;background:{styles.CLR_BORDER};margin:4px 8px;}}
        """)

        act_match = QAction("🔗  Match Item…", self)
        act_match.triggered.connect(lambda: self._open_match(row_data))
        menu.addAction(act_match)

        menu.addSeparator()

        act_view = QAction("👁  View Product", self)
        act_view.triggered.connect(lambda: self._view_product(row_data))
        if not row_data.get("barcode"):
            act_view.setEnabled(False)
        menu.addAction(act_view)

        menu.exec(self.product_table.viewport().mapToGlobal(pos))

    def _open_match(self, row_data: dict):
        if not row_data: return

        # Auto-assign if exactly one score-100 candidate exists
        all_prods = _get_all_products()
        query = row_data.get("plu_name", "")
        sales_plu = row_data.get("plu", "")
        perfect = []
        for p in all_prods:
            s = _fuzzy_score(query, p.get("description", ""))
            if p.get("barcode","").lower().startswith(str(sales_plu).lower()) and str(sales_plu).isdigit():
                s = 98
            if _plu_score(sales_plu, p.get("plu","")) == 100:
                s = 100
            if s == 100:
                perfect.append(p)
        if len(perfect) == 1:
            _save_plu_map(row_data.get("plu"), perfect[0]["barcode"])
            self.load()
            return

        # Otherwise open dialog for manual selection
        dlg = _MatchItemDialog(row_data, parent=self)
        if dlg.exec():
            self.load()

    def _view_product(self, row_data: dict):
        import controllers.product_controller as product_ctrl
        bc = row_data.get("barcode","").strip()
        if not bc: return
        prod = product_ctrl.get_product_by_barcode(bc)
        if prod:
            QMessageBox.information(self, "Product",
                f"Barcode:     {prod['barcode']}\n"
                f"Description: {prod['description']}\n"
                f"Department:  {prod.get('dept_name','')}\n"
                f"Sell Price:  ${prod.get('sell_price',0):.2f}\n"
                f"Cost Price:  ${prod.get('cost_price',0):.2f}")
        else:
            QMessageBox.warning(self, "Not Found", f"No product for barcode {bc!r}")

    # ── Import / Export ───────────────────────────────────────────────────────
    def _import_sales(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Daily PLU Sales File(s)",
            os.path.expanduser("~/Downloads"),
            "CSV Files (*.csv)")
        if not paths: return

        from views.home_screen import _run_import
        success, message = _run_import(self, paths)
        if success:
            QMessageBox.information(self, "Import Complete", message)
        else:
            QMessageBox.warning(self, "Import Issue", message)

        self.load()

    def _export(self):
        d_from, d_to = self._get_dates()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Sales CSV",
            f"sales_{d_from}_to_{d_to}.csv", "CSV (*.csv)")
        if not path: return

        group  = self.group_filter.currentData()
        where  = "WHERE sd.sale_date BETWEEN ? AND ?"
        params = [d_from, d_to]
        if group:
            where += " AND sd.sub_group = ?"
            params.append(group)

        stats      = sales_ctrl.get_sales_stats(d_from, d_to, group)
        total_rev  = stats['total_rev']
        total_days = stats['total_days'] or 1

        agg_rows  = sales_ctrl.get_sales_by_product(d_from, d_to, group)
        all_prods = sales_ctrl.get_products_with_stock()
        bc_to_prod  = {p["barcode"]: p for p in all_prods}
        plu_to_prod = {}
        for p in all_prods:
            bc = p["barcode"] or ""
            stripped = bc.lstrip("0")
            if stripped.isdigit():
                plu_to_prod[int(stripped)] = p
            sku = p.get("plu") or ""
            if sku.isdigit():
                plu_to_prod[int(sku)] = p
            if bc.startswith("02") and len(bc) == 7:
                inner = bc[2:].lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p
            if len(bc) == 7 and bc.startswith("0") and not bc.startswith("02"):
                inner = bc.lstrip("0")
                if inner.isdigit():
                    plu_to_prod[int(inner)] = p

        saved_plu_map = _load_plu_map()

        # ── Write CSV ─────────────────────────────────────────────────
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "Barcode", "PLU", "Description", "Sub Group", "Department",
                "On Hand", "Total Qty", "Total Sales $", "Avg/Day $",
                "% of Sales", "Matched"
            ])

            for row in agg_rows:
                plu      = row['plu']       or ""
                plu_name = row['plu_name']  or ""
                sub_grp  = row['sub_group'] or ""
                qty      = row['qty']       or 0
                sales    = row['sales']     or 0
                avg_day  = row['avg_day']   or 0
                pct      = (sales / total_rev * 100) if total_rev else 0

                # Resolve product — same priority order as screen
                prod = None
                try:
                    plu_int  = int(str(plu).strip())
                    saved_bc = saved_plu_map.get(plu_int)
                    if saved_bc:
                        prod = bc_to_prod.get(saved_bc)
                except (ValueError, TypeError):
                    plu_int = None
                if prod is None and plu_int is not None:
                    prod = plu_to_prod.get(plu_int)
                if prod is None:
                    prod = bc_to_prod.get(str(plu).strip())

                barcode   = prod["barcode"]   if prod else ""
                dept      = prod["dept_name"] if prod else ""
                on_hand   = prod["on_hand"]   if prod else ""
                desc      = prod["description"] if prod else plu_name
                matched   = "Yes" if prod else "No"

                w.writerow([
                    f'="{barcode}"' if barcode else "",
                    plu,
                    desc,
                    sub_grp,
                    dept,
                    f"{on_hand:.0f}" if on_hand != "" else "",
                    f"{qty:.0f}",
                    f"{sales:.2f}",
                    f"{avg_day:.2f}",
                    f"{pct:.1f}%",
                    matched,
                ])

        matched_count   = sum(1 for r in agg_rows
                              if saved_plu_map.get(
                                  int(str(r['plu']).strip()) if str(r['plu']).strip().isdigit() else -1
                              ) or plu_to_prod.get(
                                  int(str(r['plu']).strip()) if str(r['plu']).strip().isdigit() else -1
                              ))
        unmatched_count = len(agg_rows) - matched_count
        QMessageBox.information(
            self, "Exported",
            f"Saved to {path}\n\n"
            f"{len(agg_rows)} products exported\n"
            f"Matched: {matched_count}  |  Unmatched: {unmatched_count}"
        )
