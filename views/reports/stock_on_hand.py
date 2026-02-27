from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget
)
from views.reports.stock_valuation import StockValuationReport
from views.reports.reorder_report import ReorderReport
from views.reports.movement_history import MovementHistoryReport
from views.reports.gp_report import GPReport


class StockOnHandReport(QWidget):
    """Main Reports screen — tabbed interface."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(ReorderReport(),          "⚠  Reorder")
        tabs.addTab(StockValuationReport(),   "💰 Stock Valuation")
        tabs.addTab(GPReport(),               "📊 Gross Profit")
        tabs.addTab(MovementHistoryReport(),  "📋 Movement History")

        layout.addWidget(tabs)
