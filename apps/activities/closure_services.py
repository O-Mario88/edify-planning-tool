from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.activities.models import (
    Activity,
    ActivityClosure,
    ClosureChecklist,
    ClosureBlocker,
    CompletedActivitySnapshot,
    ActivityReopenRequest,
    AnalyticsPublishRecord,
    ActivityTimelineEvent,
)
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import Disbursement, NetSuiteExpenseRecord
from apps.notifications.services import WorkflowNotificationService


class ClosureEligibilityService:
    """Evaluates if an activity meets all the requirements to be closed."""

    @staticmethod
    def evaluate(activity: Activity) -> tuple[ClosureChecklist, list[ClosureBlocker]]:
        with transaction.atomic():
            # Check 1: Activity Executed
            executed = activity.status not in [
                "not_planned",
                "planned",
                "scheduled",
                "assigned_to_partner",
                "partner_scheduled",
            ]

            # Check 2: Evidence Uploaded
            evidence_uploaded = EvidenceRecord.objects.filter(
                activity=activity, quarantined=False
            ).exists()

            # Check 3: Salesforce ID entered
            salesforce_id_entered = bool(activity.salesforce_activity_id)

            # Check 4: IA Verified
            ia_verified = activity.status in [
                "ia_verified",
                "closed",
                "accountant_confirmed",
            ]

            # Check 5: Finance Required
            finance_required = (
                activity.schedule_cost_lines.exists()
                or activity.delivery_type == "partner"
            )

            # Check 6: Accounts Cleared — requires genuine ACCOUNTANT action,
            # not merely that money left the account. The mandate: "NO CLOSING
            # AN ACTIVITY WITHOUT ... FINANCE CLEARANCE." The two finance
            # systems each have a distinct accountant-clearance signal:
            #   System A (activity-level disburse+clear): the accountant's
            #     NetSuiteExpenseRecord entry IS the clearance step.
            #   System B (weekly advance accountability): the accountant
            #     approves submitted accountability, moving the advance to
            #     "accounted" (or "reimbursed").
            # "disbursed" and "accountability_pending" are pre-clearance
            # states — an advance sitting at accountability_pending means the
            # responsible user submitted but the accountant has NOT yet
            # approved, so it must NOT count as cleared (previously it did,
            # letting activities close before accountant final-clearance).
            accounts_cleared = True
            if finance_required:
                if activity.delivery_type == "partner":
                    accounts_cleared = activity.payment_status == "paid"
                else:
                    has_netsuite_expense = NetSuiteExpenseRecord.objects.filter(
                        activity=activity
                    ).exists()
                    accountant_approved_advance = activity.advance_requests.filter(
                        status__in=["accounted", "reimbursed"]
                    ).exists()
                    accounts_cleared = (
                        has_netsuite_expense or accountant_approved_advance
                    )

            # Check 7: NetSuite Code — accountability proof, required whenever
            # money moved. Two independent, equally-valid completion signals:
            # the accountant's own NetSuiteExpenseRecord entry (System A —
            # apps.fund_requests.finance_services.NetSuiteExpenseService, the
            # activity-level disburse+clear flow) OR, for advances that went
            # through the responsible-user accountability chain (System B —
            # apps.fund_requests.advance_service.submit_accountability), EVERY
            # such advance carrying its own accountability NetSuite Code.
            # These are an OR, not an either/or keyed off AdvanceRequest
            # status: an activity disbursed via the System A queue still has
            # its AdvanceRequest rows move to "disbursed" (so the money isn't
            # silently double-payable through the System B queue too), but
            # that must never by itself demand the System B accountability
            # step System A's own flow was never designed to produce.
            netsuite_id_entered = True
            if finance_required:
                from django.db.models import Q as _Q

                has_netsuite_expense_record = NetSuiteExpenseRecord.objects.filter(
                    activity=activity
                ).exists()
                money_moved_advances = activity.advance_requests.filter(
                    status__in=[
                        "disbursed",
                        "accountability_pending",
                        "accounted",
                        "reimbursement_submitted",
                        "reimbursed",
                    ]
                )
                every_advance_accounted = not money_moved_advances.filter(
                    _Q(accountability_netsuite_id__isnull=True)
                    | _Q(accountability_netsuite_id="")
                ).exists()
                netsuite_id_entered = has_netsuite_expense_record or (
                    money_moved_advances.exists() and every_advance_accounted
                )

            # Check 8: Analytics Published
            pub_rec = AnalyticsPublishRecord.objects.filter(activity=activity).first()
            analytics_published = pub_rec is not None and pub_rec.status == "published"

            # Check 9: Audit Trail Saved
            audit_trail_saved = ActivityTimelineEvent.objects.filter(
                activity=activity
            ).exists()

            # Update or create Checklist
            checklist, _ = ClosureChecklist.objects.update_or_create(
                activity=activity,
                defaults={
                    "activity_executed": executed,
                    "evidence_uploaded": evidence_uploaded,
                    "salesforce_id_entered": salesforce_id_entered,
                    "ia_verified": ia_verified,
                    "finance_required": finance_required,
                    "accounts_cleared": accounts_cleared,
                    "netsuite_id_entered": netsuite_id_entered,
                    "analytics_published": analytics_published,
                    "audit_trail_saved": audit_trail_saved,
                    "last_evaluated_at": timezone.now(),
                },
            )

            # Rebuild blockers list
            ClosureBlocker.objects.filter(activity=activity).delete()
            blockers = []

            if not executed:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="Activity not executed",
                        responsible_role="CCEO",
                    )
                )
            if not evidence_uploaded:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="Evidence Missing",
                        responsible_role="CCEO",
                    )
                )
            if not salesforce_id_entered:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="Activity SF ID Missing",
                        responsible_role="CCEO",
                    )
                )
            if not ia_verified:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="IA not verified",
                        responsible_role="ImpactAssessment",
                    )
                )
            if finance_required and not accounts_cleared:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="Accounts not cleared",
                        responsible_role="Accountant",
                    )
                )
            if finance_required and not netsuite_id_entered:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="NetSuite ID missing",
                        responsible_role="Accountant",
                    )
                )
            if not analytics_published:
                blockers.append(
                    ClosureBlocker.objects.create(
                        activity=activity,
                        blocking_reason="Analytics not published",
                        responsible_role="ImpactAssessment",
                    )
                )

            return checklist, blockers

    @staticmethod
    def _core_requirements_met(checklist: ClosureChecklist) -> bool:
        """Execution, evidence, SF ID, IA verification, and (if money moved)
        accounts cleared + NetSuite Code entered. Shared by is_eligible() and
        AnalyticsPublishingService.publish_if_ready() so analytics is only
        ever marked published once these are genuinely true."""
        return (
            checklist.activity_executed
            and checklist.evidence_uploaded
            and checklist.salesforce_id_entered
            and checklist.ia_verified
            and (
                not checklist.finance_required
                or (checklist.accounts_cleared and checklist.netsuite_id_entered)
            )
        )

    @staticmethod
    def is_eligible(activity: Activity) -> bool:
        checklist, blockers = ClosureEligibilityService.evaluate(activity)
        # All required checks must be True to close
        return ClosureEligibilityService._core_requirements_met(checklist)


