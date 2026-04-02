"""
Daily PLU Sales PDF Importer for BackOfficePro
Uses pdfplumber table extraction for accurate column separation.
After import, creates negative stock movements for all matched products.
"""
import sys, os, re

# Resolve base path for both dev and PyInstaller exe environments
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


def parse_date(text):
    m = re.search(r'Report from (\d+/\d+/\d+)', text)
    if m:
        return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
    return datetime.today().strftime("%Y-%m-%d")


def parse_pdf(path):
    rows = []
    sale_date = None

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if i == 0:
                sale_date = parse_date(text)
                print(f"  Sale date: {sale_date}")

            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not words:
                continue

            lines = {}
            for w in words:
                y = round(w['top'])
                if y not in lines:
                    lines[y] = []
                lines[y].append(w)

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
                if not line_words:
                    continue

                first = line_words[0]['text']
                if not first.isdigit():
                    continue

                plu = first
                numerics = []
                name_words = []
                subgroup_words = []
                sorted_words = sorted(line_words[1:], key=lambda w: w['x0'])

                num_start_idx = None
                for idx, w in enumerate(sorted_words):
                    cleaned = w['text'].replace('%','').replace('-','',1)
                    if re.match(r'^\d+\.\d+$', cleaned):
                        num_start_idx = idx
                        break

                if num_start_idx is None:
                    continue

                text_words = sorted_words[:num_start_idx]
                num_words  = sorted_words[num_start_idx:]

                for w in num_words:
                    cleaned = w['text'].replace('%','').strip()
                    try:
                        numerics.append(float(cleaned))
                    except ValueError:
                        pass

                if len(numerics) < 7:
                    continue

                if subgroup_x_start:
                    for w in text_words:
                        if w['x0'] < subgroup_x_start - 5:
                            name_words.append(w['text'])
                        else:
                            subgroup_words.append(w['text'])
                else:
                    name_words = [w['text'] for w in text_words]

                plu_name  = ' '.join(name_words).strip()
                sub_group = ' '.join(subgroup_words).strip()

                try:
                    rows.append({
                        'sale_date':     sale_date,
                        'plu':           plu,
                        'plu_name':      plu_name,
                        'sub_group':     sub_group,
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


def _resolve_barcode(conn, plu):
    """
    Resolve a PLU number to a barcode using all available lookup methods.
    Priority: plu_barcode_map → product.sku → zero-padded barcode formats.
    Returns barcode string or None.
    """
    try:
        plu_int = int(str(plu).strip())
    except (ValueError, TypeError):
        return None

    # 1. Persistent operator-confirmed map
    row = conn.execute(
        "SELECT barcode FROM plu_barcode_map WHERE plu=?", (plu_int,)
    ).fetchone()
    if row:
        return row[0]

    # 2. Product SKU match
    row = conn.execute(
        "SELECT barcode FROM products WHERE sku=? AND active=1", (str(plu_int),)
    ).fetchone()
    if row:
        return row[0]

    # 3. Zero-padded barcode: 02XXXXX format (7 digits, store-specific)
    padded = f"02{plu_int:05d}"
    row = conn.execute(
        "SELECT barcode FROM products WHERE barcode=? AND active=1", (padded,)
    ).fetchone()
    if row:
        return row[0]

    # 4. Pure zero-padded 7-digit barcode
    padded2 = f"{plu_int:07d}"
    row = conn.execute(
        "SELECT barcode FROM products WHERE barcode=? AND active=1", (padded2,)
    ).fetchone()
    if row:
        return row[0]

    return None


def _create_sale_movement(conn, barcode, quantity, sale_date, plu, plu_name):
    """
    Create a negative stock movement for a sale, and update stock_on_hand.
    Only creates the movement if one doesn't already exist for this date+plu.
    """
    # Check if movement already exists for this sale date + reference
    reference = f"SALE-{sale_date}-PLU{plu}"
    existing = conn.execute(
        "SELECT id FROM stock_movements WHERE barcode=? AND reference=?",
        (barcode, reference)
    ).fetchone()
    if existing:
        return False  # already recorded

    # Create negative stock movement
    conn.execute("""
        INSERT INTO stock_movements
            (barcode, movement_type, quantity, reference, notes, created_by)
        VALUES (?, 'SALE', ?, ?, ?, 'PDF Import')
    """, (barcode, -quantity, reference,
          f"Sale: {plu_name} ({quantity} units)"))

    # Update stock on hand
    conn.execute("""
        INSERT INTO stock_on_hand (barcode, quantity)
        VALUES (?, ?)
        ON CONFLICT(barcode) DO UPDATE SET
            quantity = quantity + excluded.quantity,
            last_updated = CURRENT_TIMESTAMP
    """, (barcode, -quantity))

    return True


def import_pdf(path):
    print(f"\nImporting: {os.path.basename(path)}")
    rows = parse_pdf(path)
    print(f"  Parsed {len(rows)} rows")

    if not rows:
        print("  WARNING: No data rows found")
        return 0, 0

    conn = get_connection()
    inserted = updated = 0
    movements_created = 0
    unmatched = 0

    for r in rows:
        # ── 1. Save/update sales_daily ────────────────────────────────
        existing = conn.execute(
            "SELECT id FROM sales_daily WHERE sale_date=? AND plu=?",
            (r['sale_date'], r['plu'])
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE sales_daily SET
                    plu_name=?, sub_group=?, weight_kg=?, quantity=?,
                    nominal_price=?, discount=?, rounding=?,
                    sales_dollars=?, sales_pct=?,
                    imported_at=datetime('now','localtime')
                WHERE sale_date=? AND plu=?
            """, (r['plu_name'], r['sub_group'], r['weight_kg'], r['quantity'],
                  r['nominal_price'], r['discount'], r['rounding'],
                  r['sales_dollars'], r['sales_pct'],
                  r['sale_date'], r['plu']))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO sales_daily
                    (sale_date, plu, plu_name, sub_group, weight_kg, quantity,
                     nominal_price, discount, rounding, sales_dollars, sales_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (r['sale_date'], r['plu'], r['plu_name'], r['sub_group'],
                  r['weight_kg'], r['quantity'], r['nominal_price'],
                  r['discount'], r['rounding'], r['sales_dollars'], r['sales_pct']))
            inserted += 1

        # ── 2. Create stock movement if product matched ────────────────
        if r['quantity'] > 0:
            barcode = _resolve_barcode(conn, r['plu'])
            if barcode:
                created = _create_sale_movement(
                    conn, barcode, r['quantity'],
                    r['sale_date'], r['plu'], r['plu_name']
                )
                if created:
                    movements_created += 1
            else:
                unmatched += 1

    conn.commit()
    conn.close()

    print(f"  Inserted: {inserted}  Updated: {updated}")
    print(f"  Stock movements created: {movements_created}")
    print(f"  Unmatched PLUs (no barcode): {unmatched}")
    return inserted, updated


if __name__ == "__main__":
    ensure_tables()
    paths = sys.argv[1:]
    if not paths:
        print("Usage: python3 import_sales.py <pdf_file>")
        sys.exit(1)
    for p in paths:
        if not os.path.exists(p):
            print(f"File not found: {p}")
            continue
        import_pdf(p)
