"""
merge_product_metadata.py

Selectively copies product metadata from Backup1.db into Backup2.db.

Rules:
  tax_rate        — all products except Grocery and Frozen
  variable_weight — all products
  description     — only products in department 'Fresh' or 'Liquor'

Everything else in Backup2 (prices, stock, sales history, etc.) is untouched.

Usage:
    python scripts/merge_product_metadata.py
    python scripts/merge_product_metadata.py --src ~/Desktop/Backup1.db --dst ~/Desktop/Backup2.db
    python scripts/merge_product_metadata.py --yes    # skip confirmation
"""

import sqlite3
import os
import sys
import argparse

DEFAULT_SRC = os.path.expanduser("~/Desktop/Backup1.db")
DEFAULT_DST = os.path.expanduser("~/Desktop/Backup2.db")

# Departments where description changes are allowed
DESC_DEPT_CODES = ("FRESH", "LIQ")


def _open(path, label):
    if not os.path.exists(path):
        print(f"  ERROR: {label} not found: {path}")
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _diff(val_a, val_b):
    """True if the two values differ (None-safe, string-compared)."""
    return str(val_a or '').strip() != str(val_b or '').strip()


def preview(src_path, dst_path):
    """
    Returns a list of dicts describing every change that would be applied.
    Each dict: barcode, dept_code, dept_name, field, old, new
    """
    conn = _open(dst_path, "Backup2 (destination)")
    conn.execute("ATTACH DATABASE ? AS src", (src_path,))

    rows = conn.execute("""
        SELECT
            d.barcode,
            dep.code           AS dept_code,
            dep.name           AS dept_name,
            d.description      AS d_desc,    s.description      AS s_desc,
            d.tax_rate         AS d_tax,     s.tax_rate         AS s_tax,
            d.variable_weight  AS d_vw,      s.variable_weight  AS s_vw
        FROM      products d
        JOIN      departments dep ON dep.id = d.department_id
        JOIN src.products s       ON s.barcode = d.barcode
        WHERE
            (
                dep.code NOT IN ('GROC','FROZEN')
            AND COALESCE(CAST(d.tax_rate AS TEXT),'') != COALESCE(CAST(s.tax_rate AS TEXT),'')
            )
         OR COALESCE(CAST(d.variable_weight AS TEXT),'') != COALESCE(CAST(s.variable_weight AS TEXT),'')
         OR (
                dep.code IN ('FRESH','LIQ')
            AND COALESCE(d.description,'') != COALESCE(s.description,'')
            )
        ORDER BY dep.name, d.barcode
    """).fetchall()
    conn.close()

    changes = []
    for row in rows:
        bc        = row['barcode']
        dc        = row['dept_code']
        dn        = row['dept_name']

        if dc not in ('GROC', 'FROZEN') and _diff(row['d_tax'], row['s_tax']):
            changes.append(dict(barcode=bc, dept_code=dc, dept_name=dn,
                                field='tax_rate', old=row['d_tax'], new=row['s_tax']))

        if _diff(row['d_vw'], row['s_vw']):
            old_label = "Weighed"   if row['d_vw'] else "Fixed"
            new_label = "Weighed"   if row['s_vw'] else "Fixed"
            changes.append(dict(barcode=bc, dept_code=dc, dept_name=dn,
                                field='variable_weight', old=old_label, new=new_label))

        if dc in DESC_DEPT_CODES and _diff(row['d_desc'], row['s_desc']):
            changes.append(dict(barcode=bc, dept_code=dc, dept_name=dn,
                                field='description', old=row['d_desc'], new=row['s_desc']))

    return changes


def apply_merge(src_path, dst_path):
    conn = _open(dst_path, "Backup2 (destination)")
    conn.execute("ATTACH DATABASE ? AS src", (src_path,))

    # tax_rate — all matching barcodes except Grocery and Frozen
    conn.execute("""
        UPDATE products
        SET tax_rate = (SELECT sp.tax_rate FROM src.products sp WHERE sp.barcode = products.barcode)
        WHERE barcode IN (SELECT barcode FROM src.products)
          AND department_id NOT IN (SELECT id FROM departments WHERE code IN ('GROC','FROZEN'))
          AND IFNULL(tax_rate, -1) !=
              IFNULL((SELECT sp.tax_rate FROM src.products sp WHERE sp.barcode = products.barcode), -1)
    """)
    tax_updated = conn.total_changes

    # variable_weight — all matching barcodes where it differs
    conn.execute("""
        UPDATE products
        SET variable_weight = (SELECT sp.variable_weight FROM src.products sp WHERE sp.barcode = products.barcode)
        WHERE barcode IN (SELECT barcode FROM src.products)
          AND IFNULL(variable_weight, -1) !=
              IFNULL((SELECT sp.variable_weight FROM src.products sp WHERE sp.barcode = products.barcode), -1)
    """)
    vw_updated = conn.total_changes

    # description — Fresh and Liquor departments only
    conn.execute("""
        UPDATE products
        SET description = (SELECT sp.description FROM src.products sp WHERE sp.barcode = products.barcode)
        WHERE barcode IN (SELECT barcode FROM src.products)
          AND department_id IN (SELECT id FROM departments WHERE code IN ('FRESH','LIQ'))
          AND IFNULL(description, '') !=
              IFNULL((SELECT sp.description FROM src.products sp WHERE sp.barcode = products.barcode), '')
    """)
    desc_updated = conn.total_changes

    conn.commit()
    conn.close()
    return tax_updated, vw_updated, desc_updated


def main():
    parser = argparse.ArgumentParser(description="Merge GST, variable-weight, and naming from Backup1 into Backup2.")
    parser.add_argument("--src", default=DEFAULT_SRC, help=f"Source DB  (default: {DEFAULT_SRC})")
    parser.add_argument("--dst", default=DEFAULT_DST, help=f"Destination DB (default: {DEFAULT_DST})")
    parser.add_argument("--yes", action="store_true",  help="Skip confirmation prompt")
    args = parser.parse_args()

    print(f"\n  Source (Backup1 — metadata improvements):  {args.src}")
    print(f"  Destination (Backup2 — live data):         {args.dst}")
    print(f"\n  Rules:")
    print(f"    tax_rate        — all departments except Grocery + Frozen")
    print(f"    variable_weight — all departments")
    print(f"    description     — Fresh + Liquor only\n")

    print("Scanning for differences...")
    changes = preview(args.src, args.dst)

    if not changes:
        print("  No differences found — nothing to do.\n")
        return

    # Group by department for readability
    dept_order = {}
    for c in changes:
        dept_order.setdefault(c['dept_name'], []).append(c)

    total = len(changes)
    print(f"  {total} change(s) across {len(dept_order)} department(s):\n")

    for dept, items in sorted(dept_order.items()):
        print(f"  [{dept}]")
        for c in items:
            old = str(c['old']) if c['old'] is not None else '—'
            new = str(c['new']) if c['new'] is not None else '—'
            print(f"    {c['barcode']:<16}  {c['field']:<16}  {old:<35}  →  {new}")
        print()

    if not args.yes:
        ans = input(f"  Apply these {total} change(s) to Backup2? [y/N] ").strip().lower()
        if ans != 'y':
            print("  Aborted — no changes made.\n")
            return

    tax_n, vw_n, desc_n = apply_merge(args.src, args.dst)
    print(f"\n  Done.")
    print(f"    tax_rate updates:        {tax_n}")
    print(f"    variable_weight updates: {vw_n}")
    print(f"    description updates:     {desc_n}")
    print(f"    Total:                   {tax_n + vw_n + desc_n}\n")


if __name__ == "__main__":
    main()
