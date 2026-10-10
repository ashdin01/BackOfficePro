"""
One-off correction for a sale date double-deducted by a manual import followed
by a stale (pre-v2.17.2) automatic ATRIA sync.

Signature of the bug for one (sale_date, PLU): stock_movements has SALE rows in
both formats -- versioned `SALE-<date>-PLU<n>-Q<total>` (manual import, delta
logic) and plain `SALE-<date>-PLU<n>` (stale auto-sync, full day quantity).
The plain row already deducts the whole day, so the Q rows are the excess.

The correction is the difference between the stock the product *should* have
now (replaying its movements from just before the first Q row, without the Q
rows and the auto-clamp rows they caused) and what it has. For ordinary
products that is simply the Q total. For no-negative-SOH departments (Fresh)
the clamp floors stock at zero, so the excess is often already absorbed and
the correction is smaller or zero -- restoring the raw Q total there would
invent stock.

A DUPFIX-<date>-<barcode> movement is recorded for the correction. Dry run by
default; pass --apply to write. Re-running is safe: a barcode that already has
its DUPFIX movement is skipped.

Usage:
    python3 scripts/fix_duplicate_deductions.py --date 2026-09-27 [--db PATH] [--apply]
"""
import argparse
import os
import re
import sqlite3
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

MOVEMENT_TYPE = "SA - Stock Adjust Error"
CREATED_BY = "ash (dup-import correction script)"
CLAMP_NOTE = "Auto-clamp%"
_REF = re.compile(r"^SALE-(\d{4}-\d{2}-\d{2})-PLU(\d+)(-Q[\d.e+-]+)?$")


def find_duplicates(conn, sale_date):
    """{barcode: {'plus': [...], 'excess': raw Q total, 'q_refs': set(...)}}"""
    rows = conn.execute(
        "SELECT barcode, reference, quantity FROM stock_movements "
        "WHERE movement_type='SALE' AND reference LIKE ?",
        (f"SALE-{sale_date}-PLU%",),
    ).fetchall()
    groups = {}
    for barcode, ref, qty in rows:
        m = _REF.match(ref)
        if not m or m.group(1) != sale_date:
            continue
        g = groups.setdefault((barcode, m.group(2)),
                              {"q": 0.0, "has_plain": False, "has_q": False, "q_refs": set()})
        if m.group(3):
            g["q"] += -qty
            g["has_q"] = True
            g["q_refs"].add(ref)
        else:
            g["has_plain"] = True

    out = {}
    for (barcode, plu), g in groups.items():
        if g["has_plain"] and g["has_q"] and g["q"] > 0:
            e = out.setdefault(barcode, {"plus": [], "excess": 0.0, "q_refs": set()})
            e["plus"].append(plu)
            e["excess"] += g["q"]
            e["q_refs"] |= g["q_refs"]
    return out


def _is_locked(conn, barcode):
    row = conn.execute(
        "SELECT d.no_negative_soh FROM products p JOIN departments d ON d.id=p.department_id "
        "WHERE p.barcode=?", (barcode,)).fetchone()
    return bool(row and row[0])


def _replay(conn, barcode, start_id, base, locked, skip_refs=frozenset()):
    """Stock after replaying movements from start_id, recomputing the clamp.

    Existing auto-clamp rows are skipped (and re-derived when locked); rows
    whose reference is in skip_refs are skipped as if they never happened.
    """
    running = base
    for _id, mtype, qty, ref, notes in conn.execute(
            "SELECT id, movement_type, quantity, reference, notes FROM stock_movements "
            "WHERE barcode=? AND id>=? ORDER BY id", (barcode, start_id)):
        if mtype == "ADJUSTMENT_IN" and (notes or "").startswith("Auto-clamp"):
            continue
        if ref in skip_refs and mtype in ("SALE", "ADJUSTMENT_IN"):
            continue
        running += qty
        if locked and running < 0:
            running = 0.0
    return running


def correction_for(conn, barcode, d):
    """Return (correction, actual_replay_matches_stored_soh)."""
    locked = _is_locked(conn, barcode)
    soh = conn.execute("SELECT quantity FROM stock_on_hand WHERE barcode=?", (barcode,)).fetchone()
    soh = soh[0] if soh else 0.0
    if not locked:
        return d["excess"], True
    marks = ",".join("?" * len(d["q_refs"]))
    start = conn.execute(
        f"SELECT MIN(id) FROM stock_movements WHERE barcode=? AND movement_type='SALE' "
        f"AND reference IN ({marks})", (barcode, *d["q_refs"])).fetchone()[0]
    base = conn.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM stock_movements WHERE barcode=? AND id<?",
        (barcode, start)).fetchone()[0]
    actual = _replay(conn, barcode, start, base, True)
    ideal = _replay(conn, barcode, start, base, True, skip_refs=frozenset(d["q_refs"]))
    return ideal - soh, abs(actual - soh) < 1e-9


def fix(conn, sale_date, apply=False):
    dups = find_duplicates(conn, sale_date)
    fixed = skipped = unverified = 0
    total = 0.0
    for barcode, d in sorted(dups.items()):
        ref = f"DUPFIX-{sale_date}-{barcode}"
        if conn.execute("SELECT 1 FROM stock_movements WHERE reference=?", (ref,)).fetchone():
            skipped += 1
            continue
        corr, verified = correction_for(conn, barcode, d)
        if not verified:
            unverified += 1
            print(f"  WARNING: replay does not reproduce stored SOH for {barcode}; skipped")
            continue
        if abs(corr) < 1e-9:
            continue
        fixed += 1
        total += corr
        if not apply:
            continue
        name = conn.execute("SELECT description FROM products WHERE barcode=?", (barcode,)).fetchone()
        note = (f"Correction: duplicate ATRIA import of {sale_date} sales double-deducted stock "
                f"for PLU {'/'.join(d['plus'])} ({name[0] if name else barcode}). Restoring "
                f"{corr:g} units wrongly removed by the automatic sync's stale import logic.")
        conn.execute(
            "INSERT INTO stock_movements (barcode, movement_type, quantity, reference, notes, created_by) "
            "VALUES (?,?,?,?,?,?)", (barcode, MOVEMENT_TYPE, corr, ref, note, CREATED_BY))
        conn.execute(
            "UPDATE stock_on_hand SET quantity = quantity + ?, last_updated = CURRENT_TIMESTAMP WHERE barcode=?",
            (corr, barcode))
    if apply:
        conn.commit()
    return {"candidates": len(dups), "fixed": fixed, "skipped": skipped,
            "unverified": unverified, "units_restored": total}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="sale date to correct, YYYY-MM-DD")
    ap.add_argument("--db", help="database path (default: BackOfficePro's configured DB)")
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        ap.error("--date must be YYYY-MM-DD")
    db = args.db
    if not db:
        from config.settings import DATABASE_PATH
        db = DATABASE_PATH
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        r = fix(conn, args.date, apply=args.apply)
    finally:
        conn.close()
    mode = "APPLIED" if args.apply else "DRY RUN (no changes written)"
    print(f"{mode} on {db}\n  duplicated products found: {r['candidates']}\n"
          f"  already corrected (skipped): {r['skipped']}\n  to fix / fixed: {r['fixed']}\n"
          f"  replay mismatches (skipped): {r['unverified']}\n"
          f"  net units restored: {r['units_restored']:g}")


if __name__ == "__main__":
    main()
