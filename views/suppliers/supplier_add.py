from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class SupplierAdd(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Supplier Add — coming soon"))
