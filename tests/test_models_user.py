"""Tests for models/user.py — authentication and user management."""
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

    def test_pin_stored_as_pbkdf2_not_plaintext(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        assert user["pin"] != "1234"
        assert user["pin"].startswith("pbkdf2:")

    def test_pin_verifiable_after_create(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        assert user_model.verify_pin("jdoe", "1234") is True
        assert user_model.verify_pin("jdoe", "9999") is False

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

    def test_user_with_no_pin_set_returns_false(self, test_db):
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('nopin', 'No Pin User', 'STAFF', NULL, 1)"
        )
        conn.commit()
        conn.close()
        assert user_model.verify_pin("nopin", "1234") is False

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

    def test_legacy_plaintext_pin_migrated_to_pbkdf2_after_login(self, test_db):
        """After authenticating with a plaintext PIN it should be auto-migrated to PBKDF2."""
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('legacy', 'Legacy User', 'STAFF', '5678', 1)"
        )
        conn.commit()
        conn.close()
        user_model.verify_pin("legacy", "5678")
        user = user_model.get_by_username("legacy")
        assert user["pin"].startswith("pbkdf2:")
        assert user_model.verify_pin("legacy", "5678") is True

    def test_legacy_sha256_pin_migrated_to_pbkdf2_after_login(self, test_db):
        """After authenticating with a legacy SHA-256 PIN it should be auto-migrated to PBKDF2."""
        import hashlib as _hl
        old_hash = _hl.sha256("7777".encode()).hexdigest()
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('sha2user', 'SHA2 User', 'STAFF', ?, 1)",
            (old_hash,)
        )
        conn.commit()
        conn.close()
        assert user_model.verify_pin("sha2user", "7777") is True
        user = user_model.get_by_username("sha2user")
        assert user["pin"].startswith("pbkdf2:")
        assert user_model.verify_pin("sha2user", "7777") is True

    def test_legacy_plaintext_pin_wrong_guess_returns_false(self, test_db):
        """A legacy (non-pbkdf2) stored PIN that doesn't match sha256 or
        plaintext falls through to the final `return False`."""
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('legacy', 'Legacy User', 'STAFF', '5678', 1)"
        )
        conn.commit()
        conn.close()
        assert user_model.verify_pin("legacy", "0000") is False

    def test_malformed_pbkdf2_hash_returns_false_without_raising(self, test_db):
        """A corrupted pbkdf2:-prefixed stored value must not raise — just fail closed."""
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (username, full_name, role, pin, active) "
            "VALUES ('corrupt', 'Corrupt User', 'STAFF', 'pbkdf2:not-valid-hex', 1)"
        )
        conn.commit()
        conn.close()
        assert user_model.verify_pin("corrupt", "1234") is False


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

    def test_update_nonexistent_user_id_does_not_raise(self, test_db):
        """No matching row -> `if old:` is falsy, record_changes is skipped."""
        user_model.update(99999, "ghost", "Ghost User", "STAFF")

    def test_update_with_unchanged_username_skips_conflict_check(self, test_db, monkeypatch):
        """Same username -> _check_cross_store_conflict must not even be called."""
        import models.user as um
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        called = []
        monkeypatch.setattr(um, "_check_cross_store_conflict", lambda u: called.append(u))
        user_model.update(user["id"], "jdoe", "Jane Doe", "MANAGER")
        assert called == []

    def test_update_renaming_username_checks_cross_store_conflict(self, test_db, monkeypatch):
        import models.user as um
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        called = []
        monkeypatch.setattr(um, "_check_cross_store_conflict", lambda u: called.append(u))
        user_model.update(user["id"], "jdoe2", "Jane Doe", "MANAGER")
        assert called == ["jdoe2"]

    def test_update_renamed_username_raises_on_cross_store_conflict(self, test_db, monkeypatch):
        import models.user_directory as ud
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        monkeypatch.setattr(
            ud, "find_other_store_conflict",
            lambda username, exclude_db_path=None: "Other Store",
        )
        with pytest.raises(ValueError, match="already in use"):
            user_model.update(user["id"], "taken_username", "Jane Doe", "MANAGER")


