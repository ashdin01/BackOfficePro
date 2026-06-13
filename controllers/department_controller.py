import models.department as department_model
import models.group as group_model


def get_all(active_only=True) -> list[dict]:
    return department_model.get_all(active_only=active_only)


def get_by_id(dept_id) -> dict | None:
    return department_model.get_by_id(dept_id)


def create(code, name, no_negative_soh=0) -> None:
    department_model.create(code, name, no_negative_soh)


def update(dept_id, code, name, active, no_negative_soh=0) -> None:
    department_model.update(dept_id, code, name, active, no_negative_soh)


def deactivate(dept_id) -> None:
    department_model.deactivate(dept_id)


# ── Group wrappers ────────────────────────────────────────────────────────────

def get_all_groups(active_only=True) -> list[dict]:
    return group_model.get_all(active_only=active_only)


def get_groups_by_department(dept_id, active_only=True) -> list[dict]:
    return group_model.get_by_department(dept_id, active_only=active_only)


def get_group_by_id(group_id) -> dict | None:
    return group_model.get_by_id(group_id)


def create_group(department_id, code, name) -> None:
    group_model.create(department_id, code, name)


def update_group(group_id, department_id, code, name, active) -> None:
    group_model.update(group_id, department_id, code, name, active)
