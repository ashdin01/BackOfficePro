def normalise(scanned: str) -> str:
    """
    Normalise a scanned barcode.
    Variable weight items start with '2' and are 13 digits —
    strip the embedded weight/price and return just the base SKU.
    """
    scanned = scanned.strip()
    if scanned.startswith("2") and len(scanned) == 13:
        return "2" + scanned[1:6]
    return scanned


def is_variable_weight(barcode: str) -> bool:
    return barcode.startswith("2") and len(barcode) == 13


def extract_weight(barcode: str) -> float:
    """Extract the embedded weight from a variable weight barcode (digits 7-11)."""
    if is_variable_weight(barcode):
        return int(barcode[7:12]) / 1000
    return 0.0
