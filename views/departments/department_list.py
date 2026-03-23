from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QTabWidget, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from utils.keyboard_mixin import KeyboardMixin
import models.department as dept_model
import models.group as group_model


class DepartmentList(KeyboardMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_depts()
        self._load_groups()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dept_tab(),  "🏷  Departments")
        self.tabs.addTab(self._build_group_tab(), "📂  Groups")
        layout.addWidget(self.tabs)

    # ── Departments tab ───────────────────────────────────────────────────────

    def _build_dept_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Departments"))
        top.addStretch()
        btn_add = QPushButton("&Add Department")
        btn_add.clicked.connect(self._add_dept)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.dept_table = QTableWidget()
        self.dept_table.setColumnCount(3)
        self.dept_table.setHorizontalHeaderLabels(["Code", "Name", "Active"])
        self.dept_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dept_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dept_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dept_table.doubleClicked.connect(self._edit_dept)
        layout.addWidget(self.dept_table)

        self.dept_status = QLabel("")
        layout.addWidget(self.dept_status)
        return w

    def _load_depts(self):
        rows = dept_model.get_all(active_only=False)
        self.dept_table.setRowCount(0)
        for row in rows:
            r = self.dept_table.rowCount()
            self.dept_table.insertRow(r)
            self.dept_table.setItem(r, 0, QTableWidgetItem(row['code']))
            self.dept_table.setItem(r, 1, QTableWidgetItem(row['name']))
            active = QTableWidgetItem("Yes" if row['active'] else "No")
            active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.dept_table.setItem(r, 2, active)
            self.dept_table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.dept_status.setText(f"{self.dept_table.rowCount()} departments")

    def _add_dept(self):
        from views.departments.department_edit import DepartmentEdit
        self.edit_win = DepartmentEdit(on_save=self._load_depts)
        self.edit_win.show()

    def _edit_dept(self):
        row = self.dept_table.currentRow()
        if row < 0:
            return
        dept_id = self.dept_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.departments.department_edit import DepartmentEdit
        self.edit_win = DepartmentEdit(dept_id=dept_id, on_save=self._load_depts)
        self.edit_win.show()

    # ── Groups tab ────────────────────────────────────────────────────────────

    def _build_group_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter by Department:"))

        self.dept_filter = QComboBox()
        self.dept_filter.addItem("All Departments", None)
        for d in dept_model.get_all(active_only=False):
            self.dept_filter.addItem(f"{d['code']} — {d['name']}", d['id'])
        self.dept_filter.currentIndexChanged.connect(self._load_groups)
        top.addWidget(self.dept_filter)

        top.addStretch()
        btn_add = QPushButton("&Add Group")
        btn_add.clicked.connect(self._add_group)
        top.addWidget(btn_add)
        layout.addLayout(top)

        self.group_table = QTableWidget()
        self.group_table.setColumnCount(4)
        self.group_table.setHorizontalHeaderLabels([
            "Code", "Name", "Department", "Active"
        ])
        self.group_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.group_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.group_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.group_table.doubleClicked.connect(self._edit_group)
        layout.addWidget(self.group_table)

        self.group_status = QLabel("")
        layout.addWidget(self.group_status)
        return w

    def _load_groups(self):
        dept_id = self.dept_filter.currentData()
        if dept_id:
            rows = group_model.get_by_department(dept_id, active_only=False)
        else:
            rows = group_model.get_all(active_only=False)

        self.group_table.setRowCount(0)
        for row in rows:
            r = self.group_table.rowCount()
            self.group_table.insertRow(r)
            self.group_table.setItem(r, 0, QTableWidgetItem(row['code']))
            self.group_table.setItem(r, 1, QTableWidgetItem(row['name']))
            dept_name = row['dept_name'] if 'dept_name' in row.keys() else ''
            self.group_table.setItem(r, 2, QTableWidgetItem(dept_name))
            active = QTableWidgetItem("Yes" if row['active'] else "No")
            active.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.group_table.setItem(r, 3, active)
            self.group_table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.group_status.setText(f"{self.group_table.rowCount()} groups")

    def _add_group(self):
        preset = self.dept_filter.currentData()
        from views.departments.group_edit import GroupEdit
        self.group_win = GroupEdit(preset_dept_id=preset, on_save=self._load_groups)
        self.group_win.show()

    def _edit_group(self):
        row = self.group_table.currentRow()
        if row < 0:
            return
        group_id = self.group_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        from views.departments.group_edit import GroupEdit
        self.group_win = GroupEdit(group_id=group_id, on_save=self._load_groups)
        self.group_win.show()
