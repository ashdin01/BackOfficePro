import logging

from database.connection import db_conn


# ── Sessions ─────────────────────────────────────────────────────────────────

def get_all_sessions():
    with db_conn() as conn:
        return conn.execute("""
            SELECT st.*, d.name as dept_name,
                   COUNT(sc.id) as line_count
            FROM stocktake_sessions st
            LEFT JOIN departments d  ON st.department_id = d.id
            LEFT JOIN stocktake_counts sc ON sc.session_id = st.id
            GROUP BY st.id
            ORDER BY st.started_at DESC
        """).fetchall()


def get_session(session_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT st.*, d.name as dept_name
            FROM stocktake_sessions st
            LEFT JOIN departments d ON st.department_id = d.id
            WHERE st.id = ?
        """, (session_id,)).fetchone()


def create_session(label, department_id=None, notes='', created_by=''):
    with db_conn() as conn:
        cur = conn.execute("""
            INSERT INTO stocktake_sessions (label, department_id, notes, created_by)
            VALUES (?, ?, ?, ?)
        """, (label, department_id, notes, created_by))
        session_id = cur.lastrowid
        conn.commit()
        return session_id


def close_session(session_id):
    with db_conn() as conn:
        conn.execute("""
            UPDATE stocktake_sessions
            SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (session_id,))
        conn.commit()


# ── Counts ────────────────────────────────────────────────────────────────────

def get_counts(session_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT sc.*, p.description, p.sell_price, p.cost_price,
                   COALESCE(soh.quantity, 0) as soh_qty,
                   d.name as dept_name
            FROM stocktake_counts sc
            JOIN products p         ON sc.barcode = p.barcode
            LEFT JOIN stock_on_hand soh ON soh.barcode = sc.barcode
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE sc.session_id = ?
            ORDER BY sc.scanned_at DESC
        """, (session_id,)).fetchall()


def upsert_count(session_id, barcode, qty):
    """Accumulate qty onto an existing count line, or insert a new one.

    Uses INSERT ... ON CONFLICT DO UPDATE so the read-modify-write is a single
    atomic statement with no race window between concurrent device scans.
    Raises ValueError if the session does not exist or is already CLOSED.
    """
    with db_conn() as conn:
        sess = conn.execute(
            "SELECT status FROM stocktake_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not sess or sess['status'] != 'OPEN':
            raise ValueError(f"Stocktake session {session_id} is not open")
        conn.execute("""
            INSERT INTO stocktake_counts (session_id, barcode, counted_qty)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, barcode) DO UPDATE SET
                counted_qty = counted_qty + excluded.counted_qty,
                scanned_at  = CURRENT_TIMESTAMP
        """, (session_id, barcode, qty))
        conn.commit()


def get_count_for_barcode(session_id, barcode):
    """Return the current counted_qty for a barcode in this session, or 0.0."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT counted_qty FROM stocktake_counts WHERE session_id=? AND barcode=?",
            (session_id, barcode)
        ).fetchone()
        return float(row['counted_qty']) if row else 0.0


