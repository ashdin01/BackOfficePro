"""Tests for stocktake_controller."""
import pytest
import controllers.stocktake_controller as st_ctrl


@pytest.fixture()
def session_id(test_db):
    return st_ctrl.create_session('Test Session')


class TestSessionLifecycle:
    def test_get_all_sessions_empty_initially(self, test_db):
        assert st_ctrl.get_all_sessions() == []

    def test_create_session_returns_int(self, test_db):
        sid = st_ctrl.create_session('My Session')
        assert isinstance(sid, int) and sid > 0

    def test_get_session_returns_correct_label(self, test_db, session_id):
        result = st_ctrl.get_session(session_id)
        assert result is not None
        assert result['label'] == 'Test Session'

    def test_get_session_unknown_returns_none(self, test_db):
        assert st_ctrl.get_session(99999) is None

    def test_get_all_sessions_includes_created(self, test_db, session_id):
        sessions = st_ctrl.get_all_sessions()
        assert any(s['id'] == session_id for s in sessions)

    def test_create_session_with_department(self, test_db, dept_id):
        sid = st_ctrl.create_session('Dept Session', department_id=dept_id, created_by='test')
        result = st_ctrl.get_session(sid)
        assert result['department_id'] == dept_id


class TestCounts:
    def test_get_counts_empty_for_new_session(self, test_db, session_id):
        assert st_ctrl.get_counts(session_id) == []

    def test_upsert_count_adds_row(self, test_db, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 5.0)
        counts = st_ctrl.get_counts(session_id)
        assert len(counts) == 1
        assert counts[0]['counted_qty'] == 5.0

    def test_upsert_count_accumulates_on_existing(self, test_db, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 3.0)
        st_ctrl.upsert_count(session_id, product_barcode, 7.0)
        counts = st_ctrl.get_counts(session_id)
        assert len(counts) == 1
        assert counts[0]['counted_qty'] == 10.0   # 3 + 7 accumulated

    def test_get_count_for_barcode_returns_zero_when_none(self, test_db, session_id, product_barcode):
        assert st_ctrl.get_count_for_barcode(session_id, product_barcode) == 0

    def test_get_count_for_barcode_returns_value(self, test_db, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 12.0)
        assert st_ctrl.get_count_for_barcode(session_id, product_barcode) == 12.0

    def test_delete_count(self, test_db, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 4.0)
        count_id = st_ctrl.get_counts(session_id)[0]['id']
        st_ctrl.delete_count(count_id)
        assert st_ctrl.get_counts(session_id) == []


class TestApplyAndVariance:
    def test_apply_session_updates_soh(self, test_db, db_conn, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 20.0)
        st_ctrl.apply_session(session_id)
        row = db_conn.execute(
            "SELECT quantity FROM stock_on_hand WHERE barcode=?", (product_barcode,)
        ).fetchone()
        assert row is not None
        assert row['quantity'] == 20.0

    def test_get_variance_report_returns_list(self, test_db, session_id, product_barcode):
        st_ctrl.upsert_count(session_id, product_barcode, 5.0)
        report = st_ctrl.get_variance_report(session_id)
        assert isinstance(report, list)
        assert any(r['barcode'] == product_barcode for r in report)
