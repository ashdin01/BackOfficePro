from database.connection import db_conn


def get_all(active_only=True) -> list[dict]:
    with db_conn() as conn:
        sql = "SELECT * FROM label_formats"
        if active_only:
            sql += " WHERE active = 1"
        return [dict(r) for r in conn.execute(sql + " ORDER BY id").fetchall()]
