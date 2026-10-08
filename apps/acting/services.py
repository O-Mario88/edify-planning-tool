"""Appointing, changing and cancelling acting leaders, and reading who is one.

Every rule about who may appoint whom lives here, on the server, and is
applied again at the moment of each write: the drawer lists only the people
this service would accept, and a request that names anyone else is refused
by the same function that built the list.

    Acting Programme Lead   appointed by a permanent Programme Lead, working
                            in their own capacity, from the CCEOs who report
                            to them
    Acting Country Director appointed by a permanent Country Director,
                            working in their own capacity, from the
                            Programme Leads of their country

The seat is always the appointing leader's own. Nobody chooses a team or a
country in a request, so there is no identifier to tamper with.
"""

from __future__ import annotations

import calendar
import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import acting as acting_api
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.core.role_holding import holds_role, holds_role_q

from .models import ActingAssignment, today
from .policy import ACTING_ROLES, ActingRole, Authority, offered_by

#: How many months ahead an appointment may be made, this month included.
MONTHS_AHEAD = 12

#: Roles that read every acting appointment in their reach without making any.
READ_ONLY_ROLES = (EdifyRole.HUMAN_RESOURCES.value, EdifyRole.ADMIN.value)


# ── Months ──────────────────────────────────────────────────────────────────
def month_bounds(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    """The first and last day of a calendar month."""
    return (
        datetime.date(year, month, 1),
        datetime.date(year, month, calendar.monthrange(year, month)[1]),
    )


def parse_month(value) -> tuple[datetime.date, datetime.date]:
    """ "2026-10" (or a date in the month) to that month's first and last day."""
    text = str(value or "").strip()
    try:
        year, month = (int(part) for part in text.split("-")[:2])
        return month_bounds(year, month)
    except (ValueError, TypeError):
        raise BadRequest("Choose the month the appointment is for.") from None


def month_options(on: datetime.date | None = None) -> list[dict]:
    """The months an appointment may be made for: this one and the next eleven."""
    on = on or today()
    options = []
    year, month = on.year, on.month
    for _ in range(MONTHS_AHEAD):
        start, end = month_bounds(year, month)
        options.append(
            {
                "value": f"{year:04d}-{month:02d}",
                "label": start.strftime("%B %Y"),
                "effective": effective_label(start, end),
                "start": start,
                "end": end,
            }
        )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return options


def effective_label(start: datetime.date, end: datetime.date) -> str:
    return (
        f"{start.strftime('%B')} {start.day} – "
        f"{end.strftime('%B')} {end.day}, {end.year}"
    )


# ── Who may appoint, and whom ───────────────────────────────────────────────
def _own_profile(principal):
    from apps.accounts.models import StaffProfile

    profile_id = getattr(principal, "staff_profile_id", None)
    if not profile_id:
        return None
    return (
        StaffProfile.objects.filter(id=profile_id, deleted_at__isnull=True)
        .select_related("user")
        .first()
    )


def appointing_policy(principal) -> ActingRole | None:
    """The appointment this person may make, or None.

    They must be working in their own permanent role: a person in an acting
    capacity appoints nobody, whatever role it acts in, and neither does an
    account that is merely switched to a role it does not hold.
    """
    if principal is None or not getattr(principal, "is_authenticated", False):
        return None
    if acting_api.is_acting(principal):
        return None
    role = getattr(principal, "active_role", "") or ""
    entry = offered_by(role)
    if entry is None or not _holds_permanently(principal, role):
        return None
    return entry


def _holds_permanently(principal, role: str) -> bool:
    """Whether ``role`` is one of the roles on the person's account.

    An account whose role list was never filled in holds the role it works
    in (``apps.core.role_holding``); callers have already ruled out an acting
    capacity, the only thing that presents a role the account does not hold.
    """
    held = list(getattr(principal, "roles", None) or [])
    return role in held or not held


def eligible_appointees(principal, entry: ActingRole | None = None) -> list:
    """The staff profiles this leader may appoint, by name.

    The appointee holds the appointee role permanently, is a live account,
    is not an administrator, and stands inside the appointing leader's own
    reach: on their reporting line for a team, in their country for a
    country.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    entry = entry or appointing_policy(principal)
    seat = _own_profile(principal)
    if entry is None or seat is None:
        return []
    people = (
        StaffProfile.objects.filter(
            holds_role_q(entry.appointee_role),
            deleted_at__isnull=True,
            user__deleted_at__isnull=True,
            user__is_active=True,
        )
        .exclude(id=seat.id)
        .exclude(user__roles__contains=[EdifyRole.ADMIN.value])
        # Someone who already holds the acting role has nothing to be given.
        .exclude(holds_role_q(entry.acting_role))
        .select_related("user")
        .order_by("user__name")
    )
    if entry.scope_type == acting_api.SCOPE_PL_TEAM:
        people = people.filter(
            id__in=StaffSupervisorAssignment.objects.filter(
                supervisor_id=seat.id
            ).values("supervisee_id")
        )
    else:
        country = (seat.country or "").strip()
        if not country:
            return []
        people = people.filter(country=country)
    return list(people)


def _assert_may_appoint(principal) -> tuple[ActingRole, object]:
    entry = appointing_policy(principal)
    seat = _own_profile(principal)
    if entry is None or seat is None:
        _audit(
            "acting_assignment.refused",
            principal,
            None,
            success=False,
            reason="Not a permanent leader who may appoint an acting leader.",
        )
        raise Forbidden(
            "Only a Program Lead or Country Director, working in their own "
            "role, can appoint an acting leader."
        )
    return entry, seat


# ── What was granted, for the record ────────────────────────────────────────
def _seat_members(entry: ActingRole, seat) -> list[dict]:
    """The people in the seat on the day of the appointment."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    if entry.scope_type == acting_api.SCOPE_PL_TEAM:
        members = StaffProfile.objects.filter(
            id__in=StaffSupervisorAssignment.objects.filter(
                supervisor_id=seat.id
            ).values("supervisee_id"),
            deleted_at__isnull=True,
        )
    else:
        members = StaffProfile.objects.filter(
            holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD),
            country=seat.country,
            deleted_at__isnull=True,
        )
    return [
        {"staff_profile_id": m.id, "user_id": m.user_id, "name": m.user.name}
        for m in members.select_related("user").order_by("user__name")
    ]


