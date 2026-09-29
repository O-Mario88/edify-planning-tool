"""Project school capacity — the one place its numbers are worked out.

Brief, 2026-09-29: the Project Coordinator sets how many schools each staff
member may add to a project; staff add schools only within that allocation;
a school leaves a project only before its project work has begun, and the
place it held comes back.

Everything a page shows about an allocation — used, remaining, utilisation,
whether it is full — comes from here, counted from the live enrolments
(``ProjectSchoolAssignment``). Nothing is stored but the maximum, so nothing
can drift. ``projects.services.assign_school`` asks :func:`reserve_place`
inside its transaction; the database trigger from migration 0014 holds the
same line for anything that bypasses the service.

A project nobody has set allocations for is not capacity-managed: staff add
schools to it as before. Once the coordinator sets the first allocation, the
project is managed, and a staff member without one of their own may add none.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, F, Q

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import (
    Project,
    ProjectSchoolAssignment,
    ProjectStaffCapacity,
)

__all__ = [
    "Allocation",
    "CAPACITY_EXEMPT_ROLES",
    "ELIGIBLE_STAFF_ROLES",
    "NEAR_CAPACITY_SHARE",
    "WITHDRAWAL_REASONS",
    "WithdrawalBlock",
    "allocation_for",
    "allocations_by_project",
    "allocations_for_project",
    "allocations_for_staff",
    "annotate_allocations",
    "assert_batch_fits",
    "capacity_refusal",
    "consuming_staff_id",
    "eligible_staff",
    "is_capacity_managed",
    "may_withdraw",
    "partner_held_schools",
    "project_summary",
    "reserve_place",
    "school_stages",
    "set_capacity",
    "withdrawal_block",
    "withdrawal_blocks",
    "withdrawal_reason_text",
]

#: Roles whose additions draw on nobody's allocation: the coordinator who
#: sets allocations and the country roles above them.
CAPACITY_EXEMPT_ROLES = frozenset(
    {
        EdifyRole.PROJECT_COORDINATOR.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    }
)

#: Who can hold an allocation: the staff who add their schools to projects.
ELIGIBLE_STAFF_ROLES = (EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

#: At or above this share of the allocation used, it reads "Near capacity".
NEAR_CAPACITY_SHARE = 0.8

WITHDRAWAL_REASONS = (
    ("no_longer_eligible", "School no longer eligible"),
    ("duplicate", "Duplicate assignment"),
    ("reallocation", "Staff capacity reallocation"),
    ("school_requested", "School requested removal"),
    ("other", "Other"),
)


# ── Allocations ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Allocation:
    capacity_id: str
    project_id: str
    project_name: str
    project_code: str
    staff_id: str
    staff_name: str
    maximum: int
    assigned: int

    @property
    def remaining(self) -> int:
        return max(self.maximum - self.assigned, 0)

    @property
    def utilization(self) -> float:
        return round(self.assigned / self.maximum * 100, 1) if self.maximum else 0.0

    @property
    def status(self) -> str:
        if self.assigned >= self.maximum:
            return "full"
        if self.assigned >= self.maximum * NEAR_CAPACITY_SHARE:
            return "near"
        return "available"

    @property
    def status_label(self) -> str:
        return {
            "full": "Full",
            "near": "Near capacity",
            "available": "Available",
        }[self.status]


def _allocations(queryset) -> list[Allocation]:
    rows = queryset.select_related("project", "staff__user").annotate(
        held=Count(
            "project__school_assignments",
            filter=Q(project__school_assignments__assigned_staff_id=F("staff_id")),
        )
    )
    return [
        Allocation(
            capacity_id=row.id,
            project_id=row.project_id,
            project_name=row.project.name,
            project_code=row.project.code or "",
            staff_id=row.staff_id,
            staff_name=row.staff.user.name,
            maximum=row.max_schools,
            assigned=row.held,
        )
        for row in rows
    ]


def allocations_for_project(project_id: str) -> list[Allocation]:
    return sorted(
        _allocations(ProjectStaffCapacity.objects.filter(project_id=project_id)),
        key=lambda a: a.staff_name.lower(),
    )


def allocations_for_staff(staff_id: str | None) -> list[Allocation]:
    if not staff_id:
        return []
    return sorted(
        _allocations(
            ProjectStaffCapacity.objects.filter(
                staff_id=staff_id, project__deleted_at__isnull=True
            )
        ),
        key=lambda a: a.project_name.lower(),
    )


def allocation_for(project_id: str, staff_id: str | None) -> Allocation | None:
    if not staff_id:
        return None
    found = _allocations(
        ProjectStaffCapacity.objects.filter(project_id=project_id, staff_id=staff_id)
    )
    return found[0] if found else None


def is_capacity_managed(project_id: str) -> bool:
    return ProjectStaffCapacity.objects.filter(project_id=project_id).exists()


def project_summary(project, allocations: list[Allocation] | None = None) -> dict:
    """The compact strip over a project's allocation table."""
    allocations = (
        allocations if allocations is not None else allocations_for_project(project.id)
    )
    total = sum(a.maximum for a in allocations)
    allocated_assigned = sum(a.assigned for a in allocations)
    enrolled = ProjectSchoolAssignment.objects.filter(project_id=project.id).count()
    return {
        "capacity": total,
        "assigned": allocated_assigned,
        "remaining": sum(a.remaining for a in allocations),
        "staff": len(allocations),
        # Schools a coordinator or country role added, which use no allocation.
        "outside_allocations": max(enrolled - allocated_assigned, 0),
        "enrolled": enrolled,
    }


