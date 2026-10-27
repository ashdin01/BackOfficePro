"""Widget tests for KitWindow (views/kits/kit_window.py)."""
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.kit_controller as kit_ctrl


def _product(conn, dept_id, barcode, desc, cost, soh):
    conn.execute("""
        INSERT INTO products (barcode, description, department_id, sell_price,
                              cost_price, tax_rate, pack_qty, pack_unit, active, unit)
        VALUES (?, ?, ?, 10, ?, 10.0, 1, 'EA', 1, 'EA')
    """, (barcode, desc, dept_id, cost))
    conn.execute("INSERT INTO stock_on_hand (barcode, quantity) VALUES (?, ?)", (barcode, soh))
    conn.commit()


@pytest.fixture()
def win(qtbot, db_conn, dept_id, monkeypatch):
    _product(db_conn, dept_id, "H1", "Hamper LARGE", 0, 0)
    _product(db_conn, dept_id, "C1", "Brandy 200ml", 20, 5)
    _product(db_conn, dept_id, "C2", "Dry Cider 500ml", 3, 10)
    kit_ctrl.add_component("H1", "C1", 1)
    kit_ctrl.add_component("H1", "C2", 2)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    # Imported here, not at module level: test_main_icon.py destroys its own
    # QApplication, which deletes any module-level QObject (utils.stock_events)
    # that was imported earlier — at collection time — than that test ran.
    from views.kits.kit_window import KitWindow
    w = KitWindow()
    qtbot.addWidget(w)
    w.show()
    QApplication.processEvents()
    return w


def _soh(conn, bc):
    return conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (bc,)).fetchone()[0]


class TestKitWindow:
    def test_loads_existing_kit_and_components(self, win):
        assert win.kit_combo.count() == 1
        assert win.comp_table.rowCount() == 2
        assert "Fully stocked for: 5" in win.summary.text()

    def test_build_moves_stock_and_refreshes(self, win, db_conn):
        win.qty_spin.setValue(3)
        win._do_build()
        assert _soh(db_conn, "H1") == 3
        assert _soh(db_conn, "C1") == 2
        assert win.hist.rowCount() == 1
        assert "Fully stocked for: 2" in win.summary.text()

    def test_short_stock_builds_after_warning_and_goes_negative(self, win, db_conn, monkeypatch):
        prompts = []
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: prompts.append(a[2]) or QMessageBox.StandardButton.Yes)
        win.qty_spin.setValue(9)
        win._do_build()
        assert "Brandy 200ml: need 9, have 5" in prompts[0]
        assert _soh(db_conn, "H1") == 9
        assert _soh(db_conn, "C1") == -4

    def test_add_component_button_has_alt_a_mnemonic(self, win):
        assert win.btn_add_comp.text() == "+ &Add Component…"

    def test_break_down_returns_components(self, win, db_conn):
        win.qty_spin.setValue(2)
        win._do_build()
        win.rb_break.setChecked(True)
        win.qty_spin.setValue(1)
        win._do_build()
        assert _soh(db_conn, "H1") == 1
        assert _soh(db_conn, "C1") == 4
