"""Widget regression tests for surfacing unmatched PLUs — the follow-up to
the "SOH looks wrong in Product Detail" investigation: a PLU that never
resolves to a product barcode never has its sales deducted from stock on
hand, and previously nothing told anyone that had happened.

Covers:
- SalesReportView's persistent unmatched-PLU banner (views/reports/sales_report_view.py)
- The unmatched count surfaced in the manual-import result message (views/home_screen.py::_run_import)
- sales_report_view.py's own Import Sales button now reuses that same helper
  (it used to call a module.import_file() that didn't exist — every import
  via this screen's button silently failed before this fix)

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.sales_report_controller as sales_ctrl


def _insert_sale(db_conn, sale_date, plu, plu_name="Item", qty=1, sales_dollars=1.0):
    db_conn.execute("""
        INSERT INTO sales_daily
            (sale_date, plu, plu_name, sub_group, weight_kg, quantity,
             nominal_price, discount, rounding, sales_dollars, sales_pct)
        VALUES (?, ?, ?, '', 0, ?, ?, 0, 0, ?, 0)
    """, (sale_date, str(plu), plu_name, qty, sales_dollars, sales_dollars))


def _map_plu_to_barcode(db_conn, plu, barcode):
    db_conn.execute(
        "INSERT INTO plu_barcode_map (plu, barcode) VALUES (?, ?)", (plu, barcode)
    )


@pytest.fixture()
def sales_report_view(qtbot, test_db):
    from views.reports.sales_report_view import SalesReportView
    widget = SalesReportView()
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


# ── Unmatched-PLU banner ──────────────────────────────────────────────────────

class TestUnmatchedBanner:
    def test_hidden_when_no_sales_data(self, sales_report_view):
        assert sales_report_view.unmatched_banner.isHidden() or \
               sales_report_view.unmatched_banner.text() == ""

    def test_hidden_when_all_plus_matched(self, qtbot, test_db, db_conn, product_barcode):
        _map_plu_to_barcode(db_conn, 501, product_barcode)
        _insert_sale(db_conn, "2026-07-01", 501, "Matched Item")
        db_conn.commit()

        from views.reports.sales_report_view import SalesReportView
        w = SalesReportView()
        qtbot.addWidget(w)
        w.date_from.setDate(w.date_from.date().addDays(-30))
        w._load()

        assert w.unmatched_banner.isHidden()

    def test_shown_with_correct_count_when_unmatched(self, qtbot, test_db, db_conn):
        _insert_sale(db_conn, "2026-07-01", 999, "Mystery Item")
        db_conn.commit()

        from views.reports.sales_report_view import SalesReportView
        w = SalesReportView()
        qtbot.addWidget(w)
        w.date_from.setDate(w.date_from.date().addDays(-30))
        w._load()

        assert not w.unmatched_banner.isHidden()
        assert "1 unmatched PLU" in w.unmatched_banner.text()

    def test_pluralised_for_multiple_unmatched(self, qtbot, test_db, db_conn):
        _insert_sale(db_conn, "2026-07-01", 998, "Mystery A")
        _insert_sale(db_conn, "2026-07-01", 999, "Mystery B")
        db_conn.commit()

        from views.reports.sales_report_view import SalesReportView
        w = SalesReportView()
        qtbot.addWidget(w)
        w.date_from.setDate(w.date_from.date().addDays(-30))
        w._load()

        assert "2 unmatched PLUs" in w.unmatched_banner.text()

    def test_matching_a_plu_hides_the_banner_on_reload(
        self, qtbot, test_db, db_conn, product_barcode
    ):
        _insert_sale(db_conn, "2026-07-01", 501, "Now Matched")
        db_conn.commit()

        from views.reports.sales_report_view import SalesReportView
        w = SalesReportView()
        qtbot.addWidget(w)
        w.date_from.setDate(w.date_from.date().addDays(-30))
        w._load()
        assert not w.unmatched_banner.isHidden()

        import controllers.sales_report_controller as _ctrl
        _ctrl.save_plu_map(501, product_barcode)
        w._load()

        assert w.unmatched_banner.isHidden()


# ── Manual import result message (views/home_screen.py::_run_import) ───────────

class TestRunImportUnmatchedMessage:
    def test_no_unmatched_plain_success_message(self, test_db, monkeypatch, tmp_path):
        from views.home_screen import _run_import
        import views.home_screen as _mod

        fake_module = MagicMock()
        fake_module.ensure_tables = MagicMock()
        fake_module.import_csv = MagicMock(return_value=(5, 5, 0))

        def fake_exec_module(module):
            pass

        monkeypatch.setattr(_mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            _mod.importlib.util, "spec_from_file_location",
            lambda name, path: MagicMock(loader=MagicMock(exec_module=lambda m: None))
        )
        monkeypatch.setattr(_mod.importlib.util, "module_from_spec", lambda spec: fake_module)

        success, message = _run_import(None, [str(tmp_path / "f.csv")])

        assert success
        assert "unmatched" not in message.lower()

    def test_unmatched_plus_included_in_success_message(self, test_db, monkeypatch, tmp_path):
        from views.home_screen import _run_import
        import views.home_screen as _mod

        fake_module = MagicMock()
        fake_module.ensure_tables = MagicMock()
        fake_module.import_csv = MagicMock(return_value=(5, 3, 2))

        monkeypatch.setattr(_mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            _mod.importlib.util, "spec_from_file_location",
            lambda name, path: MagicMock(loader=MagicMock(exec_module=lambda m: None))
        )
        monkeypatch.setattr(_mod.importlib.util, "module_from_spec", lambda spec: fake_module)

        success, message = _run_import(None, [str(tmp_path / "f.csv")])

        assert success
        assert "2 PLU(s)" in message
        assert "not adjusted" in message.lower()

    def test_unmatched_summed_across_multiple_files(self, test_db, monkeypatch, tmp_path):
        from views.home_screen import _run_import
        import views.home_screen as _mod

        fake_module = MagicMock()
        fake_module.ensure_tables = MagicMock()
        fake_module.import_csv = MagicMock(side_effect=[(5, 3, 1), (4, 4, 3)])

        monkeypatch.setattr(_mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            _mod.importlib.util, "spec_from_file_location",
            lambda name, path: MagicMock(loader=MagicMock(exec_module=lambda m: None))
        )
        monkeypatch.setattr(_mod.importlib.util, "module_from_spec", lambda spec: fake_module)

        success, message = _run_import(
            None, [str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]
        )

        assert success
        assert "4 PLU(s)" in message


# ── sales_report_view.py's Import Sales button (regression: used to call a
#    nonexistent module.import_file() and fail on every single import) ────────

class TestSalesReportImportButtonUsesSharedHelper(object):
    def test_import_delegates_to_run_import_and_reloads(
        self, sales_report_view, monkeypatch, tmp_path
    ):
        import views.reports.sales_report_view as _mod
        from PyQt6.QtWidgets import QFileDialog

        fake_path = str(tmp_path / "sales.csv")
        monkeypatch.setattr(
            QFileDialog, "getOpenFileNames", lambda *a, **kw: ([fake_path], "")
        )

        run_import_spy = MagicMock(return_value=(True, "Imported 1 file(s) successfully."))
        monkeypatch.setattr("views.home_screen._run_import", run_import_spy)
        monkeypatch.setattr(_mod.QMessageBox, "information", MagicMock())

        load_spy = MagicMock(wraps=sales_report_view.load)
        monkeypatch.setattr(sales_report_view, "load", load_spy)

        sales_report_view._import_sales()

        run_import_spy.assert_called_once_with(sales_report_view, [fake_path])
        load_spy.assert_called_once()

    def test_cancelling_file_dialog_does_nothing(self, sales_report_view, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **kw: ([], ""))

        run_import_spy = MagicMock()
        monkeypatch.setattr("views.home_screen._run_import", run_import_spy)

        sales_report_view._import_sales()

        run_import_spy.assert_not_called()
