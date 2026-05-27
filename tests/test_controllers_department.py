"""Tests for department_controller and its group sub-controller."""
import pytest
import controllers.department_controller as dept_ctrl


class TestDepartmentCRUD:
    def test_get_all_returns_seeded_departments(self, test_db):
        depts = dept_ctrl.get_all()
        codes = {d['code'] for d in depts}
        assert 'GROC' in codes
        assert 'DAIRY' in codes

    def test_get_all_active_only_excludes_inactive(self, db_conn, dept_id):
        dept_ctrl.deactivate(dept_id)
        active = dept_ctrl.get_all(active_only=True)
        assert all(d['id'] != dept_id for d in active)

    def test_get_all_inactive_included_when_flag_false(self, db_conn, dept_id):
        dept_ctrl.deactivate(dept_id)
        all_depts = dept_ctrl.get_all(active_only=False)
        assert any(d['id'] == dept_id for d in all_depts)

    def test_create_and_get_by_id(self, test_db, db_conn):
        dept_ctrl.create('TEST', 'Test Department')
        row = db_conn.execute("SELECT id FROM departments WHERE code='TEST'").fetchone()
        assert row is not None
        result = dept_ctrl.get_by_id(row['id'])
        assert result['name'] == 'Test Department'

    def test_get_by_id_unknown_returns_none(self, test_db):
        assert dept_ctrl.get_by_id(99999) is None

    def test_update_changes_name(self, test_db, dept_id):
        dept_ctrl.update(dept_id, 'GROC', 'Grocery Updated', active=1)
        result = dept_ctrl.get_by_id(dept_id)
        assert result['name'] == 'Grocery Updated'

    def test_deactivate_marks_inactive(self, test_db, dept_id):
        dept_ctrl.deactivate(dept_id)
        result = dept_ctrl.get_by_id(dept_id)
        assert result['active'] == 0


class TestGroupCRUD:
    def test_get_all_groups_returns_list(self, test_db):
        assert isinstance(dept_ctrl.get_all_groups(), list)

    def test_create_group_and_retrieve(self, test_db, dept_id):
        dept_ctrl.create_group(dept_id, 'TST', 'Test Group')
        groups = dept_ctrl.get_groups_by_department(dept_id)
        assert any(g['code'] == 'TST' for g in groups)

    def test_get_group_by_id(self, test_db, dept_id):
        dept_ctrl.create_group(dept_id, 'GRP', 'Group')
        from database.connection import get_connection
        conn = get_connection()
        row = conn.execute("SELECT id FROM product_groups WHERE code='GRP'").fetchone()
        conn.release()
        result = dept_ctrl.get_group_by_id(row['id'])
        assert result['name'] == 'Group'

    def test_get_group_by_id_unknown_returns_none(self, test_db):
        assert dept_ctrl.get_group_by_id(99999) is None

    def test_update_group(self, test_db, dept_id):
        dept_ctrl.create_group(dept_id, 'UPD', 'Before')
        from database.connection import get_connection
        conn = get_connection()
        gid = conn.execute("SELECT id FROM product_groups WHERE code='UPD'").fetchone()['id']
        conn.release()
        dept_ctrl.update_group(gid, dept_id, 'UPD', 'After', active=1)
        assert dept_ctrl.get_group_by_id(gid)['name'] == 'After'
