import models.settings as settings_model


def get_all_settings() -> dict:
    return settings_model.get_all_settings()


def get_setting(key, default='') -> str:
    return settings_model.get_setting(key, default=default)


def set_setting(key, value) -> None:
    settings_model.set_setting(key, value)


def get_store_settings() -> dict:
    """Return store display settings used by the API and POS."""
    keys = ('store_name', 'store_address', 'store_phone', 'store_abn', 'gst_rate')
    return {k: settings_model.get_setting(k, '') for k in keys}
