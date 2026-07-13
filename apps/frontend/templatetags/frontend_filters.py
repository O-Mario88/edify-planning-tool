from django import template

register = template.Library()


@register.filter
def replace_underscore(value):
    if not value:
        return ""
    return str(value).replace("_", " ")


@register.filter
def intcomma(value):
    """Thousands-separated integer, e.g. 118540 -> '118,540'. Safe on None/''."""
    if value is None or value == "":
        return "0"
    try:
        return f"{int(float(value)):,}"
    except (ValueError, TypeError):
        return str(value)


@register.filter
def ugx(value):
    if value is None or value == "":
        return "UGX 0"
    try:
        val = float(value)
        return f"UGX {val:,.0f}"
    except (ValueError, TypeError):
        return f"UGX {value}"


@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def lookup(dictionary, key):
    if not dictionary:
        return None
    return dictionary.get(key)


@register.filter
def divide(value, arg):
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def currency(value):
    if value is None or value == "":
        return "0"
    try:
        val = float(value)
        return f"{val:,.0f}"
    except (ValueError, TypeError):
        return str(value)


@register.filter
def avatar_initials(value):
    if not value:
        return "ED"
    parts = str(value).strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[-1][0]}".upper()
    elif len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return "ED"


@register.filter
def month_name(value):
    """1–12 → January–December; anything else falls through unchanged."""
    import calendar

    try:
        return calendar.month_name[int(value)]
    except (ValueError, TypeError, IndexError):
        return value


@register.filter
def split(value, sep=","):
    """Split a string into a list — {{ "a,b,c"|split:"," }}."""
    return [s.strip() for s in str(value).split(sep) if s.strip()]
