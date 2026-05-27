import re


def required(value, field_name):
    if not value or str(value).strip() == '':
        raise ValueError(f"{field_name} is required")

def positive_number(value, field_name):
    try:
        if float(value) < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a positive number")


def percentage(value, field_name):
    """Raise ValueError unless 0 ≤ value ≤ 100."""
    try:
        v = float(value)
        if not (0 <= v <= 100):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be between 0 and 100")


def validate_abn(abn: str) -> str:
    """Validate and format an Australian Business Number.

    Returns "" if blank, formatted "XX XXX XXX XXX" if valid,
    raises ValueError if non-blank and invalid.
    """
    if not abn or not abn.strip():
        return ""
    digits = re.sub(r"\D", "", abn)
    if len(digits) != 11:
        raise ValueError("ABN must be 11 digits")
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    d = [int(c) for c in digits]
    d[0] -= 1
    total = sum(d[i] * weights[i] for i in range(11))
    if total % 89 != 0:
        raise ValueError("ABN is not valid — checksum failed")
    return f"{digits[0:2]} {digits[2:5]} {digits[5:8]} {digits[8:11]}"


def validate_email(email: str) -> str:
    """Validate an email address.

    Returns "" if blank, stripped email if valid,
    raises ValueError if non-blank and invalid.
    """
    if not email or not email.strip():
        return ""
    email = email.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", email):
        raise ValueError(f"'{email}' is not a valid email address")
    return email


_BSB_BANKS = {
    "01": "ANZ",
    "03": "Westpac",
    "06": "Commonwealth Bank",
    "08": "NAB",
    "09": "Reserve Bank of Australia",
    "10": "BankWest",
    "11": "St.George Bank",
    "12": "Bank of Queensland",
    "14": "Citibank",
    "15": "HSBC",
    "18": "Macquarie Bank",
    "19": "Suncorp Bank",
    "22": "Bank of Melbourne",
    "23": "Bendigo Bank",
    "24": "ING",
    "25": "Rabobank",
    "28": "Greater Bank",
    "29": "Newcastle Permanent",
    "34": "Heritage Bank",
    "36": "BCU Bank",
    "40": "Adelaide Bank",
    "45": "ME Bank",
    "48": "Teachers Mutual Bank",
    "55": "Defence Bank",
    "57": "P&N Bank",
    "61": "Bendigo and Adelaide Bank",
    "66": "BankVic",
    "76": "Bank Australia",
    "80": "Westpac (Treasury)",
}


def validate_bsb(bsb: str) -> tuple[str, str]:
    """Validate and format an Australian BSB number.

    Returns ("", "") if blank.
    Returns (formatted, bank_name) where formatted is "NNN-NNN" if valid.
    Raises ValueError if non-blank and not exactly 6 digits.
    bank_name is "" if the prefix is not in the known list.
    """
    if not bsb or not bsb.strip():
        return "", ""
    digits = re.sub(r"\D", "", bsb.strip())
    if len(digits) != 6:
        raise ValueError("BSB must be exactly 6 digits (e.g. 063-000)")
    formatted = f"{digits[:3]}-{digits[3:]}"
    bank_name = _BSB_BANKS.get(digits[:2], "")
    return formatted, bank_name


def validate_phone(phone: str) -> str:
    """Validate a phone number by digit count (8–15 digits).

    Returns "" if blank, stripped phone if valid,
    raises ValueError if non-blank and invalid.
    """
    if not phone or not phone.strip():
        return ""
    phone = phone.strip()
    digits = re.sub(r"\D", "", phone)
    if not (8 <= len(digits) <= 15):
        raise ValueError(f"'{phone}' is not a valid phone number")
    return phone
