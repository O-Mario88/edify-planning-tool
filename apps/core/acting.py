"""Temporary delegated authority, as the rest of the platform reads it.

A person's permanent roles are ``User.roles`` and the one in use is
``User.active_role``; every gate on the platform asks one of those two, or the
scope resolved from them (``apps.core.scoping``). An acting appointment
(``apps.acting``) changes neither. For the month it names, a request made in
the acting capacity carries an :class:`ActingContext` on its principal, and
the principal answers the existing gates as the acting role, inside the seat
of the leader who appointed them:

    permissions   the acting role's, less what the appointment withholds
    pages         the acting role's, less what the appointment withholds
    scope         the substantive leader's team or country (the seat)

This module is the whole of what ordinary code needs to know about that. It
holds no models and imports none: ``apps.acting`` attaches the context, and
everything else asks here. A principal with no context is exactly what it was
before this existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.core.rbac import permissions_for_role

#: The attribute a principal in the acting capacity carries.
CONTEXT_ATTR = "_acting_context"
#: The attribute a principal with a live appointment carries, in either
#: capacity, for the account menu.
APPOINTMENT_ATTR = "_acting_appointment"

SCOPE_PL_TEAM = "pl_team"
SCOPE_COUNTRY = "country"

# Decisions an appointment leaves with the substantive leader. They are made
# inside services by the reporting line or by a role name, not by a
# permission key, so those services ask `refuse_withheld` by these names
# (``apps.acting.policy.Authority`` holds the same values).
FUND_DECISION = "fund_decision"
LEAVE_DECISION = "leave_decision"
PEOPLE_DECISION = "people_decision"
TARGET_ALLOCATION = "target_allocation"
STAFF_ADMINISTRATION = "staff_administration"
ACTING_APPOINTMENT = "acting_appointment"
GOVERNANCE = "governance"
VERIFICATION = "verification"

_STAMP_MEMO = "acting.audit_stamp"


@dataclass(frozen=True)
class ActingContext:
    """The delegated authority one request is made under."""

    assignment_id: str
    #: The role whose operational capabilities are delegated (EdifyRole value).
    acting_role: str
    #: The permanent role the person works in, which the database still holds.
    substantive_role: str
    label: str  # "Acting Program Lead"
    short_label: str  # "Acting PL"
    scope_type: str  # SCOPE_PL_TEAM | SCOPE_COUNTRY
    #: The leader whose seat is delegated: their staff profile and account.
    seat_staff_id: str
    seat_user_id: str
    seat_name: str
    country: str
    start_date: date
    end_date: date
    appointed_by_id: str
    appointed_by_name: str
    withheld_permissions: frozenset = field(default_factory=frozenset)
    withheld_pages: frozenset = field(default_factory=frozenset)
    #: Named authorities that stay with the substantive leader
    #: (``apps.acting.policy.Authority``).
    withheld_authorities: frozenset = field(default_factory=frozenset)

    @property
    def period_label(self) -> str:
        return self.start_date.strftime("%B %Y")

    def stamp(self) -> dict:
        """What an audit row records about the capacity an act was done in."""
        return {
            "assignment_id": self.assignment_id,
            "acting_role": self.acting_role,
            "acting_label": self.label,
            "permanent_role": self.substantive_role,
            "scope_type": self.scope_type,
            "acting_for": {
                "staff_profile_id": self.seat_staff_id,
                "user_id": self.seat_user_id,
                "name": self.seat_name,
            },
            "appointed_by": {
                "user_id": self.appointed_by_id,
                "name": self.appointed_by_name,
            },
            "period": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
            },
        }


def acting_context(principal) -> ActingContext | None:
    """The delegated authority this principal is working under, or None."""
    return getattr(principal, CONTEXT_ATTR, None)


def is_acting(principal) -> bool:
    return acting_context(principal) is not None


def substantive_role(principal) -> str:
    """The permanent role in use, whatever capacity the request is made in."""
    context = acting_context(principal)
    if context is not None:
        return context.substantive_role
    return getattr(principal, "active_role", "") or ""


def effective_permissions(principal) -> list[str]:
    """The permission keys this principal holds on this request.

    The matrix's answer for the role in use; in the acting capacity that is
    the acting role's set less the keys the appointment withholds.
    """
    role = getattr(principal, "active_role", None)
    if not role:
        return []
    keys = permissions_for_role(role)
    context = acting_context(principal)
    if context is None or not context.withheld_permissions:
        return keys
    return [key for key in keys if key not in context.withheld_permissions]


def page_withheld(principal, page: str) -> bool:
    """Whether the acting capacity leaves this page with the substantive
    leader. Never true for a principal working in their own role."""
    context = acting_context(principal)
    return context is not None and page in context.withheld_pages


def withholds(principal, authority) -> bool:
    """Whether this principal is acting, and the named authority stayed with
    the substantive leader (``apps.acting.policy.Authority``)."""
    context = acting_context(principal)
    if context is None:
        return False
    return str(getattr(authority, "value", authority)) in context.withheld_authorities


def refuse_withheld(principal, authority, what: str) -> None:
    """Refuse a decision the acting appointment leaves with the leader.

    A no-op for anyone working in their own role. ``what`` begins the
    sentence the person is shown ("Approving a fund request").
    """
    context = acting_context(principal)
    if context is None or not withholds(principal, authority):
        return
    from apps.core.exceptions import Forbidden

    raise Forbidden(
        f"{what} is not part of an acting appointment. It stays with "
        f"{context.seat_name}."
    )


def seat(principal, scope_type: str) -> ActingContext | None:
    """The context, when it delegates a seat of this kind."""
    context = acting_context(principal)
    if context is not None and context.scope_type == scope_type:
        return context
    return None


def seat_staff_ids(principal, scope_type: str = SCOPE_PL_TEAM) -> list[str]:
    """The supervisor seats this principal sits in, as staff-profile ids.

    Their own, and in the acting capacity the substantive leader's. A reader
    that asks the reporting line "who reports to me" asks it of these, so a
    person acting for a leader reads that leader's team and their own.
    """
    own = getattr(principal, "staff_profile_id", None)
    ids = [own] if own else []
    context = seat(principal, scope_type)
    if context is not None and context.seat_staff_id not in ids:
        ids.append(context.seat_staff_id)
    return ids


def seat_user_ids(principal, scope_type: str = SCOPE_PL_TEAM) -> list[str]:
    """``seat_staff_ids`` in the account id space."""
    own = getattr(principal, "user_id", None) or getattr(principal, "id", None)
    ids = [str(own)] if own else []
    context = seat(principal, scope_type)
    if context is not None and context.seat_user_id not in ids:
        ids.append(context.seat_user_id)
    return ids


def seat_leader_ids(principal, scope_type: str = SCOPE_PL_TEAM) -> list[str]:
    """Both ids of the leader whose seat is delegated, or nothing.

    Work is filed under a staff-profile id or an account id depending on the
    path that wrote it (``apps.core.scoping.owner_ids``), so a reader that
    lists "my team's work" by owner adds both for the substantive leader.
    """
    context = seat(principal, scope_type)
    if context is None:
        return []
    return [i for i in (context.seat_staff_id, context.seat_user_id) if i]


def team_lead_user_id(principal) -> str | None:
    """The account of the Programme Lead whose team this principal leads.

    Their own; as Acting Programme Lead, the Lead who appointed them. Rosters
    keyed by a Lead ("the Lead and everyone who reports to them") ask this.
    """
    context = seat(principal, SCOPE_PL_TEAM)
    if context is not None:
        return context.seat_user_id
    own = getattr(principal, "user_id", None) or getattr(principal, "id", None)
    return str(own) if own else None


def team_lead_staff_id(principal) -> str | None:
    """``team_lead_user_id`` in the staff-profile id space."""
    context = seat(principal, SCOPE_PL_TEAM)
    if context is not None:
        return context.seat_staff_id
    return getattr(principal, "staff_profile_id", None)


def capacity_label(principal) -> str:
    """ "CCEO · Acting PL" in the acting capacity, else the role in use."""
    context = acting_context(principal)
    if context is None:
        return getattr(principal, "active_role", "") or ""
    return f"{context.substantive_role} · {context.short_label}"


# ── The capacity of the request being handled ───────────────────────────────
def remember_request_capacity(principal) -> None:
    """Record the capacity of the request's principal for the audit log.

    ``apps.audit.services.log`` is handed an actor id, not a principal, and is
    called from services that never see the request. The middleware leaves the
    stamp where the log can read it for the rest of the request.
    """
    from apps.core.request_cache import store

    bucket = store()
    if bucket is None:
        return
    context = acting_context(principal)
    actor = str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))
    if context is None or not actor:
        bucket.pop(_STAMP_MEMO, None)
        return
    bucket[_STAMP_MEMO] = (actor, context.stamp())


def audit_stamp_for(actor_id) -> dict | None:
    """The acting stamp for this actor on the request being handled, or None.

    Only the request's own principal can be acting on it: an audit row written
    about another actor in the same request carries no stamp.
    """
    from apps.core.request_cache import store

    bucket = store()
    if not bucket:
        return None
    found = bucket.get(_STAMP_MEMO)
    if not found or found[0] != str(actor_id):
        return None
    return dict(found[1])


__all__ = [
    "APPOINTMENT_ATTR",
    "CONTEXT_ATTR",
    "SCOPE_COUNTRY",
    "SCOPE_PL_TEAM",
    "ActingContext",
    "acting_context",
    "audit_stamp_for",
    "capacity_label",
    "effective_permissions",
    "is_acting",
    "page_withheld",
    "refuse_withheld",
    "remember_request_capacity",
    "seat",
    "seat_leader_ids",
    "seat_staff_ids",
    "seat_user_ids",
    "substantive_role",
    "team_lead_staff_id",
    "team_lead_user_id",
    "withholds",
]
