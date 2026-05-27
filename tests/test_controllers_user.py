"""Tests for user_controller."""
import pytest
import controllers.user_controller as user_ctrl


class TestUserCRUD:
    def test_get_all_includes_default_admin(self, test_db):
        users = user_ctrl.get_all()
        assert any(u['username'] == 'admin' for u in users)

    def test_get_all_active_returns_admin(self, test_db):
        active = user_ctrl.get_all_active()
        assert any(u['username'] == 'admin' for u in active)

    def test_create_new_user(self, test_db):
        user_ctrl.create('cashier1', 'Jane Smith', 'CASHIER', '1234')
        users = user_ctrl.get_all()
        assert any(u['username'] == 'cashier1' for u in users)

    def test_update_user_changes_full_name(self, test_db):
        user_ctrl.create('op1', 'Old Name', 'CASHIER', '0000')
        uid = next(u['id'] for u in user_ctrl.get_all() if u['username'] == 'op1')
        user_ctrl.update(uid, 'op1', 'New Name', 'CASHIER')
        updated = next(u for u in user_ctrl.get_all() if u['id'] == uid)
        assert updated['full_name'] == 'New Name'

    def test_set_active_false_removes_from_active_list(self, test_db):
        user_ctrl.create('inactive1', 'Inactive User', 'CASHIER', '9999')
        uid = next(u['id'] for u in user_ctrl.get_all() if u['username'] == 'inactive1')
        user_ctrl.set_active(uid, 0)
        active_names = {u['username'] for u in user_ctrl.get_all_active()}
        assert 'inactive1' not in active_names


class TestPinAuth:
    def test_verify_pin_returns_false_when_no_pin_set(self, test_db):
        assert user_ctrl.verify_pin('admin', '1234') is False

    def test_set_pin_and_verify(self, test_db):
        user_ctrl.set_pin('admin', '5678')
        assert user_ctrl.verify_pin('admin', '5678') is True

    def test_verify_wrong_pin_returns_false(self, test_db):
        user_ctrl.set_pin('admin', '1111')
        assert user_ctrl.verify_pin('admin', '9999') is False

    def test_set_pin_by_id(self, test_db):
        uid = next(u['id'] for u in user_ctrl.get_all() if u['username'] == 'admin')
        user_ctrl.set_pin_by_id(uid, '4321')
        assert user_ctrl.verify_pin('admin', '4321') is True

    def test_verify_unknown_user_returns_false(self, test_db):
        assert user_ctrl.verify_pin('nobody', '0000') is False
