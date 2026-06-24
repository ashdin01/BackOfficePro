import models.user as user_model
import models.user_directory as user_directory


def get_all_active() -> list[dict]:
    return user_model.get_all_active()


def list_all_active_users() -> list[dict]:
    return user_directory.list_all_active_users()


def find_username_conflicts() -> list[str]:
    return user_directory.find_username_conflicts()


def find_user_for_login(username: str) -> dict | None:
    return user_directory.find_user_for_login(username)


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
