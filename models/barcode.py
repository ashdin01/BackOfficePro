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


# ── Configurable scale-label barcodes ────────────────────────────────────────
# Pure codec lives in utils/scale_label.py (byte-identical in BackOfficePro and
# RetailPOSPro). This module only adds the settings loader and keeps the
# long-standing names importable.
from utils.scale_label import (  # noqa: F401
    SCALE_LABEL_DEFAULTS, SCALE_LABEL_PRESETS, decode_label, encode_label,
    ean13_check_ok, ean13_check_digit, price_for_weight,
)


def load_scale_label_config() -> dict:
    from models.settings import get_all_settings
    cfg = dict(SCALE_LABEL_DEFAULTS)
    for k, v in get_all_settings().items():
        if k.startswith('scale_label_') and v.strip():
            cfg[k] = v.strip()
    return cfg


def decode_scale_label(barcode: str, cfg: dict | None = None) -> dict | None:
    """Decode a weigh-and-label EAN-13 using the saved (or given) layout."""
    return decode_label(barcode, load_scale_label_config() if cfg is None else cfg)


def encode_scale_label(plu, *, price: float | None = None,
                       weight_kg: float | None = None, cfg: dict | None = None) -> str:
    """Build a weigh-and-label EAN-13 using the saved (or given) layout."""
    return encode_label(plu, price=price, weight_kg=weight_kg,
                        cfg=load_scale_label_config() if cfg is None else cfg)
