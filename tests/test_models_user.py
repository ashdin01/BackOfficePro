"""Tests for models/user.py — authentication and user management."""
import hashlib
import pytest
from database.connection import get_connection
import models.user as user_model


class TestCreate:
    def test_creates_user_retrievable_by_username(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        assert user is not None
        assert user["full_name"] == "John Doe"
        assert user["role"] == "STAFF"
        assert user["active"] == 1

    def test_pin_stored_as_sha256_hash_not_plaintext(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        assert user["pin"] != "1234"
        assert len(user["pin"]) == 64  # SHA-256 hex digest

    def test_pin_hash_matches_expected(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        expected = hashlib.sha256("1234".encode()).hexdigest()
        assert user["pin"] == expected

    def test_duplicate_username_raises(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        with pytest.raises(Exception):
            user_model.create("jdoe", "Jane Doe", "MANAGER", "5678")

    def test_inactive_user_not_returned_by_get_by_username(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_active(user["id"], False)
        assert user_model.get_by_username("jdoe") is None


class TestVerifyPin:
    def test_correct_pin_returns_true(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        assert user_model.verify_pin("jdoe", "1234") is True

    def test_wrong_pin_returns_false(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        assert user_model.verify_pin("jdoe", "9999") is False

    def test_nonexistent_user_returns_false(self, test_db):
        assert user_model.verify_pin("nobody", "1234") is False

    def test_legacy_plaintext_pin_authenticates(self, test_db):
        """A plaintext PIN stored in the DB (pre-hash era) must still work."""
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('legacy', 'Legacy User', 'STAFF', '5678', 1)"
        )
        conn.commit()
        conn.close()
        assert user_model.verify_pin("legacy", "5678") is True

    def test_legacy_plaintext_pin_migrated_to_hash_after_login(self, test_db):
        """After authenticating with a plaintext PIN it should be auto-migrated."""
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('legacy', 'Legacy User', 'STAFF', '5678', 1)"
        )
        conn.commit()
        conn.close()
        user_model.verify_pin("legacy", "5678")
        user = user_model.get_by_username("legacy")
        expected_hash = hashlib.sha256("5678".encode()).hexdigest()
        assert user["pin"] == expected_hash


class TestSetPin:
    def test_new_pin_allows_login(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_pin_by_id(user["id"], "9999")
        assert user_model.verify_pin("jdoe", "9999") is True

    def test_old_pin_rejected_after_change(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_pin_by_id(user["id"], "9999")
        assert user_model.verify_pin("jdoe", "1234") is False


class TestSetActive:
    def test_deactivated_user_not_in_active_list(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_active(user["id"], False)
        active = user_model.get_all_active()
        assert not any(u["username"] == "jdoe" for u in active)

    def test_reactivated_user_returned_again(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_active(user["id"], False)
        user_model.set_active(user["id"], True)
        assert user_model.get_by_username("jdoe") is not None


class TestHasAnyPinSet:
    def test_false_when_no_pins_set(self, test_db):
        # Default schema inserts admin user with NULL pin
        assert user_model.has_any_pin_set() is False

    def test_true_after_creating_user_with_pin(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        assert user_model.has_any_pin_set() is True

    def test_false_after_clearing_all_pins(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        conn = get_connection()
        conn.execute("UPDATE users SET pin=NULL")
        conn.commit()
        conn.close()
        assert user_model.has_any_pin_set() is False


class TestGetAll:
    def test_includes_inactive_users(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_active(user["id"], False)
        all_users = user_model.get_all()
        assert any(u["username"] == "jdoe" for u in all_users)

    def test_returns_at_least_default_admin(self, test_db):
        all_users = user_model.get_all()
        assert len(all_users) >= 1


class TestUpdate:
    def test_update_changes_full_name_and_role(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.update(user["id"], "jdoe", "Jane Doe", "MANAGER")
        updated = user_model.get_by_username("jdoe")
        assert updated["full_name"] == "Jane Doe"
        assert updated["role"] == "MANAGER"
