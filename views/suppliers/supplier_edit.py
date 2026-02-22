from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class SupplierEdit(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Supplier Edit — coming soon"))
