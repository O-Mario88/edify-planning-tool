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

        # Confirmed records only -- an unverified upload must never satisfy a
        # verification gate (apps.ssa.services.latest_applicable_record).
        from apps.ssa.services import latest_applicable_record

        latest_ssa = latest_applicable_record(activity.school)

        if not latest_ssa:
            return (
                False,
                "SSA Required: no confirmed assessment score is recorded for "
                "this school.",
            )

        # Check if it was uploaded/completed
        return True, f"SSA uploaded: average score is {latest_ssa.average_score}."


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


class DuplicateReviewService:
    """Own the IA duplicate-review state machine and its audit trail."""

    @staticmethod
    def decide(duplicate_id: str, action: str, actor) -> DuplicateActivity:
        targets = {"ignore": "ignored", "flag": "flagged", "return": "resolved"}
        if action not in targets:
            raise BadRequest("Select a valid duplicate-review action.")

        with transaction.atomic():
            duplicate = (
                DuplicateActivity.objects.select_for_update()
                .select_related("activity")
                .filter(id=duplicate_id)
                .first()
            )
            if not duplicate:
                raise BadRequest("Duplicate flag not found.")
            if duplicate.status != "potential":
                raise BadRequest(f"This duplicate flag is already {duplicate.status}.")
            if action == "return":
                ActivityReturnService.return_activity(
                    duplicate.activity,
                    ["Duplicate Activity"],
                    f"Flagged as duplicate of Activity ID {duplicate.duplicate_of_id}.",
                    actor.user_id,
                )
            duplicate.status = targets[action]
            duplicate.save(update_fields=["status", "updated_at"])

            from apps.audit.services import log as audit_log

            audit_log(
                action=f"ia.duplicate_{action}",
                subject_kind="duplicate_activity",
                subject_id=duplicate.id,
                actor_id=actor.id,
                actor_role=getattr(actor, "active_role", None),
                payload={
                    "activityId": duplicate.activity_id,
                    "duplicateOfId": duplicate.duplicate_of_id,
                },
            )
        return duplicate


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
        # racing the same queue. The check outside the transaction is the
        # cheap early exit; the one that decides anything is the re-check
        # below, on a row re-fetched under select_for_update. A status read
        # from the instance the caller happened to be holding is a comment,
        # not a guard — two staffers who both loaded the queue see AWAITING
        # in memory simultaneously, and the race test proved both were then
        # told their action succeeded.
        if activity.status != ActivityStatus.AWAITING_IA_VERIFICATION:
            raise BadRequest("Activity is not awaiting IA verification")
        with transaction.atomic():
            activity = (
                Activity.objects.select_for_update().filter(id=activity.id).first()
            )
            if (
                activity is None
                or activity.status != ActivityStatus.AWAITING_IA_VERIFICATION
            ):
                raise BadRequest("Activity is not awaiting IA verification")
            activity.status = ActivityStatus.RETURNED_BY_IA
            activity.ia_verification_status = VerificationStatus.RETURNED
            activity.save(
                update_fields=["status", "ia_verification_status", "updated_at"]
            )
            # A returned activity is no longer verified work: its milestone
            # credit reverses with it — the same rule services.ia_return
            # applies; this UI path previously left credits standing.
            from apps.hr.milestone_progress import reverse_activity_progress

            returned = activity
            transaction.on_commit(lambda: reverse_activity_progress(returned))

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


def _assert_may_certify(actor) -> None:
    """Only a holder of `ia.verify` may certify that work was done.

    Read from the permission matrix rather than a role tuple, the same
    contract `RolePermissionService.can_verify_ia` enforces on the page
    surface and `finance_services._assert_may_pay` enforces on the money.
    `ia.verify` is one of the authorities ADMIN_EXCLUDED_PERMISSIONS withholds
    from Admin, so that no single account can both verify work and release the
    money for it — that separation is only real if it is asserted where the
    verification actually happens.

    `actor` is a principal or the bare `actor_id` this service is handed by
    every caller. An actor that does not resolve has no authority anyone can
    establish, and this is the last gate before an activity is stamped
    verified, so it is refused.
    """
    from apps.core.exceptions import Forbidden
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    if isinstance(actor, str):
        from apps.accounts.models import User

        actor = User.objects.filter(id=actor).first()
    if not has_permission(actor, Permission.IA_VERIFY.value):
        raise Forbidden("Only Impact Assessment can verify an activity.")


