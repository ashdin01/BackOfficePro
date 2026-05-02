"""
Daily PLU Sales Importer for BackOfficePro
Supports both CSV and PDF exports from the same POS reporting system.
After import, creates negative stock movements for all matched products.

Duplicate handling: keyed on (sale_date, plu). Re-importing the same file
overwrites existing rows rather than creating duplicates.
"""
import csv
import sys
import os
import re

if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

try:
    import pdfplumber
except ImportError:
    os.system("pip3 install pdfplumber --break-system-packages -q")
    import pdfplumber

from database.connection import get_connection
from datetime import datetime


def ensure_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales_daily (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date     TEXT NOT NULL,
            plu           TEXT,
            plu_name      TEXT,
            sub_group     TEXT,
            weight_kg     REAL DEFAULT 0,
            quantity      REAL DEFAULT 0,
            nominal_price REAL DEFAULT 0,
            discount      REAL DEFAULT 0,
            rounding      REAL DEFAULT 0,
            sales_dollars REAL DEFAULT 0,
            sales_pct     REAL DEFAULT 0,
            imported_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(sale_date, plu)
        )
    """)
    conn.commit()
    conn.close()


def _parse_date_dmy(text):
    return datetime.strptime(text.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")


# ── CSV parser ────────────────────────────────────────────────────────────────
#
# The CSV export has 36 columns per row. Columns 0–18 repeat the report header
# and day totals on every row. The actual PLU data lives in columns 19–29.
# Row 1 is a header of internal widget names (textBox2, textBox5, …) — skipped.

_COL_PLU           = 19
_COL_PLU_NAME      = 20
_COL_WEIGHT        = 21
_COL_NOMINAL       = 22
_COL_DISC          = 23
_COL_SALES_PCT     = 24
_COL_SALES_DOLLARS = 25
_COL_QUANTITY      = 26
_COL_SUB_GROUP     = 27
_COL_ROUNDING      = 28
_COL_DATE          = 29


def parse_csv(path):
    rows = []
    sale_date = None

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader)  # skip textBox widget-name header row

        for line in reader:
            if len(line) <= _COL_DATE:
                continue

            plu      = line[_COL_PLU].strip()
            raw_date = line[_COL_DATE].strip()

            if not plu.isdigit() or not raw_date:
                continue

            try:
                row_date = _parse_date_dmy(raw_date)
            except ValueError:
                continue

            if sale_date is None:
                sale_date = row_date
                print(f"  Sale date: {sale_date}")

            try:
                rows.append({
                    'sale_date':     row_date,
                    'plu':           plu,
                    'plu_name':      ' '.join(line[_COL_PLU_NAME].split()),
                    'sub_group':     line[_COL_SUB_GROUP].strip(),
                    'weight_kg':     float(line[_COL_WEIGHT]        or 0),
                    'quantity':      float(line[_COL_QUANTITY]       or 0),
                    'nominal_price': float(line[_COL_NOMINAL]        or 0),
                    'discount':      float(line[_COL_DISC]           or 0),
                    'rounding':      float(line[_COL_ROUNDING]       or 0),
                    'sales_dollars': float(line[_COL_SALES_DOLLARS]  or 0),
                    'sales_pct':     float(line[_COL_SALES_PCT].replace('%', '') or 0),
                })
            except (ValueError, IndexError):
                continue

    print(f"  Preview (first 5 rows):")
    for r in rows[:5]:
        print(f"    PLU {r['plu']:>6}  name: {r['plu_name']!r:<40}  sub: {r['sub_group']!r}")

    return rows


# ── PDF parser ────────────────────────────────────────────────────────────────

def parse_pdf(path):
    rows = []
    sale_date = None

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if i == 0:
                m = re.search(r'Report from (\d+/\d+/\d+)', text)
                sale_date = _parse_date_dmy(m.group(1)) if m else datetime.today().strftime("%Y-%m-%d")
                print(f"  Sale date: {sale_date}")

            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not words:
                continue

            lines = {}
            for w in words:
                y = round(w['top'])
                lines.setdefault(y, []).append(w)

            header_y = None
            subgroup_x_start = None

            for y in sorted(lines.keys()):
                line_words = [w['text'] for w in lines[y]]
                line_text = ' '.join(line_words)
                if 'Sub Group' in line_text or 'Sub' in line_words:
                    header_y = y
                    for w in lines[y]:
                        if w['text'] in ('Sub', 'Group'):
                            subgroup_x_start = w['x0']
                            break
                    break

            for y in sorted(lines.keys()):
                if header_y and abs(y - header_y) < 5:
                    continue

                line_words = lines[y]
                if not line_words or not line_words[0]['text'].isdigit():
                    continue

                plu = line_words[0]['text']
                sorted_words = sorted(line_words[1:], key=lambda w: w['x0'])

                num_start_idx = None
                for idx, w in enumerate(sorted_words):
                    cleaned = w['text'].replace('%', '').replace('-', '', 1)
                    if re.match(r'^\d+\.\d+$', cleaned):
                        num_start_idx = idx
                        break

                if num_start_idx is None:
                    continue

                text_words = sorted_words[:num_start_idx]
                num_words  = sorted_words[num_start_idx:]

                numerics = []
                for w in num_words:
                    try:
                        numerics.append(float(w['text'].replace('%', '').strip()))
                    except ValueError:
                        pass

                if len(numerics) < 7:
                    continue

                name_words = []
                subgroup_words = []
                if subgroup_x_start:
                    for w in text_words:
                        if w['x0'] < subgroup_x_start - 5:
                            name_words.append(w['text'])
                        else:
                            subgroup_words.append(w['text'])
                else:
                    name_words = [w['text'] for w in text_words]

                try:
                    rows.append({
                        'sale_date':     sale_date,
                        'plu':           plu,
                        'plu_name':      ' '.join(name_words).strip(),
                        'sub_group':     ' '.join(subgroup_words).strip(),
                        'weight_kg':     numerics[0],
                        'quantity':      numerics[1],
                        'nominal_price': numerics[2],
                        'discount':      numerics[3],
                        'rounding':      numerics[4],
                        'sales_dollars': numerics[5],
                        'sales_pct':     numerics[6],
                    })
                except (ValueError, IndexError):
                    continue

    print(f"  Preview (first 5 rows):")
    for r in rows[:5]:
        print(f"    PLU {r['plu']:>6}  name: {r['plu_name']!r:<40}  sub: {r['sub_group']!r}")

    return rows


# ── Barcode resolution ────────────────────────────────────────────────────────

def _resolve_barcode(conn, plu):
    """
    Returns (master_barcode, unit_qty) where unit_qty is the stock multiplier.
    For regular products unit_qty=1. For selling units (case, 6-pack) unit_qty
    reflects how many base units are consumed per sale.
    """
    try:
        plu_int = int(str(plu).strip())
    except (ValueError, TypeError):
        return None, 1

    barcode = None
    for query, params in [
        ("SELECT barcode FROM plu_barcode_map WHERE plu=?",               (plu_int,)),
        ("SELECT barcode FROM products WHERE sku=? AND active=1",          (str(plu_int),)),
        ("SELECT barcode FROM products WHERE barcode=? AND active=1",      (f"02{plu_int:05d}",)),
        ("SELECT barcode FROM products WHERE barcode=? AND active=1",      (f"{plu_int:07d}",)),
    ]:
        row = conn.execute(query, params).fetchone()
        if row:
            barcode = row[0]
            break

    if not barcode:
        return None, 1

    # Check if this barcode is a selling unit — if so return master + multiplier
    su = conn.execute(
        "SELECT master_barcode, unit_qty FROM product_selling_units "
        "WHERE barcode=? AND active=1",
        (barcode,)
    ).fetchone()
    if su:
        return su['master_barcode'], su['unit_qty']

    return barcode, 1


def _create_sale_movement(conn, barcode, quantity, sale_date, plu, plu_name, source):
    reference = f"SALE-{sale_date}-PLU{plu}"
    existing = conn.execute(
        "SELECT id FROM stock_movements WHERE barcode=? AND reference=?",
        (barcode, reference)
    ).fetchone()
    if existing:
        return False

    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by)
        VALUES (?, 'SALE', ?, ?, ?, ?)
    """, (barcode, -quantity, reference,
          f"Sale: {plu_name} ({quantity} units)", source))

    conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity)
        VALUES (?, ?)
        ON CONFLICT(barcode) DO UPDATE SET
            quantity     = quantity + excluded.quantity,
            last_updated = CURRENT_TIMESTAMP
    """, (barcode, -quantity))

    return True


# ── Shared import logic ───────────────────────────────────────────────────────

def _import_rows(rows, source):
    """
    Upsert parsed rows into sales_daily and create stock movements.

    sales_daily has UNIQUE(sale_date, plu). ON CONFLICT DO UPDATE means
    re-importing the same date silently overwrites existing values rather
    than inserting duplicates. Stock movements are keyed on the same
    reference string, so they are also created only once per PLU per date.
    """
    if not rows:
        print("  WARNING: No data rows found")
        return 0, 0, 0

    conn = get_connection()
    try:
        upserted = movements_created = unmatched = 0

        for r in rows:
            conn.execute("""
                INSERT INTO sales_daily
                    (sale_date, plu, plu_name, sub_group, weight_kg, quantity,
                     nominal_price, discount, rounding, sales_dollars, sales_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(sale_date, plu) DO UPDATE SET
                    plu_name      = excluded.plu_name,
                    sub_group     = excluded.sub_group,
                    weight_kg     = excluded.weight_kg,
                    quantity      = excluded.quantity,
                    nominal_price = excluded.nominal_price,
                    discount      = excluded.discount,
                    rounding      = excluded.rounding,
                    sales_dollars = excluded.sales_dollars,
                    sales_pct     = excluded.sales_pct,
                    imported_at   = datetime('now','localtime')
            """, (r['sale_date'], r['plu'], r['plu_name'], r['sub_group'],
                  r['weight_kg'], r['quantity'], r['nominal_price'],
                  r['discount'], r['rounding'], r['sales_dollars'], r['sales_pct']))
            upserted += 1

            if r['quantity'] > 0:
                barcode, unit_qty = _resolve_barcode(conn, r['plu'])
                if barcode:
                    stock_qty = r['quantity'] * unit_qty
                    if _create_sale_movement(conn, barcode, stock_qty,
                                             r['sale_date'], r['plu'],
                                             r['plu_name'], source):
                        movements_created += 1
                else:
                    unmatched += 1

        conn.commit()
    finally:
        conn.close()

    print(f"  Rows upserted:                {upserted}")
    print(f"  Stock movements created:      {movements_created}")
    print(f"  Unmatched PLUs (no barcode):  {unmatched}")
    return upserted, movements_created, unmatched


# ── Public entry points ───────────────────────────────────────────────────────

def import_csv(path):
    print(f"\nImporting CSV: {os.path.basename(path)}")
    rows = parse_csv(path)
    print(f"  Parsed {len(rows)} rows")
    return _import_rows(rows, source="CSV Import")


def import_pdf(path):
    print(f"\nImporting PDF: {os.path.basename(path)}")
    rows = parse_pdf(path)
    print(f"  Parsed {len(rows)} rows")
    return _import_rows(rows, source="PDF Import")


def import_file(path):
    """Dispatch to CSV or PDF importer based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return import_csv(path)
    elif ext == '.pdf':
        return import_pdf(path)
    else:
        print(f"  Unsupported file type: {ext}")
        return 0, 0, 0


if __name__ == "__main__":
    ensure_tables()
    paths = sys.argv[1:]
    if not paths:
        print("Usage: python3 import_sales.py <file.csv|file.pdf> [...]")
        sys.exit(1)
    for p in paths:
        if not os.path.exists(p):
            print(f"File not found: {p}")
            continue
        import_file(p)
