#!/bin/bash
# BackOfficePro v1.1.21 — Deploy logging + crash reporting + migration fix
# Run this from your BackOfficePro project root:
#   bash deploy_v1.1.21.sh

set -e  # Stop on any error

echo "=== BackOfficePro v1.1.21 Deploy ==="
echo ""

# ── 1. Copy patched files into place ─────────────────────────────────
echo "Copying patched files..."
cp main_logging_patch.py main.py
cp migrations_patch.py database/migrations.py
echo "  main.py updated"
echo "  database/migrations.py updated"
echo ""

# ── 2. Apply the main_window screen patch ────────────────────────────
# This replaces the block from "from views.home_screen" to the closing
# "for screen in self.screens:" block in main_window.py
echo "Patching views/main_window.py..."
python3 - << 'PYEOF'
import re

with open("views/main_window.py", "r") as f:
    content = f.read()

old = """        from views.home_screen import HomeScreen
        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.stock_on_hand import StockOnHandReport
        from views.stocktake.stocktake_list import StocktakeList
        from views.stock_adjust.stock_adjust_view import StockAdjustView
        from views.reports.sales_report_view import SalesReportView

        self.screens = [
            HomeScreen(on_navigate=self._switch),   # index 0
            ProductList(on_escape=lambda: self._switch(0)),  # index 1
            SupplierList(),                          # index 2
            DepartmentList(),                        # index 3
            POList(),                                # index 4
            StockOnHandReport(),                     # index 5
            StocktakeList(),                         # index 6
            StockAdjustView(current_user=self.current_user),  # index 7
            SalesReportView(),                       # index 8
        ]
        for screen in self.screens:
            self.stack.addWidget(screen)"""

new = """        import logging
        from views.home_screen import HomeScreen
        from views.products.product_list import ProductList
        from views.suppliers.supplier_list import SupplierList
        from views.departments.department_list import DepartmentList
        from views.purchase_orders.po_list import POList
        from views.reports.stock_on_hand import StockOnHandReport
        from views.stocktake.stocktake_list import StocktakeList
        from views.stock_adjust.stock_adjust_view import StockAdjustView
        from views.reports.sales_report_view import SalesReportView

        screen_classes = [
            ("HomeScreen",        lambda: HomeScreen(on_navigate=self._switch)),
            ("ProductList",       lambda: ProductList(on_escape=lambda: self._switch(0))),
            ("SupplierList",      lambda: SupplierList()),
            ("DepartmentList",    lambda: DepartmentList()),
            ("POList",            lambda: POList()),
            ("StockOnHandReport", lambda: StockOnHandReport()),
            ("StocktakeList",     lambda: StocktakeList()),
            ("StockAdjustView",   lambda: StockAdjustView(current_user=self.current_user)),
            ("SalesReportView",   lambda: SalesReportView()),
        ]

        self.screens = []
        for name, factory in screen_classes:
            logging.info(f"Initialising screen: {name}")
            try:
                screen = factory()
                self.screens.append(screen)
                logging.info(f"  {name} OK")
            except Exception as e:
                logging.critical(f"  {name} FAILED: {e}", exc_info=True)
                raise

        for screen in self.screens:
            self.stack.addWidget(screen)"""

if old in content:
    content = content.replace(old, new)
    with open("views/main_window.py", "w") as f:
        f.write(content)
    print("  views/main_window.py patched successfully")
else:
    print("  WARNING: Could not find expected block in main_window.py")
    print("  Please apply main_window_screen_patch.py manually")
PYEOF

echo ""

# ── 3. Commit and tag ─────────────────────────────────────────────────
echo "Committing changes..."
git add main.py database/migrations.py views/main_window.py
git commit -m "v1.1.21: Add logging/crash reporting, fix migrate_v7 missing from apply_migrations"

echo ""
echo "Tagging v1.1.21..."
git tag v1.1.21

echo ""
echo "Pushing to GitHub..."
git push origin main
git push origin v1.1.21

echo ""
echo "=== Done! ==="
echo "Build triggered at: https://github.com/ashdin01/BackOfficePro/actions"
echo "Release will appear at: https://github.com/ashdin01/BackOfficePro/releases/tag/v1.1.21"