# ── Who uses a place ────────────────────────────────────────────────────────
def consuming_staff_id(principal) -> str | None:
    """The staff member whose allocation this principal's addition uses."""
    if principal is None:
        return None
    if getattr(principal, "active_role", "") in CAPACITY_EXEMPT_ROLES:
        return None
    if getattr(principal, "is_superuser", False):
        return None
    return getattr(principal, "staff_profile_id", None) or None


def capacity_refusal(allocation: Allocation, *, titled: bool = True) -> str:
    return (
        ("Project capacity reached. " if titled else "")
        + "You have reached your allocation of "
        f"{allocation.maximum} schools for {allocation.project_name}. No "
        "additional schools can be added unless the Project Coordinator "
        "increases your allocation."
    )


def reserve_place(project, staff_id: str | None) -> str | None:
    """Refuse an addition past the allocation; return the staff id it uses.

    Must run inside the enrolling transaction. The allocation row is locked
    first, so two additions racing for the last place are served one after
    the other and the second is refused.
    """
    if not staff_id:
        return None
    capacity = (
        ProjectStaffCapacity.objects.select_for_update()
        .filter(project_id=project.id, staff_id=staff_id)
        .first()
    )
    if capacity is None:
        if is_capacity_managed(project.id):
            raise Forbidden(
                f"You have no school allocation for {project.name}. Ask its "
                "Project Coordinator to set one before adding schools."
            )
        return staff_id
    held = ProjectSchoolAssignment.objects.filter(
        project_id=project.id, assigned_staff_id=staff_id
    ).count()
    if held >= capacity.max_schools:
        raise BadRequest(
            capacity_refusal(
                Allocation(
                    capacity_id=capacity.id,
                    project_id=project.id,
                    project_name=project.name,
                    project_code=project.code or "",
                    staff_id=staff_id,
                    staff_name="",
                    maximum=capacity.max_schools,
                    assigned=held,
                )
            )
        )
    return staff_id


def assert_batch_fits(project, staff_id: str | None, count: int) -> None:
    """Refuse a batch larger than what remains, before adding any of it."""
    if not staff_id or count <= 0:
        return
    allocation = allocation_for(project.id, staff_id)
    if allocation is None:
        return
    if count > allocation.remaining:
        if allocation.remaining == 0:
            raise BadRequest(capacity_refusal(allocation))
        raise BadRequest(
            "Capacity exceeded. You can add a maximum of "
            f"{allocation.remaining} more school"
            f"{'s' if allocation.remaining != 1 else ''} to this project."
        )


