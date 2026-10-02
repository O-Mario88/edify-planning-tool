"""Who supports a school, as distinct from who owns it.

Owner rule, 2026-09-23 (supersedes every earlier instruction to take a
Partner-assigned school off the staff Planning page):

    A school assigned to a Partner remains in the staff member's Planning page
    and Cluster School List. Partner assignment changes who delivers specific
    support; it does not transfer school ownership.

Three different people answer three different questions, and this module keeps
them apart:

* **Portfolio owner** — who owns the school relationship. Read from the
  canonical ownership records (``School.account_owner_id`` with
  ``StaffSchoolAssignment`` behind it), never copied onto the school.
* **Support responsibility** — who currently delivers the assigned support: the
  owner, or a Partner organisation through a live ``PartnerAssignment``.
* **Activity owner** — who is responsible for one activity. That is the
  activity's own ``responsible_staff_id`` / ``assigned_partner_id`` and is not
  decided here.

Nothing is stored. Every answer is derived from the live assignment rows on
each read, so a closed or returned assignment cannot leave a stale Partner name
behind: the next read simply stops finding it.

Reads are batched: ``resolve`` answers for a page of schools in a constant
number of queries whatever the page size.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from django.conf import settings
from django.db.models import Q

#: Activity states that end a Partner's hold on the school's support. A
#: scheduled assignment whose activity reached one of these no longer makes the
#: Partner responsible; the school reads as Staff Managed again.
CLOSED_ACTIVITY_STATUSES = ("cancelled", "rejected", "deferred", "closed")

RESPONSIBILITY_STAFF = "staff"
RESPONSIBILITY_PARTNER = "partner"
RESPONSIBILITY_MULTIPLE = "multiple_partners"

MULTIPLE_PARTNERS_LABEL = "Multiple Partners — Review Required"
PARTNER_RETURNED_LABEL = "Partner Returned — Staff Action Required"

#: The data-quality issue raised when one school has more than one Partner
#: holding live support in the same period. Reconciled here, not by the
#: school-record builder (see apps.schools.data_quality.reconcile_issues).
MULTIPLE_PARTNER_ISSUE_TYPE = "multiple_partner_support"

# Partner workflow stages, as one vocabulary for Planning and Monitoring.
STAGE_AWAITING_SCHEDULE = "awaiting_schedule"
STAGE_SCHEDULED = "scheduled"
STAGE_IN_PROGRESS = "in_progress"
STAGE_EVIDENCE_SUBMITTED = "evidence_submitted"
STAGE_RETURNED_BY_IA = "returned_by_ia"
STAGE_VERIFIED = "ia_verified"
STAGE_RETURNED = "returned"

STAGE_LABELS = {
    STAGE_AWAITING_SCHEDULE: "Awaiting Schedule",
    STAGE_SCHEDULED: "Scheduled",
    STAGE_IN_PROGRESS: "In Progress",
    STAGE_EVIDENCE_SUBMITTED: "Evidence Submitted",
    STAGE_RETURNED_BY_IA: "Returned by IA",
    STAGE_VERIFIED: "IA Verified",
    STAGE_RETURNED: PARTNER_RETURNED_LABEL,
}

_IN_PROGRESS = (
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
)
_SUBMITTED = (
    "submitted_to_pl",
    "awaiting_ia_verification",
    "salesforce_id_required",
)
_RETURNED_BY_REVIEW = ("returned", "returned_by_pl", "returned_by_ia")
_VERIFIED = ("ia_verified", "accountant_confirmed", "completed", "closed")


# ── Feature flag ─────────────────────────────────────────────────────────────
def visibility_enabled(user=None) -> bool:
    """Whether the Partner-supported school rule is live for this reader.

    The global switch, or — while it is off — the pilot roles and sign-in
    emails named in settings. With neither, every surface renders exactly as it
    did before the rule, and no record is touched either way.
    """
    if getattr(settings, "PARTNER_SUPPORTED_SCHOOL_PLANNING_VISIBILITY_ENABLED", True):
        return True
    if user is None:
        return False
    roles = getattr(settings, "PARTNER_SUPPORTED_SCHOOL_PLANNING_PILOT_ROLES", [])
    if getattr(user, "active_role", None) in roles:
        return True
    users = getattr(settings, "PARTNER_SUPPORTED_SCHOOL_PLANNING_PILOT_USERS", [])
    email = (getattr(user, "email", "") or "").lower()
    return bool(email) and email in users


# ── What counts as live Partner support ─────────────────────────────────────
def active_assignment_q(fy: str | None = None, prefix: str = "") -> Q:
    """A PartnerAssignment that currently holds a school's support.

    Live when it has not been returned or withdrawn (both leave
    ``returned_to_staff``) and, once scheduled, while its activity is neither
    deleted nor closed. Scheduled work in an EARLIER financial year than the
    one being read no longer holds the school, so last year's delivered
    handover does not keep a Partner's name on this year's Planning row; work
    the Partner has scheduled into this year or a later one does, because in
    September a Partner dating October's visit is still the one supporting the
    school. A handover still waiting for a date is live whatever year it was
    made in, because the Partner still owes it.

    ``prefix`` lets the same rule be applied through a relation
    (``partner_assignments__``) in an ``Exists`` filter, so the list filters
    and the resolver below cannot disagree about which schools are
    Partner-supported.
    """
    p = prefix
    unscheduled = Q(**{f"{p}scheduled_activity__isnull": True})
    scheduled = (
        Q(**{f"{p}scheduled_activity__isnull": False})
        & Q(**{f"{p}scheduled_activity__deleted_at__isnull": True})
        & ~Q(**{f"{p}scheduled_activity__status__in": CLOSED_ACTIVITY_STATUSES})
    )
    if fy:
        # Four-digit years, so the string comparison is the year comparison.
        scheduled &= Q(**{f"{p}scheduled_activity__fy__gte": fy})
    return (
        Q(**{f"{p}school__isnull": False})
        & ~Q(**{f"{p}status": "returned_to_staff"})
        & (unscheduled | scheduled)
    )


def returned_unresolved_q(prefix: str = "") -> Q:
    """A Partner hand-back no staff member has decided on yet."""
    return Q(**{f"{prefix}status": "returned_to_staff"}) & Q(
        **{f"{prefix}resolved_at__isnull": True}
    )


def partner_stage(assignment) -> str:
    """Where one assignment is in the Partner workflow, in one word."""
    if assignment.status == "returned_to_staff":
        return STAGE_RETURNED
    activity = assignment.scheduled_activity
    if activity is None:
        return STAGE_AWAITING_SCHEDULE
    return activity_stage(activity.status, activity.ia_verification_status)


def activity_stage(status: str, ia_status: str | None = None) -> str:
    if status in _RETURNED_BY_REVIEW:
        return STAGE_RETURNED_BY_IA
    if ia_status == "confirmed" or status in ("ia_verified", "accountant_confirmed"):
        return STAGE_VERIFIED
    if status in _SUBMITTED or status in ("completed", "closed"):
        return STAGE_EVIDENCE_SUBMITTED
    if status in _IN_PROGRESS:
        return STAGE_IN_PROGRESS
    return STAGE_SCHEDULED


# ── The answer ───────────────────────────────────────────────────────────────
@dataclass
class SupportResponsibility:
    school_id: str
    responsibility_type: str = RESPONSIBILITY_STAFF
    label: str = "Staff Managed"
    responsible_name: str = ""
    staff_owner_id: str | None = None
    staff_owner_name: str = ""
    staff_assignment_id: str | None = None
    partner_organisation_id: str | None = None
    partner_assignment_id: str | None = None
    partner_status: str | None = None
    partner_status_label: str = ""
    partner_names: list[str] = field(default_factory=list)
    partner_assignment_ids: list[str] = field(default_factory=list)
    # The next dated Partner activity, if any: "Partner Visit · 18 Oct".
    partner_next_date: date | None = None
    partner_next_activity: str = ""
    # A Partner hand-back waiting on staff — shown whatever the current
    # responsibility, because the school's support is undecided until it is.
    returned_assignment_id: str | None = None
    returned_partner_id: str | None = None
    returned_partner_name: str = ""
    returned_reason: str = ""

    @property
    def is_partner(self) -> bool:
        return self.responsibility_type in (
            RESPONSIBILITY_PARTNER,
            RESPONSIBILITY_MULTIPLE,
        )

    @property
    def needs_review(self) -> bool:
        return self.responsibility_type == RESPONSIBILITY_MULTIPLE

    @property
    def staff_action_required(self) -> bool:
        return bool(self.returned_assignment_id)

    @property
    def display(self) -> str:
        """The Responsible cell: kind, then the name that is actually meant."""
        if self.responsibility_type == RESPONSIBILITY_MULTIPLE:
            return MULTIPLE_PARTNERS_LABEL
        kind = "Partner" if self.is_partner else "Staff"
        return f"{kind} · {self.responsible_name or 'Unassigned'}"

    @property
    def workflow_label(self) -> str:
        """The Partner Workflow cell, or an em dash for staff-managed work."""
        if self.staff_action_required:
            return PARTNER_RETURNED_LABEL
        if self.is_partner:
            return self.partner_status_label or "—"
        return "—"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["display"] = self.display
        data["workflow_label"] = self.workflow_label
        data["is_partner"] = self.is_partner
        data["needs_review"] = self.needs_review
        data["staff_action_required"] = self.staff_action_required
        return data


class SchoolSupportResponsibilityService:
    """The one resolver Planning, the Cluster School List and Monitoring read."""

    @staticmethod
    def resolve(schools, *, fy: str | None = None) -> dict[str, SupportResponsibility]:
        """Responsibility for each school, in four queries whatever the count.

        ``schools`` may be School instances (the pages already hold them, so no
        query is spent re-reading ownership) or bare ids.
        """
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        from apps.partners.models import PartnerAssignment
        from apps.schools.models import School

        from apps.core.fy import get_operational_fy

        fy = fy or get_operational_fy()
        rows = list(schools)
        if not rows:
            return {}
        if not hasattr(rows[0], "account_owner_id"):
            rows = list(
                School.objects.filter(id__in=rows).only(
                    "id", "account_owner_id", "account_owner_name_raw"
                )
            )
        ids = [s.id for s in rows]

        # 1. Canonical ownership links, for the assignment id and for schools
        #    whose owner column was never filled.
        links: dict[str, list] = {}
        for link in StaffSchoolAssignment.objects.filter(school_id__in=ids).values(
            "id", "school_id", "staff_id"
        ):
            links.setdefault(link["school_id"], []).append(link)

        owner_of: dict[str, str | None] = {}
        for s in rows:
            owner = s.account_owner_id
            if not owner and links.get(s.id):
                owner = links[s.id][0]["staff_id"]
            owner_of[s.id] = owner

        # 2. Names for both id spaces the owner column holds.
        wanted = {o for o in owner_of.values() if o}
        names: dict[str, str] = {}
        canonical: dict[str, str] = {}
        if wanted:
            for sp in StaffProfile.objects.filter(
                Q(id__in=wanted) | Q(user_id__in=wanted)
            ).select_related("user"):
                label = getattr(sp.user, "name", "") or getattr(sp.user, "email", "")
                for key in (sp.id, sp.user_id):
                    if key:
                        names[key] = label
                        canonical[key] = sp.id

        # 3. Live and returned-but-undecided Partner assignments, one query.
        assignments = list(
            PartnerAssignment.objects.filter(school_id__in=ids)
            .filter(active_assignment_q(fy) | returned_unresolved_q())
            .select_related("partner", "scheduled_activity")
            .order_by("created_at")
        )

        by_school: dict[str, list] = {}
        returned: dict[str, object] = {}
        for a in assignments:
            if a.status == "returned_to_staff":
                returned[a.school_id] = a  # newest wins (ordered ascending)
            else:
                by_school.setdefault(a.school_id, []).append(a)

        today = date.today()
        out: dict[str, SupportResponsibility] = {}
        raw_names = {s.id: s.account_owner_name_raw for s in rows}
        for sid in ids:
            owner = owner_of.get(sid)
            owner_name = names.get(owner or "", "") or raw_names.get(sid) or ""
            staff_link = next(
                (
                    link["id"]
                    for link in links.get(sid, [])
                    if canonical.get(owner or "", owner) == link["staff_id"]
                ),
                None,
            )
            result = SupportResponsibility(
                school_id=sid,
                responsible_name=owner_name or "Unassigned",
                staff_owner_id=canonical.get(owner or "", owner),
                staff_owner_name=owner_name,
                staff_assignment_id=staff_link,
            )
            live = by_school.get(sid, [])
            if live:
                partner_ids = []
                for a in live:
                    if a.partner_id not in partner_ids:
                        partner_ids.append(a.partner_id)
                lead = live[-1]
                result.partner_assignment_ids = [a.id for a in live]
                result.partner_names = [
                    next(a.partner.name for a in live if a.partner_id == pid)
                    for pid in partner_ids
                ]
                upcoming = sorted(
                    (
                        a.scheduled_activity
                        for a in live
                        if a.scheduled_activity is not None
                        and a.scheduled_activity.planned_date
                        and a.scheduled_activity.planned_date >= today
                    ),
                    key=lambda act: act.planned_date,
                )
                if upcoming:
                    result.partner_next_date = upcoming[0].planned_date
                    result.partner_next_activity = (
                        upcoming[0].activity_name_snapshot
                        or upcoming[0].get_activity_type_display()
                    )
                if len(partner_ids) > 1:
                    # Never silently pick one: both are shown, and the pair is
                    # a data-quality exception for a manager to resolve.
                    result.responsibility_type = RESPONSIBILITY_MULTIPLE
                    result.label = MULTIPLE_PARTNERS_LABEL
                    result.responsible_name = " / ".join(result.partner_names)
                    result.partner_status = None
                    result.partner_status_label = MULTIPLE_PARTNERS_LABEL
                else:
                    stage = partner_stage(lead)
                    result.responsibility_type = RESPONSIBILITY_PARTNER
                    result.label = "Partner Support"
                    result.responsible_name = lead.partner.name
                    result.partner_organisation_id = lead.partner_id
                    result.partner_assignment_id = lead.id
                    result.partner_status = stage
                    result.partner_status_label = STAGE_LABELS[stage]
            back = returned.get(sid)
            if back is not None:
                result.returned_assignment_id = back.id
                result.returned_partner_id = back.partner_id
                result.returned_partner_name = back.partner.name
                result.returned_reason = (
                    back.get_return_reason_category_display() or ""
                ) + (f" — {back.return_reason}" if back.return_reason else "")
            out[sid] = result
        return out

    @staticmethod
    def for_school(school, *, fy: str | None = None) -> SupportResponsibility:
        return SchoolSupportResponsibilityService.resolve([school], fy=fy)[
            getattr(school, "id", school)
        ]


# ── Multiple-Partner data-quality exception ─────────────────────────────────
def live_partner_ids(school_id: str, *, fy: str | None = None) -> set[str]:
    """The Partners holding live support in the period (the operational FY by
    default) — the same rule and period the Planning resolver reads."""
    from apps.core.fy import get_operational_fy
    from apps.partners.models import PartnerAssignment

    fy = fy or get_operational_fy()
    return set(
        PartnerAssignment.objects.filter(school_id=school_id)
        .filter(active_assignment_q(fy))
        .values_list("partner_id", flat=True)
    )


def sync_multiple_partner_exception(school_id: str | None) -> None:
    """Open, update or resolve the school's multiple-Partner exception.

    Called by every write that can change how many Partners hold a school's
    support — a new assignment, a return, a withdrawal, a resolution — so the
    exception opens the moment the ambiguity exists and closes the moment it
    does not. The assignment rows themselves are never altered.
    """
    if not school_id:
        return
    from django.utils import timezone

    from apps.partners.models import Partner
    from apps.schools.models import DataQualityIssue

    key = f"school:{school_id}|dq:{MULTIPLE_PARTNER_ISSUE_TYPE}"
    partner_ids = live_partner_ids(school_id)
    open_row = DataQualityIssue.objects.filter(condition_key=key, status="open").first()
    if len(partner_ids) > 1:
        names = ", ".join(
            sorted(
                Partner.all_objects.filter(id__in=partner_ids).values_list(
                    "name", flat=True
                )
            )
        )
        if open_row is None:
            reopen = (
                DataQualityIssue.objects.filter(condition_key=key, status="resolved")
                .order_by("-resolved_at")
                .first()
            )
            row = reopen or DataQualityIssue(school_id=school_id, condition_key=key)
            row.issue_type = MULTIPLE_PARTNER_ISSUE_TYPE
            row.severity = "critical"
            row.field_name = "partner_assignment"
            row.status = "open"
            row.resolved_at = None
            row.current_value = names
            row.suggested_fix = (
                "More than one Partner holds live support at this school. "
                "Withdraw or return all but one assignment from Partner "
                "Monitoring; no new Partner can be assigned until then."
            )
            row.save()
        elif open_row.current_value != names:
            open_row.current_value = names
            open_row.save(update_fields=["current_value", "updated_at"])
    elif open_row is not None:
        open_row.status = "resolved"
        open_row.resolved_at = timezone.now()
        open_row.save(update_fields=["status", "resolved_at", "updated_at"])


def assert_school_accepts_another_partner(school, partner_id: str) -> None:
    """Refuse a new Partner at a school already in the multiple-Partner state.

    Existing assignments are preserved exactly; only the creation of a further
    one is held until a manager resolves which Partner supports the school. The
    same Partner taking another piece of its own work is not a new Partner and
    is not held.
    """
    from apps.core.exceptions import ConflictError

    if school is None or not visibility_enabled():
        return
    partners = live_partner_ids(school.id)
    if len(partners) > 1 and partner_id not in partners:
        raise ConflictError(
            f"{school.name} already has more than one Partner holding its "
            "support. Resolve the Multiple Partners review on Partner "
            "Monitoring before assigning another."
        )


__all__ = [
    "CLOSED_ACTIVITY_STATUSES",
    "MULTIPLE_PARTNERS_LABEL",
    "MULTIPLE_PARTNER_ISSUE_TYPE",
    "PARTNER_RETURNED_LABEL",
    "STAGE_LABELS",
    "SchoolSupportResponsibilityService",
    "SupportResponsibility",
    "activity_stage",
    "active_assignment_q",
    "assert_school_accepts_another_partner",
    "partner_stage",
    "returned_unresolved_q",
    "sync_multiple_partner_exception",
    "visibility_enabled",
]
