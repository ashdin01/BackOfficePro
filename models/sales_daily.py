"""Model for sales_daily table and related PLU-based sales queries."""
import logging
from datetime import date, timedelta
from database.connection import db_conn


# ── Internal helper ───────────────────────────────────────────────────────────

def _where_params(d_from, d_to, group=None):
    where  = "WHERE sale_date BETWEEN ? AND ?"
    params = [d_from, d_to]
    if group:
        where += " AND sub_group = ?"
        params.append(group)
    return where, params


# ── Table helpers ─────────────────────────────────────────────────────────────

def table_exists() -> bool:
    """Return True if the sales_daily table exists."""
    with db_conn() as conn:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sales_daily'"
        ).fetchone() is not None


def get_groups() -> list:
    """Distinct sub_group values from sales_daily, sorted."""
    with db_conn() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT sub_group FROM sales_daily "
                "WHERE sub_group IS NOT NULL ORDER BY sub_group"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            logging.exception("sales_daily.get_groups failed")
            return []


def get_stats(d_from: str, d_to: str, group=None) -> dict:
    """
    Aggregate stats for the date range.
    Returns: total_rev, total_qty, total_days, top_name, top_sales.
    """
    where, params = _where_params(d_from, d_to, group)
    with db_conn() as conn:
        stats = conn.execute(f"""
            SELECT SUM(sales_dollars) + SUM(discount), SUM(quantity),
                   COUNT(DISTINCT sale_date)
            FROM sales_daily {where}
        """, params).fetchone()
        top = conn.execute(f"""
            SELECT plu_name, SUM(sales_dollars) AS s
            FROM sales_daily {where}
            GROUP BY plu ORDER BY s DESC LIMIT 1
        """, params).fetchone()
        return {
            'total_rev':   stats[0] or 0,
            'total_qty':   stats[1] or 0,
            'total_days':  stats[2] or 0,
            'top_name':    top[0][:30] if top else None,
            'top_sales':   top[1]      if top else None,
        }


