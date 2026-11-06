from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QMessageBox,
)
from PyQt6.QtGui import QShortcut, QKeySequence
from utils.error_dialog import show_error
import controllers.product_controller as product_controller


class MergeProductDialog(QDialog):
    """Merge the open (duplicate) product into another product, keeping the
    other product's price and description."""

    def __init__(self, dup_barcode, dup_description, parent=None):
        super().__init__(parent)
        self.dup = dup_barcode
        self.dup_desc = dup_description
        self._target = None
        self.setWindowTitle("Merge Product")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            f"<b>{dup_description}</b> ({dup_barcode}) will be merged into another "
            "product and then deleted.<br>Its barcode becomes an alternate barcode "
            "of the product you pick, which keeps its own price and description."))
        form = QFormLayout()
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("Barcode or PLU of the product to keep")
        self.inp.returnPressed.connect(self._lookup)
        form.addRow("Merge into", self.inp)
        lay.addLayout(form)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        btns = QHBoxLayout()
        find = QPushButton("Look up")
        find.clicked.connect(self._lookup)
        self.ok = QPushButton("Merge")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._merge)
        cancel = QPushButton("Cancel  [Esc]")
        cancel.clicked.connect(self.reject)
        for b in (find, self.ok, cancel):
            b.setFixedHeight(32)
            btns.addWidget(b)
        lay.addLayout(btns)
        QShortcut(QKeySequence("Escape"), self, self.reject)
        self.inp.setFocus()

    def _lookup(self):
        self._target = None
        self.ok.setEnabled(False)
        row = product_controller.find_merge_target(self.inp.text())
        if row is None:
            self.info.setText("No product found for that barcode or PLU.")
            return
        try:
            p = product_controller.preview_merge(self.dup, row['barcode'])
        except ValueError as e:
            self.info.setText(f"<span style='color:#c0392b'>Cannot merge:<br>{e}</span>")
            return
        self._target = row['barcode']
        k, d = p['keeper'], p['dup']
        lines = [
            f"<b>Keep:</b> {k['description']} ({k['barcode']}), stock {p['keeper_soh']:g}",
            f"<b>Remove:</b> {d['description']} ({d['barcode']}), stock {p['dup_soh']:g}",
            f"New stock on hand: <b>{p['keeper_soh'] + p['dup_soh']:g}</b>",
            f"Moves {p['movements']} stock movements, {p['po_lines']} PO lines "
            f"({p['open_po_lines']} on open POs), {p['stocktake_counts']} stocktake counts, "
            f"{p['aliases']} existing aliases.",
            "A verified backup is taken first. This cannot be undone.",
        ]
        if d.get('plu'):
            lines.append(f"The duplicate's PLU {d['plu']} is dropped.")
        self.info.setText("<br>".join(lines))
        self.ok.setEnabled(True)

    def _merge(self):
        if not self._target:
            return
        if QMessageBox.question(
            self, "Confirm merge",
            f"Merge {self.dup_desc} ({self.dup}) into {self._target} and delete it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            product_controller.merge_products(self.dup, self._target)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot merge", str(e))
            return
        except Exception as e:
            show_error(self, "Could not merge products. Nothing was changed.", e)
            return
        self.merged_into = self._target
        self.accept()
