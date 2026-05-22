import models.stocktake as stocktake_model


def get_all_sessions():
    return stocktake_model.get_all_sessions()


def create_session(label, department_id=None, notes='', created_by=''):
    return stocktake_model.create_session(label, department_id=department_id,
                                          notes=notes, created_by=created_by)


def get_session(session_id):
    return stocktake_model.get_session(session_id)


def get_counts(session_id):
    return stocktake_model.get_counts(session_id)


def import_from_csv(session_id, filepath):
    return stocktake_model.import_from_csv(session_id, filepath)


def import_from_sqlite(session_id, filepath):
    return stocktake_model.import_from_sqlite(session_id, filepath)


def upsert_count(session_id, barcode, qty):
    return stocktake_model.upsert_count(session_id, barcode, qty)


def delete_count(count_id):
    return stocktake_model.delete_count(count_id)


def apply_session(session_id):
    return stocktake_model.apply_session(session_id)


def get_variance_report(session_id):
    return stocktake_model.get_variance_report(session_id)
