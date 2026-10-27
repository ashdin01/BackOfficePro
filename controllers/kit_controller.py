import models.kit as kit_model


def get_kits() -> list[dict]:
    return kit_model.get_kits()


def get_components(parent_barcode) -> list[dict]:
    return kit_model.get_components(parent_barcode)


def add_component(parent_barcode, component_barcode, qty=1) -> int:
    return kit_model.add_component(parent_barcode, component_barcode, qty)


def update_component_qty(component_id, qty) -> None:
    return kit_model.update_component_qty(component_id, qty)


def delete_component(component_id) -> None:
    return kit_model.delete_component(component_id)


def get_recipe_cost(parent_barcode) -> float:
    return kit_model.get_recipe_cost(parent_barcode)


def get_shortages(parent_barcode, qty) -> list[dict]:
    return kit_model.get_shortages(parent_barcode, qty)


def get_max_buildable(parent_barcode) -> int:
    return kit_model.get_max_buildable(parent_barcode)


def build(parent_barcode, qty, notes='', created_by='') -> int:
    """Assemble (qty > 0) or break down (qty < 0) kits; returns the build id."""
    return kit_model.build(parent_barcode, qty, notes, created_by)


def get_builds(parent_barcode=None, limit=100) -> list[dict]:
    return kit_model.get_builds(parent_barcode, limit)