class ActivityClosureService:
    """Orchestrates locking and closing eligible activities."""

    @staticmethod
    def close(
        activity: Activity, closed_by: str = "system", bypass_checks: bool = False
    ) -> ActivityClosure:
        # Check eligibility first
        if not bypass_checks and not ClosureEligibilityService.is_eligible(activity):
            raise ValueError(
                "Activity does not meet final closure checklist requirements."
            )

        with transaction.atomic():
            # Update Activity Status
            activity.status = "closed"
            activity.save(update_fields=["status", "updated_at"])

            # Create Closure detail record
            closure, _ = ActivityClosure.objects.update_or_create(
                activity=activity,
                defaults={
                    "closed_at": timezone.now(),
                    "closed_by": closed_by,
                    "status": "closed",
                },
            )

            # Freeze snapshot of financial stats
            budget_total = (
                activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
            )
            disb_total = (
                Disbursement.objects.filter(activity=activity).aggregate(
                    s=Sum("amount_disbursed")
                )["s"]
                or 0
            )
            ns_rec = NetSuiteExpenseRecord.objects.filter(activity=activity).first()
            ns_id = ns_rec.netsuite_expense_id if ns_rec else None

            CompletedActivitySnapshot.objects.update_or_create(
                activity=activity,
                defaults={
                    "final_budget_amount": budget_total,
                    "disbursed_amount": disb_total,
                    "actual_spend_amount": disb_total,
                    "netsuite_expense_id": ns_id,
                    "evidence_count": EvidenceRecord.objects.filter(
                        activity=activity
                    ).count(),
                    "snapshot_taken_at": timezone.now(),
                },
            )

            # Log event to Audit trail
            AuditTrailService.log_event(
                activity=activity,
                event_name="Closed",
                actor_id=closed_by,
                actor_role="System",
                description="Activity met all closure checklist conditions and is locked.",
            )

            # Send Notification
            if activity.responsible_staff_id:
                WorkflowNotificationService.trigger(
                    event_type="activity_closed",
                    category="my_plan",
                    priority="normal",
                    title="Activity Closed",
                    body=f"Activity #{activity.id[:8]} is now closed and archived under Completed Activities.",
                    context_type="Activity",
                    context_id=activity.id,
                    recipients=[activity.responsible_staff_id],
                )

            return closure


