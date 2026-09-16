"""Transferring school and district portfolio ownership (owner, 2026-09-15).

Admin and Impact Assessment move a school — or every school one person holds
in a district — to another staff member. What this is and is not:

* It moves ``School.account_owner_id`` and the active ``StaffSchoolAssignment``.
  It never changes the school's district, sub-county, parish or village: "a
  staff member owns a school assignment; the staff member does not become the
  school's geographic district".
* Open work does not move silently. The actor chooses: keep each open activity
  with its current owner, or transfer the eligible ones. Verified, confirmed
  and closed activities are never re-owned, whatever is chosen.
* Approved target allocations are never rewritten. Where one depends on the
  portfolio that moved, the transfer is flagged for reconciliation and IA and
  the Programme Lead are told; the figures change only through the governed
  amendment workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

#: Open work a transfer may carry across. Anything verified or beyond is
#: history and keeps the person who did it.
TRANSFERABLE_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "returned",
    "returned_by_pl",
    "returned_by_ia",
    "rescheduled",
)
#: Never re-owned: the record of who did the work and whose money it was.
SETTLED_STATUSES = (
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
)

#: Roles that can hold a school portfolio.
PORTFOLIO_ROLES = ("CCEO", "Program Lead")


@dataclass
class TransferPreview:
    school_id: str = ""
    school_name: str = ""
    district_id: str = ""
    district_name: str = ""
    current_owner_id: str | None = None
    current_owner_name: str = "Unassigned"
    new_owner_id: str = ""
    new_owner_name: str = ""
    school_count: int = 1
    open_activities: int = 0
    scheduled_activities: int = 0
    settled_activities: int = 0
    open_team_actions: int = 0
    partner_assignments: int = 0
    project_memberships: int = 0
    target_allocations: int = 0
    leave_conflicts: int = 0
    warnings: list = None

    def as_dict(self) -> dict:
        data = self.__dict__.copy()
        data["warnings"] = self.warnings or []
        return data


def _actor(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def may_transfer_school(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.SCHOOL_OWNERSHIP_TRANSFER.value)
    )


def may_transfer_district(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.DISTRICT_PORTFOLIO_TRANSFER.value)
    )


def may_transfer_open_activities(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.OPEN_ACTIVITY_TRANSFER.value)
    )


def _owner_ids(staff) -> set[str]:
    """Both id spaces of one staff member — activities carry either."""
    if staff is None:
        return set()
    return {i for i in (staff.id, staff.user_id) if i}


def resolve_staff(staff_id: str):
    from apps.accounts.models import StaffProfile

    if not staff_id:
        return None
    return (
        StaffProfile.objects.select_related("user")
        .filter(Q(id=staff_id) | Q(user_id=staff_id), deleted_at__isnull=True)
        .first()
    )


def current_owner(school):
    return resolve_staff(school.account_owner_id or "")


def _assert_new_owner(staff) -> None:
    if staff is None:
        raise BadRequest("Choose the staff member who will own the school.")
    user = staff.user
    if not user or not user.is_active or user.status != "active":
        raise BadRequest(f"{getattr(user, 'name', 'That account')} is not active.")
    from apps.core.navigation import get_user_role_slug

    roles = set(user.roles or []) | {user.active_role}
    slugs = {
        get_user_role_slug(
            type("P", (), {"is_authenticated": True, "active_role": r})()
        )
        for r in roles
        if r
    }
    if not ({"CCEO", "PL"} & slugs):
        raise BadRequest(
            f"{user.name} is not a field officer or Programme Lead, so they "
            "cannot hold a school portfolio."
        )


def preview_school_transfer(
    school, new_owner=None, *, fy: str | None = None
) -> TransferPreview:
    """What a transfer would touch, for the drawer to show before confirming."""
    from apps.accounts.models import Leave
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning.action_models import ACTIVE_STATES, TeamAction
    from apps.projects.models import ProjectSchoolAssignment

    fy = fy or get_operational_fy()
    owner = current_owner(school)
    activities = Activity.objects.filter(school_id=school.id, deleted_at__isnull=True)
    open_qs = activities.filter(status__in=TRANSFERABLE_STATUSES)
    preview = TransferPreview(
        school_id=school.id,
        school_name=school.name,
        district_id=school.district_id or "",
        district_name=school.district.name if school.district_id else "",
        current_owner_id=owner.id if owner else None,
        current_owner_name=owner.user.name if owner else "Unassigned",
        new_owner_id=new_owner.id if new_owner else "",
        new_owner_name=new_owner.user.name if new_owner else "",
        open_activities=open_qs.count(),
        scheduled_activities=open_qs.filter(
            status__in=("scheduled", "partner_scheduled")
        ).count(),
        settled_activities=activities.filter(status__in=SETTLED_STATUSES).count(),
        partner_assignments=PartnerAssignment.objects.filter(school_id=school.id)
        .exclude(status__in=("returned", "cancelled", "completed"))
        .count(),
        project_memberships=ProjectSchoolAssignment.objects.filter(
            school_id=school.id
        ).count(),
        open_team_actions=TeamAction.objects.filter(
            school_id=school.id, state__in=ACTIVE_STATES
        ).count()
        if hasattr(TeamAction, "school_id")
        else 0,
        warnings=[],
    )
    preview.target_allocations = (
        _portfolio_allocations(owner, fy).count() if owner else 0
    )
    if preview.target_allocations:
        preview.warnings.append(
            "Approved target allocations depend on this portfolio. They are not "
            "rewritten: the transfer is flagged for reconciliation."
        )
    if new_owner is not None:
        # Leave dates are stored as text (a legacy convention on this model),
        # so the comparison is made on the ISO string.
        preview.leave_conflicts = Leave.objects.filter(
            staff=new_owner,
            status="approved",
            end_date__gte=timezone.localdate().isoformat(),
        ).count()
        if preview.leave_conflicts:
            preview.warnings.append(
                f"{new_owner.user.name} has approved leave coming up; check "
                "coverage for the work moving to them."
            )
    return preview


def _portfolio_allocations(staff, fy: str):
    """Approved allocations whose denominator is this person's portfolio."""
    from apps.hr.models import MilestoneAllocation

    if staff is None:
        from apps.hr.models import MilestoneAllocation as _M

        return _M.objects.none()
    return MilestoneAllocation.objects.filter(
        employee=staff,
        status__in=("approved", "confirmed", "locked"),
        milestone__priority__cycle__financial_year=str(fy),
    )


