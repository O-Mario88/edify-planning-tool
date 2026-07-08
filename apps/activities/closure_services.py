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
from apps.notifications.models import Notification


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

            # Check 6: Accounts Cleared
            accounts_cleared = True
            if finance_required:
                if activity.delivery_type == "partner":
                    accounts_cleared = activity.payment_status == "paid"
                else:
                    disbursed = (
                        Disbursement.objects.filter(activity=activity).aggregate(
                            s=Sum("amount_disbursed")
                        )["s"]
                        or 0
                    )
                    accounts_cleared = disbursed > 0

            # Check 7: NetSuite ID entered
            netsuite_id_entered = True
            if finance_required:
                netsuite_id_entered = NetSuiteExpenseRecord.objects.filter(
                    activity=activity
                ).exists()

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
    def is_eligible(activity: Activity) -> bool:
        checklist, blockers = ClosureEligibilityService.evaluate(activity)
        # All required checks must be True to close
        required_pass = (
            checklist.activity_executed
            and checklist.evidence_uploaded
            and checklist.salesforce_id_entered
            and checklist.ia_verified
            and (
                not checklist.finance_required
                or (checklist.accounts_cleared and checklist.netsuite_id_entered)
            )
        )
        return required_pass


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
                Notification.objects.create(
                    recipient_id=activity.responsible_staff_id,
                    title="Activity Closed",
                    body=f"Activity #{activity.id[:8]} is now closed and archived under Completed Activities.",
                    priority="normal",
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
