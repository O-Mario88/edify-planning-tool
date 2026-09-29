"""``{% staff_activity_attrs %}`` — the body attributes the activity
heartbeat reads (static/js/staff-activity-beat.js): on for a signed-in
person, with the thresholds from settings.STAFF_ACTIVITY."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def staff_activity_attrs(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return ""
    from apps.accounts.presence import activity_setting

    return format_html(
        'data-edify-activity="on" data-edify-activity-beat="{}" data-edify-activity-idle="{}"',
        activity_setting("HEARTBEAT_SECONDS"),
        activity_setting("IDLE_SECONDS"),
    )
