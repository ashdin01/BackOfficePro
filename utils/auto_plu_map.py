"""
utils/auto_plu_map.py

Runs on startup. Finds any PLU in products that has no entry in
plu_barcode_map and inserts it automatically — but only when there
is exactly one unambiguous product match. Ambiguous or unknown PLUs
are skipped and returned for optional display to the user.
"""

import logging
from database.connection import get_connection


def auto_map_plu_barcodes() -> dict:
    """
    Automatically maps PLUs from the products table into plu_barcode_map
    where no mapping exists yet and the match is unambiguous (exactly 1 product).

    Returns a dict:
        {
            "mapped":    [(plu, barcode, description), ...],  # successfully auto-mapped
            "skipped":   [(plu, count), ...],                 # ambiguous — multiple products share this PLU
            "unmapped":  [plu, ...],                          # no product found at all
        }
    """
    result = {"mapped": [], "skipped": [], "unmapped": []}

    try:
        conn = get_connection()

        # All PLUs in sales_daily that have no mapping yet
        unmapped_plus = conn.execute("""
            SELECT DISTINCT plu
            FROM sales_daily
            WHERE plu NOT IN (SELECT plu FROM plu_barcode_map)
            ORDER BY plu
        """).fetchall()

        for (plu,) in unmapped_plus:
            matches = conn.execute("""
                SELECT barcode, description
                FROM products
                WHERE CAST(plu AS TEXT) = CAST(? AS TEXT)
                  AND active = 1
            """, (plu,)).fetchall()

            if len(matches) == 1:
                barcode, description = matches[0]
                conn.execute("""
                    INSERT OR IGNORE INTO plu_barcode_map (plu, barcode, mapped_at)
                    VALUES (?, ?, datetime('now'))
                """, (plu, barcode))
                result["mapped"].append((plu, barcode, description))
                logging.info(f"[auto_plu_map] Mapped PLU {plu} -> {barcode} ({description})")

            elif len(matches) > 1:
                result["skipped"].append((plu, len(matches)))
                logging.warning(f"[auto_plu_map] Skipped PLU {plu} — {len(matches)} ambiguous matches")

            else:
                result["unmapped"].append(plu)

        conn.commit()
        conn.close()

        logging.info(
            f"[auto_plu_map] Complete — "
            f"{len(result['mapped'])} mapped, "
            f"{len(result['skipped'])} skipped (ambiguous), "
            f"{len(result['unmapped'])} unknown"
        )

    except Exception as e:
        logging.error(f"[auto_plu_map] Failed: {e}", exc_info=True)

    return result