def grant_snapshot(entry: ActingRole, seat) -> dict:
    return {
        "policy": entry.key,
        "acting_role": entry.acting_role_value,
        "scope_type": entry.scope_type,
        "seat": {
            "staff_profile_id": seat.id,
            "user_id": seat.user_id,
            "name": seat.user.name,
            "country": seat.country,
        },
        "seat_members": _seat_members(entry, seat),
        "delegated_write_pages": sorted(entry.delegated_write_pages),
        "follow_up_actions": sorted(entry.follow_up_views or ()),
        "withheld_actions": sorted(entry.withheld_views),
        "delegated_read_pages": sorted(entry.delegated_read_pages),
        "withheld_pages": sorted(entry.withheld_pages),
        "withheld_permissions": sorted(entry.withheld_permission_values()),
        "withheld_authorities": sorted(entry.withheld_authorities),
    }


# ── Appoint ─────────────────────────────────────────────────────────────────
def preview(principal, *, appointee_staff_id: str, month) -> dict:
    """Everything the confirmation step states, validated as the save will be."""
    entry, seat = _assert_may_appoint(principal)
    try:
        appointee = _eligible_appointee(principal, entry, appointee_staff_id)
    except OutOfReach as refusal:
        _audit_out_of_reach(principal, entry, refusal)
        raise
    start, end = _appointable_month(month)
    _assert_no_conflict(entry, seat, appointee.user_id, start)
    return {
        "entry": entry,
        "seat": seat,
        "appointee": appointee,
        "start": start,
        "end": end,
        "month_value": f"{start.year:04d}-{start.month:02d}",
        "month_label": start.strftime("%B %Y"),
        "effective": effective_label(start, end),
        "statement": confirmation_statement(entry, appointee.user.name, start, end),
    }