class ActivityReopenService:
    """Manages reopening locked/closed activities with audited trails."""

    @staticmethod
    def reopen(
        activity: Activity, reason: str, category: str, user_id: str
    ) -> ActivityReopenRequest:
        with transaction.atomic():
            # Create reopen record
            req = ActivityReopenRequest.objects.create(
                activity=activity,
                reopened_by=user_id,
                reason=reason,
                category=category,
                approved=True,
            )

            # Reset activity status
            activity.status = (
                "ia_verified"  # Revert to verified so it can be re-cleared/fixed
            )
            activity.save(update_fields=["status", "updated_at"])

            # Update closure record status
            ActivityClosure.objects.filter(activity=activity).update(
                status="reopened", notes=f"Reopened by {user_id}. Reason: {reason}"
            )

            # Reset analytics publishing state to trigger recalculations
            AnalyticsPublishRecord.objects.filter(activity=activity).update(
                status="recalculation_required"
            )

            # Log event to Audit trail
            AuditTrailService.log_event(
                activity=activity,
                event_name="Reopened",
                actor_id=user_id,
                actor_role="Admin",
                description=f"Reopened activity under category: {category}. Reason: {reason}",
            )

            return req


class AnalyticsPublishingService:
    """Simulates publishing verified and cleared activity metrics into the central analytics database."""

    @staticmethod
    def publish(activity: Activity) -> AnalyticsPublishRecord:
        with transaction.atomic():
            rec, _ = AnalyticsPublishRecord.objects.update_or_create(
                activity=activity,
                defaults={"status": "published", "published_at": timezone.now()},
            )
            return rec

    @staticmethod
    def publish_if_ready(activity: Activity) -> ClosureChecklist:
        """Marks analytics published only once genuinely earned — never a
        blind force-satisfy. Evaluates the checklist and, only when the
        activity has actually met the core closure requirements (executed,
        evidence, SF ID, IA verified, and finance cleared if money moved),
        publishes analytics and re-evaluates so callers see the fresh state.
        A failed/ineligible close attempt must never leave a false
        "published" record behind."""
        checklist, _ = ClosureEligibilityService.evaluate(activity)
        if ClosureEligibilityService._core_requirements_met(checklist):
            AnalyticsPublishingService.publish(activity)
            checklist, _ = ClosureEligibilityService.evaluate(activity)
        return checklist


class AuditTrailService:
    """Maintains a vertical timeline audit record for each activity."""

    @staticmethod
    def log_event(
        activity: Activity,
        event_name: str,
        actor_id: str,
        actor_role: str,
        description: str = "",
    ) -> ActivityTimelineEvent:
        return ActivityTimelineEvent.objects.create(
            activity=activity,
            event_name=event_name,
            actor_id=actor_id,
            actor_role=actor_role,
            description=description,
        )
