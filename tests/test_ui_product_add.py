"""Widget regression tests for ProductAdd (views/products/product_add.py).

Includes the fix for: the Department field (marked required) used to be a
QComboBox with no placeholder, silently defaulting to whichever department
sorted first — the same bug class as the PO supplier / invoice customer /
user role fixes elsewhere in this session.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.product_controller as product_ctrl


@pytest.fixture()
def two_departments(db_conn):
    """A second department, alphabetically before the default GROC seed,
    so a test can prove the active choice isn't just whatever sorts first."""
    db_conn.execute("INSERT INTO departments (code, name) VALUES ('AAA', 'AAA Department')")
    db_conn.commit()
    return db_conn.execute("SELECT id FROM departments WHERE code='AAA'").fetchone()["id"]


@pytest.fixture()
def product_add_view(qtbot, test_db, supplier_id):
    from views.products.product_add import ProductAdd
    widget = ProductAdd()
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


def _fill_minimum(widget, barcode="9300000055501", description="New Test Product"):
    widget.barcode.setText(barcode)
    widget.description.setText(description)


# ── Reorder point labelling ───────────────────────────────────────────────────

class TestReorderPointLabel:
    def test_labelled_as_minimum(self, product_add_view):
        from PyQt6.QtWidgets import QLabel
        texts = [lbl.text() for lbl in product_add_view.findChildren(QLabel)]
        assert "Reorder Point (Min)" in texts

    def test_tooltip_explains_below_threshold_trigger(self, product_add_view):
        assert "falls below" in product_add_view.reorder_point.toolTip()


# ── Department must be actively chosen ──────────────────────────────────────────

class TestDepartmentNotPreselected:
    def test_placeholder_is_the_initial_selection(self, product_add_view):
        assert product_add_view.dept.currentData() is None
        assert "select" in product_add_view.dept.currentText().lower()

    def test_save_blocked_without_choosing_department(self, product_add_view, monkeypatch):
        _fill_minimum(product_add_view)
        import views.products.product_add as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)
        create_spy = MagicMock(wraps=product_ctrl.add_product)
        monkeypatch.setattr(product_ctrl, "add_product", create_spy)

        product_add_view._save()

        mock_mb.warning.assert_called_once()
        create_spy.assert_not_called()

    def test_save_succeeds_for_the_actively_chosen_department_not_the_first(
        self, qtbot, test_db, supplier_id, two_departments, dept_id
    ):
        """dept_id (GROC, seeded first / lowest id) must NOT be what gets
        saved when the test explicitly picks the AAA department instead.

        Builds its own widget (rather than the product_add_view fixture)
        so construction happens after two_departments has already seeded
        the extra row — ProductAdd snapshots the department list in
        __init__, so building it too early would miss the new department.
        """
        from views.products.product_add import ProductAdd
        w = ProductAdd()
        qtbot.addWidget(w)
        _fill_minimum(w)
        idx = w.dept.findData(two_departments)
        assert idx != -1, "AAA department not found in the combo — fixture ordering bug"
        w.dept.setCurrentIndex(idx)

        w._save()

        row = product_ctrl.get_product_by_barcode("9300000055501")
        assert row is not None
        assert row["department_id"] == two_departments
        assert row["department_id"] != dept_id


class TestSaveValidation:
    def test_blank_barcode_blocked(self, product_add_view, dept_id):
        product_add_view.description.setText("Missing Barcode")
        idx = product_add_view.dept.findData(dept_id)
        product_add_view.dept.setCurrentIndex(idx)
        with patch('views.products.product_add.QMessageBox') as mock_mb:
            product_add_view._save()
            mock_mb.warning.assert_called_once()

    def test_blank_description_blocked(self, product_add_view, dept_id):
        product_add_view.barcode.setText("9300000055502")
        idx = product_add_view.dept.findData(dept_id)
        product_add_view.dept.setCurrentIndex(idx)
        with patch('views.products.product_add.QMessageBox') as mock_mb:
            product_add_view._save()
            mock_mb.warning.assert_called_once()

    def test_successful_save_closes_widget_and_calls_on_save(
        self, qtbot, test_db, dept_id
    ):
        from views.products.product_add import ProductAdd
        on_save = MagicMock()
        w = ProductAdd(on_save=on_save)
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()
        _fill_minimum(w, barcode="9300000055503")
        idx = w.dept.findData(dept_id)
        w.dept.setCurrentIndex(idx)

        w._save()
        QApplication.processEvents()

        on_save.assert_called_once()
        assert not w.isVisible()
        assert product_ctrl.get_product_by_barcode("9300000055503") is not None

    def test_duplicate_barcode_shows_error_not_crash(
        self, product_add_view, dept_id, product_barcode
    ):
        product_add_view.barcode.setText(product_barcode)  # already exists
        product_add_view.description.setText("Duplicate")
        idx = product_add_view.dept.findData(dept_id)
        product_add_view.dept.setCurrentIndex(idx)

        with patch('views.products.product_add.show_error') as mock_show_error:
            product_add_view._save()  # must not raise
            mock_show_error.assert_called_once()


