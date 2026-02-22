from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class POReceive(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Receive PO — coming soon"))
