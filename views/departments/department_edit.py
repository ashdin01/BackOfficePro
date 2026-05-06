from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox
)
from utils.keyboard_mixin import KeyboardMixin
from utils.error_dialog import show_error
import models.department as dept_model


class DepartmentEdit(KeyboardMixin, QWidget):
    def __init__(self, dept_id=None, on_save=None):
        super().__init__()
        self.dept_id = dept_id
        self.on_save = on_save
        self.setWindowTitle("Edit Department" if dept_id else "Add Department")
        self.setMinimumWidth(350)
        self._build_ui()
        self.setup_keyboard()
        if dept_id:
            self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.code = QLineEdit()
        self.name = QLineEdit()
        self.active = QCheckBox("Active")
        self.active.setChecked(True)
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

    def _populate(self):
        dept = dept_model.get_by_id(self.dept_id)
        if dept:
            self.code.setText(dept['code'])
            self.name.setText(dept['name'])
            self.active.setChecked(bool(dept['active']))

    def _save(self):
        code = self.code.text().strip()
        name = self.name.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Validation", "Code and Name are required.")
            return
        try:
            if self.dept_id:
                dept_model.update(self.dept_id, code, name, int(self.active.isChecked()))
            else:
                dept_model.add(code, name)
            if self.on_save:
                self.on_save()
            self.close()
        except Exception as e:
            show_error(self, "Could not save department.", e)
