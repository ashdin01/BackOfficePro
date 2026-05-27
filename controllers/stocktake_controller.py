import models.stocktake as stocktake_model


def get_all_sessions() -> list[dict]:
    return stocktake_model.get_all_sessions()


def create_session(label, department_id=None, notes='', created_by='') -> int:
    return stocktake_model.create_session(label, department_id=department_id,
                                          notes=notes, created_by=created_by)


def get_session(session_id) -> dict | None:
    return stocktake_model.get_session(session_id)


def get_counts(session_id) -> list[dict]:
    return stocktake_model.get_counts(session_id)


def import_from_csv(session_id, filepath) -> int:
    return stocktake_model.import_from_csv(session_id, filepath)


def import_from_sqlite(session_id, filepath) -> int:
    return stocktake_model.import_from_sqlite(session_id, filepath)


def upsert_count(session_id, barcode, qty) -> None:
    return stocktake_model.upsert_count(session_id, barcode, qty)


def delete_count(count_id) -> None:
    return stocktake_model.delete_count(count_id)


def apply_session(session_id) -> None:
    return stocktake_model.apply_session(session_id)


def get_variance_report(session_id) -> list[dict]:
    return stocktake_model.get_variance_report(session_id)


def get_count_for_barcode(session_id, barcode) -> float:
    """Return counted qty for a barcode in a session, or 0."""
    return stocktake_model.get_count_for_barcode(session_id, barcode)