def delete_count(count_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM stocktake_counts WHERE id=?", (count_id,))
        conn.commit()


def import_from_csv(session_id, filepath):
    """
    Import counts from a CSV file into this session.
    Supported column names (case-insensitive):
      barcode / ean / code / upc
      qty / quantity / count / counted / counted_qty
    Returns (imported, skipped, errors) counts.
    """
    import csv
    imported = 0
    skipped  = 0
    errors   = []

    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        barcode_col = next(
            (h for h in (reader.fieldnames or [])
             if h.lower().strip() in ('barcode', 'ean', 'code', 'upc', 'barcode/ean')),
            None
        )
        qty_col = next(
            (h for h in (reader.fieldnames or [])
             if h.lower().strip() in ('qty', 'quantity', 'count', 'counted', 'counted_qty')),
            None
        )

        if not barcode_col:
            raise ValueError(
                f"No barcode column found. Headers: {reader.fieldnames}\n"
                "Expected one of: barcode, ean, code, upc"
            )
        if not qty_col:
            raise ValueError(
                f"No quantity column found. Headers: {reader.fieldnames}\n"
                "Expected one of: qty, quantity, count, counted, counted_qty"
            )

        with db_conn() as conn:
            for row in reader:
                barcode = str(row[barcode_col]).strip()
                if not barcode:
                    skipped += 1
                    continue
                try:
                    qty = float(str(row[qty_col]).strip() or 0)
                except ValueError:
                    errors.append(f"Bad qty for barcode {barcode}: {row[qty_col]!r}")
                    skipped += 1
                    continue

                product = conn.execute(
                    "SELECT barcode FROM products WHERE barcode=?", (barcode,)
                ).fetchone()
                if not product:
                    alias = conn.execute(
                        "SELECT master_barcode FROM barcode_aliases WHERE alias_barcode=?",
                        (barcode,)
                    ).fetchone()
                    if alias:
                        barcode = alias['master_barcode']
                    else:
                        errors.append(f"Unknown barcode: {barcode}")
                        skipped += 1
                        continue

                existing = conn.execute(
                    "SELECT id, counted_qty FROM stocktake_counts WHERE session_id=? AND barcode=?",
                    (session_id, barcode)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE stocktake_counts SET counted_qty=?, scanned_at=CURRENT_TIMESTAMP WHERE id=?",
                        (existing['counted_qty'] + qty, existing['id'])
                    )
                else:
                    conn.execute(
                        "INSERT INTO stocktake_counts (session_id, barcode, counted_qty) VALUES (?,?,?)",
                        (session_id, barcode, qty)
                    )
                imported += 1
            conn.commit()

    logging.info(
        "Stocktake CSV import: session=%s file=%r imported=%d skipped=%d errors=%d",
        session_id, filepath, imported, skipped, len(errors),
    )
    if errors:
        logging.warning("Stocktake CSV import errors: %s", errors)
    return imported, skipped, errors


def _check_identifier(name):
    """Raise ValueError if name contains characters that break bracket-quoted SQL identifiers."""
    if ']' in name:
        raise ValueError(
            f"Unsafe identifier in SQLite file: {name!r} — contains ']'"
        )


def import_from_sqlite(session_id, filepath):
    """
    Import counts from an external SQLite database.
    Looks for a table containing barcode + qty columns.
    Returns (imported, skipped, errors).
    """
    import sqlite3
    imported = 0
    skipped  = 0
    errors   = []

    # Open read-only — we never write to the external file
    ext_conn = sqlite3.connect(f"file:{filepath}?mode=ro", uri=True)
    ext_conn.row_factory = sqlite3.Row
    try:
        tables = [
            r[0] for r in
            ext_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        if not tables:
            raise ValueError("No tables found in the SQLite file.")

        target_table = barcode_col = qty_col = None
        for table in tables:
            _check_identifier(table)
            cols = [r[1].lower() for r in ext_conn.execute(f"PRAGMA table_info([{table}])").fetchall()]
            bc = next((c for c in cols if c in ('barcode', 'ean', 'code', 'upc', 'barcode/ean')), None)
            qc = next((c for c in cols if c in ('qty', 'quantity', 'count', 'counted', 'counted_qty')), None)
            if bc and qc:
                orig = [r[1] for r in ext_conn.execute(f"PRAGMA table_info([{table}])").fetchall()]
                target_table = table
                barcode_col  = next(c for c in orig if c.lower() == bc)
                qty_col      = next(c for c in orig if c.lower() == qc)
                break

        if not target_table:
            raise ValueError(
                f"No suitable table found. Tables: {tables}\n"
                "Need a table with barcode and qty columns."
            )

        _check_identifier(barcode_col)
        _check_identifier(qty_col)

        rows = ext_conn.execute(
            f"SELECT [{barcode_col}], [{qty_col}] FROM [{target_table}]"
        ).fetchall()
    finally:
        ext_conn.close()

    with db_conn() as conn:
        for row in rows:
            barcode = str(row[0]).strip()
            if not barcode:
                skipped += 1
                continue
            try:
                qty = float(row[1] or 0)
            except (ValueError, TypeError):
                errors.append(f"Bad qty for barcode {barcode}: {row[1]!r}")
                skipped += 1
                continue

            product = conn.execute(
                "SELECT barcode FROM products WHERE barcode=?", (barcode,)
            ).fetchone()
            if not product:
                alias = conn.execute(
                    "SELECT master_barcode FROM barcode_aliases WHERE alias_barcode=?",
                    (barcode,)
                ).fetchone()
                if alias:
                    barcode = alias['master_barcode']
                else:
                    errors.append(f"Unknown barcode: {barcode}")
                    skipped += 1
                    continue

            existing = conn.execute(
                "SELECT id, counted_qty FROM stocktake_counts WHERE session_id=? AND barcode=?",
                (session_id, barcode)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE stocktake_counts SET counted_qty=?, scanned_at=CURRENT_TIMESTAMP WHERE id=?",
                    (existing['counted_qty'] + qty, existing['id'])
                )
            else:
                conn.execute(
                    "INSERT INTO stocktake_counts (session_id, barcode, counted_qty) VALUES (?,?,?)",
                    (session_id, barcode, qty)
                )
            imported += 1
        conn.commit()

    logging.info(
        "Stocktake SQLite import: session=%s file=%r imported=%d skipped=%d errors=%d",
        session_id, filepath, imported, skipped, len(errors),
    )
    if errors:
        logging.warning("Stocktake SQLite import errors: %s", errors)
    return imported, skipped, errors


def get_variance_report(session_id):
    """
    Returns all products relevant to this session's department(s),
    showing SOH vs counted qty and variance. Products not yet counted
    are included with counted_qty = None.
    """
    with db_conn() as conn:
        session = conn.execute(
            "SELECT * FROM stocktake_sessions WHERE id=?", (session_id,)
        ).fetchone()
        dept_filter  = ""
        params_base  = []
        if session and session['department_id']:
            dept_filter = "AND p.department_id = ?"
            params_base = [session['department_id']]

        return conn.execute(f"""
            SELECT
                p.barcode,
                p.description,
                p.cost_price,
                p.sell_price,
                d.name as dept_name,
                COALESCE(soh.quantity, 0) as soh_qty,
                sc.counted_qty
            FROM products p
            LEFT JOIN departments d      ON p.department_id = d.id
            LEFT JOIN stock_on_hand soh  ON soh.barcode = p.barcode
            LEFT JOIN stocktake_counts sc
                ON sc.barcode = p.barcode AND sc.session_id = ?
            WHERE p.active = 1
              AND p.expected = 1
              {dept_filter}
            ORDER BY d.name, p.description
        """, [session_id] + params_base).fetchall()


def apply_session(session_id):
    """Write counted quantities to stock_on_hand and log movements."""
    from database.audit_context import get_user, get_source
    who = get_user()
    src = get_source()
    with db_conn() as conn:
        session = conn.execute(
            "SELECT status FROM stocktake_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session:
            raise ValueError(f"Stocktake session {session_id} not found")
        if session['status'] != 'OPEN':
            raise ValueError(
                f"Stocktake session {session_id} cannot be applied — "
                f"status is '{session['status']}' (expected OPEN)"
            )

        counts = conn.execute(
            "SELECT * FROM stocktake_counts WHERE session_id=?", (session_id,)
        ).fetchall()
        for c in counts:
            barcode = c['barcode']
            counted = c['counted_qty']
            soh = conn.execute(
                "SELECT quantity FROM stock_on_hand WHERE barcode=?", (barcode,)
            ).fetchone()
            current = soh['quantity'] if soh else 0
            diff = counted - current
            conn.execute("""
                INSERT INTO stock_on_hand (barcode, quantity)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    quantity = excluded.quantity,
                    last_updated = CURRENT_TIMESTAMP
            """, (barcode, counted))
            conn.execute("""
                INSERT INTO stock_movements
                    (barcode, movement_type, quantity, reference, notes, created_by, source)
                VALUES (?, 'STOCKTAKE', ?, ?, ?, ?, ?)
            """, (barcode, diff, f"Stocktake #{session_id}", "Applied from stocktake", who, src))
        conn.execute("""
            UPDATE stocktake_sessions
            SET status='CLOSED', closed_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (session_id,))
        conn.commit()
        logging.info(
            "Stocktake session %s applied: %d lines written to stock_on_hand",
            session_id, len(counts),
        )