# ── Cost price precision (regression: was capped at 2dp) ────────────────────────

class TestCostPricePrecision:
    def test_cost_price_accepts_four_decimal_places(self, product_add_view):
        assert product_add_view.cost_price.decimals() == 4

    def test_fractional_cent_cost_price_saved_exactly(
        self, product_add_view, dept_id
    ):
        _fill_minimum(product_add_view, barcode="9300000055504")
        idx = product_add_view.dept.findData(dept_id)
        product_add_view.dept.setCurrentIndex(idx)
        product_add_view.cost_price.setValue(1.2345)

        product_add_view._save()

        row = product_ctrl.get_product_by_barcode("9300000055504")
        assert row["cost_price"] == pytest.approx(1.2345)


# ── Gross profit display ──────────────────────────────────────────────────────

class TestGrossProfitDisplay:
    def test_shows_dashes_when_sell_price_zero(self, product_add_view):
        product_add_view.cost_price.setValue(2.00)
        product_add_view.sell_price.setValue(0.0)
        assert "--" in product_add_view.gp_label.text()

    def test_computes_percentage_including_tax_on_cost(self, product_add_view):
        product_add_view.tax_rate.setCurrentIndex(1)  # GST 10%
        product_add_view.cost_price.setValue(5.00)
        product_add_view.sell_price.setValue(11.00)
        # cost inc gst = 5.50; gp = 1 - 5.50/11.00 = 50%
        assert "50.0%" in product_add_view.gp_label.text()

    def test_cost_inc_gst_label_updates(self, product_add_view):
        product_add_view.tax_rate.setCurrentIndex(1)  # GST 10%
        product_add_view.cost_price.setValue(2.00)
        assert "$2.20" in product_add_view.cost_inc_label.text()


# ── Group list follows department selection ──────────────────────────────────

class TestGroupFollowsDepartment:
    def test_group_list_scoped_to_chosen_department(
        self, qtbot, test_db, db_conn, dept_id, two_departments
    ):
        db_conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'GRP1', 'Group One')",
            (dept_id,)
        )
        db_conn.execute(
            "INSERT INTO product_groups (department_id, code, name) VALUES (?, 'GRP2', 'Group Two')",
            (two_departments,)
        )
        db_conn.commit()

        # Groups are loaded fresh in __init__, so seed the rows above first.
        from views.products.product_add import ProductAdd
        w = ProductAdd()
        qtbot.addWidget(w)

        idx = w.dept.findData(dept_id)
        w.dept.setCurrentIndex(idx)
        w._on_dept_changed()
        names_for_dept1 = {w.group.itemText(i) for i in range(w.group.count())}
        assert "Group One" in names_for_dept1
        assert "Group Two" not in names_for_dept1

        idx2 = w.dept.findData(two_departments)
        w.dept.setCurrentIndex(idx2)
        w._on_dept_changed()
        names_for_dept2 = {w.group.itemText(i) for i in range(w.group.count())}
        assert "Group Two" in names_for_dept2
        assert "Group One" not in names_for_dept2

    def test_placeholder_department_shows_only_no_group(self, product_add_view):
        product_add_view._on_dept_changed()
        items = [product_add_view.group.itemText(i) for i in range(product_add_view.group.count())]
        assert items == ["— No Group —"]
