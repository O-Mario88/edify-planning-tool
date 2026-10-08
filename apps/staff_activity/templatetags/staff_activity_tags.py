"""``{% staff_activity_attrs %}`` — the body attributes the activity
heartbeat reads (static/js/staff-activity-beat.js): on for a signed-in
person, with the thresholds from settings.STAFF_ACTIVITY and the session's
idle window."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def staff_activity_attrs(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return ""
    from django.conf import settings

    from apps.accounts.presence import activity_setting

    return format_html(
        'data-edify-activity="on" data-edify-activity-beat="{}" data-edify-activity-idle="{}"'
        ' data-edify-session-idle="{}"',
        activity_setting("HEARTBEAT_SECONDS"),
        activity_setting("IDLE_SECONDS"),
        # After this long untouched the page asks whether it is still signed
        # in (the session's idle window, SlidingSessionMiddleware).
        settings.SESSION_COOKIE_AGE,
    )
