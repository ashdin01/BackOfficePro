from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class SupplierList(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Supplier List — coming soon"))