# ── Setting allocations ─────────────────────────────────────────────────────
def eligible_staff(project):
    """Staff who may hold an allocation on this project: active CCEOs and
    Programme Leads in the project's country."""
    from apps.accounts.models import StaffProfile
    from apps.projects.services import project_country

    qs = StaffProfile.objects.filter(
        deleted_at__isnull=True,
        user__status="active",
        user__deleted_at__isnull=True,
        user__roles__overlap=list(ELIGIBLE_STAFF_ROLES),
    ).select_related("user")
    country = project_country(project)
    if country:
        qs = qs.filter(country=country)
    return qs.order_by("user__name")


def set_capacity(
    project_id: str,
    staff_id: str,
    max_schools,
    principal,
    *,
    create: bool,
) -> Allocation:
    """Create or change one staff member's allocation on one project."""
    from django.db import IntegrityError, transaction

    from apps.audit.services import log as audit_log
    from apps.projects.authority import directs_project_work

    try:
        maximum = int(str(max_schools).strip())
    except (TypeError, ValueError):
        raise BadRequest("Maximum schools must be a whole number.") from None
    if maximum <= 0:
        raise BadRequest("Maximum schools must be a positive whole number.")

    project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if project is None:
        raise NotFoundError("Project not found.")
    if not directs_project_work(principal, project.id):
        raise Forbidden(
            f"Only {project.name}'s Project Coordinator can set staff school "
            "allocations."
        )
    staff = eligible_staff(project).filter(id=staff_id).first()
    if staff is None:
        raise BadRequest(
            "Choose a CCEO or Programme Lead working in this project's country."
        )

    actor = str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))
    role = getattr(principal, "active_role", "") or ""
    with transaction.atomic():
        existing = (
            ProjectStaffCapacity.objects.select_for_update()
            .filter(project=project, staff=staff)
            .first()
        )
        if create and existing is not None:
            raise BadRequest(
                f"{staff.user.name} already has an allocation of "
                f"{existing.max_schools} schools on {project.name}. Edit that "
                "allocation instead."
            )
        if not create and existing is None:
            raise NotFoundError("That allocation no longer exists.")
        held = ProjectSchoolAssignment.objects.filter(
            project=project, assigned_staff=staff
        ).count()
        if maximum < held:
            raise BadRequest(
                "Capacity cannot be reduced below the current number of "
                f"assigned schools. Current assignment: {held}."
            )
        previous = existing.max_schools if existing else None
        try:
            with transaction.atomic():
                if existing is None:
                    existing = ProjectStaffCapacity.objects.create(
                        project=project,
                        staff=staff,
                        max_schools=maximum,
                        set_by=actor,
                        set_by_role=role,
                    )
                else:
                    existing.max_schools = maximum
                    existing.set_by = actor
                    existing.set_by_role = role
                    existing.save(
                        update_fields=[
                            "max_schools",
                            "set_by",
                            "set_by_role",
                            "updated_at",
                        ]
                    )
        except IntegrityError:
            raise BadRequest(
                f"{staff.user.name} already has an allocation on {project.name}. "
                "Edit that allocation instead."
            ) from None
        if previous != maximum:
            audit_log(
                action=(
                    "project.capacity_created"
                    if previous is None
                    else "project.capacity_changed"
                ),
                subject_kind="Project",
                subject_id=project.id,
                actor_id=getattr(principal, "user_id", None),
                actor_role=role or None,
                payload={
                    "projectId": project.id,
                    "project": project.name,
                    "staffId": staff.id,
                    "staff": staff.user.name,
                    "previous": {"maxSchools": previous},
                    "new": {"maxSchools": maximum},
                    "assigned": held,
                },
            )
    return allocation_for(project.id, staff.id)