def confirmation_statement(
    entry: ActingRole, appointee_name: str, start: datetime.date, end: datetime.date
) -> str:
    first = (appointee_name or "").split(" ")[0] or appointee_name
    period = f"from {start.strftime('%B')} {start.day} through {end.strftime('%B')} {end.day}"
    if entry.scope_type == acting_api.SCOPE_PL_TEAM:
        return (
            f"{first} will receive {entry.short_label} operational access for your "
            f"entire PL team, including your own operational scope, {period}. "
            "Your permanent PL role will remain unchanged."
        )
    return (
        f"{first} will receive {entry.short_label} operational access for the "
        f"country {period}. Your permanent Country Director role will remain "
        "unchanged."
    )


def _eligible_appointee(principal, entry: ActingRole, appointee_staff_id):
    wanted = str(appointee_staff_id or "").strip()
    if not wanted:
        raise BadRequest(f"Choose the {entry.appointee_role.value} to appoint.")
    for person in eligible_appointees(principal, entry):
        if person.id == wanted:
            return person
    raise OutOfReach(
        f"You can appoint only a {entry.appointee_role.value} in your own "
        f"{entry.scope_label.lower()}.",
        requested=wanted,
    )


class OutOfReach(Forbidden):
    """An appointee outside the appointing leader's reach or role."""

    def __init__(self, detail, *, requested: str):
        super().__init__(detail)
        self.requested = requested


def _audit_out_of_reach(principal, entry: ActingRole, refusal: OutOfReach) -> None:
    """Written after the refused transaction has unwound, so the attempt is
    kept when nothing else of it is."""
    _audit(
        "acting_assignment.refused",
        principal,
        None,
        success=False,
        reason="Appointee is outside the appointing leader's reach or role.",
        payload={
            "requested_staff_profile_id": refusal.requested[:30],
            "policy": entry.key,
        },
    )


def _appointable_month(month) -> tuple[datetime.date, datetime.date]:
    start, end = parse_month(month)
    on = today()
    if end < on:
        raise BadRequest("That month has ended. Choose this month or a later one.")
    last = month_options(on)[-1]["start"]
    if start > last:
        raise BadRequest(f"Appointments can be made up to {MONTHS_AHEAD} months ahead.")
    return start, end


def _assert_no_conflict(entry, seat, appointee_user_id, start, *, ignore_id=None):
    standing = ActingAssignment.objects.standing().filter(start_date=start)
    if ignore_id:
        standing = standing.exclude(id=ignore_id)
    taken = (
        standing.filter(seat_id=seat.id, role_key=entry.key)
        .select_related("appointee")
        .first()
    )
    if taken is not None:
        raise ConflictError(
            f"{taken.appointee.name} is already {entry.label} for "
            f"{start.strftime('%B %Y')}. Cancel that appointment first."
        )
    other = standing.filter(appointee_id=appointee_user_id).first()
    if other is not None:
        raise ConflictError(
            f"This person already holds an acting appointment ({other.label}) "
            f"for {start.strftime('%B %Y')}."
        )


def appoint(principal, *, appointee_staff_id: str, month) -> ActingAssignment:
    """Appoint an acting leader for one calendar month."""
    entry, seat = _assert_may_appoint(principal)
    try:
        return _appoint(principal, entry, seat, appointee_staff_id, month)
    except OutOfReach as refusal:
        _audit_out_of_reach(principal, entry, refusal)
        raise


