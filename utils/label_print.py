"""
Silent, direct-to-printer shelf label printing.

utils.label_pdf owns the label layout (tested, reused unchanged here) and
generates the label as a PDF. This module's job is purely getting that PDF
onto paper without a viewer or a print dialog in the way: rasterise the PDF
page (via QtPdf) and paint it onto a QPrinter targeting the printer chosen
in Settings > Label Printing — no ZPL, no printer-specific command
language, so it works with whatever's selected there, Zebra or otherwise.

Requires a printer to be selected in Settings first. With none configured,
callers should fall back to utils.label_pdf.generate_label_pdf +
utils.open_file.open_with_default_app instead (open the PDF, let the user
print it manually) — see ProductEdit._print_label.
"""
import os

import models.settings as settings_model
from utils.label_pdf import generate_label_pdf, get_label_size_mm

_RENDER_DPI = 300


def get_printer_names() -> list[str]:
    from PyQt6.QtPrintSupport import QPrinterInfo
    return QPrinterInfo.availablePrinterNames()


def get_configured_printer_name() -> str:
    return settings_model.get_setting('label_printer_name', '')


def render_label_image(barcode, description, price_inc_gst, plu=None, large=False):
    """
    Build the label PDF (utils.label_pdf, unchanged/tested layout) and
    rasterise its single page to a QImage at print resolution. Split out
    from print_label_direct so tests can verify rendering without opening
    a real printer.
    """
    from PyQt6.QtCore import QSize
    from PyQt6.QtPdf import QPdfDocument

    width_mm, height_mm = get_label_size_mm(large=large)
    pdf_path = generate_label_pdf(barcode, description, price_inc_gst, plu=plu,
                                   path=None, large=large)
    try:
        doc = QPdfDocument(None)
        if doc.load(pdf_path) != QPdfDocument.Error.None_:
            return None
        px_size = QSize(
            round(width_mm / 25.4 * _RENDER_DPI),
            round(height_mm / 25.4 * _RENDER_DPI),
        )
        return doc.render(0, px_size)
    finally:
        os.remove(pdf_path)


def print_label_direct(barcode, description, price_inc_gst, plu=None,
                        copies=1, large=False, printer=None) -> tuple[bool, str]:
    """
    Print directly to the printer configured in Settings > Label Printing —
    no dialog, no viewer. Returns (success, message); message explains the
    failure when success is False (no printer configured, printer not
    found, etc.) so the caller can show it to the user.

    printer: inject a pre-built QPrinter (e.g. targeting PdfFormat output)
    for testing; production callers should leave this as None so it targets
    the printer configured in Settings by name.
    """
    from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
    from PyQt6.QtGui import QPageSize, QPainter
    from PyQt6.QtCore import QSizeF

    if printer is None:
        printer_name = get_configured_printer_name()
        if not printer_name:
            return False, "No printer configured — set one in Settings > Label Printing."
        printer_info = QPrinterInfo.printerInfo(printer_name)
        if printer_info.isNull():
            return False, (
                f"Printer '{printer_name}' is not available — check it's connected, "
                "or choose a different one in Settings > Label Printing."
            )
        printer = QPrinter(printer_info, QPrinter.PrinterMode.HighResolution)

    width_mm, height_mm = get_label_size_mm(large=large)
    image = render_label_image(barcode, description, price_inc_gst, plu=plu, large=large)
    if image is None or image.isNull():
        return False, "Could not render the label."

    printer.setPageSize(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter))
    printer.setFullPage(True)

    painter = QPainter(printer)
    try:
        for i in range(max(1, int(copies))):
            if i > 0:
                printer.newPage()
            painter.drawImage(painter.viewport(), image)
    finally:
        painter.end()
    return True, "Printed"
