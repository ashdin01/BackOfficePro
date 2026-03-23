from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QComboBox
)
from PyQt6.QtGui import QKeySequence, QShortcut
import models.group as group_model
import models.department as dept_model


class GroupEdit(QWidget):
    def __init__(self, group_id=None, preset_dept_id=None, on_save=None):
        super().__init__()
        self.group_id = group_id
        self.on_save = on_save
        self.setWindowTitle("Edit Group" if group_id else "Add Group")
        self.setMinimumWidth(380)
        self._depts = dept_model.get_all(active_only=False)
        self._build_ui()
        if preset_dept_id:
            # Pre-select department
            for i, d in enumerate(self._depts):
                if d['id'] == preset_dept_id:
                    self.dept.setCurrentIndex(i)
                    break
        if group_id:
            self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.dept = QComboBox()
        for d in self._depts:
            self.dept.addItem(f"{d['code']} — {d['name']}", d['id'])

        self.code = QLineEdit()
        self.code.setPlaceholderText("e.g. APPLES")

        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Apples")

        self.active = QCheckBox("Active")
        self.active.setChecked(True)

        form.addRow("Department *", self.dept)
        form.addRow("Code *", self.code)
        form.addRow("Name *", self.name)
        form.addRow("", self.active)
        layout.addLayout(form)

        layout.addSpacing(10)
        btns = QHBoxLayout()
        save_btn = QPushButton("Save  [Ctrl+S]")
        save_btn.setFixedHeight(35)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(35)
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Escape"), self, self.close)
        self.code.setFocus()

    def _populate(self):
        g = group_model.get_by_id(self.group_id)
        if g:
            for i, d in enumerate(self._depts):
                if d['id'] == g['department_id']:
                    self.dept.setCurrentIndex(i)
                    break
            self.code.setText(g['code'])
            self.name.setText(g['name'])
            self.active.setChecked(bool(g['active']))

    def _save(self):
        dept_id = self.dept.currentData()
        code = self.code.text().strip()
        name = self.name.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Validation", "Code and Name are required.")
            return
        try:
            if self.group_id:
                group_model.update(self.group_id, dept_id, code, name,
                                   int(self.active.isChecked()))
            else:
                group_model.add(dept_id, code, name)
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