def get_by_product(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by PLU for the date range.
    Returns list of dicts: plu, plu_name, sub_group, qty, sales, avg_day.
    """
    where, params = _where_params(d_from, d_to, group)
    with db_conn() as conn:
        rows = conn.execute(f"""
            SELECT
                sd.plu,
                sd.plu_name,
                sd.sub_group,
                SUM(sd.quantity)      AS qty,
                SUM(sd.sales_dollars) AS sales,
                SUM(sd.sales_dollars) / NULLIF(COUNT(DISTINCT sd.sale_date), 0) AS avg_day
            FROM sales_daily sd
            {where}
            GROUP BY sd.plu
            ORDER BY sales DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_by_day(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by date.
    Returns list of dicts: sale_date, quantity, sales_dollars, discount, net_sales.
    """
    where, params = _where_params(d_from, d_to, group)
    with db_conn() as conn:
        rows = conn.execute(f"""
            SELECT sale_date,
                   SUM(quantity)      AS quantity,
                   SUM(sales_dollars) AS sales_dollars,
                   SUM(discount)      AS discount,
                   SUM(sales_dollars) + SUM(discount) AS net_sales
            FROM sales_daily {where}
            GROUP BY sale_date ORDER BY sale_date DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_by_group(d_from: str, d_to: str, group=None) -> list:
    """
    Sales aggregated by sub_group.
    Returns list of dicts: sub_group, quantity, sales_dollars.
    """
    where, params = _where_params(d_from, d_to, group)
    with db_conn() as conn:
        rows = conn.execute(f"""
            SELECT sub_group,
                   SUM(quantity)      AS quantity,
                   SUM(sales_dollars) AS sales_dollars
            FROM sales_daily {where}
            GROUP BY sub_group ORDER BY SUM(sales_dollars) DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_last_import_date():
    """Return the most recent sale_date in sales_daily as a date object, or None."""
    with db_conn() as conn:
        row = conn.execute("SELECT MAX(sale_date) FROM sales_daily").fetchone()
        if row and row[0]:
            return date.fromisoformat(row[0])
        return None


# ── Per-barcode sales queries ─────────────────────────────────────────────────

def _period_bounds():
    """Returns (last_week_start, last_week_end, two_weeks_start, two_weeks_end,
    month_start, year_start, today) — the window boundaries shared by the
    per-barcode last_week/two_weeks/this_month/ytd breakdowns."""
    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end   = this_week_start - timedelta(days=1)
    two_weeks_start = last_week_start - timedelta(days=7)
    two_weeks_end   = last_week_start - timedelta(days=1)
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)
    return (last_week_start, last_week_end, two_weeks_start, two_weeks_end,
            month_start, year_start, today)


def get_sales_for_barcode(barcode):
    """
    Return a dict of sales totals (last_week, two_weeks, this_month, ytd)
    by looking up the product's PLU in the plu_barcode_map and aggregating sales_daily.
    Returns None if no PLU mapping exists.
    """
    (last_week_start, last_week_end, two_weeks_start, two_weeks_end,
     month_start, year_start, today) = _period_bounds()

    with db_conn() as conn:
        try:
            plu_row = conn.execute(
                "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
            ).fetchone()
            if not plu_row:
                return None

            plu = str(plu_row[0])

            def _qty(d_from, d_to):
                row = conn.execute("""
                    SELECT COALESCE(SUM(quantity), 0)
                    FROM sales_daily
                    WHERE plu = ? AND sale_date BETWEEN ? AND ?
                """, (plu, str(d_from), str(d_to))).fetchone()
                return int(row[0]) if row else 0

            return {
                "last_week":   _qty(last_week_start, last_week_end),
                "two_weeks":   _qty(two_weeks_start, two_weeks_end),
                "this_month":  _qty(month_start, today),
                "ytd":         _qty(year_start, today),
            }
        except Exception:
            logging.exception("sales_daily.get_sales_for_barcode failed")
            return None


def get_weight_for_barcode(barcode):
    """
    Return a dict of weight sold in kg (last_week, two_weeks, this_month, ytd)
    for a variable-weight product, by looking up its PLU in plu_barcode_map
    and summing sales_daily.weight_kg. Returns None if no PLU mapping exists.
    """
    (last_week_start, last_week_end, two_weeks_start, two_weeks_end,
     month_start, year_start, today) = _period_bounds()

    with db_conn() as conn:
        try:
            plu_row = conn.execute(
                "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
            ).fetchone()
            if not plu_row:
                return None

            plu = str(plu_row[0])

            def _weight(d_from, d_to):
                row = conn.execute("""
                    SELECT COALESCE(SUM(weight_kg), 0)
                    FROM sales_daily
                    WHERE plu = ? AND sale_date BETWEEN ? AND ?
                """, (plu, str(d_from), str(d_to))).fetchone()
                return round(float(row[0]), 3) if row else 0.0

            return {
                "last_week":   _weight(last_week_start, last_week_end),
                "two_weeks":   _weight(two_weeks_start, two_weeks_end),
                "this_month":  _weight(month_start, today),
                "ytd":         _weight(year_start, today),
            }
        except Exception:
            logging.exception("sales_daily.get_weight_for_barcode failed")
            return None


def get_sales_for_barcode_range(barcode, date_from, date_to):
    """
    Return total sales quantity for barcode between date_from and date_to (inclusive).
    Returns None if no PLU mapping exists, otherwise an int.
    """
    with db_conn() as conn:
        try:
            plu_row = conn.execute(
                "SELECT plu FROM plu_barcode_map WHERE barcode = ?", (barcode,)
            ).fetchone()
            if not plu_row:
                return None
            plu = str(plu_row[0])
            row = conn.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM sales_daily
                WHERE plu = ? AND sale_date BETWEEN ? AND ?
            """, (plu, str(date_from), str(date_to))).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            logging.exception("sales_daily.get_sales_for_barcode_range failed")
            return None


def get_sales_for_barcodes_range(barcodes, date_from, date_to):
    """
    Bulk version of get_sales_for_barcode_range.
    Returns {barcode: int|None} — None means no PLU mapping exists.
    """
    if not barcodes:
        return {}
    with db_conn() as conn:
        ph = ','.join('?' * len(barcodes))
        plu_rows = conn.execute(
            f"SELECT barcode, plu FROM plu_barcode_map WHERE barcode IN ({ph})",
            barcodes
        ).fetchall()
        barcode_to_plu = {r['barcode']: str(r['plu']) for r in plu_rows}

        result = {b: None for b in barcodes}
        if barcode_to_plu:
            all_plus = list(barcode_to_plu.values())
            ph2 = ','.join('?' * len(all_plus))
            sales_rows = conn.execute(f"""
                SELECT plu, COALESCE(SUM(quantity), 0) AS total
                FROM sales_daily
                WHERE plu IN ({ph2}) AND sale_date BETWEEN ? AND ?
                GROUP BY plu
            """, all_plus + [str(date_from), str(date_to)]).fetchall()
            plu_to_qty = {r['plu']: int(r['total']) for r in sales_rows}
            for barcode, plu in barcode_to_plu.items():
                result[barcode] = plu_to_qty.get(plu, 0)
        return result


# ── Backfill helper ───────────────────────────────────────────────────────────

def backfill_movements(plu, barcode: str):
    """Create stock movements for sales_daily rows imported before PLU was mapped."""
    try:
        plu_str = str(plu).strip()
        with db_conn() as conn:
            orphaned = conn.execute("""
                SELECT sd.sale_date, sd.plu, sd.plu_name, sd.quantity
                FROM sales_daily sd
                WHERE sd.plu = ?
                AND NOT EXISTS (
                    SELECT 1 FROM stock_movements sm
                    WHERE sm.barcode = ?
                    AND sm.reference = 'SALE-' || sd.sale_date || '-PLU' || sd.plu
                )
                ORDER BY sd.sale_date
            """, (plu_str, barcode)).fetchall()

            if not orphaned:
                return

            backfilled = 0
            for row in orphaned:
                reference = f"SALE-{row['sale_date']}-PLU{row['plu']}"
                quantity  = float(row['quantity'])
                plu_name  = row['plu_name'] or ""

                conn.execute("""
                    INSERT INTO stock_movements
                        (barcode, movement_type, quantity, reference, notes, created_by)
                    VALUES (?, 'SALE', ?, ?, ?, 'PDF Import (backfill)')
                """, (barcode, -quantity, reference,
                      f"Backfill: {plu_name} ({quantity} units)"))

                conn.execute("""
                    INSERT INTO stock_on_hand (barcode, quantity)
                    VALUES (?, ?)
                    ON CONFLICT(barcode) DO UPDATE SET
                        quantity = quantity + excluded.quantity,
                        last_updated = CURRENT_TIMESTAMP
                """, (barcode, -quantity))

                backfilled += 1

            import models.stock_on_hand as stock_on_hand
            stock_on_hand.clamp_negative_soh(
                conn, barcode, reference=f"PLU{plu_str} backfill",
                created_by='PDF Import (backfill)')
            conn.commit()
            if backfilled:
                logging.info("Backfilled %d sale movements for PLU %s → %s",
                             backfilled, plu, barcode)
    except Exception as e:
        logging.warning("Sales backfill error: %s", e, exc_info=True)