@transaction.atomic
def transfer_school_owner(school_id: str, data: dict, principal, *, batch=None):
    """Move one school's portfolio ownership. Geography is untouched."""
    from apps.accounts.models import StaffSchoolAssignment
    from apps.schools.models import School, SchoolOwnershipTransfer
    from apps.schools.ownership_models import OpenActivityDecision, TargetReconciliation

    if not may_transfer_school(principal):
        raise Forbidden(
            "Only an Admin or Impact Assessment can reassign school ownership."
        )
    school = (
        School.objects
        # Lock the school row only: `district` is nullable, and locking across
        # that outer join is not something Postgres allows.
        .select_for_update(of=("self",))
        .select_related("district")
        .filter(Q(id=school_id) | Q(school_id=school_id), deleted_at__isnull=True)
        .first()
    )
    if school is None:
        raise NotFoundError("School not found.")
    new_owner = resolve_staff((data.get("newOwnerId") or "").strip())
    _assert_new_owner(new_owner)
    old_owner = current_owner(school)
    if old_owner and old_owner.id == new_owner.id:
        raise BadRequest(f"{school.name} already belongs to {new_owner.user.name}.")
    reason = (data.get("reason") or "").strip()
    if len(reason) < 5:
        raise BadRequest("Give the reason for the transfer.")
    effective = data.get("effectiveDate") or timezone.localdate()
    if isinstance(effective, str):
        try:
            effective = date.fromisoformat(effective)
        except ValueError:
            raise BadRequest("Enter the effective date as a calendar date.") from None
    decision = (
        OpenActivityDecision.TRANSFER
        if (data.get("openActivityDecision") or "") == OpenActivityDecision.TRANSFER
        else OpenActivityDecision.KEEP
    )
    if decision == OpenActivityDecision.TRANSFER and not may_transfer_open_activities(
        principal
    ):
        raise Forbidden("You may not transfer open activities with the school.")

    fy = get_operational_fy()
    allocations = list(_portfolio_allocations(old_owner, fy)) if old_owner else []

    # ── The school record and the portfolio assignment ────────────────────
    previous = {
        "ownerStaffId": old_owner.id if old_owner else None,
        "ownerName": school.account_owner_name_raw,
        "districtId": school.district_id,
    }
    school.account_owner_id = new_owner.id
    school.account_owner_name_raw = new_owner.user.name
    school.account_owner_status = "matched"
    school.save(
        update_fields=[
            "account_owner_id",
            "account_owner_name_raw",
            "account_owner_status",
            "updated_at",
        ]
    )
    StaffSchoolAssignment.objects.filter(school_id=school.id).exclude(
        staff_id=new_owner.id
    ).delete()
    StaffSchoolAssignment.objects.get_or_create(
        school_id=school.id, staff_id=new_owner.id
    )

    transferred, kept = _move_open_activities(
        school, old_owner, new_owner, decision, principal
    )

    record = SchoolOwnershipTransfer.objects.create(
        school=school,
        from_staff=old_owner,
        to_staff=new_owner,
        effective_date=effective,
        reason=reason,
        open_activity_decision=decision,
        transferred_activity_ids=transferred,
        kept_activity_ids=kept,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", "") or "",
        correlation_id=_correlation_id(),
        batch=batch,
        target_reconciliation_status=(
            TargetReconciliation.REQUIRED
            if allocations
            else TargetReconciliation.NOT_REQUIRED
        ),
        target_reconciliation_note=(
            f"{len(allocations)} approved FY{fy} allocation(s) counted this "
            "portfolio. Reconcile through the amendment workflow."
            if allocations
            else ""
        ),
    )

    from apps.audit.services import log as audit_log

    audit_log(
        action="school.owner_transferred",
        subject_kind="school",
        subject_id=school.id,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "previous": previous,
            "new": {
                "ownerStaffId": new_owner.id,
                "ownerName": new_owner.user.name,
                # Geography is deliberately unchanged, and the audit says so.
                "districtId": school.district_id,
            },
            "effectiveDate": effective.isoformat(),
            "openActivityDecision": decision,
            "transferredActivityIds": transferred,
            "targetReconciliation": record.target_reconciliation_status,
        },
    )
    if transferred:
        audit_log(
            action="activity.ownership_transferred",
            subject_kind="school",
            subject_id=school.id,
            actor_id=_actor(principal),
            actor_role=getattr(principal, "active_role", None),
            reason=reason,
            payload={
                "previous": {"ownerStaffId": old_owner.id if old_owner else None},
                "new": {"ownerStaffId": new_owner.id},
                "activityIds": transferred,
            },
        )
    transaction.on_commit(lambda: _notify_school_transfer(record.id))
    return record