def _assert_verifiable(activity) -> None:
    """The preconditions verification must not skip, on either door.

    The Salesforce reference is LOCKED once IA confirms
    (apps/frontend/views/my_plan_views.py refuses to change it afterwards) and
    the database forbids closing without one
    (`closed_activity_must_have_sf_id`). So an activity verified without a
    reference can never acquire one and can never close — an unrecoverable
    state reached by a single click, on the door Impact Assessment actually
    uses. Refusing here fails early with something the verifier can fix in a
    minute instead. (The DRF door, `apps.activities.services.ia_confirm`,
    applies its own strict block to Core work; this mirrors it rather than
    inventing a second standard.)
    """
    from apps.hr.milestone_progress import SALESFORCE_EXEMPT_RECORD_TYPES

    exempt = activity.salesforce_record_type_snapshot in SALESFORCE_EXEMPT_RECORD_TYPES
    if not exempt and not (activity.salesforce_activity_id or "").strip():
        raise BadRequest(
            "IA Verification failed: the Salesforce ID is missing. It cannot be "
            "added after verification, and the activity cannot close without "
            "it — ask the owner to enter it, then verify."
        )

    # Core work keeps the stricter checks the DRF door applies to it. They are
    # deliberately NOT extended to every activity here: evidence requirements
    # vary by type (apps/evidence/requirements.py), and a blanket rule would
    # refuse types the platform never asks evidence of.
    if activity.activity_type in ("core_visit", "core_training"):
        from apps.evidence.models import EvidenceRecord

        if (
            EvidenceRecord.objects.filter(
                activity_id=activity.id, quarantined=False
            ).count()
            == 0
        ):
            raise BadRequest("IA Verification failed: no evidence files uploaded.")
        if not activity.focus_intervention:
            raise BadRequest("IA Verification failed: focus intervention not recorded.")


def assert_ssa_visit_is_verifiable(activity) -> None:
    """SSA-01. A visit scheduled to collect an SSA is only valid work if the
    scores were actually entered — that is what IA verification certifies.

    The product rule, in the user's words: "the ssa support visits is only
    considered valid if the ssa scores are entered." A CCEO who arrives to a
    closed school can still COMPLETE the visit by giving a reason — the record
    stays honest and the work is not stuck in their queue — but the visit does
    not become certified work, does not count toward SSA targets, and does not
    feed the improvement analytics. It shows as done-but-unverified.

    Completion asks the question (apps.activities.services.complete). This is
    the other half: the answer "no scores, here is why" must not pass through
    verification as though scores existed.

    `SSAValidationService.validate_ssa` already computed almost this rule, but
    only as a RECOMMENDATION: `get_verification_checks` puts its result in a
    dict that prepopulates the IA's checklist, and the form submits fine with
    the box ticked over it. Advisory, not a gate. Measured before this
    function existed: an activity with `ssa_collection_expected=True` and
    `ssa_not_collected_reason=None` completed via the API, verified to
    `ia_verified`, and was counted.

    Two deliberate differences from the advisory check:

    1. It requires the record to be dated no earlier than the visit.
       `latest_applicable_record` has no date scoping at all, so the school's
       assessment from a previous cycle would satisfy a visit that collected
       nothing — the exact case the rule exists to catch.

       The comparison anchors on the EARLIEST date the visit is known by, not
       on one chosen field, and that choice was forced by measurement. A first
       version compared against `actual_delivery_date or planned_date`; since
       `actual_delivery_date` is only set when a caller sends
       `actualDeliveryDate`, and the web completion form does not, it fell back
       to `planned_date` and refused a visit delivered AHEAD of plan. A false
       refusal here blocks verification, and verification is what releases
       credit and money, so the rule has to be wrong in the safe direction.

    2. School-level, not activity-level, because that is all the data model
       can express: `SsaRecord` has no FK to Activity (apps/ssa/models.py).
       So this is a proxy — a confirmed assessment for this school, dated no
       earlier than the visit. Two SSA visits to one school on the same day
       would be satisfied by a single record. Closing that needs a
       record→activity link rather than a stricter query here.
    """
    if not activity.ssa_collection_expected:
        return

    if not activity.school:
        raise BadRequest(
            "IA Verification failed: this visit was scheduled to collect an "
            "SSA but has no school attached."
        )

    from apps.ssa.models import SsaRecord

    # The earliest date this visit is known by. An assessment collected ON the
    # visit cannot predate every date the visit has. Taking the MINIMUM rather
    # than one chosen field is what keeps a legitimate early delivery from
    # being refused: `planned_date` alone refuses a visit delivered ahead of
    # plan, and `actual_delivery_date` is only set when a caller sends
    # `actualDeliveryDate`, which the web completion form does not.
    known_dates = [
        d
        for d in (
            activity.planned_date,
            activity.actual_delivery_date,
            timezone.localdate(activity.execution_started_at)
            if activity.execution_started_at
            else None,
        )
        if d
    ]
    anchor = min(known_dates) if known_dates else None

    records = SsaRecord.objects.filter(
        school=activity.school,
        deleted_at__isnull=True,
        verification_status="confirmed",
    )
    if anchor is not None:
        # `__date__gte` compares the stored instant AFTER conversion to the
        # programme timezone, which is the comparison the rule means. Uganda is
        # UTC+3 and the SSA service stores a date-only input as local midnight,
        # so that instant sits at 21:00 the PREVIOUS day in UTC; a naive
        # comparison reads every assessment as a day early. Measured: it
        # refused the partner SSA monitor-completion flow, which records the
        # scores and confirms in one transaction, dated exactly on the visit.
        records = records.filter(date_of_ssa__date__gte=anchor)
    if not records.exists():
        reason = (activity.ssa_not_collected_reason or "").strip()
        detail = f' The recorded reason was: "{reason}".' if reason else ""
        raise BadRequest(
            "IA Verification failed: this visit was scheduled to collect an "
            "SSA and no confirmed assessment was recorded for the school on "
            "or after the visit date. An SSA visit is only valid work once "
            "the scores are entered — it can stay completed, but it cannot "
            "be verified or counted." + detail
        )


