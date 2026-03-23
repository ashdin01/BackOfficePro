from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
import models.stocktake as stocktake_model
import models.department as dept_model


class StocktakeList(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        lbl = QLabel("<b>Stocktake Sessions</b>")
        top.addWidget(lbl)
        top.addStretch()
        btn_new = QPushButton("&New Session")
        btn_new.setFixedHeight(32)
        btn_new.clicked.connect(self._new_session)
        top.addWidget(btn_new)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Label", "Department", "Status", "Lines", "Started"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open_session)
        self.table.setColumnWidth(0, 50)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)

        QShortcut(QKeySequence("N"), self, self._new_session)
        QShortcut(QKeySequence("Return"), self, self._open_session)

    def _load(self):
        rows = stocktake_model.get_all_sessions()
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(row['id'])))
            self.table.setItem(r, 1, QTableWidgetItem(row['label']))
            self.table.setItem(r, 2, QTableWidgetItem(row['dept_name'] or 'All Departments'))
            status_item = QTableWidgetItem(row['status'])
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if row['status'] == 'OPEN':
                status_item.setForeground(Qt.GlobalColor.green)
            self.table.setItem(r, 3, status_item)
            lines_item = QTableWidgetItem(str(row['line_count']))
            lines_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, lines_item)
            self.table.setItem(r, 5, QTableWidgetItem(str(row['started_at'])[:16]))
            self.table.item(r, 0).setData(Qt.ItemDataRole.UserRole, row['id'])
        self.status.setText(f"{self.table.rowCount()} sessions")

    def _new_session(self):
        dlg = NewSessionDialog(parent=self)
        if dlg.exec():
            self._load()
            # Auto-open the new session
            session_id = dlg.created_id
            if session_id:
                self._open_by_id(session_id)

    def _open_session(self):
        row = self.table.currentRow()
        if row < 0:
            return
        session_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._open_by_id(session_id)

    def _open_by_id(self, session_id):
        from views.stocktake.stocktake_session import StocktakeSession
        self.session_win = StocktakeSession(session_id=session_id, on_close=self._load)
        self.session_win.show()


class NewSessionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Stocktake Session")
        self.setMinimumWidth(380)
        self.created_id = None
        self._depts = dept_model.get_all()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.label = QLineEdit()
        self.label.setPlaceholderText("e.g. Full Stocktake March 2026")

        self.dept = QComboBox()
        self.dept.addItem("All Departments", None)
        for d in self._depts:
            self.dept.addItem(d['name'], d['id'])

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(60)
        self.notes.setPlaceholderText("Optional notes...")

        form.addRow("Label *", self.label)
        form.addRow("Department", self.dept)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        layout.addSpacing(8)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Create Session")
        ok_btn.setFixedHeight(33)
        ok_btn.clicked.connect(self._create)
        cancel_btn = QPushButton("Cancel  [Esc]")
        cancel_btn.setFixedHeight(33)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, self.reject)
        self.label.setFocus()

    def _create(self):
        label = self.label.text().strip()
        if not label:
            QMessageBox.warning(self, "Validation", "Please enter a label for this session.")
            return
        try:
            self.created_id = stocktake_model.create_session(
                label=label,
                department_id=self.dept.currentData(),
                notes=self.notes.toPlainText(),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