def _correlation_id() -> str:
    try:
        from apps.core.request_context import get_correlation_id

        value = get_correlation_id()
        return "" if value == "unknown" else value
    except Exception:  # noqa: BLE001
        return ""


def _move_open_activities(school, old_owner, new_owner, decision, principal):
    """Carry the eligible open work across, or leave every bit of it."""
    from apps.activities.models import Activity
    from apps.schools.ownership_models import OpenActivityDecision

    open_qs = Activity.objects.filter(
        school_id=school.id,
        deleted_at__isnull=True,
        status__in=TRANSFERABLE_STATUSES,
    )
    if decision != OpenActivityDecision.TRANSFER:
        return [], list(open_qs.values_list("id", flat=True))

    old_ids = _owner_ids(old_owner)
    moved: list[str] = []
    for activity in open_qs.select_for_update():
        if old_ids and activity.responsible_staff_id not in old_ids:
            # Somebody else's work that happens to sit at this school — a
            # country role's approved visit, say. It keeps its owner.
            continue
        activity.responsible_staff_id = new_owner.id
        activity.save(update_fields=["responsible_staff_id", "updated_at"])
        moved.append(activity.id)
        # Re-owning work re-owns its money: the cost lines carry the
        # responsible user and the weekly/monthly drafts are per owner.
        if activity.scheduled_date:
            from apps.activities.services import _apply_schedule_cost_snapshot

            try:
                _apply_schedule_cost_snapshot(activity, {}, principal=principal)
            except Exception:  # noqa: BLE001 - re-pricing never loses the move
                import logging

                logging.getLogger(__name__).warning(
                    "cost re-snapshot failed for %s", activity.id, exc_info=True
                )
    kept = [
        aid for aid in open_qs.values_list("id", flat=True) if aid not in set(moved)
    ]
    return moved, kept


