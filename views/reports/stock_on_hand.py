from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class StockOnHandReport(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stock On Hand Report — coming soon"))
