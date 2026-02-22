def required(value, field_name):
    if not value or str(value).strip() == '':
        raise ValueError(f"{field_name} is required")

def positive_number(value, field_name):
    try:
        if float(value) < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a positive number")