def _notify_school_transfer(record_id: str) -> None:
    """Tell the old owner, the new owner and their supervisors; ask IA and the
    Programme Lead to reconcile targets when one is affected."""
    import logging

    try:
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.notifications.services import WorkflowNotificationService
        from apps.schools.models import SchoolOwnershipTransfer
        from apps.schools.ownership_models import TargetReconciliation

        record = (
            SchoolOwnershipTransfer.objects.select_related(
                "school", "from_staff__user", "to_staff__user"
            )
            .filter(id=record_id)
            .first()
        )
        if record is None:
            return
        school = record.school
        recipients = []
        for staff in (record.from_staff, record.to_staff):
            if staff and staff.user_id and staff.user_id != record.actor_id:
                recipients.append(staff.user_id)
        supervisors = list(
            StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=[
                    s.id for s in (record.from_staff, record.to_staff) if s
                ]
            ).values_list("supervisor__user_id", flat=True)
        )
        recipients += [s for s in supervisors if s and s != record.actor_id]
        if recipients:
            WorkflowNotificationService.trigger(
                event_type="school_ownership_transferred",
                category="portfolio",
                priority="high",
                title="School ownership transferred",
                body=(
                    f"{school.name} moved to {record.to_staff.user.name}"
                    + (
                        f" from {record.from_staff.user.name}"
                        if record.from_staff
                        else ""
                    )
                    + f". {record.reason}"
                ),
                context_type="School",
                context_id=school.id,
                recipients=list(dict.fromkeys(recipients)),
            )
        if record.target_reconciliation_status == TargetReconciliation.REQUIRED:
            _notify_target_reconciliation(record)
    except Exception:  # noqa: BLE001 - a notice never undoes a transfer
        logging.getLogger(__name__).warning(
            "ownership transfer notification failed for %s", record_id, exc_info=True
        )


def _notify_target_reconciliation(record) -> None:
    from apps.notifications.services import WorkflowNotificationService, role_recipients

    recipients = role_recipients("ImpactAssessment") + role_recipients("Program Lead")
    if not recipients:
        return
    WorkflowNotificationService.trigger(
        event_type="target_reconciliation_required",
        category="targets",
        priority="high",
        title="Target Reconciliation Required",
        body=(
            f"{record.school.name} moved to {record.to_staff.user.name}. "
            f"{record.target_reconciliation_note}"
        ),
        context_type="school_ownership_transfer",
        context_id=record.id,
        recipients=recipients,
    )