def _appoint(principal, entry, seat, appointee_staff_id, month) -> ActingAssignment:
    with transaction.atomic():
        # The seat's own row serialises two appointments for one seat; the
        # unique constraints are what finally hold if anything gets past.
        from apps.accounts.models import StaffProfile

        StaffProfile.objects.select_for_update().filter(id=seat.id).first()
        appointee = _eligible_appointee(principal, entry, appointee_staff_id)
        start, end = _appointable_month(month)
        _assert_no_conflict(entry, seat, appointee.user_id, start)
        try:
            with transaction.atomic():
                assignment = ActingAssignment.objects.create(
                    role_key=entry.key,
                    acting_role=entry.acting_role_value,
                    appointee_id=appointee.user_id,
                    appointee_role=entry.appointee_role.value,
                    appointed_by_id=principal.id,
                    appointed_by_role=entry.appointer_role.value,
                    scope_type=entry.scope_type,
                    seat_id=seat.id,
                    country=(seat.country or "").strip(),
                    start_date=start,
                    end_date=end,
                    grant_snapshot=grant_snapshot(entry, seat),
                )
        except IntegrityError:
            raise ConflictError(
                "An acting appointment for that month was made a moment ago. "
                "Reload the page to see it."
            ) from None
        sync_hint(appointee.user_id)
        _audit(
            "acting_assignment.created",
            principal,
            assignment,
            payload=_describe(assignment),
            required=True,
        )
        transaction.on_commit(lambda: _notify_appointed(assignment.id))
    return assignment


# ── Change and cancel ───────────────────────────────────────────────────────
def get_visible(principal, assignment_id) -> ActingAssignment:
    """The appointment, when this person may manage it; 404 otherwise.

    Not found rather than forbidden, so an id from another team or country
    says nothing about whether it exists.
    """
    assignment = (
        visible_to(principal)
        .filter(id=str(assignment_id or ""))
        .select_related("appointee", "appointed_by", "seat__user")
        .first()
    )
    if assignment is None:
        raise NotFoundError("That acting appointment was not found.")
    return assignment


def may_manage(principal, assignment: ActingAssignment) -> bool:
    """Whether this person may change or cancel the appointment.

    The leader whose seat it delegates, working in their own role. A Country
    Director also for an Acting Programme Lead in their country, and an
    administrator for any, so delegated access can always be stopped; neither
    of those may appoint in the seat's place.
    """
    if principal is None or acting_api.is_acting(principal):
        return False
    role = getattr(principal, "active_role", "") or ""
    if role == EdifyRole.ADMIN.value:
        return True
    if not _holds_permanently(principal, role):
        return False
    own = getattr(principal, "staff_profile_id", None)
    if own and assignment.seat_id == own and role == assignment.appointed_by_role:
        return True
    if (
        role == EdifyRole.COUNTRY_DIRECTOR.value
        and assignment.scope_type == acting_api.SCOPE_PL_TEAM
    ):
        profile = _own_profile(principal)
        return bool(
            profile
            and (profile.country or "").strip()
            and (profile.country or "").strip() == assignment.country
        )
    return False


def cancel(principal, assignment_id, *, reason: str = "") -> ActingAssignment:
    """End an upcoming or active appointment now. The record is kept."""
    with transaction.atomic():
        assignment = get_visible(principal, assignment_id)
        assignment = (
            ActingAssignment.objects.select_for_update()
            .select_related("appointee", "appointed_by", "seat__user")
            .get(id=assignment.id)
        )
        if not may_manage(principal, assignment):
            _audit(
                "acting_assignment.refused",
                principal,
                assignment,
                success=False,
                reason="Not permitted to cancel this acting appointment.",
            )
            raise Forbidden("You cannot cancel this acting appointment.")
        state = assignment.state()
        if state not in ("upcoming", "active"):
            raise BadRequest(
                f"This appointment is already {assignment.state_label.lower()}."
            )
        assignment.cancelled_at = timezone.now()
        assignment.cancelled_by_id = principal.id
        assignment.cancel_reason = (reason or "").strip()[:512]
        assignment.save(
            update_fields=[
                "cancelled_at",
                "cancelled_by",
                "cancel_reason",
                "updated_at",
            ]
        )
        sync_hint(assignment.appointee_id)
        _audit(
            "acting_assignment.cancelled",
            principal,
            assignment,
            payload={
                **_describe(assignment),
                "state_when_cancelled": state,
                "reason": assignment.cancel_reason,
            },
            required=True,
        )
        transaction.on_commit(lambda: _notify_cancelled(assignment.id))
    return assignment


