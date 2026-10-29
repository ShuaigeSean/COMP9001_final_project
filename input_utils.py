"""Exact, shared hour input conversion for the terminal and desktop views."""

from decimal import Decimal, DecimalException


def hours_to_minutes(value, allow_zero=False, maximum=None):
    """Accept decimal hours or H:MM, rejecting rounding and extreme input."""
    limit = 60_000_000 if maximum is None else maximum
    try:
        value = value.strip()
        if not value or len(value) > 80:
            raise ValueError
        if ":" in value:
            parts = value.split(":")
            if (len(parts) != 2 or any(not part.isascii() or not part.isdigit() for part in parts)
                    or len(parts[1]) != 2 or int(parts[1]) >= 60):
                raise ValueError
            minutes = int(parts[0]) * 60 + int(parts[1])
        else:
            number = Decimal(value)
            if (not number.is_finite() or number < 0 or number > Decimal(limit) / 60 or
                    (number != 0 and number.adjusted() < -3)):
                raise ValueError
            numerator, denominator = number.as_integer_ratio()
            if (numerator * 60) % denominator:
                raise ValueError
            minutes = (numerator * 60) // denominator
        if not (0 if allow_zero else 1) <= minutes <= limit:
            raise ValueError
        return minutes
    except (DecimalException, ValueError, OverflowError, AttributeError) as exc:
        minimum = "zero or positive" if allow_zero else "positive"
        raise ValueError(f"Enter {minimum} hours as a decimal or H:MM, in whole minutes "
                         f"(maximum {limit // 60} hours).") from exc


def minutes_to_hours(minutes):
    """Return an exact editable value, using H:MM for repeating decimals."""
    if minutes % 3:
        hours, remainder = divmod(minutes, 60)
        return f"{hours}:{remainder:02d}"
    return str(Decimal(minutes) / 60).rstrip("0").rstrip(".") if minutes % 60 else str(minutes // 60)