# ── Where a school's project work has reached ──────────────────────────────
#: Activity statuses, mapped onto the stages the withdrawal rule names. The
#: activity workflow is the record; this only reads it.
_COMPLETED = {"ia_verified", "accountant_confirmed", "completed", "closed"}
_EVIDENCE = {
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "returned_by_pl",
    "awaiting_ia_verification",
    "returned",
    "returned_by_ia",
}
_STARTED = {"in_progress", "completion_started"}
_NOT_WORK = {"not_planned", "cancelled", "rejected", "deferred"}
_STAGE_ORDER = ("none", "planned", "started", "evidence", "completed")


def _stage_of(status: str, evidence_status: str) -> str:
    if status in _NOT_WORK:
        return "none"
    if status in _COMPLETED:
        return "completed"
    if status in _EVIDENCE or evidence_status in ("uploaded", "accepted"):
        return "evidence"
    if status in _STARTED:
        return "started"
    return "planned"


def school_stages(project_id: str, school_ids) -> dict[str, dict]:
    """Per school: the furthest stage its project work has reached, and how
    many project activities it has planned and completed."""
    from apps.activities.models import Activity

    out: dict[str, dict] = {
        sid: {"stage": "none", "planned": 0, "completed": 0} for sid in school_ids
    }
    if not out:
        return out
    for row in Activity.objects.filter(
        project_id=project_id, school_id__in=list(out), deleted_at__isnull=True
    ).values("school_id", "status", "evidence_status"):
        stage = _stage_of(row["status"] or "", row["evidence_status"] or "")
        if stage == "none":
            continue
        entry = out[row["school_id"]]
        entry["planned"] += 1
        entry["completed"] += int(stage == "completed")
        if _STAGE_ORDER.index(stage) > _STAGE_ORDER.index(entry["stage"]):
            entry["stage"] = stage
    return out


@dataclass(frozen=True)
class WithdrawalBlock:
    code: str
    title: str
    message: str


_BLOCKS = {
    "planned": WithdrawalBlock(
        "planned",
        "Cannot withdraw",
        "This school already has a planned project activity. Remove or resolve "
        "the planned activity before attempting to withdraw the school.",
    ),
    "started": WithdrawalBlock(
        "started",
        "Cannot withdraw",
        "This project activity has already started. The school cannot be "
        "withdrawn from the project.",
    ),
    "evidence": WithdrawalBlock(
        "evidence",
        "Cannot withdraw",
        "Evidence has already been submitted for this project activity.",
    ),
    "completed": WithdrawalBlock(
        "completed",
        "Cannot withdraw",
        "This project has already been completed for this school.",
    ),
    "partner": WithdrawalBlock(
        "partner",
        "Cannot withdraw",
        "This school's project work has been assigned to a partner. Withdraw "
        "or undo that partner assignment first.",
    ),
}


def withdrawal_block(
    project_id: str, school_id: str, *, stage: str | None = None, handed_over=None
) -> WithdrawalBlock | None:
    """Why this school may not leave the project now, or None if it may.

    A school leaves only before its project work begins: nothing planned,
    started, evidenced or completed, and nothing handed to a partner.
    """
    if stage is None:
        stage = school_stages(project_id, [school_id])[school_id]["stage"]
    if stage != "none":
        return _BLOCKS[stage]
    if handed_over is None:
        from apps.partners.models import PartnerAssignment

        handed_over = (
            PartnerAssignment.objects.filter(project_id=project_id, school_id=school_id)
            .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
            .exists()
        )
    if handed_over:
        return _BLOCKS["partner"]
    return None


def partner_held_schools(project_id: str, school_ids) -> set[str]:
    from apps.partners.models import PartnerAssignment

    return set(
        PartnerAssignment.objects.filter(
            project_id=project_id, school_id__in=list(school_ids)
        )
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .values_list("school_id", flat=True)
    )


