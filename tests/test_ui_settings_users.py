"""Widget regression tests for settings_users.py — _UserDialog role selection.

Covers the fix for: the Role field used to be a QComboBox defaulting to
ROLES[0] == "ADMIN" with no active-choice requirement, so a new user
created without touching that field silently got full admin access.

Requires pytest-qt (installed) and a live display (DISPLAY=:0).
"""
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

import controllers.user_controller as user_ctrl


@pytest.fixture()
def user_dialog(qtbot, test_db):
    from views.settings.settings_users import _UserDialog
    dlg = _UserDialog(user=None)
    qtbot.addWidget(dlg)
    dlg.show()
    QApplication.processEvents()
    return dlg


def _fill_required_fields(dlg, name="Jane Smith", username="jsmith", pin="1234"):
    dlg._full_name.setText(name)
    dlg._username.setText(username)
    dlg._pin.setText(pin)
    dlg._pin2.setText(pin)


class TestNewUserRoleNotPreselected:
    def test_placeholder_is_the_current_selection(self, user_dialog):
        assert user_dialog._role.currentText() == "— Select a role —"

    def test_admin_is_not_the_default_selection(self, user_dialog):
        """The specific regression: ROLES[0] is ADMIN — must never be
        pre-selected for a brand new account."""
        assert user_dialog._role.currentText() != "ADMIN"

    def test_save_blocked_without_picking_a_role(self, user_dialog, monkeypatch):
        _fill_required_fields(user_dialog)
        # role left on the placeholder

        import views.settings.settings_users as _mod
        mock_mb = MagicMock()
        monkeypatch.setattr(_mod, "QMessageBox", mock_mb)

        user_dialog._validate()

        mock_mb.warning.assert_called_once()
        assert user_dialog.result() != user_dialog.DialogCode.Accepted

    def test_save_succeeds_once_role_actively_chosen(self, user_dialog):
        _fill_required_fields(user_dialog)
        idx = user_dialog._role.findText("STAFF")
        user_dialog._role.setCurrentIndex(idx)

        user_dialog._validate()

        assert user_dialog.result_data["role"] == "STAFF"

    def test_can_still_choose_admin_deliberately(self, user_dialog):
        """The fix blocks the *default*, not the choice — ADMIN must still
        be selectable when someone actually means to pick it."""
        _fill_required_fields(user_dialog, username="newadmin")
        idx = user_dialog._role.findText("ADMIN")
        user_dialog._role.setCurrentIndex(idx)

        user_dialog._validate()

        assert user_dialog.result_data["role"] == "ADMIN"


class TestEditExistingUserRole:
    def test_current_role_is_preselected_not_the_placeholder(self, qtbot, test_db):
        user_ctrl.create("mgr1", "Existing Manager", "MANAGER", "1234")
        existing = next(u for u in user_ctrl.get_all() if u["username"] == "mgr1")

        from views.settings.settings_users import _UserDialog
        dlg = _UserDialog(user=existing)
        qtbot.addWidget(dlg)

        assert dlg._role.currentText() == "MANAGER"
        # No placeholder item should even exist in edit mode.
        assert dlg._role.findText("— Select a role —") == -1

    def test_editing_does_not_require_repicking_role(self, qtbot, test_db):
        user_ctrl.create("staff1", "Existing Staff", "STAFF", "1234")
        existing = next(u for u in user_ctrl.get_all() if u["username"] == "staff1")

        from views.settings.settings_users import _UserDialog
        dlg = _UserDialog(user=existing)
        qtbot.addWidget(dlg)
        dlg._full_name.setText("Renamed Staff")

        dlg._validate()

        assert dlg.result_data["role"] == "STAFF"


class TestEndToEndCreateUser:
    def test_new_user_via_add_user_gets_chosen_role_not_admin(self, qtbot, test_db):
        from views.settings.settings_users import UsersScreen
        screen = UsersScreen()
        qtbot.addWidget(screen)

        from views.settings.settings_users import _UserDialog
        dlg = _UserDialog(user=None, parent=screen)
        qtbot.addWidget(dlg)
        _fill_required_fields(dlg, name="Casual Worker", username="casual1")
        idx = dlg._role.findText("STAFF")
        dlg._role.setCurrentIndex(idx)
        dlg._validate()

        user_ctrl.create(
            dlg.result_data['username'], dlg.result_data['full_name'],
            dlg.result_data['role'], dlg.result_data['pin'],
        )

        created = next(u for u in user_ctrl.get_all() if u["username"] == "casual1")
        assert created["role"] == "STAFF"
