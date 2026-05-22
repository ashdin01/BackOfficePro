import models.bundle as bundle_model


def get_all(active_only=False):
    return bundle_model.get_all(active_only=active_only)


def get_by_id(bundle_id):
    return bundle_model.get_by_id(bundle_id)


def add(name, description, required_qty, price):
    return bundle_model.add(name, description, required_qty, price)


def update(bundle_id, name, description, required_qty, price, active):
    return bundle_model.update(bundle_id, name, description, required_qty, price, active)


def get_eligible(bundle_id):
    return bundle_model.get_eligible(bundle_id)


def add_eligible(bundle_id, barcode, description, unit_qty=1):
    return bundle_model.add_eligible(bundle_id, barcode, description, unit_qty)


def update_eligible_unit_qty(eligible_id, unit_qty):
    return bundle_model.update_eligible_unit_qty(eligible_id, unit_qty)


def remove_eligible(eligible_id):
    return bundle_model.remove_eligible(eligible_id)


def resolve_barcode_description(barcode):
    return bundle_model.resolve_barcode_description(barcode)


def resolve_barcode_unit_qty(barcode):
    return bundle_model.resolve_barcode_unit_qty(barcode)
