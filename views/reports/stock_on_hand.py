from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget
)
from views.reports.stock_valuation import StockValuationReport
from views.reports.reorder_report import ReorderReport
from views.reports.movement_history import MovementHistoryReport
from views.reports.gp_report import GPReport
from views.reports.supplier_sales_report import SupplierSalesReport
from views.reports.writeoff_report import WriteOffReport
from views.reports.gst_report import GSTReport
from views.reports.sales_report_view import SalesReportView
from views.reports.liquor_report import LiquorReport


class StockOnHandReport(QWidget):
    """Main Reports screen — tabbed interface."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        tabs.addTab(SalesReportView(),        "📈 Sales")
        tabs.addTab(GSTReport(),              "🧾 GST / BAS")
        tabs.addTab(ReorderReport(),          "⚠  Reorder")
        tabs.addTab(StockValuationReport(),   "💰 Stock Valuation")
        tabs.addTab(GPReport(),               "📊 Gross Profit")
        tabs.addTab(MovementHistoryReport(),  "📋 Movement History")
        tabs.addTab(SupplierSalesReport(),    "🏪 Supplier Sales")
        tabs.addTab(WriteOffReport(),         "🗑  Write-Offs")
        tabs.addTab(LiquorReport(),           "🍺 Liquor Tracking")
        layout.addWidget(tabs)
