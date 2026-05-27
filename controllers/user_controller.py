import models.user as user_model


def get_all_active() -> list[dict]:
    return user_model.get_all_active()


def verify_pin(username, pin) -> bool:
    return user_model.verify_pin(username, pin)


def set_pin(username, pin) -> None:
    user_model.set_pin(username, pin)


def get_all() -> list[dict]:
    return user_model.get_all()


def create(username, full_name, role, pin) -> None:
    user_model.create(username, full_name, role, pin)


def update(user_id, username, full_name, role) -> None:
    user_model.update(user_id, username, full_name, role)


def set_pin_by_id(user_id, pin) -> None:
    user_model.set_pin_by_id(user_id, pin)


def set_active(user_id, active) -> None:
    user_model.set_active(user_id, active)
