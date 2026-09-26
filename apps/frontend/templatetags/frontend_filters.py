from django import template

register = template.Library()


@register.filter
def replace_underscore(value):
    if not value:
        return ""
    return str(value).replace("_", " ")


# Words the platform capitalises as initialisms. Title-casing a status token
# turns "submitted_to_pl" into "Submitted To Pl", which reads as a typo for a
# role everybody knows as the PL.
_STATUS_INITIALISMS = {
    "Pl": "PL",
    "Ia": "IA",
    "Cd": "CD",
    "Rvp": "RVP",
    "Hr": "HR",
    "Ssa": "SSA",
    "Mfi": "MFI",
    "Bt": "BT",
    "Netsuite": "NetSuite",
    "Salesforce": "Salesforce",
    "Edtech": "EdTech",
    "Nssf": "NSSF",
    "Ura": "URA",
}


@register.filter
def status_label(value):
    """Render a stored status token as the phrase a person would say.

    `{{ obj.status|title }}` leaves the underscores in — live finance and
    activity pages were showing "Submitted_To_Pl", "Awaiting_Ia_Verification"
    and "Pending_Responsible_Confirmation" to users (2026-08 UI/UX audit).
    Prefer a model's own `get_status_display` where one exists; this is for the
    surfaces reading a bare CharField.
    """
    if value is None or value == "":
        return ""
    words = str(value).replace("_", " ").replace("-", " ").split()
    return " ".join(
        _STATUS_INITIALISMS.get(w.capitalize(), w.capitalize()) for w in words
    )


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
def ugx_amount(value):
    """The formatted amount without the UGX prefix, for tables whose column
    header already carries the currency — e.g. "Total (UGX)"."""
    if value is None or value == "":
        return "0"
    try:
        return f"{float(value):,.0f}"
    except (ValueError, TypeError):
        return f"{value}"


@register.filter
def sub(value, arg):
    try:
        return int(value or 0) - int(arg or 0)
    except (ValueError, TypeError):
        return 0


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


@register.filter
def get_item(mapping, key):
    """Look a key up in a dict, for columns rendered by key rather than position."""
    if not mapping:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def can_open(user, url):
    """`{% if request.user|can_open:"/leave/team-availability" %}` — show a link
    only to someone its page lets in (apps.core.permissions.can_open_url)."""
    from apps.core.permissions import can_open_url

    return can_open_url(user, str(url or ""))


@register.filter
def ssa_score_colour(value):
    """The font colour for a 0-10 SSA score, from the canonical band.

    Owner, 2026-09-18: SSA scores are colour-coded wherever they are shown.
    The colour comes from apps.core.enums.ssa_score_band and nowhere else, so
    a score cannot be red on one page and green on another, and it is applied
    to the FONT rather than as a highlight.

    Returns an empty string for anything that is not a score, which leaves the
    span's colour to the stylesheet rather than painting an unknown value.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return ""
    from apps.core.enums import ssa_score_band

    return ssa_score_band(score)[1]


@register.filter
def ssa_score_band_label(value):
    """The band a 0-10 SSA score falls in, for a title or a screen reader.

    Colour never carries the score on its own: the number is printed beside
    it, and this names the band for anyone who cannot see the colour.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return ""
    from apps.core.enums import ssa_score_band

    return ssa_score_band(score)[0]


@register.filter
def outbox_owner(user):
    """An opaque, per-account token for the offline field outbox.

    static/js/field-outbox.js stamps each saved action with it and replays an
    action only on a page signed in as the same account, so a phone shared by
    two officers never sends one person's saved "complete activity" under the
    other's session (frontend audit, 2026-09-23). Derived with the site
    secret, so it identifies nobody outside this deployment and is not the
    account id.
    """
    if not getattr(user, "is_authenticated", False):
        return ""
    from django.utils.crypto import salted_hmac

    return salted_hmac("edify.field-outbox.owner", str(user.pk)).hexdigest()[:24]


@register.filter
def field_role(user):
    """ "partner" or "staff" for <body data-edify-field-role>, "" signed out.

    The upload drawer served without signal is made for nobody
    (partials/my_plan/offline_evidence_drawer.html), so it reads this to show
    the Salesforce ID to staff only (owner, 2026-09-26: partners upload, staff
    complete). A display hint from the active role, costing no query; the
    server decides what an upload may carry when it arrives.
    """
    if not getattr(user, "is_authenticated", False):
        return ""
    from apps.core.rbac import EdifyRole

    partner_roles = {
        EdifyRole.PARTNER_ADMIN.value,
        EdifyRole.PARTNER_FIELD_OFFICER.value,
    }
    return "partner" if getattr(user, "active_role", "") in partner_roles else "staff"