def reschedule(principal, assignment_id, *, month) -> ActingAssignment:
    """Move an appointment that has not begun to another month.

    Only before it begins. An active appointment is never edited: what it
    granted has been in use, so it is cancelled and a new one made, and both
    stay on the record. The month it was first made for is kept on the row.
    """
    with transaction.atomic():
        assignment = get_visible(principal, assignment_id)
        assignment = (
            ActingAssignment.objects.select_for_update()
            .select_related("appointee", "appointed_by", "seat__user")
            .get(id=assignment.id)
        )
        own = getattr(principal, "staff_profile_id", None)
        if (
            acting_api.is_acting(principal)
            or assignment.seat_id != own
            or appointing_policy(principal) is None
        ):
            raise Forbidden("Only the appointing leader can change this appointment.")
        if not assignment.is_upcoming():
            raise BadRequest(
                "Only an appointment that has not begun can be changed. Cancel "
                "this one and make a new appointment instead."
            )
        start, end = _appointable_month(month)
        if start == assignment.start_date:
            return assignment
        _assert_no_conflict(
            assignment.policy,
            assignment.seat,
            assignment.appointee_id,
            start,
            ignore_id=assignment.id,
        )
        before = _describe(assignment)
        assignment.revisions = [
            *(assignment.revisions or []),
            {
                "start_date": assignment.start_date.isoformat(),
                "end_date": assignment.end_date.isoformat(),
                "changed_at": timezone.now().isoformat(),
                "changed_by": principal.id,
            },
        ]
        assignment.start_date, assignment.end_date = start, end
        assignment.reminded_at = None
        try:
            with transaction.atomic():
                assignment.save(
                    update_fields=[
                        "start_date",
                        "end_date",
                        "revisions",
                        "reminded_at",
                        "updated_at",
                    ]
                )
        except IntegrityError:
            raise ConflictError(
                "Another acting appointment already stands for that month."
            ) from None
        sync_hint(assignment.appointee_id)
        _audit(
            "acting_assignment.updated",
            principal,
            assignment,
            payload={"before": before, "after": _describe(assignment)},
            required=True,
        )
        transaction.on_commit(lambda: _notify_rescheduled(assignment.id))
    return assignment


# ── Reading ─────────────────────────────────────────────────────────────────
def visible_to(principal):
    """The appointments this person may read, as a queryset.

    Their own always. A Programme Lead: those for their seat. A Country
    Director and Human Resources: those of their country. An administrator:
    all. The reach is the person's own permanent role, never an acting one.
    """
    from django.db.models import Q

    if principal is None or not getattr(principal, "is_authenticated", False):
        return ActingAssignment.objects.none()
    mine = Q(appointee_id=principal.id)
    role = acting_api.substantive_role(principal)
    if role == EdifyRole.ADMIN.value:
        return ActingAssignment.objects.all()
    profile = _own_profile(principal)
    if profile is None:
        return ActingAssignment.objects.filter(mine)
    reach = mine | Q(seat_id=profile.id) | Q(appointed_by_id=principal.id)
    country = (profile.country or "").strip()
    if country and role in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.HUMAN_RESOURCES.value,
    ):
        reach |= Q(country=country)
    return ActingAssignment.objects.filter(reach)


def board(principal) -> dict:
    """Current, upcoming and history, for the Acting Leadership page."""
    on = today()
    rows = list(
        visible_to(principal)
        .select_related("appointee", "appointed_by", "seat__user", "cancelled_by")
        .order_by("-start_date", "-created_at")
    )
    current, upcoming, history = [], [], []
    for row in rows:
        row.can_manage = may_manage(principal, row)
        state = row.state(on)
        if state == "active":
            current.append(row)
        elif state == "upcoming":
            upcoming.append(row)
        else:
            history.append(row)
    upcoming.sort(key=lambda r: r.start_date)
    return {"current": current, "upcoming": upcoming, "history": history}


def scope_label(assignment: ActingAssignment) -> str:
    seat_name = getattr(getattr(assignment.seat, "user", None), "name", "") or ""
    if assignment.scope_type == acting_api.SCOPE_PL_TEAM:
        return f"{seat_name}'s PL team" if seat_name else "PL team"
    return assignment.country or "Country"


