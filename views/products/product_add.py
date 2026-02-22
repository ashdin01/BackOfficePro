from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ProductAdd(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Product Add — coming soon"))
