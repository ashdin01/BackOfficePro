import models.settings as settings_model


def get_all_settings():
    return settings_model.get_all_settings()


def get_setting(key, default=''):
    return settings_model.get_setting(key, default=default)


def set_setting(key, value):
    return settings_model.set_setting(key, value)
