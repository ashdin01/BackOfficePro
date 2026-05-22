import models.user as user_model


def get_all_active():
    return user_model.get_all_active()


def verify_pin(username, pin):
    return user_model.verify_pin(username, pin)


def set_pin(username, pin):
    user_model.set_pin(username, pin)