@transaction.atomic
def transfer_district_portfolio(district_id: str, data: dict, principal):
    """Move every school one person holds in a district to another person."""
    from apps.geography.models import District
    from apps.schools.models import DistrictPortfolioTransfer, School
    from apps.schools.ownership_models import OpenActivityDecision, TargetReconciliation

    if not may_transfer_district(principal):
        raise Forbidden(
            "Only an Admin or Impact Assessment can transfer a district portfolio."
        )
    district = District.objects.filter(id=district_id).first()
    if district is None:
        raise NotFoundError("District not found.")
    from_staff = resolve_staff((data.get("fromStaffId") or "").strip())
    new_owner = resolve_staff((data.get("newOwnerId") or "").strip())
    _assert_new_owner(new_owner)
    if from_staff is None:
        raise BadRequest("Choose the staff member whose district portfolio moves.")
    if from_staff.id == new_owner.id:
        raise BadRequest("Choose a different staff member to receive the portfolio.")
    reason = (data.get("reason") or "").strip()
    if len(reason) < 5:
        raise BadRequest("Give the reason for the transfer.")
    effective = data.get("effectiveDate") or timezone.localdate()
    if isinstance(effective, str):
        try:
            effective = date.fromisoformat(effective)
        except ValueError:
            raise BadRequest("Enter the effective date as a calendar date.") from None
    decision = (
        OpenActivityDecision.TRANSFER
        if (data.get("openActivityDecision") or "") == OpenActivityDecision.TRANSFER
        else OpenActivityDecision.KEEP
    )

    schools = list(
        School.objects.filter(
            district_id=district.id,
            deleted_at__isnull=True,
            account_owner_id__in=list(_owner_ids(from_staff)),
        )
    )
    if not schools:
        raise BadRequest(f"{from_staff.user.name} holds no school in {district.name}.")

    batch = DistrictPortfolioTransfer.objects.create(
        district=district,
        from_staff=from_staff,
        to_staff=new_owner,
        effective_date=effective,
        reason=reason,
        open_activity_decision=decision,
        school_count=len(schools),
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", "") or "",
        correlation_id=_correlation_id(),
        preview=preview_district_transfer(district, from_staff, new_owner).as_dict(),
    )
    moved = 0
    flagged = False
    for school in schools:
        record = transfer_school_owner(
            school.id,
            {
                "newOwnerId": new_owner.id,
                "reason": reason,
                "effectiveDate": effective,
                "openActivityDecision": decision,
            },
            principal,
            batch=batch,
        )
        moved += len(record.transferred_activity_ids or [])
        flagged = flagged or record.target_reconciliation_status == (
            TargetReconciliation.REQUIRED
        )
    batch.activities_transferred = moved
    batch.target_reconciliation_status = (
        TargetReconciliation.REQUIRED if flagged else TargetReconciliation.NOT_REQUIRED
    )
    batch.save(
        update_fields=[
            "activities_transferred",
            "target_reconciliation_status",
            "updated_at",
        ]
    )

    from apps.audit.services import log as audit_log

    audit_log(
        action="district.portfolio_transferred",
        subject_kind="district",
        subject_id=district.id,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "previous": {
                "ownerStaffId": from_staff.id,
                "ownerName": from_staff.user.name,
            },
            "new": {"ownerStaffId": new_owner.id, "ownerName": new_owner.user.name},
            "schools": len(schools),
            "activitiesTransferred": moved,
            "effectiveDate": effective.isoformat(),
        },
    )
    transaction.on_commit(lambda: _notify_district_transfer(batch.id))
    return batch


def preview_district_transfer(district, from_staff, new_owner=None) -> TransferPreview:
    """The numbers a district transfer would touch, before confirming."""
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.projects.models import ProjectSchoolAssignment
    from apps.schools.models import School

    fy = get_operational_fy()
    school_ids = list(
        School.objects.filter(
            district_id=district.id,
            deleted_at__isnull=True,
            account_owner_id__in=list(_owner_ids(from_staff)),
        ).values_list("id", flat=True)
    )
    activities = Activity.objects.filter(
        school_id__in=school_ids, deleted_at__isnull=True
    )
    preview = TransferPreview(
        district_id=district.id,
        district_name=district.name,
        current_owner_id=from_staff.id if from_staff else None,
        current_owner_name=from_staff.user.name if from_staff else "Unassigned",
        new_owner_id=new_owner.id if new_owner else "",
        new_owner_name=new_owner.user.name if new_owner else "",
        school_count=len(school_ids),
        open_activities=activities.filter(status__in=TRANSFERABLE_STATUSES).count(),
        scheduled_activities=activities.filter(
            status__in=("scheduled", "partner_scheduled")
        ).count(),
        settled_activities=activities.filter(status__in=SETTLED_STATUSES).count(),
        partner_assignments=PartnerAssignment.objects.filter(school_id__in=school_ids)
        .exclude(status__in=("returned", "cancelled", "completed"))
        .count(),
        project_memberships=ProjectSchoolAssignment.objects.filter(
            school_id__in=school_ids
        ).count(),
        warnings=[],
    )
    preview.target_allocations = (
        _portfolio_allocations(from_staff, fy).count() if from_staff else 0
    )
    if preview.target_allocations:
        preview.warnings.append(
            "Approved target allocations counted this portfolio. They are not "
            "rewritten: the transfer is flagged for reconciliation."
        )
    from apps.planning.action_models import ACTIVE_STATES, TeamAction

    if hasattr(TeamAction, "school_id"):
        preview.open_team_actions = TeamAction.objects.filter(
            school_id__in=school_ids, state__in=ACTIVE_STATES
        ).count()
    return preview