def actions_under(assignment: ActingAssignment):
    """The audited acts performed in this appointment's acting capacity,
    newest first, as a queryset for the caller to page."""
    from apps.audit.models import AuditLog

    start = timezone.make_aware(
        datetime.datetime.combine(assignment.start_date, datetime.time.min)
    )
    end = timezone.make_aware(
        datetime.datetime.combine(
            assignment.end_date + datetime.timedelta(days=1), datetime.time.min
        )
    )
    return (
        AuditLog.objects.filter(
            actor_id=assignment.appointee_id,
            created_at__gte=start,
            created_at__lt=end,
            payload__acting__assignment_id=assignment.id,
        )
        .exclude(action__startswith="notification.")
        .order_by("-created_at")
    )


# ── The acting capacity of a request ────────────────────────────────────────
def sync_hint(user_id) -> None:
    """Keep ``User.acting_until`` equal to the last day of the person's
    latest standing appointment (see the field)."""
    from django.db.models import Max

    from apps.accounts.models import User

    latest = (
        ActingAssignment.objects.standing()
        .filter(appointee_id=user_id)
        .aggregate(latest=Max("end_date"))["latest"]
    )
    User.all_objects.filter(id=user_id).update(acting_until=latest)


_CAPACITY_FIELDS = (
    "id",
    "role_key",
    "acting_role",
    "appointee_id",
    "appointee_role",
    "appointed_by_id",
    "appointed_by_role",
    "scope_type",
    "seat_id",
    "country",
    "start_date",
    "end_date",
    "cancelled_at",
    "in_capacity",
    "seat__id",
    "seat__country",
    "seat__deleted_at",
    "seat__user_id",
    "seat__user__id",
    "seat__user__name",
    "seat__user__roles",
    "seat__user__active_role",
    "seat__user__is_active",
    "seat__user__deleted_at",
    "appointed_by__id",
    "appointed_by__name",
)


def current_for(user_id, on: datetime.date | None = None) -> ActingAssignment | None:
    """The appointment this person holds today, or None."""
    return (
        ActingAssignment.objects.active(on)
        .filter(appointee_id=user_id)
        .select_related("seat__user", "appointed_by")
        # Asked on every request an appointee makes: the record of what was
        # granted and the wide account rows stay in the table.
        .only(*_CAPACITY_FIELDS)
        .first()
    )


def still_valid(assignment: ActingAssignment, user) -> bool:
    """Whether the appointment still stands on the people it names.

    Dates and cancellation are the lifecycle; this is the rest. The appointee
    must still hold the role they were appointed from and be a live account,
    and the seat must still be held by a live leader of the appointing role.
    A leader who has left takes the delegation of their seat with them.
    """
    entry = ACTING_ROLES.get(assignment.role_key)
    if entry is None:
        return False
    if not getattr(user, "is_active", True) or getattr(user, "deleted_at", None):
        return False
    held = set(getattr(user, "roles", None) or [])
    if entry.appointee_role.value not in held or EdifyRole.ADMIN.value in held:
        return False
    seat = assignment.seat
    leader = getattr(seat, "user", None)
    if seat is None or leader is None or seat.deleted_at or leader.deleted_at:
        return False
    if not leader.is_active or not holds_role(leader, entry.appointer_role):
        return False
    if (
        entry.scope_type == acting_api.SCOPE_COUNTRY
        and not (seat.country or "").strip()
    ):
        return False
    return True


def build_context(assignment: ActingAssignment, user) -> acting_api.ActingContext:
    entry = assignment.policy
    seat = assignment.seat
    return acting_api.ActingContext(
        assignment_id=assignment.id,
        acting_role=entry.acting_role_value,
        substantive_role=user.active_role,
        label=entry.label,
        short_label=entry.short_label,
        scope_type=entry.scope_type,
        seat_staff_id=seat.id,
        seat_user_id=seat.user_id,
        seat_name=seat.user.name,
        country=(seat.country or "").strip(),
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        appointed_by_id=assignment.appointed_by_id,
        appointed_by_name=assignment.appointed_by.name,
        withheld_permissions=entry.withheld_permission_values(),
        withheld_pages=frozenset(entry.withheld_pages),
        withheld_authorities=frozenset(entry.withheld_authorities),
    )


