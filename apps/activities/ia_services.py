from django.db import transaction
from django.utils import timezone
from apps.activities.models import (
    Activity,
    IAVerification,
    VerificationChecklist,
    VerificationComment,
    VerificationDecision,
    ReturnedReason,
    DuplicateActivity,
    VerificationHistory,
)
from apps.core.enums import (
    ActivityStatus,
    VerificationStatus,
    EvidenceStatus,
    PaymentStatus,
)
from apps.core.exceptions import BadRequest


class EvidenceValidationService:
    """Validates presence and quality of uploaded evidence records."""

    @staticmethod
    def validate_evidence(activity: Activity) -> tuple[bool, str]:
        from apps.evidence.models import EvidenceRecord

        evidence = EvidenceRecord.objects.filter(
            activity_id=activity.id, quarantined=False
        )
        if not evidence.exists():
            return False, "Evidence missing: No evidence records uploaded."

        # Check if any evidence is in returned or rejected status
        rejected = evidence.filter(
            status__in=[EvidenceStatus.RETURNED, EvidenceStatus.REJECTED]
        )
        if rejected.exists():
            return (
                False,
                f"Evidence returned/rejected: {rejected.count()} file(s) require correction.",
            )

        return True, "Evidence exists and is accepted."


class AttendanceValidationService:
    """Validates teacher/leader/participant headcount for training and meetings."""

    @staticmethod
    def validate_attendance(activity: Activity) -> tuple[bool, str]:
        # Check if activity type is training or meeting-like
        from apps.activities.services import sf_kind

        kind = sf_kind(activity.activity_type)

        if kind == "training":
            teachers = activity.teachers_attended or 0
            leaders = activity.leaders_attended or 0
            other = activity.other_participants or 0

            if teachers + leaders + other == 0:
                return (
                    False,
                    "Attendance missing: Participant headcount must be greater than zero.",
                )
            return (
                True,
                f"Attendance valid: {teachers + leaders + other} participants recorded.",
            )

        return True, "Attendance check not applicable for this activity type."


