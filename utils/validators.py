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
