from django import template

register = template.Library()

@register.filter
def replace_underscore(value):
    if not value:
        return ""
    return str(value).replace("_", " ")

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
