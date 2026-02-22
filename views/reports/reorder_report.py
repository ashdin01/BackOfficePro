from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ReorderReport(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Reorder Report — coming soon"))
