from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ProductEdit(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Product Edit — coming soon"))
