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
# Weigh-and-label machines print an EAN-13 with the item's PLU and either the
# weight (grams) or the total price (cents) embedded. Same settings keys and
# semantics as RetailPOSPro's utils/barcode.py, so one layout works in both:
#
#   scale_label_enabled / _prefixes / _plu_start / _plu_len /
#   scale_label_value_start / _value_len / _value_type ('weight'|'price') / _check
#
# Offsets are 0-based into the 13 digits. Defaults: 2 D PPPPP WWWWW C, weight.

SCALE_LABEL_DEFAULTS = {
    'scale_label_enabled':     '1',
    'scale_label_prefixes':    '2,02',
    'scale_label_plu_start':   '2',
    'scale_label_plu_len':     '5',
    'scale_label_value_start': '7',
    'scale_label_value_len':   '5',
    'scale_label_value_type':  'weight',
    'scale_label_check':       '0',
}

SCALE_LABEL_PRESETS = {
    '2 D PPPPP VVVVV C':  ('2', 2, 5, 7, 5),
    '2 PPPPPP VVVVV C':   ('2', 1, 6, 7, 5),
    '2 PPPPP VVVVVV C':   ('2', 1, 5, 6, 6),
    '2 PPPP VVVVVVV C':   ('2', 1, 4, 5, 7),
}


def load_scale_label_config() -> dict:
    from models.settings import get_all_settings
    cfg = dict(SCALE_LABEL_DEFAULTS)
    for k, v in get_all_settings().items():
        if k.startswith('scale_label_') and v.strip():
            cfg[k] = v.strip()
    return cfg


def ean13_check_ok(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


def decode_scale_label(barcode: str, cfg: dict | None = None) -> dict | None:
    """
    Decode a weigh-and-label EAN-13 using the configured layout.

    Returns {'plu': str, 'weight_kg': float | None, 'price': float | None}
    (exactly one of weight_kg / price set), or None if it isn't a scale label.
    """
    if cfg is None:
        cfg = load_scale_label_config()
    c = {**SCALE_LABEL_DEFAULTS, **cfg}
    if c['scale_label_enabled'] != '1':
        return None
    barcode = (barcode or '').strip()
    if len(barcode) != 13 or not barcode.isdigit():
        return None
    prefixes = [p.strip() for p in c['scale_label_prefixes'].split(',') if p.strip()]
    if not any(barcode.startswith(p) for p in prefixes):
        return None
    try:
        plu_start, plu_len = int(c['scale_label_plu_start']), int(c['scale_label_plu_len'])
        val_start, val_len = int(c['scale_label_value_start']), int(c['scale_label_value_len'])
    except ValueError:
        return None
    if min(plu_start, plu_len, val_start, val_len) < 0 or plu_len == 0 or val_len == 0:
        return None
    if plu_start + plu_len > 12 or val_start + val_len > 12:
        return None
    if c['scale_label_check'] == '1' and not ean13_check_ok(barcode):
        return None

    plu = barcode[plu_start:plu_start + plu_len].lstrip('0') or '0'
    raw = int(barcode[val_start:val_start + val_len])
    if raw <= 0:
        return None
    if c['scale_label_value_type'] == 'price':
        return {'plu': plu, 'weight_kg': None, 'price': raw / 100.0}
    return {'plu': plu, 'weight_kg': raw / 1000.0, 'price': None}