def _notify_district_transfer(batch_id: str) -> None:
    import logging

    try:
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.notifications.services import WorkflowNotificationService
        from apps.schools.models import DistrictPortfolioTransfer

        batch = (
            DistrictPortfolioTransfer.objects.select_related(
                "district", "from_staff__user", "to_staff__user"
            )
            .filter(id=batch_id)
            .first()
        )
        if batch is None:
            return
        recipients = [
            staff.user_id
            for staff in (batch.from_staff, batch.to_staff)
            if staff and staff.user_id and staff.user_id != batch.actor_id
        ]
        recipients += [
            s
            for s in StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=[
                    staff.id for staff in (batch.from_staff, batch.to_staff) if staff
                ]
            ).values_list("supervisor__user_id", flat=True)
            if s and s != batch.actor_id
        ]
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type="district_portfolio_transferred",
            category="portfolio",
            priority="high",
            title="District portfolio transferred",
            body=(
                f"{batch.school_count} school(s) in {batch.district.name} moved to "
                f"{batch.to_staff.user.name}. {batch.reason}"
            ),
            context_type="district",
            context_id=batch.district_id,
            recipients=list(dict.fromkeys(recipients)),
        )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "district transfer notification failed for %s", batch_id, exc_info=True
        )


@transaction.atomic
def resolve_target_reconciliation(transfer_id: str, principal, *, note: str):
    """Record that the affected allocations have been reconciled."""
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.schools.models import SchoolOwnershipTransfer
    from apps.schools.ownership_models import TargetReconciliation

    if not (
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.MILESTONES_ALLOCATE.value)
    ):
        raise Forbidden("Only the roles that allocate targets can reconcile them.")
    note = (note or "").strip()
    if not note:
        raise BadRequest("Say how the targets were reconciled.")
    record = (
        SchoolOwnershipTransfer.objects.select_for_update()
        .filter(id=transfer_id)
        .first()
    )
    if record is None:
        raise NotFoundError("Transfer not found.")
    record.target_reconciliation_status = TargetReconciliation.RESOLVED
    record.target_reconciliation_note = note
    record.target_reconciliation_resolved_by = _actor(principal)
    record.target_reconciliation_resolved_at = timezone.now()
    record.save(
        update_fields=[
            "target_reconciliation_status",
            "target_reconciliation_note",
            "target_reconciliation_resolved_by",
            "target_reconciliation_resolved_at",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log
    from apps.notifications.services import resolve_condition

    audit_log(
        action="targets.reconciliation_resolved",
        subject_kind="school_ownership_transfer",
        subject_id=record.id,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=note,
        payload={
            "previous": {"status": "required"},
            "new": {"status": "resolved"},
            "schoolId": record.school_id,
        },
    )
    resolve_condition(
        "target_reconciliation_required", "school_ownership_transfer", record.id
    )
    return record


__all__ = [
    "PORTFOLIO_ROLES",
    "SETTLED_STATUSES",
    "TRANSFERABLE_STATUSES",
    "TransferPreview",
    "current_owner",
    "may_transfer_district",
    "may_transfer_open_activities",
    "may_transfer_school",
    "preview_district_transfer",
    "preview_school_transfer",
    "resolve_staff",
    "resolve_target_reconciliation",
    "transfer_district_portfolio",
    "transfer_school_owner",
]