class ActivityCertificationService:
    """Certifies activity as official, updating status and triggering downstream integrations."""

    @staticmethod
    def certify_activity(
        activity: Activity, checklist_data: dict, actor_id: str
    ) -> dict:
        # Authority first, before the status read and before any write. This
        # service took actor_id on trust and stamped it onto ia_confirmed_by,
        # with the only guard living in one view (ia_views.ia_verify_action).
        # That is the FIN-03 shape, and FIN-03's own fix says why it matters:
        # "asserting here, at the money, is what stops the next screen
        # re-opening the hole." Permission.IA_VERIFY sits in
        # ADMIN_EXCLUDED_PERMISSIONS precisely so no single account can verify
        # work AND release the money for it — a separation the service was
        # handing to whichever caller happened to show up. "False IA
        # verification" is a P0 by name. Found by the Journey 19 sweep, where
        # all fourteen roles certified successfully.
        _assert_may_certify(actor_id)
        # Same race/replay guard as ActivityReturnService.return_activity,
        # and the same two-layer shape: the early check is a courtesy, the
        # re-check under select_for_update is the guard. Without it, two IA
        # staffers racing the same queue were BOTH told their certification
        # succeeded, and the second write overwrote ia_confirmed_by — the
        # verifier's identity on an audit-relevant field.
        if activity.status != ActivityStatus.AWAITING_IA_VERIFICATION:
            raise BadRequest("Activity is not awaiting IA verification")
        _assert_verifiable(activity)
        assert_ssa_visit_is_verifiable(activity)
        with transaction.atomic():
            activity = (
                Activity.objects.select_for_update().filter(id=activity.id).first()
            )
            if (
                activity is None
                or activity.status != ActivityStatus.AWAITING_IA_VERIFICATION
            ):
                raise BadRequest("Activity is not awaiting IA verification")
            _assert_verifiable(activity)
            assert_ssa_visit_is_verifiable(activity)
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
            # Milestone credit + integration sync — same rule as
            # apps.activities.services.ia_confirm(). This live UI path
            # previously wrote neither, so work verified through the IA
            # workspace (the path IA actually uses) earned no
            # MilestoneProgressCredit and every Uganda-cascade allocation's
            # actuals stayed at zero. One verification, one credit engine,
            # whichever door it came through.
            from apps.hr.milestone_progress import record_activity_progress
            from apps.integrations.services import (
                enqueue_activity_salesforce_sync,
            )

            certified = activity
            transaction.on_commit(lambda: record_activity_progress(certified))
            enqueue_activity_salesforce_sync(certified.id)

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
