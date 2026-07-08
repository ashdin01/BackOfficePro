"""Tests for models/user_directory.py — cross-store user lookups.

Each store is a standalone SQLite file (mirroring production), so these
tests build real temp .db files rather than using the shared test_db
fixture, which only models a single active store.
"""
import sqlite3

import pytest

import config.settings as cfg
import models.user_directory as ud


def _make_store_db(path, users):
    """users: list of (username, full_name, role, active) tuples."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, full_name TEXT, role TEXT, active INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO users (username, full_name, role, active) VALUES (?,?,?,?)",
        users,
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def two_stores(tmp_path, monkeypatch):
    """Store A: bob (active), carol (inactive). Store B: bob, alice."""
    _make_store_db(tmp_path / "a.db", [
        ("bob", "Bob A", "STAFF", 1),
        ("carol", "Carol A", "STAFF", 0),
    ])
    _make_store_db(tmp_path / "b.db", [
        ("bob", "Bob B", "MANAGER", 1),
        ("alice", "Alice B", "STAFF", 1),
    ])
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cfg, "STORES", [
        {"name": "Store A", "db": "a.db"},
        {"name": "Store B", "db": "b.db"},
    ])
    return tmp_path


class TestListAllActiveUsers:
    def test_merges_active_users_from_all_stores(self, two_stores):
        users = ud.list_all_active_users()
        usernames = sorted(u["username"] for u in users)
        assert usernames == ["alice", "bob", "bob"]

    def test_excludes_inactive_users(self, two_stores):
        users = ud.list_all_active_users()
        assert all(u["username"] != "carol" for u in users)

    def test_tags_each_user_with_store_name_and_db_path(self, two_stores):
        users = ud.list_all_active_users()
        alice = next(u for u in users if u["username"] == "alice")
        assert alice["store_name"] == "Store B"
        assert alice["db_path"].endswith("b.db")

    def test_skips_store_with_missing_db_file(self, tmp_path, monkeypatch):
        _make_store_db(tmp_path / "a.db", [("bob", "Bob A", "STAFF", 1)])
        monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(cfg, "STORES", [
            {"name": "Store A", "db": "a.db"},
            {"name": "Store C", "db": "does_not_exist.db"},
        ])
        users = ud.list_all_active_users()
        assert [u["username"] for u in users] == ["bob"]

    def test_skips_unreadable_store_db_without_raising(self, tmp_path, monkeypatch):
        _make_store_db(tmp_path / "a.db", [("bob", "Bob A", "STAFF", 1)])
        (tmp_path / "corrupt.db").write_bytes(b"not a sqlite file")
        monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(cfg, "STORES", [
            {"name": "Store A", "db": "a.db"},
            {"name": "Store Corrupt", "db": "corrupt.db"},
        ])
        users = ud.list_all_active_users()
        assert [u["username"] for u in users] == ["bob"]


class TestFindUsernameConflicts:
    def test_returns_usernames_used_in_more_than_one_store(self, two_stores):
        assert ud.find_username_conflicts() == ["bob"]

    def test_returns_empty_list_when_no_overlap(self, tmp_path, monkeypatch):
        _make_store_db(tmp_path / "a.db", [("bob", "Bob A", "STAFF", 1)])
        _make_store_db(tmp_path / "b.db", [("alice", "Alice B", "STAFF", 1)])
        monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(cfg, "STORES", [
            {"name": "Store A", "db": "a.db"},
            {"name": "Store B", "db": "b.db"},
        ])
        assert ud.find_username_conflicts() == []


class TestFindUserForLogin:
    def test_finds_user_in_any_store(self, two_stores):
        user = ud.find_user_for_login("alice")
        assert user is not None
        assert user["store_name"] == "Store B"

    def test_returns_none_when_not_found(self, two_stores):
        assert ud.find_user_for_login("nobody") is None

    def test_returns_none_for_inactive_user(self, two_stores):
        assert ud.find_user_for_login("carol") is None


class TestFindOtherStoreConflict:
    def test_returns_store_name_when_used_elsewhere(self, two_stores):
        db_a = str(two_stores / "a.db")
        conflict = ud.find_other_store_conflict("bob", exclude_db_path=db_a)
        assert conflict == "Store B"

    def test_returns_none_when_no_conflict(self, two_stores):
        db_a = str(two_stores / "a.db")
        assert ud.find_other_store_conflict("nobody", exclude_db_path=db_a) is None

    def test_excludes_the_given_db_path_from_matching(self, tmp_path, monkeypatch):
        """A username that only exists at exclude_db_path itself is not a conflict."""
        _make_store_db(tmp_path / "a.db", [("bob", "Bob A", "STAFF", 1)])
        _make_store_db(tmp_path / "b.db", [("alice", "Alice B", "STAFF", 1)])
        monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(cfg, "STORES", [
            {"name": "Store A", "db": "a.db"},
            {"name": "Store B", "db": "b.db"},
        ])
        db_a = str(tmp_path / "a.db")
        assert ud.find_other_store_conflict("bob", exclude_db_path=db_a) is None
