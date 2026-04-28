import models.department as department_model


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
