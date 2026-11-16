"""
Weigh-and-label barcode codec (pure logic, no app imports).

KEEP THIS FILE BYTE-IDENTICAL in BackOfficePro (utils/scale_label.py) and
RetailPOSPro (utils/scale_label.py). Check with:
    diff ~/BackOfficePro/utils/scale_label.py ~/RetailPOSPro/utils/scale_label.py
Each app wraps it with its own settings loader (models/barcode.py in
BackOfficePro, utils/barcode.py in RetailPOSPro).

A weigh-and-label scale prints an EAN-13 carrying the item's PLU and either the
total price (cents) or the weight (grams), e.g. 0210334013915:
    02 10334 01391 5  ->  prefix 02, PLU 10334, price $13.91, check digit 5

Layout settings (0-based offsets into the 13 digits):
    scale_label_enabled     '1' / '0'
    scale_label_prefixes    comma-separated leading digits, e.g. '2,02'
    scale_label_plu_start / scale_label_plu_len
    scale_label_value_start / scale_label_value_len
    scale_label_value_type  'weight' (grams) or 'price' (cents)
    scale_label_check       '1' to reject labels with a bad EAN-13 check digit
"""

from decimal import Decimal, ROUND_HALF_UP

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

# name -> (prefixes, plu_start, plu_len, value_start, value_len)
SCALE_LABEL_PRESETS = {
    '2 D PPPPP VVVVV C':  ('2', 2, 5, 7, 5),
    '2 PPPPPP VVVVV C':   ('2', 1, 6, 7, 5),
    '2 PPPPP VVVVVV C':   ('2', 1, 5, 6, 6),
    '2 PPPP VVVVVVV C':   ('2', 1, 4, 5, 7),
}


def ean13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def ean13_check_ok(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == code[12]


def price_for_weight(weight_kg: float, price_per_kg: float) -> float:
    """Total price for a weight, rounded half-up to the cent. The one rounding
    rule shared by the label printer and the POS so the two always agree."""
    total = Decimal(str(weight_kg)) * Decimal(str(price_per_kg))
    return float(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def decode_label(barcode: str, cfg: dict | None = None) -> dict | None:
    """
    Decode a weigh-and-label EAN-13 using the layout in cfg (defaults fill gaps).

    Returns {'plu': str, 'weight_kg': float | None, 'price': float | None}
    (exactly one of weight_kg / price set), or None if it isn't a scale label.
    """
    c = {**SCALE_LABEL_DEFAULTS, **(cfg or {})}
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


def encode_label(plu, *, price: float | None = None,
                 weight_kg: float | None = None, cfg: dict | None = None) -> str:
    """
    Build the 13-digit EAN-13 a weigh-and-label machine would print (inverse of
    decode_label). Embeds price (cents) or weight (grams) per
    scale_label_value_type; pass the matching argument. Uses the longest
    configured prefix (e.g. '02' from '2,02'), zero-fills unused positions and
    appends the check digit. Raises ValueError if anything doesn't fit.
    """
    c = {**SCALE_LABEL_DEFAULTS, **(cfg or {})}
    plu_start, plu_len = int(c['scale_label_plu_start']), int(c['scale_label_plu_len'])
    val_start, val_len = int(c['scale_label_value_start']), int(c['scale_label_value_len'])
    if plu_len <= 0 or val_len <= 0 or min(plu_start, val_start) < 0 \
            or plu_start + plu_len > 12 or val_start + val_len > 12:
        raise ValueError("invalid scale label layout")
    if plu_start < val_start + val_len and val_start < plu_start + plu_len:
        raise ValueError("PLU and value positions overlap")
    plu_s = str(plu).strip()
    if not plu_s.isdigit() or len(plu_s) > plu_len:
        raise ValueError(f"PLU {plu!r} does not fit in {plu_len} digits")
    if c['scale_label_value_type'] == 'price':
        if price is None:
            raise ValueError("price required for a price label")
        raw = int(round(price * 100))
    else:
        if weight_kg is None:
            raise ValueError("weight_kg required for a weight label")
        raw = int(round(weight_kg * 1000))
    if raw <= 0 or len(str(raw)) > val_len:
        raise ValueError(f"value {raw} does not fit in {val_len} digits (or is not positive)")
    prefixes = [p.strip() for p in c['scale_label_prefixes'].split(',') if p.strip()]
    prefix = max(prefixes, key=len) if prefixes else ''
    digits = list('0' * 12)
    digits[:len(prefix)] = prefix
    digits[plu_start:plu_start + plu_len] = plu_s.zfill(plu_len)
    digits[val_start:val_start + val_len] = str(raw).zfill(val_len)
    body = ''.join(digits)
    return body + ean13_check_digit(body)