def attach(user, on: datetime.date | None = None) -> acting_api.ActingContext | None:
    """Resolve this person's acting capacity for the request being handled.

    Reads the appointment itself, with its dates, every time: nothing about
    an acting capacity is cached between requests, so an appointment that is
    cancelled or has ended grants nothing on the very next request.
    """
    on = on or today()
    # Never trust a capacity left on a reused instance.
    drop(user)
    until = getattr(user, "acting_until", None)
    if not until or until < on:
        return None
    assignment = current_for(user.id, on)
    if assignment is None or not still_valid(assignment, user):
        return None
    setattr(user, acting_api.APPOINTMENT_ATTR, assignment)
    if not assignment.in_capacity:
        return None
    # Only from the role the appointment was made from. An account switched
    # to another role it holds is working in that role.
    if user.active_role != assignment.policy.appointee_role.value:
        return None
    context = build_context(assignment, user)
    setattr(user, acting_api.CONTEXT_ATTR, context)
    user.active_role = context.acting_role
    return context


def drop(user) -> None:
    """Return a principal to their own role, in memory."""
    context = acting_api.acting_context(user)
    if context is not None:
        user.active_role = context.substantive_role
    for name in (acting_api.CONTEXT_ATTR, acting_api.APPOINTMENT_ATTR):
        if hasattr(user, name):
            delattr(user, name)


def set_capacity(user, *, acting: bool) -> ActingAssignment | None:
    """The appointee chooses to work in the acting capacity or their own role."""
    assignment = current_for(user.id)
    if assignment is None:
        return None
    if assignment.in_capacity != acting:
        ActingAssignment.objects.filter(id=assignment.id).update(
            in_capacity=acting, updated_at=timezone.now()
        )
        assignment.in_capacity = acting
        from apps.audit.services import log as audit_log

        audit_log(
            action="acting_capacity.entered" if acting else "acting_capacity.left",
            subject_kind="ActingAssignment",
            subject_id=assignment.id,
            actor_id=str(user.id),
            actor_role=acting_api.substantive_role(user),
            payload=_describe(assignment),
        )
    return assignment


def refuse_if_withheld(principal, authority: Authority, what: str) -> None:
    """Refuse a decision the appointment leaves with the substantive leader."""
    if acting_api.withholds(principal, authority):
        context = acting_api.acting_context(principal)
        raise Forbidden(
            f"{what} is not part of an acting appointment. It stays with "
            f"{context.seat_name}."
        )


# ── Audit and notices ───────────────────────────────────────────────────────
def _describe(assignment: ActingAssignment) -> dict:
    return {
        "assignment_id": assignment.id,
        "acting_role": assignment.acting_role,
        "acting_label": assignment.label,
        "appointee": {
            "user_id": assignment.appointee_id,
            "name": assignment.appointee.name,
            "permanent_role": assignment.appointee_role,
        },
        "appointed_by": {
            "user_id": assignment.appointed_by_id,
            "name": assignment.appointed_by.name,
            "role": assignment.appointed_by_role,
        },
        "scope_type": assignment.scope_type,
        "scope": scope_label(assignment),
        "seat_staff_profile_id": assignment.seat_id,
        "country": assignment.country,
        "month": assignment.period_label,
        "start_date": assignment.start_date.isoformat(),
        "end_date": assignment.end_date.isoformat(),
    }


def _audit(
    action,
    principal,
    assignment,
    *,
    success=True,
    reason=None,
    payload=None,
    required=False,
) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="ActingAssignment",
        subject_id=getattr(assignment, "id", None),
        actor_id=str(getattr(principal, "id", "") or "") or None,
        actor_role=acting_api.substantive_role(principal) or None,
        success=success,
        reason=reason,
        payload=payload,
        required=required,
    )


def _load(assignment_id) -> ActingAssignment | None:
    return (
        ActingAssignment.objects.filter(id=assignment_id)
        .select_related("appointee", "appointed_by", "seat__user", "cancelled_by")
        .first()
    )


