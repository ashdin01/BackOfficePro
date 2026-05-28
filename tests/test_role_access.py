"""Tests for utils/role_access and migration v52 (password_hash removal)."""
import sqlite3
import pytest
from utils.role_access import user_can_access_screen, staff_allowed_screens


class TestUserCanAccessScreen:
    def test_admin_can_access_all_screens(self):
        for i in range(12):
            assert user_can_access_screen("ADMIN", i) is True

    def test_manager_can_access_all_screens(self):
        for i in range(12):
            assert user_can_access_screen("MANAGER", i) is True

    def test_staff_allowed_screens_are_accessible(self):
        for i in staff_allowed_screens():
            assert user_can_access_screen("STAFF", i) is True

    def test_staff_blocked_from_restricted_screens(self):
        restricted = set(range(12)) - staff_allowed_screens()
        for i in restricted:
            assert user_can_access_screen("STAFF", i) is False

    def test_unknown_role_treated_as_staff(self):
        # An unrecognised role gets the most restrictive access.
        assert user_can_access_screen("UNKNOWN", 2) is False
        assert user_can_access_screen("UNKNOWN", 0) is True


class TestMigrationV52:
    def test_password_hash_column_absent_after_schema(self, test_db):
        """Fresh schema (which runs through all migrations) must not have password_hash."""
        conn = sqlite3.connect(test_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        conn.close()
        assert "password_hash" not in cols

    def test_users_table_has_expected_columns(self, test_db):
        conn = sqlite3.connect(test_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        conn.close()
        assert {"id", "username", "full_name", "pin", "role", "active", "created_at"} <= cols
