from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QComboBox, QMessageBox,
)
from PyQt6.QtGui import QShortcut, QKeySequence


def text_popup(title, label, current, parent=None):
    """Prompt for a required text value. Returns the stripped string or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QLineEdit(current)
    inp.selectAll()
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    result = [None]
    def confirm():
        v = inp.text().strip()
        if not v:
            QMessageBox.warning(dlg, "Validation", f"{label} cannot be empty.")
            return
        result[0] = v
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def text_popup_optional(title, label, current, parent=None):
    """Prompt for an optional text value. Returns the stripped string (may be empty) or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QLineEdit(current or "")
    inp.selectAll()
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    result = [None]
    def confirm():
        result[0] = inp.text().strip()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def price_popup(title, label, current, parent=None):
    """Prompt for a price (4 dp). Returns float or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QDoubleSpinBox()
    inp.setMaximum(99999)
    inp.setDecimals(4)
    inp.setValue(float(current))
    price_row = QHBoxLayout()
    price_row.addWidget(QLabel("$"))
    price_row.addWidget(inp)
    form.addRow(label, price_row)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    result = [None]
    def confirm():
        result[0] = inp.value()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def number_popup(title, label, current, parent=None):
    """Prompt for a whole number. Returns float or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(260)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QDoubleSpinBox()
    inp.setMaximum(99999)
    inp.setDecimals(0)
    inp.setValue(float(current))
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    result = [None]
    def confirm():
        result[0] = inp.value()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    inp.setFocus()
    dlg.exec()
    return result[0]


def choice_popup(title, label, options, current, parent=None):
    """Prompt for a choice from a list. Returns selected string or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    form = QFormLayout()
    inp = QComboBox()
    inp.addItems(options)
    if current in options:
        inp.setCurrentText(current)
    form.addRow(label, inp)
    layout.addLayout(form)
    btns = QHBoxLayout()
    ok = QPushButton("Save  [Ctrl+S]")
    ok.setFixedHeight(32)
    cancel = QPushButton("Cancel  [Esc]")
    cancel.setFixedHeight(32)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    result = [None]
    def confirm():
        result[0] = inp.currentText()
        dlg.accept()
    ok.clicked.connect(confirm)
    cancel.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    dlg.exec()
    return result[0]
