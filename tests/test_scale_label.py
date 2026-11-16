"""Contract tests for the shared weigh-and-label codec. Keep identical in
BackOfficePro and RetailPOSPro; the vectors are labels the store's scale printed."""
import pytest
from utils.scale_label import (decode_label, encode_label, price_for_weight,
                               ean13_check_ok)

PRICE = {'scale_label_value_type': 'price', 'scale_label_check': '1'}
REAL = [("10334", 13.91, "0210334013915"),   # Istra Salami, $36.99/kg, 0.376 kg
        ("6837", 10.32, "0206837010322"),    # Cliffords Lamb Burgers, $23.99/kg, 0.430 kg
        ("132", 3.50, "0200132003508")]      # Pineapple half, $3.50 each


@pytest.mark.parametrize("plu,price,code", REAL)
def test_real_labels_encode_and_decode(plu, price, code):
    assert ean13_check_ok(code)
    assert encode_label(plu, price=price, cfg=PRICE) == code
    assert decode_label(code, PRICE) == {'plu': plu, 'weight_kg': None, 'price': price}


def test_default_mode_is_weight():
    assert decode_label("0210334013915")['weight_kg'] == 1.391


def test_weight_round_trip():
    cfg = {'scale_label_value_type': 'weight'}
    assert decode_label(encode_label("10334", weight_kg=0.376, cfg=cfg), cfg)['weight_kg'] == 0.376


def test_bad_check_digit_rejected_when_enabled():
    assert decode_label("0210334013916", PRICE) is None


def test_price_for_weight_rounds_half_up():
    assert price_for_weight(0.376, 36.99) == 13.91
    assert price_for_weight(0.430, 23.99) == 10.32
    assert price_for_weight(0.005, 1.00) == 0.01


@pytest.mark.parametrize("kw", [dict(plu="1234567", price=1), dict(plu="1", price=1000.0), dict(plu="1")])
def test_encode_rejects_bad_input(kw):
    with pytest.raises(ValueError):
        encode_label(cfg=PRICE, **kw)
