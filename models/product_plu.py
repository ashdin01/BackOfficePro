"""PLU management queries for the products table."""
from database.connection import get_connection


def get_all_plu() -> list:
    """All products that have a PLU assigned, ordered by PLU numerically then barcode."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT p.barcode, p.plu, p.description, p.active,
                   d.name AS dept_name, s.name AS supplier_name
            FROM products p
            LEFT JOIN departments d ON d.id = p.department_id
            LEFT JOIN suppliers   s ON s.id = p.supplier_id
            WHERE p.plu IS NOT NULL AND p.plu != ''
            ORDER BY CAST(p.plu AS INTEGER), p.barcode
        """).fetchall()]
    finally:
        conn.release()


def get_duplicate_plu_groups() -> list:
    """
    All products sharing a PLU with at least one other product.
    Grouped by PLU; within a group sorted by active desc then barcode.
    """
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT p.plu, p.barcode, p.description, p.active,
                   d.name AS dept_name, s.name AS supplier_name
            FROM products p
            LEFT JOIN departments d ON d.id = p.department_id
            LEFT JOIN suppliers   s ON s.id = p.supplier_id
            WHERE p.plu IN (
                SELECT plu FROM products
                WHERE plu IS NOT NULL AND plu != ''
                GROUP BY plu HAVING COUNT(*) > 1
            )
            ORDER BY CAST(p.plu AS INTEGER), p.active DESC, p.barcode
        """).fetchall()]
    finally:
        conn.release()


def get_plu_map_conflicts() -> list:
    """
    Barcodes where plu_barcode_map.plu differs from products.plu.
    Returns list of dicts with keys: map_plu, barcode, prod_plu, description.
    """
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT m.plu AS map_plu, m.barcode, p.plu AS prod_plu, p.description
            FROM plu_barcode_map m
            JOIN products p ON p.barcode = m.barcode
            WHERE p.plu IS NOT NULL AND p.plu != ''
              AND CAST(p.plu AS INTEGER) != m.plu
            ORDER BY m.plu
        """).fetchall()]
    finally:
        conn.release()


def set_plu(barcode, new_plu) -> None:
    """
    Assign a PLU to a product. new_plu may be a string or int; pass '' or None to clear.
    Raises ValueError if new_plu is already used by a different product.
    """
    new_plu = str(new_plu).strip() if new_plu is not None else ''
    conn = get_connection()
    try:
        if new_plu:
            conflict = conn.execute(
                "SELECT barcode FROM products WHERE plu=? AND barcode!=?",
                (new_plu, barcode)
            ).fetchone()
            if conflict:
                desc = conn.execute(
                    "SELECT description FROM products WHERE barcode=?",
                    (conflict['barcode'],)
                ).fetchone()
                raise ValueError(
                    f"PLU {new_plu} is already assigned to "
                    f"{desc['description'] if desc else conflict['barcode']}"
                )
        conn.execute(
            "UPDATE products SET plu=?, updated_at=CURRENT_TIMESTAMP WHERE barcode=?",
            (new_plu or None, barcode)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.release()


def find_barcode_by_plu(plu_str) -> str | None:
    """Return barcode for a product whose plu column matches plu_str, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT barcode FROM products WHERE plu = ? AND active = 1 LIMIT 1",
            (str(plu_str),)
        ).fetchone()
        return row['barcode'] if row else None
    finally:
        conn.release()