def _notify(
    event: str, assignment, title: str, body: str, recipients, priority="normal"
):
    from apps.notifications.services import WorkflowNotificationService

    WorkflowNotificationService.trigger(
        event_type=event,
        category="acting_leadership",
        priority=priority,
        title=title,
        body=body,
        context_type="ActingAssignment",
        context_id=assignment.id,
        recipients=[r for r in recipients if r],
    )


def _notify_appointed(assignment_id) -> None:
    assignment = _load(assignment_id)
    if assignment is None:
        return
    scope = scope_label(assignment)
    _notify(
        "acting.appointed",
        assignment,
        f"You have been appointed {assignment.short_label} for {assignment.period_label}.",
        (
            f"{assignment.appointed_by.name} appointed you {assignment.label} for "
            f"{assignment.period_label}. Scope: {scope}. Effective "
            f"{assignment.effective_label}. Your permanent role "
            f"({assignment.appointee_role}) does not change."
        ),
        [assignment.appointee],
        priority="high",
    )
    team = _seat_team_user_ids(assignment)
    if team:
        _notify(
            "acting.team_informed",
            assignment,
            f"{assignment.appointee.name} is {assignment.short_label} for {assignment.period_label}.",
            (
                f"{assignment.appointed_by.name} appointed {assignment.appointee.name} "
                f"{assignment.label} for {assignment.period_label} "
                f"({assignment.effective_label}). {assignment.appointed_by.name} "
                f"remains {assignment.appointed_by_role}."
            ),
            team,
        )


def _notify_cancelled(assignment_id) -> None:
    assignment = _load(assignment_id)
    if assignment is None:
        return
    by = getattr(assignment.cancelled_by, "name", "") or "A leader"
    _notify(
        "acting.cancelled",
        assignment,
        f"Your {assignment.short_label} appointment for {assignment.period_label} was cancelled.",
        (
            f"{by} cancelled your {assignment.label} appointment for "
            f"{assignment.period_label}. Your {assignment.appointee_role} role is "
            "unchanged."
            + (
                f" Reason: {assignment.cancel_reason}"
                if assignment.cancel_reason
                else ""
            )
        ),
        [assignment.appointee, assignment.seat.user]
        if assignment.cancelled_by_id != assignment.seat.user_id
        else [assignment.appointee],
        priority="high",
    )


def _notify_rescheduled(assignment_id) -> None:
    assignment = _load(assignment_id)
    if assignment is None:
        return
    _notify(
        "acting.rescheduled",
        assignment,
        f"Your {assignment.short_label} appointment is now for {assignment.period_label}.",
        (
            f"{assignment.appointed_by.name} moved your {assignment.label} "
            f"appointment to {assignment.period_label} "
            f"({assignment.effective_label})."
        ),
        [assignment.appointee],
    )


def _seat_team_user_ids(assignment: ActingAssignment) -> list[str]:
    """The other people in the seat, who should know who is acting."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    if assignment.scope_type == acting_api.SCOPE_PL_TEAM:
        members = StaffProfile.objects.filter(
            id__in=StaffSupervisorAssignment.objects.filter(
                supervisor_id=assignment.seat_id
            ).values("supervisee_id")
        )
    else:
        members = StaffProfile.objects.filter(
            holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD), country=assignment.country
        )
    return list(
        members.filter(
            deleted_at__isnull=True, user__is_active=True, user__deleted_at__isnull=True
        )
        .exclude(user_id=assignment.appointee_id)
        .exclude(user_id=assignment.appointed_by_id)
        .values_list("user_id", flat=True)
    )


__all__ = [
    "MONTHS_AHEAD",
    "actions_under",
    "appoint",
    "appointing_policy",
    "attach",
    "board",
    "build_context",
    "cancel",
    "confirmation_statement",
    "current_for",
    "drop",
    "effective_label",
    "eligible_appointees",
    "get_visible",
    "grant_snapshot",
    "may_manage",
    "month_bounds",
    "month_options",
    "parse_month",
    "preview",
    "refuse_if_withheld",
    "reschedule",
    "scope_label",
    "set_capacity",
    "still_valid",
    "sync_hint",
    "visible_to",
]
