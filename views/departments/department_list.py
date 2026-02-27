from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
from utils.keyboard_mixin import KeyboardMixin
import models.department as dept_model


class DepartmentList(KeyboardMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Departments"))
        top.addStretch()
        btn_add = QPushButton("&Add Department")
        btn_add.clicked.connect(self._add)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Code", "Name", "Active"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.setup_keyboard(table=self.table)

    def _load(self):
        rows = dept_model.get_all(active_only=False)
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row['code']))
            self.table.setItem(r, 1, QTableWidgetItem(row['name']))
            active = QTableWidgetItem("Yes" if row['active'] else "No")
            active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, active)
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.status.setText(f"{self.table.rowCount()} departments")

    def _add(self):
        from views.departments.department_edit import DepartmentEdit
        self.edit_win = DepartmentEdit(on_save=self._load)
        self.edit_win.show()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        dept_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.departments.department_edit import DepartmentEdit
        self.edit_win = DepartmentEdit(dept_id=dept_id, on_save=self._load)
        self.edit_win.show()
