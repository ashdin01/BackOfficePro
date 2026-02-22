mkdir -p database models controllers utils config assets/icons assets/styles data
mkdir -p views/products views/suppliers views/departments views/purchase_orders views/reports
touch main.py
touch database/__init__.py database/connection.py database/schema.py database/migrations.py
touch models/__init__.py models/product.py models/supplier.py models/department.py models/purchase_order.py models/po_lines.py models/stock_on_hand.py models/barcode.py
touch views/__init__.py views/main_window.py
touch views/products/product_list.py views/products/product_add.py views/products/product_edit.py
touch views/suppliers/supplier_list.py views/suppliers/supplier_add.py views/suppliers/supplier_edit.py
touch views/departments/department_list.py views/departments/department_edit.py
touch views/purchase_orders/po_list.py views/purchase_orders/po_create.py views/purchase_orders/po_detail.py views/purchase_orders/po_receive.py views/purchase_orders/po_history.py
touch views/reports/stock_on_hand.py views/reports/reorder_report.py views/reports/stock_valuation.py
touch controllers/__init__.py controllers/product_controller.py controllers/supplier_controller.py controllers/department_controller.py controllers/po_controller.py controllers/report_controller.py
touch utils/__init__.py utils/barcode_utils.py utils/export.py utils/printer.py utils/validators.py
touch config/settings.py config/constants.py
touch data/.gitkeep
echo "Done!"
