"""Tests for barcode normalisation and variable-weight barcode handling."""
import pytest
from models.barcode import normalise, is_variable_weight, extract_weight


class TestNormalise:
    def test_standard_barcode_unchanged(self):
        assert normalise("9300000000001") == "9300000000001"

    def test_strips_leading_trailing_whitespace(self):
        assert normalise("  9300000000001  ") == "9300000000001"

    def test_variable_weight_stripped_to_6_char_prefix(self):
        # Format: 2 + 5 item digits + 5 weight digits + 1 check digit = 13 chars
        barcode = "2012345067891"
        assert normalise(barcode) == "201234"

    def test_variable_weight_prefix_length(self):
        result = normalise("2099999012341")
        assert len(result) == 6
        assert result.startswith("2")

    def test_starts_with_2_but_not_13_digits_unchanged(self):
        # Only 12 digits — not variable weight
        assert normalise("201234506789") == "201234506789"

    def test_13_digit_not_starting_with_2_unchanged(self):
        assert normalise("9300012345678") == "9300012345678"

    def test_empty_string_unchanged(self):
        assert normalise("") == ""


class TestIsVariableWeight:
    def test_valid_variable_weight_barcode(self):
        assert is_variable_weight("2012345067891") is True

    def test_standard_barcode_is_not_variable(self):
        assert is_variable_weight("9300000000001") is False

    def test_starts_with_2_wrong_length_not_variable(self):
        assert is_variable_weight("201234") is False

    def test_13_digits_not_starting_2_not_variable(self):
        assert is_variable_weight("9300012345678") is False

    def test_exactly_13_digits_starting_2_is_variable(self):
        assert is_variable_weight("2" + "0" * 12) is True


class TestExtractWeight:
    def test_extract_500g(self):
        # Digits at index 7:12 = '00500' → 500 / 1000 = 0.5 kg
        barcode = "2012345005001"
        assert extract_weight(barcode) == pytest.approx(0.500)

    def test_extract_250g(self):
        barcode = "2012345002501"
        assert extract_weight(barcode) == pytest.approx(0.250)

    def test_extract_1kg(self):
        barcode = "2012345010001"
        assert extract_weight(barcode) == pytest.approx(1.000)

    def test_standard_barcode_returns_zero(self):
        assert extract_weight("9300000000001") == pytest.approx(0.0)

    def test_weight_digits_at_correct_position(self):
        # barcode: 2 A B C D E W W W W W C
        #          0 1 2 3 4 5 6 7 8 9 10 11 12
        # weight = digits[7:12]
        barcode = "2000000001230"  # weight digits = '00123' → 0.123 kg
        assert extract_weight(barcode) == pytest.approx(0.123)


class TestScaleLabel:
    @staticmethod
    def _ean13(body12):
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
        return body12 + str((10 - total % 10) % 10)

    def test_default_weight_layout(self):
        from models.barcode import decode_scale_label
        r = decode_scale_label(self._ean13("210014000625"), {})
        assert r == {'plu': '140', 'weight_kg': 0.625, 'price': None}

    def test_price_layout(self):
        from models.barcode import decode_scale_label
        cfg = {'scale_label_plu_start': '1', 'scale_label_plu_len': '6',
               'scale_label_value_type': 'price'}
        r = decode_scale_label(self._ean13("200014000845"), cfg)
        assert r == {'plu': '140', 'weight_kg': None, 'price': 8.45}

    def test_upca_style_02_prefix_label_decodes_by_default(self):
        # UPC-A 2PPPPPVVVVVC arrives from the scanner as 13 digits with a leading 0
        from models.barcode import decode_scale_label
        from_ = {}
        code = "0200140006953"
        r = decode_scale_label(code, from_)
        assert r == {'plu': '140', 'weight_kg': 0.695, 'price': None}

    def test_rejects_ordinary_barcode_and_bad_config(self):
        from models.barcode import decode_scale_label
        assert decode_scale_label("9300675009657", {}) is None
        assert decode_scale_label(self._ean13("210014000625"), {'scale_label_value_start': '9'}) is None
        assert decode_scale_label(self._ean13("210014000625"), {'scale_label_enabled': '0'}) is None


class TestScaleLabelLookup:
    def test_controller_resolves_label_to_product_by_plu(self, test_db, product_barcode):
        import controllers.product_controller as pc
        pc.set_product_plu(product_barcode, '140')
        label = TestScaleLabel._ean13("210014000625")
        found = pc.get_product_by_barcode(label)
        assert found is not None and found['barcode'] == product_barcode
        pos = pc.get_product_for_pos(label)
        assert pos['scale_label'] == {'weight_kg': 0.625, 'price': None}

    def test_unknown_plu_is_not_found(self, test_db):
        import controllers.product_controller as pc
        assert pc.get_product_by_barcode(TestScaleLabel._ean13("210099900625")) is None
        assert pc.get_product_for_pos(TestScaleLabel._ean13("210099900625")) is None
