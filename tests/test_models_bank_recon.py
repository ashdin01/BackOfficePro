"""Tests for models/bank_recon.py."""
import pytest
import models.bank_recon as recon_model
import models.ar_invoice as invoice_model
import models.ar_payment as payment_model


# ── Profile CRUD ──────────────────────────────────────────────────────────────

class TestBankCsvProfile:
    def _default_kwargs(self, name="ANZ Chequing"):
        return dict(
            name=name,
            delimiter=",",
            has_header=1,
            skip_rows=0,
            date_format="%d/%m/%Y",
            amount_type="single",
            col_date=0,
            col_amount=3,
            col_description=2,
        )

    def test_save_returns_id(self, test_db):
        pid = recon_model.save_profile(**self._default_kwargs())
        assert isinstance(pid, int) and pid > 0

    def test_get_profile_returns_saved_data(self, test_db):
        pid = recon_model.save_profile(**self._default_kwargs())
        p = recon_model.get_profile(pid)
        assert p is not None
        assert p["name"] == "ANZ Chequing"
        assert p["delimiter"] == ","
        assert p["amount_type"] == "single"

    def test_save_profile_upserts_on_same_name(self, test_db):
        pid1 = recon_model.save_profile(**self._default_kwargs())
        pid2 = recon_model.save_profile(**self._default_kwargs(name="ANZ Chequing"))
        assert pid1 == pid2

    def test_upsert_updates_fields(self, test_db):
        recon_model.save_profile(**self._default_kwargs())
        kwargs = self._default_kwargs()
        kwargs["delimiter"] = ";"
        recon_model.save_profile(**kwargs)
        p = recon_model.get_profile(
            recon_model.get_all_profiles()[0]["id"]
        )
        assert p["delimiter"] == ";"

    def test_get_all_profiles_returns_list(self, test_db):
        recon_model.save_profile(**self._default_kwargs("Profile A"))
        recon_model.save_profile(**self._default_kwargs("Profile B"))
        profiles = recon_model.get_all_profiles()
        names = [p["name"] for p in profiles]
        assert "Profile A" in names
        assert "Profile B" in names

    def test_get_all_profiles_sorted_by_name(self, test_db):
        recon_model.save_profile(**self._default_kwargs("Z Profile"))
        recon_model.save_profile(**self._default_kwargs("A Profile"))
        names = [p["name"] for p in recon_model.get_all_profiles()]
        assert names == sorted(names, key=str.casefold)

    def test_delete_profile(self, test_db):
        pid = recon_model.save_profile(**self._default_kwargs())
        recon_model.delete_profile(pid)
        assert recon_model.get_profile(pid) is None

    def test_get_profile_unknown_returns_none(self, test_db):
        assert recon_model.get_profile(99999) is None


# ── Transactions ──────────────────────────────────────────────────────────────

class TestBankTransactions:
    def _save_profile(self):
        return recon_model.save_profile(
            name="Test Bank", delimiter=",", has_header=1,
            skip_rows=0, date_format="%d/%m/%Y", amount_type="single",
            col_date=0, col_amount=3, col_description=2,
        )

    def _sample_rows(self):
        return [
            {"txn_date": "2026-05-01", "amount": 110.00,
             "description": "Payment from ACME", "reference": "REF001"},
            {"txn_date": "2026-05-02", "amount": -50.00,
             "description": "Bank fee", "reference": ""},
        ]

    def test_insert_and_get_transactions(self, test_db):
        pid = self._save_profile()
        recon_model.insert_transactions(pid, "BATCH-001", self._sample_rows())
        txns = recon_model.get_transactions("BATCH-001")
        assert len(txns) == 2

    def test_transaction_date_and_amount_stored(self, test_db):
        pid = self._save_profile()
        recon_model.insert_transactions(pid, "BATCH-002", self._sample_rows())
        txns = recon_model.get_transactions("BATCH-002")
        assert txns[0]["txn_date"] == "2026-05-01"
        assert float(txns[0]["amount"]) == pytest.approx(110.00)

    def test_new_transactions_have_unmatched_status(self, test_db):
        pid = self._save_profile()
        recon_model.insert_transactions(pid, "BATCH-003", self._sample_rows())
        txns = recon_model.get_transactions("BATCH-003")
        assert all(t["status"] == "UNMATCHED" for t in txns)

    def test_get_transactions_empty_batch_returns_empty(self, test_db):
        assert recon_model.get_transactions("NO-SUCH-BATCH") == []

    def test_get_all_batches_returns_summary(self, test_db):
        pid = self._save_profile()
        recon_model.insert_transactions(pid, "BATCH-004", self._sample_rows())
        batches = recon_model.get_all_batches()
        batch_names = [b["import_batch"] for b in batches]
        assert "BATCH-004" in batch_names

    def test_get_all_batches_counts_totals(self, test_db):
        pid = self._save_profile()
        recon_model.insert_transactions(pid, "BATCH-005", self._sample_rows())
        batches = {b["import_batch"]: b for b in recon_model.get_all_batches()}
        assert batches["BATCH-005"]["total"] == 2
        assert batches["BATCH-005"]["unmatched"] == 2

    def test_transactions_ordered_by_date(self, test_db):
        pid = self._save_profile()
        rows = [
            {"txn_date": "2026-05-03", "amount": 10.00, "description": "C"},
            {"txn_date": "2026-05-01", "amount": 20.00, "description": "A"},
            {"txn_date": "2026-05-02", "amount": 30.00, "description": "B"},
        ]
        recon_model.insert_transactions(pid, "BATCH-006", rows)
        txns = recon_model.get_transactions("BATCH-006")
        dates = [t["txn_date"] for t in txns]
        assert dates == sorted(dates)


