"""Tests for settings_controller."""
import controllers.settings_controller as settings_ctrl


class TestGetSetSetting:
    def test_get_missing_key_returns_default(self, test_db):
        assert settings_ctrl.get_setting('no_such_key', 'fallback') == 'fallback'

    def test_get_missing_key_returns_empty_string_when_no_default(self, test_db):
        assert settings_ctrl.get_setting('no_such_key') == ''

    def test_set_and_get_roundtrip(self, test_db):
        settings_ctrl.set_setting('test_key', 'hello')
        assert settings_ctrl.get_setting('test_key') == 'hello'

    def test_overwrite_existing_setting(self, test_db):
        settings_ctrl.set_setting('test_key', 'first')
        settings_ctrl.set_setting('test_key', 'second')
        assert settings_ctrl.get_setting('test_key') == 'second'


class TestGetAllSettings:
    def test_returns_dict(self, test_db):
        result = settings_ctrl.get_all_settings()
        assert isinstance(result, dict)

    def test_schema_version_not_in_settings(self, test_db):
        # schema_version was moved to db_meta (v54); it must not appear in settings
        result = settings_ctrl.get_all_settings()
        assert 'schema_version' not in result


class TestGetStoreSettings:
    _REQUIRED = ('store_name', 'store_address', 'store_phone', 'store_abn', 'gst_rate')

    def test_returns_all_required_keys(self, test_db):
        result = settings_ctrl.get_store_settings()
        for key in self._REQUIRED:
            assert key in result, f"missing key: {key}"

    def test_values_are_strings(self, test_db):
        result = settings_ctrl.get_store_settings()
        for key, val in result.items():
            assert isinstance(val, str), f"{key} is not a string"

    def test_reflects_set_value(self, test_db):
        settings_ctrl.set_setting('store_name', 'Harcourt Apples')
        assert settings_ctrl.get_store_settings()['store_name'] == 'Harcourt Apples'