class TestCrossStoreConflict:
    def test_create_raises_when_username_used_at_other_store(self, test_db, monkeypatch):
        import models.user_directory as ud
        monkeypatch.setattr(
            ud, "find_other_store_conflict",
            lambda username, exclude_db_path=None: "Other Store",
        )
        with pytest.raises(ValueError, match="already in use at Other Store"):
            user_model.create("taken", "Someone", "STAFF", "1234")

    def test_create_succeeds_when_no_conflict(self, test_db, monkeypatch):
        import models.user_directory as ud
        monkeypatch.setattr(
            ud, "find_other_store_conflict",
            lambda username, exclude_db_path=None: None,
        )
        user_model.create("free_user", "Someone", "STAFF", "1234")
        assert user_model.get_by_username("free_user") is not None


class TestSetActiveAndSetPinByIdNonexistent:
    def test_set_active_nonexistent_user_id_does_not_raise(self, test_db):
        user_model.set_active(99999, True)

    def test_set_pin_by_id_nonexistent_user_id_does_not_raise(self, test_db):
        user_model.set_pin_by_id(99999, "1234")


# ── PIN validation ────────────────────────────────────────────────────────────

class TestPinValidation:
    def test_create_rejects_short_pin(self, test_db):
        with pytest.raises(ValueError, match="PIN"):
            user_model.create("jdoe", "John Doe", "STAFF", "12")

    def test_create_rejects_non_digit_pin(self, test_db):
        with pytest.raises(ValueError, match="PIN"):
            user_model.create("jdoe", "John Doe", "STAFF", "abcd")

    def test_create_rejects_empty_pin(self, test_db):
        with pytest.raises(ValueError, match="PIN"):
            user_model.create("jdoe", "John Doe", "STAFF", "")

    def test_create_rejects_too_long_pin(self, test_db):
        with pytest.raises(ValueError, match="PIN"):
            user_model.create("jdoe", "John Doe", "STAFF", "123456789")

    def test_create_accepts_4_digit_pin(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        assert user_model.get_by_username("jdoe") is not None

    def test_create_accepts_8_digit_pin(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "12345678")
        assert user_model.get_by_username("jdoe") is not None

    def test_set_pin_rejects_short_pin(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        with pytest.raises(ValueError, match="PIN"):
            user_model.set_pin("jdoe", "12")

    def test_set_pin_by_id_rejects_non_digit(self, test_db):
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        with pytest.raises(ValueError, match="PIN"):
            user_model.set_pin_by_id(user["id"], "abcd")


# ── Audit log for user events ─────────────────────────────────────────────────

class TestUserAuditLog:
    def test_create_writes_audit_entry(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        entries = get_for_entity("user", "jdoe")
        assert len(entries) > 0

    def test_update_writes_audit_on_role_change(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.update(user["id"], "jdoe", "John Doe", "MANAGER")
        entries = get_for_entity("user", "jdoe")
        role_changes = [e for e in entries if e["field"] == "role"]
        assert role_changes, "Expected a role change audit entry"
        assert role_changes[0]["new_value"] == "MANAGER"
        assert role_changes[0]["old_value"] == "STAFF"

    def test_set_active_writes_audit_entry(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        user_model.set_active(user["id"], False)
        entries = get_for_entity("user", "jdoe")
        active_changes = [e for e in entries if e["field"] == "active"]
        assert active_changes
        assert active_changes[0]["new_value"] == "0"

    def test_set_pin_writes_audit_entry(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user_model.set_pin("jdoe", "5678")
        entries = get_for_entity("user", "jdoe")
        pin_changes = [e for e in entries if e["field"] == "pin"]
        assert pin_changes

    def test_set_pin_audit_does_not_store_hash(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user_model.set_pin("jdoe", "5678")
        entries = get_for_entity("user", "jdoe")
        for e in entries:
            assert "pbkdf2:" not in (e.get("old_value") or "")
            assert "pbkdf2:" not in (e.get("new_value") or "")

    def test_update_no_audit_when_nothing_changes(self, test_db):
        from models.audit_log import get_for_entity
        user_model.create("jdoe", "John Doe", "STAFF", "1234")
        user = user_model.get_by_username("jdoe")
        # Update with same values — no fields changed
        user_model.update(user["id"], "jdoe", "John Doe", "STAFF")
        entries = get_for_entity("user", "jdoe")
        # Only the create entry should exist
        non_create = [e for e in entries if e["field"] != "role" or e["old_value"] != ""]
        role_changes = [e for e in entries if e["field"] == "role" and e["old_value"] == "STAFF"]
        assert not role_changes, "No role-change entry expected when role did not change"
