from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class POList(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Purchase Orders — coming soon"))