def withdrawal_reason_text(code: str, other: str = "") -> str:
    labels = dict(WITHDRAWAL_REASONS)
    if code not in labels:
        raise BadRequest("Choose a reason for withdrawing the school.")
    if code == "other":
        other = (other or "").strip()
        if not other:
            raise BadRequest("Say why the school is being withdrawn.")
        return f"Other: {other}"
    return labels[code]


def annotate_allocations(projects, principal):
    """Attach this principal's allocation state to each project, for pages
    offering Add to Project: ``allocation`` (None when it uses nobody's
    places), ``capacity_remaining`` (None when unlimited) and
    ``capacity_block`` (why no school can be added, or "")."""
    projects = list(projects)
    staff_id = consuming_staff_id(principal)
    ids = [p.id for p in projects]
    mine = {a.project_id: a for a in allocations_for_staff(staff_id)} if ids else {}
    managed = (
        set(
            ProjectStaffCapacity.objects.filter(project_id__in=ids).values_list(
                "project_id", flat=True
            )
        )
        if staff_id and ids
        else set()
    )
    for project in projects:
        allocation = mine.get(project.id)
        project.allocation = allocation
        project.capacity_remaining = allocation.remaining if allocation else None
        if allocation is not None and allocation.remaining == 0:
            project.capacity_block = capacity_refusal(allocation, titled=False)
        elif allocation is None and project.id in managed:
            project.capacity_block = (
                f"You have no school allocation for {project.name}. Ask its "
                "Project Coordinator to set one."
            )
            project.capacity_remaining = 0
        else:
            project.capacity_block = ""
    return projects


def withdrawal_blocks(pairs) -> dict[tuple[str, str], WithdrawalBlock | None]:
    """:func:`withdrawal_block` for many enrolments in two queries, keyed by
    ``(project_id, school_id)``, for pages that draw the control per row."""
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment

    pairs = {(str(p), str(s)) for p, s in pairs}
    if not pairs:
        return {}
    project_ids = {p for p, _ in pairs}
    school_ids = {s for _, s in pairs}
    stages = {pair: "none" for pair in pairs}
    for row in Activity.objects.filter(
        project_id__in=project_ids, school_id__in=school_ids, deleted_at__isnull=True
    ).values("project_id", "school_id", "status", "evidence_status"):
        key = (row["project_id"], row["school_id"])
        if key not in stages:
            continue
        stage = _stage_of(row["status"] or "", row["evidence_status"] or "")
        if _STAGE_ORDER.index(stage) > _STAGE_ORDER.index(stages[key]):
            stages[key] = stage
    held = set(
        PartnerAssignment.objects.filter(
            project_id__in=project_ids, school_id__in=school_ids
        )
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .values_list("project_id", "school_id")
    )
    return {
        pair: withdrawal_block(
            pair[0], pair[1], stage=stages[pair], handed_over=pair in held
        )
        for pair in pairs
    }


def allocations_by_project(project_ids) -> dict[str, list[Allocation]]:
    out: dict[str, list[Allocation]] = {}
    for allocation in _allocations(
        ProjectStaffCapacity.objects.filter(project_id__in=list(project_ids))
    ):
        out.setdefault(allocation.project_id, []).append(allocation)
    for rows in out.values():
        rows.sort(key=lambda a: a.staff_name.lower())
    return out


def may_withdraw(principal, assignment) -> bool:
    """Whether this principal may take this enrolment out of its project: the
    staff member whose allocation it uses (or, for an older row, who added
    it), or the project's coordinator (and Admin)."""
    from apps.projects.authority import directs_project_work

    own = getattr(principal, "staff_profile_id", None)
    if own and (
        assignment.assigned_staff_id == own
        or (
            assignment.assigned_staff_id is None
            and assignment.assigned_by in {own, getattr(principal, "user_id", None)}
        )
    ):
        return True
    return directs_project_work(principal, assignment.project_id)
