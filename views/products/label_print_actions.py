"""Shelf-label and Edikio-card printing actions for the Product Detail screen.

Each print action tries the printer configured in Settings > Label Printing
first; if none is configured, or the configured one currently isn't found
(unplugged/renamed), it falls back to a small "how many copies" dialog that
generates a PDF and opens it for the user to print manually. A real failure
from the direct-print call (render error, driver fault) is surfaced as an
error instead of silently falling back.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QPushButton, QSpinBox,
)
from PyQt6.QtGui import QShortcut, QKeySequence
import config.styles as styles
from utils.error_dialog import show_error


def print_shelf_label(parent, *, barcode, description, sell_price, plu, large=False):
    from utils.label_print import get_configured_printer_name, print_label_direct

    printer_name = get_configured_printer_name()
    if printer_name:
        # A printer is configured — print one label straight to it, no
        # dialog. Pressing the button again prints another; that's the
        # whole workflow for printing several labels in a row.
        ok, msg = print_label_direct(
            barcode=barcode, description=description,
            price_inc_gst=sell_price, plu=plu, large=large,
        )
        if ok:
            return
        if "is not available" not in msg:
            show_error(parent, "Could not print the label.", RuntimeError(msg))
            return
        # else: configured printer isn't currently found (unplugged,
        # renamed, etc.) — fall through to the PDF, same as unconfigured.

    print_shelf_label_via_pdf(parent, barcode=barcode, description=description,
                               sell_price=sell_price, plu=plu, large=large)


def print_shelf_label_via_pdf(parent, *, barcode, description, sell_price, plu, large=False):
    """No printer configured (Settings > Label Printing) — fall back to
    generating a PDF and opening it for the user to print manually."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Print Large Shelf Label" if large else "Print Shelf Label")
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    form = QFormLayout()
    copies_spin = QSpinBox()
    copies_spin.setMinimum(1)
    copies_spin.setMaximum(200)
    copies_spin.setValue(1)
    form.addRow("Copies", copies_spin)
    layout.addLayout(form)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    cancel_btn = QPushButton("Cancel  [Esc]")
    cancel_btn.setFixedHeight(30)
    print_btn = QPushButton("Print  [Ctrl+S]")
    print_btn.setFixedHeight(30)
    print_btn.setStyleSheet(
        f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
        "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
        f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
    )
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(print_btn)
    layout.addLayout(btn_row)

    def confirm():
        from utils.label_pdf import generate_label_pdf
        from utils.open_file import open_with_default_app
        try:
            path = generate_label_pdf(
                barcode=barcode, description=description,
                price_inc_gst=sell_price, plu=plu,
                copies=copies_spin.value(), large=large,
            )
            open_with_default_app(path)
        except Exception as e:
            show_error(parent, "Could not generate the label.", e)
            return
        dlg.accept()

    print_btn.clicked.connect(confirm)
    cancel_btn.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    dlg.exec()


def print_edikio_label(parent, *, barcode, description, sell_price, unit):
    from utils.label_print import get_configured_edikio_printer_name, print_edikio_label_direct

    printer_name = get_configured_edikio_printer_name()
    if printer_name:
        # A printer is configured — print one card straight to it, no
        # dialog, matching print_shelf_label's behaviour for shelf labels.
        ok, msg = print_edikio_label_direct(
            barcode=barcode, description=description,
            price_inc_gst=sell_price, unit=unit,
        )
        if ok:
            return
        if "is not available" not in msg:
            show_error(parent, "Could not print the Edikio card.", RuntimeError(msg))
            return
        # else: configured printer isn't currently found (unplugged,
        # renamed, etc.) — fall through to the PDF, same as unconfigured.

    print_edikio_label_via_pdf(parent, barcode=barcode, description=description,
                                sell_price=sell_price, unit=unit)


def print_edikio_label_via_pdf(parent, *, barcode, description, sell_price, unit):
    """No Edikio printer configured (Settings > Label Printing) — fall back
    to generating a PDF and opening it for the user to print manually."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Print Edikio Card")
    dlg.setMinimumWidth(280)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    form = QFormLayout()
    copies_spin = QSpinBox()
    copies_spin.setMinimum(1)
    copies_spin.setMaximum(200)
    copies_spin.setValue(1)
    form.addRow("Copies", copies_spin)
    layout.addLayout(form)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    cancel_btn = QPushButton("Cancel  [Esc]")
    cancel_btn.setFixedHeight(30)
    print_btn = QPushButton("Print  [Ctrl+S]")
    print_btn.setFixedHeight(30)
    print_btn.setStyleSheet(
        f"QPushButton {{ background: {styles.CLR_ACCENT}; color: white; border: none; "
        "border-radius: 4px; padding: 0 18px; font-weight: bold; }"
        f"QPushButton:hover {{ background: {styles.CLR_ACCENT_HOVER}; }}"
    )
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(print_btn)
    layout.addLayout(btn_row)

    def confirm():
        from utils.label_pdf import generate_edikio_label_pdf
        from utils.open_file import open_with_default_app
        try:
            path = generate_edikio_label_pdf(
                barcode=barcode, description=description,
                price_inc_gst=sell_price, unit=unit,
                copies=copies_spin.value(),
            )
            open_with_default_app(path)
        except Exception as e:
            show_error(parent, "Could not generate the Edikio card.", e)
            return
        dlg.accept()

    print_btn.clicked.connect(confirm)
    cancel_btn.clicked.connect(dlg.reject)
    QShortcut(QKeySequence("Ctrl+S"), dlg, confirm)
    QShortcut(QKeySequence("Escape"), dlg, dlg.reject)
    dlg.exec()
