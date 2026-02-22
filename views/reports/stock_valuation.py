from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class StockValuation(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stock Valuation — coming soon"))
