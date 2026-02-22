from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class POHistory(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PO History — coming soon"))
