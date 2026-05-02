from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer
from utils.keyboard_mixin import KeyboardMixin
import models.bundle as bundle_model


class BundleList(KeyboardMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._open_wins = []
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        title = QLabel("Bundles")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #e6edf3;")
        top.addWidget(title)
        top.addStretch()
        btn_add = QPushButton("+ Add Bundle")
        btn_add.setFixedHeight(32)
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)
        layout.addLayout(top)

        note = QLabel(
            "Bundles allow mixed-case selling — e.g. 4 × any eligible 6-pack = 1 carton at bundle price. "
            "Define eligible items per bundle."
        )
        note.setStyleSheet("color: #8b949e; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search bundles...")
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(lambda: self._load(self.search.text()))
        self.search.textChanged.connect(lambda _: self._timer.start())
        layout.addWidget(self.search)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Description", "Required Qty", "Bundle Price", "Active"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 70)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.status)

        self.setup_keyboard(table=self.table)

    def _load(self, search=''):
        rows = bundle_model.get_all(active_only=False)
        if search:
            term = search.lower()
            rows = [r for r in rows if term in r['name'].lower()
                    or term in (r['description'] or '').lower()]
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name_item = QTableWidgetItem(row['name'])
            name_item.setData(Qt.ItemDataRole.UserRole, row['id'])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(row['description'] or ''))
            qty_item = QTableWidgetItem(f"×{row['required_qty']}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, qty_item)
            price_item = QTableWidgetItem(f"${row['price']:.2f}")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 3, price_item)
            active_item = QTableWidgetItem("Yes" if row['active'] else "No")
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not row['active']:
                active_item.setForeground(Qt.GlobalColor.darkGray)
            self.table.setItem(r, 4, active_item)
        self.status.setText(f"{self.table.rowCount()} bundle(s)")

    def _open_win(self, win):
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.show()
        win.raise_()
        win.activateWindow()
        self._open_wins = [w for w in self._open_wins if self._alive(w)]
        self._open_wins.append(win)

    def _alive(self, w):
        try:
            w.isVisible()
            return True
        except RuntimeError:
            return False

    def _add(self):
        from views.bundles.bundle_edit import BundleEdit
        self._open_win(BundleEdit(on_save=self._load))

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        bundle_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.bundles.bundle_edit import BundleEdit
        self._open_win(BundleEdit(bundle_id=bundle_id, on_save=self._load))
