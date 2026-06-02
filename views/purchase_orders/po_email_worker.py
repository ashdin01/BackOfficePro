import logging

from PyQt6.QtCore import QThread, pyqtSignal


class _PoEmailWorker(QThread):
    """Generates the PO PDF and sends via MS Graph on a background thread.

    Emits success(pdf_path) when the Graph API returns 202.
    Emits failure(error_message) on any exception so the PO status is
    never updated unless the email was actually accepted for delivery.
    """
    success = pyqtSignal(str)   # pdf_path
    failure = pyqtSignal(str)   # human-readable error

    def __init__(self, po_id: int, supplier_email: str):
        super().__init__()
        self._po_id = po_id
        self._supplier_email = supplier_email

    def run(self):
        try:
            import controllers.purchase_order_controller as _po_ctrl
            path = _po_ctrl.send_po_email(self._po_id, self._supplier_email)
            self.success.emit(path)
        except Exception as exc:
            logging.error("PO email worker failed", exc_info=True)
            self.failure.emit(str(exc))
        finally:
            from database.connection import close_thread_connection
            close_thread_connection()
