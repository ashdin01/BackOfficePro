"""Widget regression tests for SupplierEdit (views/suppliers/supplier_edit.py).

The role-based permission split here is security-relevant, not just UX:
STAFF gets a fully read-only form with Save hidden; MANAGER can edit
everything except bank details (locked to prevent an unauthorised change
of where supplier payments go); ADMIN has full access. Bank fields being
silently preserved (not blanked) when a non-ADMIN saves is the specific
behaviour that stops a MANAGER edit from wiping out payment details they
can't even see.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QMessageBox

import controllers.supplier_controller as supplier_ctrl

VALID_ABN = "51824753556"


def _fill_required(widget, code="SUP1", name="Test Supplier Pty Ltd"):
    widget.code.setText(code)
    widget.name.setText(name)


@pytest.fixture()
def supplier_edit_admin(qtbot, test_db):
    from views.suppliers.supplier_edit import SupplierEdit
    widget = SupplierEdit(current_user={"role": "ADMIN"})
    qtbot.addWidget(widget)
    widget.show()
    QApplication.processEvents()
    return widget


# ── Role-based permissions ──────────────────────────────────────────────────────

class TestRolePermissions:
    def test_admin_can_edit_bank_fields(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "ADMIN"})
        qtbot.addWidget(w)
        assert not w.bank_account_name.isReadOnly()
        assert not w.bank_bsb.isReadOnly()
        assert not w._save_btn.isHidden()

    def test_manager_cannot_edit_bank_fields(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "MANAGER"})
        qtbot.addWidget(w)
        assert w.bank_account_name.isReadOnly()
        assert w.bank_bsb.isReadOnly()
        assert w.bank_account_number.isReadOnly()

    def test_manager_can_still_edit_supplier_details(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "MANAGER"})
        qtbot.addWidget(w)
        assert not w.code.isReadOnly()
        assert not w.name.isReadOnly()
        assert not w._save_btn.isHidden()

    def test_staff_form_entirely_read_only_and_save_hidden(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "STAFF"})
        qtbot.addWidget(w)
        assert w.code.isReadOnly()
        assert w.name.isReadOnly()
        assert w.bank_bsb.isReadOnly()
        assert w._save_btn.isHidden()

    def test_unknown_role_treated_as_staff(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "SOMETHING_WEIRD"})
        qtbot.addWidget(w)
        assert w.code.isReadOnly()
        assert w._save_btn.isHidden()

    def test_manager_save_preserves_existing_bank_details_untouched(
        self, qtbot, test_db, supplier_id
    ):
        """The specific security-relevant behaviour: a MANAGER editing a
        supplier can't blank out bank details even though the fields are
        disabled in their UI — the save path must re-use the saved values,
        not whatever the (empty, read-only) widget currently shows."""
        supplier_ctrl.update(
            supplier_id, "TST", "Test Supplier", "", "", "", "", "", "", 1,
            bank_account_name="Original Account", bank_bsb="063-000",
            bank_account_number="12345678",
        )
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=supplier_id, current_user={"role": "MANAGER"})
        qtbot.addWidget(w)

        w._save()

        s = supplier_ctrl.get_by_id(supplier_id)
        assert s['bank_account_name'] == "Original Account"
        assert s['bank_bsb'] == "063-000"
        assert s['bank_account_number'] == "12345678"


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_blank_code_and_name_blocked(self, supplier_edit_admin, monkeypatch):
        import views.suppliers.supplier_edit as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        supplier_edit_admin._save()

        msg = mock_mb.warning.call_args[0][2]
        assert "Code is required" in msg
        assert "Company Name is required" in msg

    def test_invalid_abn_blocks_save_with_message(self, supplier_edit_admin, monkeypatch):
        _fill_required(supplier_edit_admin)
        supplier_edit_admin.abn.setText("123")
        import views.suppliers.supplier_edit as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        supplier_edit_admin._save()

        assert "ABN" in mock_mb.warning.call_args[0][2]

    def test_invalid_bsb_blocks_save_for_admin(self, supplier_edit_admin, monkeypatch):
        _fill_required(supplier_edit_admin)
        supplier_edit_admin.bank_bsb.setText("12")
        import views.suppliers.supplier_edit as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        supplier_edit_admin._save()

        assert "BSB" in mock_mb.warning.call_args[0][2]

    def test_manager_bsb_not_validated_since_field_is_locked(self, qtbot, test_db):
        """MANAGER's bank_bsb field is always blank/read-only, so the BSB
        branch in _save() is skipped entirely for that role — must not
        block an otherwise-valid save."""
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(current_user={"role": "MANAGER"})
        qtbot.addWidget(w)
        _fill_required(w, code="MGR1")

        w._save()

        created = [s for s in supplier_ctrl.get_all(active_only=False) if s['code'] == 'MGR1']
        assert len(created) == 1

    def test_all_validation_errors_collected_together(self, supplier_edit_admin, monkeypatch):
        _fill_required(supplier_edit_admin)
        supplier_edit_admin.abn.setText("123")
        supplier_edit_admin.phone.setText("1")
        supplier_edit_admin.email_orders.setText("not-an-email")
        import views.suppliers.supplier_edit as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        supplier_edit_admin._save()

        msg = mock_mb.warning.call_args[0][2]
        assert "ABN" in msg and "Phone" in msg and "Orders Email" in msg

    def test_valid_data_saves_without_warning(self, supplier_edit_admin, monkeypatch):
        _fill_required(supplier_edit_admin)
        supplier_edit_admin.abn.setText(VALID_ABN)
        supplier_edit_admin.phone.setText("0398765432")
        supplier_edit_admin.email_orders.setText("orders@supplier.com.au")
        import views.suppliers.supplier_edit as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        supplier_edit_admin._save()

        mock_mb.warning.assert_not_called()
        assert supplier_ctrl.get_all(active_only=False)


# ── Create / update round-trip ──────────────────────────────────────────────────

class TestSaveRoundTrip:
    def test_new_supplier_created_and_closes(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        on_save = MagicMock()
        w = SupplierEdit(on_save=on_save, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)
        w.show()
        QApplication.processEvents()
        _fill_required(w, code="NEW1", name="Brand New Supplier")

        w._save()
        QApplication.processEvents()

        on_save.assert_called_once()
        assert not w.isVisible()
        rows = [s for s in supplier_ctrl.get_all(active_only=False) if s['code'] == 'NEW1']
        assert len(rows) == 1

    def test_editing_existing_supplier_updates_not_duplicates(
        self, qtbot, test_db, supplier_id
    ):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=supplier_id, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)
        w.name.setText("Renamed Supplier")

        w._save()

        s = supplier_ctrl.get_by_id(supplier_id)
        assert s['name'] == "Renamed Supplier"
        assert len(supplier_ctrl.get_all(active_only=False)) == 1

    def test_save_failure_shows_error_not_crash(self, supplier_edit_admin, monkeypatch):
        _fill_required(supplier_edit_admin)
        monkeypatch.setattr(
            supplier_ctrl, "create",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db exploded")),
        )
        with patch('views.suppliers.supplier_edit.show_error') as mock_show_error:
            supplier_edit_admin._save()  # must not raise
            mock_show_error.assert_called_once()


# ── Populate (loading an existing supplier) ──────────────────────────────────────

class TestPopulate:
    def test_order_and_delivery_days_restored(self, qtbot, test_db, supplier_id):
        supplier_ctrl.update(
            supplier_id, "TST", "Test Supplier", "", "", "", "", "", "", 1,
            order_days="MON,WED,FRI", delivery_days="TUE,THU",
        )
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=supplier_id, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)

        assert w._day_checks['MON'].isChecked()
        assert w._day_checks['WED'].isChecked()
        assert w._day_checks['FRI'].isChecked()
        assert not w._day_checks['TUE'].isChecked()
        assert w._delivery_day_checks['TUE'].isChecked()
        assert w._delivery_day_checks['THU'].isChecked()
        assert not w._delivery_day_checks['MON'].isChecked()

    def test_fortnightly_start_restored_and_checked(self, qtbot, test_db, supplier_id):
        supplier_ctrl.update(
            supplier_id, "TST", "Test Supplier", "", "", "", "", "", "", 1,
            order_fortnightly_start="2026-01-05",
        )
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=supplier_id, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)

        assert w.order_fortnightly.isChecked()
        assert w.order_fortnightly_start.date().toString("yyyy-MM-dd") == "2026-01-05"

    def test_no_fortnightly_date_leaves_checkbox_unchecked(self, qtbot, test_db, supplier_id):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=supplier_id, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)
        assert not w.order_fortnightly.isChecked()

    def test_missing_supplier_id_leaves_form_blank(self, qtbot, test_db):
        from views.suppliers.supplier_edit import SupplierEdit
        w = SupplierEdit(supplier_id=999999, current_user={"role": "ADMIN"})
        qtbot.addWidget(w)  # must not raise
        assert w.code.text() == ""


# ── BSB live indicator ───────────────────────────────────────────────────────────

class TestBsbIndicator:
    def test_typing_digits_auto_inserts_hyphen(self, supplier_edit_admin):
        supplier_edit_admin.bank_bsb.setText("063000")
        assert supplier_edit_admin.bank_bsb.text() == "063-000"

    def test_valid_bsb_shows_positive_indicator(self, supplier_edit_admin):
        supplier_edit_admin.bank_bsb.setText("063000")
        assert "✓" in supplier_edit_admin._bsb_indicator.text()

    def test_incomplete_bsb_shows_no_indicator(self, supplier_edit_admin):
        supplier_edit_admin.bank_bsb.setText("063")
        assert supplier_edit_admin._bsb_indicator.text() == ""

    def test_clearing_bsb_clears_indicator(self, supplier_edit_admin):
        supplier_edit_admin.bank_bsb.setText("063000")
        supplier_edit_admin.bank_bsb.setText("")
        assert supplier_edit_admin._bsb_indicator.text() == ""
