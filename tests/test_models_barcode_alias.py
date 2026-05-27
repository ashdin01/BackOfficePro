"""Tests for models/barcode_alias.py."""
import pytest
import models.barcode_alias as alias_model


class TestResolve:
    def test_unknown_barcode_resolves_to_itself(self, test_db):
        assert alias_model.resolve('9999999') == '9999999'

    def test_alias_resolves_to_master(self, test_db, product_barcode):
        alias_model.add('ALIAS001', product_barcode)
        assert alias_model.resolve('ALIAS001') == product_barcode

    def test_master_barcode_resolves_to_itself(self, test_db, product_barcode):
        assert alias_model.resolve(product_barcode) == product_barcode


class TestGetAliases:
    def test_empty_for_product_with_no_aliases(self, test_db, product_barcode):
        assert list(alias_model.get_aliases(product_barcode)) == []

    def test_returns_added_alias(self, test_db, product_barcode):
        alias_model.add('ALI1', product_barcode, 'First alias')
        alias_model.add('ALI2', product_barcode, 'Second alias')
        aliases = alias_model.get_aliases(product_barcode)
        codes = {a['alias_barcode'] for a in aliases}
        assert codes == {'ALI1', 'ALI2'}

    def test_ordered_by_alias_barcode(self, test_db, product_barcode):
        alias_model.add('ZZZ', product_barcode)
        alias_model.add('AAA', product_barcode)
        aliases = list(alias_model.get_aliases(product_barcode))
        assert aliases[0]['alias_barcode'] == 'AAA'
        assert aliases[1]['alias_barcode'] == 'ZZZ'


class TestAddAndDelete:
    def test_add_stores_description(self, test_db, product_barcode):
        alias_model.add('ALI_DESC', product_barcode, 'A description')
        aliases = alias_model.get_aliases(product_barcode)
        match = next(a for a in aliases if a['alias_barcode'] == 'ALI_DESC')
        assert match['description'] == 'A description'

    def test_delete_removes_alias(self, test_db, product_barcode):
        alias_model.add('DEL_ME', product_barcode)
        aid = alias_model.get_aliases(product_barcode)[0]['id']
        alias_model.delete(aid)
        assert list(alias_model.get_aliases(product_barcode)) == []

    def test_delete_does_not_affect_resolve_for_master(self, test_db, product_barcode):
        alias_model.add('RM_ALIAS', product_barcode)
        aid = alias_model.get_aliases(product_barcode)[0]['id']
        alias_model.delete(aid)
        assert alias_model.resolve(product_barcode) == product_barcode

    def test_duplicate_alias_raises(self, test_db, product_barcode):
        alias_model.add('DUP', product_barcode)
        with pytest.raises(Exception):
            alias_model.add('DUP', product_barcode)
