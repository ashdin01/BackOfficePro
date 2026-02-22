from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
class POCreate(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Create PO — coming soon"))
