import models.bundle as bundle_model


def get_all(active_only=False) -> list[dict]:
    return bundle_model.get_all(active_only=active_only)


def get_by_id(bundle_id) -> dict | None:
    return bundle_model.get_by_id(bundle_id)


def create(name, description, required_qty, price) -> int:
    return bundle_model.create(name, description, required_qty, price)


def update(bundle_id, name, description, required_qty, price, active) -> None:
    return bundle_model.update(bundle_id, name, description, required_qty, price, active)


def get_eligible(bundle_id) -> list[dict]:
    return bundle_model.get_eligible(bundle_id)


def add_eligible(bundle_id, barcode, description, unit_qty=1) -> None:
    return bundle_model.add_eligible(bundle_id, barcode, description, unit_qty)


def update_eligible_unit_qty(eligible_id, unit_qty) -> None:
    return bundle_model.update_eligible_unit_qty(eligible_id, unit_qty)


def delete_eligible(eligible_id) -> None:
    return bundle_model.delete_eligible(eligible_id)


def resolve_barcode_description(barcode) -> str | None:
    return bundle_model.resolve_barcode_description(barcode)


def resolve_barcode_unit_qty(barcode) -> float | None:
    return bundle_model.resolve_barcode_unit_qty(barcode)
