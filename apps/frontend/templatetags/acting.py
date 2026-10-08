"""The acting capacity, for the account menu and the profile (apps.acting).

``{% acting_identity request.user as acting %}`` gives a template everything
it states about a person's acting appointment, or None when they hold none
that is active today. It reads what the request's middleware already resolved
and makes no query.
"""

from __future__ import annotations

from django import template

from apps.core.acting import APPOINTMENT_ATTR, acting_context, substantive_role

register = template.Library()


@register.simple_tag
def acting_identity(user):
    appointment = getattr(user, APPOINTMENT_ATTR, None)
    if appointment is None:
        return None
    working = acting_context(user) is not None
    role = substantive_role(user)
    return {
        "working": working,
        "permanent_role": role,
        "label": appointment.label,
        "short_label": appointment.short_label,
        "period": appointment.period_label,
        # "CCEO · Acting PL": the permanent role first, always.
        "identity": f"{role} · {appointment.short_label}" if working else role,
        # Offered only from the role the appointment was made from.
        "can_enter": not working and role == appointment.appointee_role,
    }


@register.filter
def audit_capacity(row):
    """Who an audit row's actor was acting as: "CCEO · Acting Program Lead"
    for an act done in an acting appointment, else the row's own role.

    The row's `actor_role` is the capacity the act was done in; an acting
    appointment stamps the permanent role beside it (apps.core.acting).
    """
    read = (
        row.get
        if isinstance(row, dict)
        else lambda key, default=None: getattr(row, key, default)
    )
    role = read("actor_role") or ""
    payload = read("payload")
    stamp = payload.get("acting") if isinstance(payload, dict) else None
    if not isinstance(stamp, dict) or not stamp.get("permanent_role"):
        return role
    return f"{stamp['permanent_role']} · {stamp.get('acting_label') or role}"
