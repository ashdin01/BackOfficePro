import models.department as department_model
import models.group as group_model


def get_all(active_only=True):
    return department_model.get_all(active_only=active_only)


def get_by_id(dept_id):
    return department_model.get_by_id(dept_id)


def add(code, name):
    department_model.add(code, name)


def update(dept_id, code, name, active):
    department_model.update(dept_id, code, name, active)


def deactivate(dept_id):
    department_model.deactivate(dept_id)


# ── Group wrappers ────────────────────────────────────────────────────────────

def get_all_groups(active_only=True):
    return group_model.get_all(active_only=active_only)


def get_groups_by_department(dept_id, active_only=True):
    return group_model.get_by_department(dept_id, active_only=active_only)


def get_group_by_id(group_id):
    return group_model.get_by_id(group_id)


def add_group(department_id, code, name):
    group_model.add(department_id, code, name)


def update_group(group_id, department_id, code, name, active):
    group_model.update(group_id, department_id, code, name, active)
