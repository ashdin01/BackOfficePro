"""Tests for models/plu_barcode_map.py."""
import pytest
import models.plu_barcode_map as plu_map


class TestEnsureTable:
    def test_idempotent(self, test_db):
        plu_map.ensure_table()
        plu_map.ensure_table()  # must not raise


class TestSaveAndLoad:
    def test_save_and_load_roundtrip(self, test_db):
        plu_map.save(1001, "9300000001001")
        result = plu_map.load()
        assert result[1001] == "9300000001001"

    def test_load_returns_dict(self, test_db):
        assert isinstance(plu_map.load(), dict)

    def test_load_empty_on_fresh_db(self, test_db):
        assert plu_map.load() == {}

    def test_save_multiple(self, test_db):
        plu_map.save(2001, "9300000002001")
        plu_map.save(2002, "9300000002002")
        result = plu_map.load()
        assert result[2001] == "9300000002001"
        assert result[2002] == "9300000002002"

    def test_save_overwrites_existing_plu(self, test_db):
        plu_map.save(3001, "9300000003001")
        plu_map.save(3001, "9300000003999")  # replace
        result = plu_map.load()
        assert result[3001] == "9300000003999"


class TestDelete:
    def test_delete_removes_entry(self, test_db):
        plu_map.save(4001, "9300000004001")
        plu_map.delete(4001)
        result = plu_map.load()
        assert 4001 not in result

    def test_delete_nonexistent_does_not_raise(self, test_db):
        plu_map.delete(9999)  # must not raise


class TestSync:
    def test_sync_inserts_new_mapping(self, test_db):
        plu_map.sync("9300000005001", 5001)
        result = plu_map.load()
        assert result[5001] == "9300000005001"

    def test_sync_updates_existing_plu(self, test_db):
        plu_map.sync("9300000005001", 5001)
        plu_map.sync("9300000005999", 5001)
        result = plu_map.load()
        assert result[5001] == "9300000005999"

    def test_sync_none_plu_removes_mapping(self, test_db):
        plu_map.sync("9300000006001", 6001)
        plu_map.sync("9300000006001", None)
        result = plu_map.load()
        assert 6001 not in result

    def test_sync_empty_string_plu_removes_mapping(self, test_db):
        plu_map.sync("9300000007001", 7001)
        plu_map.sync("9300000007001", "")
        result = plu_map.load()
        assert 7001 not in result


class TestGetPluForBarcodes:
    def test_returns_empty_dict_for_empty_input(self, test_db):
        assert plu_map.get_plu_for_barcodes([]) == {}

    def test_returns_only_mapped_barcodes(self, test_db):
        plu_map.save(8001, "9300000008001")
        result = plu_map.get_plu_for_barcodes(["9300000008001", "9999999999999"])
        assert "9300000008001" in result
        assert "9999999999999" not in result

    def test_plu_value_is_string(self, test_db):
        plu_map.save(8002, "9300000008002")
        result = plu_map.get_plu_for_barcodes(["9300000008002"])
        assert isinstance(result["9300000008002"], str)
        assert result["9300000008002"] == "8002"


class TestFindBarcodeByPlu:
    def test_returns_barcode_for_known_plu(self, test_db):
        plu_map.save(9001, "9300000009001")
        assert plu_map.find_barcode_by_plu(9001) == "9300000009001"

    def test_returns_none_for_unknown_plu(self, test_db):
        assert plu_map.find_barcode_by_plu(9999) is None


class TestGetPluForBarcode:
    def test_returns_plu_string_for_known_barcode(self, test_db):
        plu_map.save(10001, "9300000010001")
        result = plu_map.get_plu_for_barcode("9300000010001")
        assert result == "10001"

    def test_returns_none_for_unknown_barcode(self, test_db):
        assert plu_map.get_plu_for_barcode("0000000000000") is None
