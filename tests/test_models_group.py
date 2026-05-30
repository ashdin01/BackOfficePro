"""Tests for models/group.py."""
import pytest
import models.group as group_model


@pytest.fixture()
def group_id(db_conn, dept_id):
    """Insert a test product group and return its id."""
    group_model.create(dept_id, "TST", "Test Group")
    row = db_conn.execute(
        "SELECT id FROM product_groups WHERE code='TST'"
    ).fetchone()
    return row["id"]


class TestGetAll:
    def test_returns_list(self, test_db):
        result = group_model.get_all()
        assert isinstance(result, list)

    def test_active_only_true_default(self, group_id):
        groups = group_model.get_all(active_only=True)
        ids = [g["id"] for g in groups]
        assert group_id in ids

    def test_inactive_excluded_by_default(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "TST", "Test Group", active=False)
        groups = group_model.get_all(active_only=True)
        ids = [g["id"] for g in groups]
        assert group_id not in ids

    def test_active_only_false_includes_inactive(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "TST", "Test Group", active=False)
        groups = group_model.get_all(active_only=False)
        ids = [g["id"] for g in groups]
        assert group_id in ids

    def test_includes_dept_name(self, group_id):
        groups = group_model.get_all()
        found = next(g for g in groups if g["id"] == group_id)
        assert found["dept_name"] is not None


class TestGetByDepartment:
    def test_returns_only_matching_department(self, group_id, dept_id, db_conn):
        other_dept = db_conn.execute(
            "SELECT id FROM departments WHERE code='MEAT'"
        ).fetchone()["id"]
        group_model.create(other_dept, "MT1", "Meat Group")
        result = group_model.get_by_department(dept_id)
        for g in result:
            assert g["department_id"] == dept_id

    def test_returns_empty_for_unknown_dept(self, test_db):
        assert group_model.get_by_department(9999) == []

    def test_active_only_false_includes_inactive(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "TST", "Test Group", active=False)
        result = group_model.get_by_department(dept_id, active_only=False)
        ids = [g["id"] for g in result]
        assert group_id in ids


class TestGetById:
    def test_returns_none_for_missing(self, test_db):
        assert group_model.get_by_id(9999) is None

    def test_returns_dict_with_correct_fields(self, group_id):
        result = group_model.get_by_id(group_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["code"] == "TST"
        assert result["name"] == "Test Group"
        assert "dept_name" in result


class TestCreate:
    def test_create_raises_on_duplicate_code_in_dept(self, group_id, dept_id):
        with pytest.raises(Exception):
            group_model.create(dept_id, "TST", "Duplicate")

    def test_same_code_allowed_in_different_dept(self, dept_id, db_conn):
        other_dept = db_conn.execute(
            "SELECT id FROM departments WHERE code='BAKERY'"
        ).fetchone()["id"]
        group_model.create(other_dept, "TST", "Bakery TST")
        row = db_conn.execute(
            "SELECT id FROM product_groups WHERE code='TST' AND department_id=?",
            (other_dept,)
        ).fetchone()
        assert row is not None


class TestUpdate:
    def test_update_name(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "TST", "Renamed Group", active=True)
        result = group_model.get_by_id(group_id)
        assert result["name"] == "Renamed Group"

    def test_update_active_false(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "TST", "Test Group", active=False)
        result = group_model.get_by_id(group_id)
        assert result["active"] == 0

    def test_code_uppercased(self, group_id, dept_id):
        group_model.update(group_id, dept_id, "low", "Test Group", active=True)
        result = group_model.get_by_id(group_id)
        assert result["code"] == "LOW"
