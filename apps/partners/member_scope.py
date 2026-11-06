"""What a partner's team member may see and do.

Owner, 2026-11-06: "Partner admin is the only who should be shown cost
(40,000). Team members only have access to schools assigned to them and their
only work is to schedule. the scheduling drawer should not have the cost
(40000) labels". Asked, the owner chose: the cost is hidden from team members
only; a team member schedules and has My Plan.

A team member is a person on the roster (``PartnerMember``) with a login of
their own (``PartnerMember.user``) who does not lead the team
(``member_logins.leads_team``). The organisation's own login and its Partner
Admins are not team members and keep the whole portal.

A team member:

* reads only the schools the Partner Admin gave them (``PartnerSchoolMember``)
  and the work there;
* schedules that work and reschedules it from My Plan, and does nothing else:
  no return, no delivery or evidence, no invoices or payments;
* sees no money anywhere.

Both partner roles share one menu (``navigation`` maps them to PARTNER), so
the pages they may not open are withheld per person here, beside the acting
appointment's own withholding (``apps.core.acting.page_withheld``).
"""

from __future__ import annotations

#: Where a team member starts: the schools waiting for them to schedule.
MEMBER_HOME_URL = "/partner/assigned-schools"

#: Every partner page a team member may not open. Pages outside the partner
#: portal follow their own permission (Settings, Messages, Notifications).
MEMBER_WITHHELD_PAGES = frozenset(
    {
        "partner_assignments",
        "partner_activities",
        "partner_evidence",
        "partner_my_plan",
        "partner_users",
        "partner_detail",
        "partners",
        "calendar",
        "todos",
        "my_actions",
        "daily_debrief",
        "debriefs_list",
        "debrief_detail",
        "decision_log",
        "my_target",
        "evidence_center",
    }
)

_PARTNER_ROLES = ("PartnerAdmin", "PartnerFieldOfficer")
_CACHE_ATTR = "_edify_team_member"


def team_member(user):
    """The roster entry whose own login this is, when the login does not lead
    the team; otherwise None. Read once per request object."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "active_role", "") not in _PARTNER_ROLES:
        return None
    # A role with no account behind it (the permission matrix asks by role
    # alone) is nobody's login.
    if getattr(user, "pk", None) is None:
        return None
    cached = getattr(user, _CACHE_ATTR, False)
    if cached is not False:
        return cached
    from .member_logins import leads_team
    from .models import PartnerMember

    member = (
        PartnerMember.objects.filter(
            user_id=user.pk, active=True, partner__active_status=True
        )
        .select_related("partner")
        .first()
    )
    if member is not None and leads_team(user, member.partner):
        member = None
    setattr(user, _CACHE_ATTR, member)
    return member


def is_team_member(user) -> bool:
    return team_member(user) is not None


def member_school_ids(user) -> set[str] | None:
    """The schools a team member looks after, or None for anyone else (no
    narrowing)."""
    member = team_member(user)
    if member is None:
        return None
    from .models import PartnerSchoolMember

    return set(
        PartnerSchoolMember.objects.filter(member=member).values_list(
            "school_id", flat=True
        )
    )


def sees_money(user) -> bool:
    """Costs, payments and invoices: never shown to a team member."""
    return not is_team_member(user)


def page_withheld(user, page: str) -> bool:
    """A partner page this team member may not open."""
    return page in MEMBER_WITHHELD_PAGES and is_team_member(user)


def narrow_to_member(queryset, user, field: str = "school_id"):
    """The rows a team member may read: those at their schools. Unchanged for
    anyone else."""
    schools = member_school_ids(user)
    if schools is None:
        return queryset
    return queryset.filter(**{f"{field}__in": schools})


def may_touch_school(user, school_id) -> bool:
    """May this login act on work at this school? Always, unless it is a team
    member and the school is not one of theirs."""
    schools = member_school_ids(user)
    return schools is None or (school_id is not None and school_id in schools)
