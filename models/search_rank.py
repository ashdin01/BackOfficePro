"""Relevance ordering for product searches.

Searches match substrings, so typing PLU 140 also matches 14140, 1401 and any
barcode containing 140. That's useful for descriptions but buries the exact
PLU a user typed. `rank_order` returns an ORDER BY expression that puts exact
PLU/barcode matches first, then prefix matches, then everything else — the
caller's own ordering (e.g. description) breaks ties.
"""

# A word this short and all-digit is treated as a PLU; longer ones as a barcode.
_MAX_PLU_DIGITS = 8


def rank_order(words, plu_col="p.plu", barcode_col="p.barcode"):
    """(sql, params) ordering expression for a list of search words.

    Rank 0 exact PLU (so 140 matches '140' and '0140'), 1 exact barcode,
    2 PLU starts with the word, 3 barcode starts with it, 4 everything else.
    Uses the first all-digit word; with none, every row ranks 4 (no effect).
    """
    num = next((w for w in words if w.isdigit()), None)
    if num is None:
        return "4", []
    plu_exact = (f"({plu_col} GLOB '[0-9]*' AND {plu_col} NOT GLOB '*[^0-9]*' "
                 f"AND CAST({plu_col} AS INTEGER) = CAST(? AS INTEGER))")
    params = [num, num, f"{num}%", f"{num}%"]
    if len(num) > _MAX_PLU_DIGITS:   # a barcode, not a PLU
        plu_exact, params = "0", params[1:]
    sql = (f"CASE WHEN {plu_exact} THEN 0 WHEN {barcode_col} = ? THEN 1 "
           f"WHEN {plu_col} LIKE ? THEN 2 WHEN {barcode_col} LIKE ? THEN 3 ELSE 4 END")
    return sql, params
