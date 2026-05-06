"""Tests for utils/validators.py."""
import pytest
from utils.validators import required, positive_number, validate_abn, validate_email, validate_phone


class TestRequired:
    def test_raises_for_empty_string(self):
        with pytest.raises(ValueError, match="Name"):
            required("", "Name")

    def test_raises_for_whitespace_only(self):
        with pytest.raises(ValueError):
            required("   ", "Field")

    def test_raises_for_none(self):
        with pytest.raises(ValueError):
            required(None, "Field")

    def test_passes_for_valid_string(self):
        required("hello", "Field")

    def test_passes_for_string_zero(self):
        required("0", "Field")

    def test_passes_for_single_character(self):
        required("x", "Field")

    def test_error_message_includes_field_name(self):
        with pytest.raises(ValueError, match="Barcode"):
            required("", "Barcode")


class TestPositiveNumber:
    def test_raises_for_negative_int(self):
        with pytest.raises(ValueError, match="Price"):
            positive_number(-1, "Price")

    def test_raises_for_negative_float(self):
        with pytest.raises(ValueError):
            positive_number(-0.01, "Amount")

    def test_raises_for_non_numeric_string(self):
        with pytest.raises(ValueError):
            positive_number("abc", "Amount")

    def test_raises_for_none(self):
        with pytest.raises(ValueError):
            positive_number(None, "Amount")

    def test_passes_for_zero(self):
        positive_number(0, "Amount")

    def test_passes_for_positive_int(self):
        positive_number(5, "Amount")

    def test_passes_for_positive_float(self):
        positive_number(1.99, "Price")

    def test_passes_for_numeric_string(self):
        positive_number("3.50", "Price")


class TestValidateAbn:
    # Real Australian ABNs used for testing (publicly known entities)
    VALID_ABN_PLAIN   = "51824753556"   # digits only
    VALID_ABN_SPACED  = "51 824 753 556"
    VALID_FORMATTED   = "51 824 753 556"

    def test_returns_empty_for_blank(self):
        assert validate_abn("") == ""

    def test_returns_empty_for_whitespace(self):
        assert validate_abn("   ") == ""

    def test_returns_empty_for_none(self):
        assert validate_abn(None) == ""

    def test_formats_valid_abn_digits_only(self):
        assert validate_abn(self.VALID_ABN_PLAIN) == self.VALID_FORMATTED

    def test_strips_spaces_from_valid_abn(self):
        assert validate_abn(self.VALID_ABN_SPACED) == self.VALID_FORMATTED

    def test_raises_for_10_digits(self):
        with pytest.raises(ValueError, match="11 digits"):
            validate_abn("1234567890")

    def test_raises_for_12_digits(self):
        with pytest.raises(ValueError, match="11 digits"):
            validate_abn("123456789012")

    def test_raises_for_invalid_checksum(self):
        with pytest.raises(ValueError, match="checksum"):
            validate_abn("12345678901")

    def test_raises_for_all_zeros(self):
        with pytest.raises(ValueError):
            validate_abn("00000000000")

    def test_strips_dashes_and_spaces(self):
        # Same digits as VALID_ABN_PLAIN but with dashes
        dashed = "51-824-753-556"
        assert validate_abn(dashed) == self.VALID_FORMATTED


class TestValidateEmail:
    def test_returns_empty_for_blank(self):
        assert validate_email("") == ""

    def test_returns_empty_for_whitespace(self):
        assert validate_email("   ") == ""

    def test_returns_empty_for_none(self):
        assert validate_email(None) == ""

    def test_accepts_simple_email(self):
        assert validate_email("user@example.com") == "user@example.com"

    def test_accepts_au_email(self):
        assert validate_email("orders@supplier.com.au") == "orders@supplier.com.au"

    def test_strips_surrounding_whitespace(self):
        assert validate_email("  user@example.com  ") == "user@example.com"

    def test_raises_for_missing_at(self):
        with pytest.raises(ValueError):
            validate_email("userexample.com")

    def test_raises_for_missing_domain(self):
        with pytest.raises(ValueError):
            validate_email("user@")

    def test_raises_for_short_tld(self):
        with pytest.raises(ValueError):
            validate_email("user@example.c")

    def test_raises_for_spaces_in_email(self):
        with pytest.raises(ValueError):
            validate_email("user @example.com")


class TestValidatePhone:
    def test_returns_empty_for_blank(self):
        assert validate_phone("") == ""

    def test_returns_empty_for_whitespace(self):
        assert validate_phone("   ") == ""

    def test_returns_empty_for_none(self):
        assert validate_phone(None) == ""

    def test_accepts_8_digit_number(self):
        assert validate_phone("54742483") == "54742483"

    def test_accepts_australian_local_with_area_code(self):
        assert validate_phone("(03) 5474 2483") == "(03) 5474 2483"

    def test_accepts_mobile(self):
        assert validate_phone("0412 345 678") == "0412 345 678"

    def test_accepts_international_format(self):
        assert validate_phone("+61 3 5474 2483") == "+61 3 5474 2483"

    def test_raises_for_too_few_digits(self):
        with pytest.raises(ValueError):
            validate_phone("1234567")

    def test_raises_for_too_many_digits(self):
        with pytest.raises(ValueError):
            validate_phone("1234567890123456")

    def test_raises_for_letters(self):
        with pytest.raises(ValueError):
            validate_phone("CALL-ME")