# ── set_matched / set_ignored ─────────────────────────────────────────────────

class TestSetStatus:
    def _setup_txn(self, test_db):
        pid = recon_model.save_profile(
            name="Test Bank", delimiter=",", has_header=1,
            skip_rows=0, date_format="%d/%m/%Y", amount_type="single",
            col_date=0, col_amount=3, col_description=2,
        )
        recon_model.insert_transactions(pid, "BATCH-S1", [
            {"txn_date": "2026-05-01", "amount": 110.00, "description": "Payment"}
        ])
        return recon_model.get_transactions("BATCH-S1")[0]["id"]

    def test_set_matched_updates_status(self, test_db, customer_id):
        txn_id = self._setup_txn(test_db)
        inv_id = invoice_model.create(
            "INV-M001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        pay_id = payment_model.create(inv_id, customer_id, "2026-05-01", 110.00)
        recon_model.set_matched(txn_id, inv_id, pay_id)
        from database.connection import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT status, invoice_id, payment_id FROM bank_transactions WHERE id=?",
            (txn_id,)
        ).fetchone()
        conn.close()
        assert row["status"] == "MATCHED"
        assert row["invoice_id"] == inv_id
        assert row["payment_id"] == pay_id

    def test_set_ignored_updates_status(self, test_db):
        txn_id = self._setup_txn(test_db)
        recon_model.set_ignored(txn_id)
        from database.connection import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT status FROM bank_transactions WHERE id=?", (txn_id,)
        ).fetchone()
        conn.close()
        assert row["status"] == "IGNORED"


# ── unmatch_transaction ───────────────────────────────────────────────────────

class TestUnmatchTransaction:
    def _matched_txn(self, test_db, customer_id):
        """Return (txn_id, inv_id, pay_id) for a matched transaction."""
        pid = recon_model.save_profile(
            name="Test Bank", delimiter=",", has_header=1,
            skip_rows=0, date_format="%d/%m/%Y", amount_type="single",
            col_date=0, col_amount=3, col_description=2,
        )
        recon_model.insert_transactions(pid, "BATCH-U1", [
            {"txn_date": "2026-05-01", "amount": 110.00, "description": "Payment"}
        ])
        txn_id = recon_model.get_transactions("BATCH-U1")[0]["id"]

        inv_id = invoice_model.create(
            "INV-U001", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")
        pay_id, _, _ = invoice_model.apply_payment(inv_id, customer_id, "2026-05-01", 110.00)
        recon_model.set_matched(txn_id, inv_id, pay_id)
        return txn_id, inv_id, pay_id

    def test_unmatch_resets_txn_to_unmatched(self, test_db, customer_id):
        txn_id, _, _ = self._matched_txn(test_db, customer_id)
        recon_model.unmatch_transaction(txn_id)
        from database.connection import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT status, invoice_id, payment_id FROM bank_transactions WHERE id=?",
            (txn_id,)
        ).fetchone()
        conn.close()
        assert row["status"] == "UNMATCHED"
        assert row["invoice_id"] is None
        assert row["payment_id"] is None

    def test_unmatch_deletes_payment_record(self, test_db, customer_id):
        txn_id, inv_id, pay_id = self._matched_txn(test_db, customer_id)
        recon_model.unmatch_transaction(txn_id)
        assert payment_model.get_by_invoice(inv_id) == []

    def test_unmatch_resets_invoice_amount_paid(self, test_db, customer_id):
        txn_id, inv_id, _ = self._matched_txn(test_db, customer_id)
        recon_model.unmatch_transaction(txn_id)
        assert invoice_model.get_by_id(inv_id)["amount_paid"] == pytest.approx(0.0)

    def test_unmatch_reverts_invoice_status_to_sent(self, test_db, customer_id):
        txn_id, inv_id, _ = self._matched_txn(test_db, customer_id)
        recon_model.unmatch_transaction(txn_id)
        assert invoice_model.get_by_id(inv_id)["status"] == "SENT"

    def test_unmatch_unknown_txn_is_noop(self, test_db):
        recon_model.unmatch_transaction(99999)  # should not raise

    def test_partial_payment_status_after_unmatch(self, test_db, customer_id):
        """After unmatching one of two payments the invoice reverts to PARTIAL."""
        pid = recon_model.save_profile(
            name="Test Bank2", delimiter=",", has_header=1,
            skip_rows=0, date_format="%d/%m/%Y", amount_type="single",
            col_date=0, col_amount=3, col_description=2,
        )
        recon_model.insert_transactions(pid, "BATCH-U2", [
            {"txn_date": "2026-05-01", "amount": 60.00, "description": "First"},
            {"txn_date": "2026-05-02", "amount": 50.00, "description": "Second"},
        ])
        txns = recon_model.get_transactions("BATCH-U2")
        inv_id = invoice_model.create(
            "INV-U002", customer_id, "2026-05-01", "2026-06-07"
        )
        invoice_model.add_line(inv_id, "Goods", 1, 100.00, gst_rate=10.0)
        invoice_model.update_status(inv_id, "SENT")

        pay1, _, _ = invoice_model.apply_payment(inv_id, customer_id, "2026-05-01", 60.00)
        pay2, _, _ = invoice_model.apply_payment(inv_id, customer_id, "2026-05-02", 50.00)
        recon_model.set_matched(txns[0]["id"], inv_id, pay1)
        recon_model.set_matched(txns[1]["id"], inv_id, pay2)

        # Unmatch the second payment
        recon_model.unmatch_transaction(txns[1]["id"])
        inv = invoice_model.get_by_id(inv_id)
        assert inv["amount_paid"] == pytest.approx(60.00)
        assert inv["status"] == "PARTIAL"