class SSAValidationService:
    """Validates that a School Self-Assessment (SSA) is completed for the school."""

    @staticmethod
    def validate_ssa(activity: Activity) -> tuple[bool, str]:
        if not activity.ssa_collection_expected:
            return True, "SSA check not applicable (no SSA expected)."

        if not activity.school:
            return False, "SSA missing: No school associated with the activity."

        from apps.ssa.models import SsaRecord

        latest_ssa = (
            SsaRecord.objects.filter(school=activity.school, deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )

        if not latest_ssa:
            return (
                False,
                "SSA missing: No baseline or assessment recorded for this school.",
            )

        # Check if it was uploaded/completed
        return True, f"SSA uploaded: Baseline score is {latest_ssa.average_score}."


class DuplicateDetectionService:
    """Scans for potential duplicates by school/date/staff/type, Salesforce ID, or evidence files."""

    @staticmethod
    def detect_duplicates(activity: Activity) -> list[dict]:
        duplicates = []

        # 1. School, date, staff, and type match
        if activity.school and activity.planned_date:
            qs1 = Activity.objects.filter(
                deleted_at__isnull=True,
                school=activity.school,
                planned_date=activity.planned_date,
                responsible_staff_id=activity.responsible_staff_id,
                activity_type=activity.activity_type,
            ).exclude(id=activity.id)
            for dup in qs1:
                duplicates.append(
                    {
                        "activity": dup,
                        "reason": f"Same School, Date ({activity.planned_date}), Staff, and Activity Type",
                    }
                )

        # 2. Salesforce ID match
        if activity.salesforce_activity_id:
            qs2 = Activity.objects.filter(
                deleted_at__isnull=True,
                salesforce_activity_id=activity.salesforce_activity_id,
            ).exclude(id=activity.id)
            for dup in qs2:
                duplicates.append(
                    {
                        "activity": dup,
                        "reason": f"Same Salesforce Activity ID ({activity.salesforce_activity_id})",
                    }
                )

        # 3. Same Evidence files (filename + size match)
        from apps.evidence.models import EvidenceRecord

        my_evs = EvidenceRecord.objects.filter(activity_id=activity.id)
        for ev in my_evs:
            qs3 = (
                EvidenceRecord.objects.filter(
                    original_name=ev.original_name, file_size=ev.file_size
                )
                .exclude(activity_id=activity.id)
                .select_related("activity")
            )
            for dup_ev in qs3:
                if dup_ev.activity and dup_ev.activity.deleted_at is None:
                    duplicates.append(
                        {
                            "activity": dup_ev.activity,
                            "reason": f"Duplicate evidence file: '{ev.original_name}'",
                        }
                    )

        return duplicates

    @staticmethod
    def run_and_log_duplicates(activity: Activity) -> bool:
        """Finds duplicates and logs them to DuplicateActivity table."""
        dups = DuplicateDetectionService.detect_duplicates(activity)
        with transaction.atomic():
            # Clear old flags for this activity
            DuplicateActivity.objects.filter(activity=activity).delete()
            for d in dups:
                DuplicateActivity.objects.create(
                    activity=activity,
                    duplicate_of=d["activity"],
                    reason=d["reason"],
                    status="potential",
                )
        return len(dups) == 0


class AnalyticsPublishingService:
    """Updates and triggers downstream analytics metrics recalculations."""

    @staticmethod
    def publish_analytics(activity: Activity):
        # In this codebase, analytics calculate dynamically based on activities status.
        # This service can trigger invalidations of analytical caches or update summary statistics if cached.
        pass


class AccountsRoutingService:
    """Routes IA verified activities automatically to the Accounts Queue."""

    @staticmethod
    def route_to_accounts(activity: Activity):
        with transaction.atomic():
            if activity.delivery_type == "partner":
                activity.payment_status = PaymentStatus.IA_CONFIRMED
            else:
                # Staff-delivered activities are funded via WeeklyFundRequests.
                # Mark payment status as pending or clearance pending.
                activity.payment_status = PaymentStatus.PENDING_IA
            activity.save(update_fields=["payment_status"])


class ActivityReturnService:
    """Handles returning activity to the owner's My Plan under Needs Correction."""

    @staticmethod
    def return_activity(
        activity: Activity, reasons: list[str], comment: str, actor_id: str
    ) -> dict:
        # Guard against a stale tab, a replayed POST, or a second IA staffer
        # racing the same queue: only an activity actually awaiting IA
        # verification may be returned. Without this, an already-closed,
        # cancelled, or otherwise-progressed activity could be silently
        # knocked back to "returned_by_ia".
        if activity.status != ActivityStatus.AWAITING_IA_VERIFICATION:
            raise BadRequest("Activity is not awaiting IA verification")
        with transaction.atomic():
            activity.status = ActivityStatus.RETURNED_BY_IA
            activity.ia_verification_status = VerificationStatus.RETURNED
            activity.save(
                update_fields=["status", "ia_verification_status", "updated_at"]
            )

            # Setup IAVerification record if not exists
            verification, _ = IAVerification.objects.get_or_create(
                activity=activity, defaults={"status": VerificationStatus.RETURNED}
            )
            verification.status = VerificationStatus.RETURNED
            verification.save(update_fields=["status"])

            # Record decision
            VerificationDecision.objects.create(
                verification=verification,
                decision="RETURN",
                decided_by=actor_id,
                comments=comment,
            )

            # Save return reasons
            ReturnedReason.objects.filter(verification=verification).delete()
            for reason in reasons:
                ReturnedReason.objects.create(verification=verification, reason=reason)

            # Log comment if any
            if comment:
                VerificationComment.objects.create(
                    verification=verification, comment=comment, created_by=actor_id
                )

            # Notify staff
            from apps.notifications.services import WorkflowNotificationService

            # Resolve recipient
            recipient = activity.responsible_staff_id
            if recipient:
                WorkflowNotificationService.trigger(
                    event_type="evidence_returned",
                    category="ia",
                    priority="high",
                    title="Activity Returned by IA",
                    body=f"Activity '{activity.activity_type}' at '{activity.school.name if activity.school else ''}' needs correction. Reason: {', '.join(reasons)}",
                    context_type="Activity",
                    context_id=activity.id,
                    recipients=[recipient],
                )

            from apps.activities.services import _serialize

            return _serialize(activity)


class ActivityCertificationService:
    """Certifies activity as official, updating status and triggering downstream integrations."""

    @staticmethod
    def certify_activity(
        activity: Activity, checklist_data: dict, actor_id: str
    ) -> dict:
        # Same race/replay guard as ActivityReturnService.return_activity:
        # only an activity actually awaiting IA verification may be
        # certified, so a stale tab or two IA staffers on the same queue
        # cannot double-certify or certify a closed/cancelled activity.
        if activity.status != ActivityStatus.AWAITING_IA_VERIFICATION:
            raise BadRequest("Activity is not awaiting IA verification")
        with transaction.atomic():
            activity.status = ActivityStatus.IA_VERIFIED
            activity.ia_verification_status = VerificationStatus.CONFIRMED
            activity.ia_confirmed_at = timezone.now()
            activity.ia_confirmed_by = actor_id
            # Payment path: partner activities enter the payment queue —
            # same rule as apps.activities.services.ia_confirm(); this live
            # UI path previously omitted it, leaving verified partner
            # activities stuck at payment_status="none" and invisible to
            # the Accountant's partner-payments queue.
            if activity.delivery_type == "partner":
                activity.payment_status = PaymentStatus.IA_CONFIRMED
            activity.save(
                update_fields=[
                    "status",
                    "ia_verification_status",
                    "ia_confirmed_at",
                    "ia_confirmed_by",
                    "payment_status",
                    "updated_at",
                ]
            )

            # Setup IAVerification record
            verification, _ = IAVerification.objects.get_or_create(
                activity=activity, defaults={"status": VerificationStatus.CONFIRMED}
            )
            verification.status = VerificationStatus.CONFIRMED
            verification.verified_by = actor_id
            verification.verified_at = timezone.now()
            verification.save(update_fields=["status", "verified_by", "verified_at"])

            # Save Checklist
            VerificationChecklist.objects.update_or_create(
                verification=verification,
                defaults={
                    "evidence_exists": checklist_data.get("evidence_exists", False),
                    "attendance_valid": checklist_data.get("attendance_valid", False),
                    "ssa_uploaded": checklist_data.get("ssa_uploaded", False),
                    "correct_school": checklist_data.get("correct_school", False),
                    "correct_cluster": checklist_data.get("correct_cluster", False),
                    "correct_intervention": checklist_data.get(
                        "correct_intervention", False
                    ),
                    "sf_id_entered": checklist_data.get("sf_id_entered", False),
                    "duplicate_check_passed": checklist_data.get(
                        "duplicate_check_passed", False
                    ),
                    "analytics_ready": checklist_data.get("analytics_ready", False),
                },
            )

            # Record decision
            VerificationDecision.objects.create(
                verification=verification,
                decision="APPROVE",
                decided_by=actor_id,
                comments="Checklist verified successfully.",
            )

            # Write History
            VerificationHistory.objects.create(
                activity=activity,
                verified_by=actor_id,
                verified_at=timezone.now(),
                analytics_included=True,
            )

            # Route to Accounts automatically
            AccountsRoutingService.route_to_accounts(activity)

            # Publish Analytics updates
            AnalyticsPublishingService.publish_analytics(activity)

            from apps.activities.services import _serialize

            return _serialize(activity)


class VerificationTimelineService:
    """Reconstructs the full lifecycle timeline audit trail of an activity."""

    @staticmethod
    def get_timeline(activity: Activity) -> list[dict]:
        from apps.audit.models import AuditLog

        logs = AuditLog.objects.filter(
            subject_kind="Activity", subject_id=str(activity.id)
        ).order_by("created_at")

        timeline = []

        # We can map specific AuditLog actions to timeline states.
        # If there are no audit logs yet, we can infer from activity states.

        # Add basic scheduling state
        timeline.append(
            {
                "state": "Scheduled",
                "date": activity.created_at,
                "actor": "System / Planner",
                "details": f"Planned for {activity.planned_date or 'N/A'}",
            }
        )

        # Loop through audit logs
        for log in logs:
            state = None
            details = log.reason or ""

            if log.action == "create_activity":
                state = "Moved to My Plan"
                details = "Activity initialized in My Plan queue"
            elif log.action == "start_completion":
                state = "Started"
                details = "Field execution started"
            elif log.action == "complete_activity":
                state = "Completed"
                details = "CCEO finished field work"
            elif log.action == "evidence_upload":
                state = "Evidence Uploaded"
                details = "Evidence documentation uploaded"
            elif log.action == "salesforce_id_action":
                state = "Activity SF ID Entered"
                details = f"Linked to Salesforce ID: {log.payload.get('salesforceId') if log.payload else ''}"
            elif log.action == "submit_for_review":
                state = "Submitted"
                details = "Submitted for PL/IA approval"
            elif log.action == "ia_return_completion":
                state = "Returned"
                details = f"Returned by IA. Reason: {log.payload.get('reason') if log.payload else ''}"
            elif log.action == "pl_return_completion":
                state = "Returned"
                details = f"Returned by PL. Reason: {log.payload.get('reason') if log.payload else ''}"
            elif log.action == "ia_verify_completion":
                state = "Verified"
                details = "IA Verified & certified as official"
            elif (
                log.action == "clear_partner_payment"
                or log.action == "confirm_accountability"
            ):
                state = "Accounts"
                details = "Finance Clearance approved"

            if state:
                timeline.append(
                    {
                        "state": state,
                        "date": log.created_at,
                        "actor": f"{log.actor_role or 'User'} ({log.actor_id or ''})",
                        "details": details,
                    }
                )

        # If terminal status, make sure it is reflected
        if (
            activity.status == ActivityStatus.CLOSED
            or activity.status == ActivityStatus.COMPLETED
        ):
            # Check if Accounts event is already there, if not add it
            if not any(item["state"] == "Closed" for item in timeline):
                timeline.append(
                    {
                        "state": "Closed",
                        "date": activity.updated_at,
                        "actor": "Program Accountant",
                        "details": "Activity closed and archived",
                    }
                )

        return timeline


class IAVerificationService:
    """High-level service class coordinating all IA verification workspace requests."""

    @staticmethod
    def get_verification_checks(activity: Activity) -> dict:
        """Runs the validation rules to compute checklist recommendations."""
        ev_ok, ev_desc = EvidenceValidationService.validate_evidence(activity)
        att_ok, att_desc = AttendanceValidationService.validate_attendance(activity)
        ssa_ok, ssa_desc = SSAValidationService.validate_ssa(activity)

        dups = DuplicateDetectionService.detect_duplicates(activity)
        dup_ok = len(dups) == 0

        sf_ok = bool(activity.salesforce_activity_id)

        # Prepopulate recommendation states
        return {
            "evidence_exists": ev_ok,
            "evidence_desc": ev_desc,
            "attendance_valid": att_ok,
            "attendance_desc": att_desc,
            "ssa_uploaded": ssa_ok,
            "ssa_desc": ssa_desc,
            "correct_school": bool(activity.school),
            "correct_cluster": bool(activity.cluster),
            "correct_intervention": bool(activity.focus_intervention),
            "sf_id_entered": sf_ok,
            "duplicate_check_passed": dup_ok,
            "duplicate_count": len(dups),
            "duplicates": dups,
            "analytics_ready": ev_ok and att_ok and ssa_ok and sf_ok and dup_ok,
        }
