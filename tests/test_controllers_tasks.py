"""Tests for controllers/tasks_controller.py — the home-screen 'Upcoming
Tasks' aggregator that merges recurring order reminders, PO deliveries, and
RSA cert expiries into one sorted list."""
from datetime import date, timedelta
import controllers.tasks_controller as tasks_ctrl
import controllers.purchase_order_controller as po_ctrl
import controllers.user_controller as user_ctrl


class TestUpcomingTasks:
    def test_empty_when_nothing_due(self, test_db, supplier_id):
        assert tasks_ctrl.get_upcoming_tasks() == []

    def test_order_due_today_included(self, test_db, supplier_id, db_conn):
        today_code = date.today().strftime('%a').upper()
        db_conn.execute("UPDATE suppliers SET order_days=? WHERE id=?",
                         (today_code, supplier_id))
        db_conn.commit()

        tasks = tasks_ctrl.get_upcoming_tasks()
        order_tasks = [t for t in tasks if t['kind'] == 'order_due']
        assert len(order_tasks) == 1
        assert order_tasks[0]['ref_id'] == supplier_id
        assert order_tasks[0]['severity'] == 'today'
        assert order_tasks[0]['due_date'] == date.today()

    def test_po_delivery_included(self, test_db, supplier_id):
        soon = (date.today() + timedelta(days=5)).isoformat()
        po_id = po_ctrl.create_po(supplier_id, delivery_date=soon)

        tasks = tasks_ctrl.get_upcoming_tasks()
        po_tasks = [t for t in tasks if t['kind'] == 'po_delivery']
        assert len(po_tasks) == 1
        assert po_tasks[0]['ref_id'] == po_id
        assert po_tasks[0]['severity'] == 'soon'

    def test_rsa_expiry_included(self, test_db):
        soon = (date.today() + timedelta(days=10)).isoformat()
        user_ctrl.create("jdoe", "John Doe", "STAFF", "1234",
                          rsa_cert_number="RSA-1", rsa_expiry_date=soon)

        tasks = tasks_ctrl.get_upcoming_tasks()
        rsa_tasks = [t for t in tasks if t['kind'] == 'rsa_expiry']
        assert len(rsa_tasks) == 1
        assert rsa_tasks[0]['title'] == 'John Doe'
        assert rsa_tasks[0]['severity'] == 'soon'

    def test_overdue_rsa_marked_overdue(self, test_db):
        expired = (date.today() - timedelta(days=2)).isoformat()
        user_ctrl.create("jdoe", "John Doe", "STAFF", "1234",
                          rsa_cert_number="RSA-1", rsa_expiry_date=expired)

        tasks = tasks_ctrl.get_upcoming_tasks()
        assert tasks[0]['severity'] == 'overdue'

    def test_sorted_by_due_date_ascending_across_kinds(self, test_db, supplier_id):
        far_po = (date.today() + timedelta(days=20)).isoformat()
        near_po = (date.today() + timedelta(days=1)).isoformat()
        po_ctrl.create_po(supplier_id, delivery_date=far_po)
        po_ctrl.create_po(supplier_id, delivery_date=near_po)
        user_ctrl.create("jdoe", "John Doe", "STAFF", "1234",
                          rsa_cert_number="RSA-1", rsa_expiry_date=near_po)

        tasks = tasks_ctrl.get_upcoming_tasks()
        due_dates = [t['due_date'] for t in tasks]
        assert due_dates == sorted(due_dates)
