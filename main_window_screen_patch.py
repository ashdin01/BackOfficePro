        import logging
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
            self.stack.addWidget(screen)
