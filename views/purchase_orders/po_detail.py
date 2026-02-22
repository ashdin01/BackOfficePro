from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class PODetail(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PO Detail — coming soon"))
