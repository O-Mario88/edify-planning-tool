from django.db import models
from django.utils import timezone
from apps.core.models import CuidField, TimeStampedModel
from apps.activities.models import Activity


class ActivityClosure(TimeStampedModel):
    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="closure_details"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.CharField(max_length=30, default="system")
    status = models.CharField(max_length=32, default="closure_not_ready")
    # closure_not_ready, program_verified, finance_pending, accountability_pending, analytics_pending, ready_to_close, closed, reopened
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "activity_closure"
        indexes = [
            models.Index(fields=["status"]),
        ]


class ClosureChecklist(TimeStampedModel):
    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="closure_checklist"
    )
    activity_executed = models.BooleanField(default=False)
    evidence_uploaded = models.BooleanField(default=False)
    salesforce_id_entered = models.BooleanField(default=False)
    ia_verified = models.BooleanField(default=False)
    finance_required = models.BooleanField(default=False)
    accounts_cleared = models.BooleanField(default=False)
    netsuite_id_entered = models.BooleanField(default=False)
    analytics_published = models.BooleanField(default=False)
    audit_trail_saved = models.BooleanField(default=False)
    last_evaluated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "closure_checklist"
        indexes = [
            models.Index(fields=["ia_verified"]),
            models.Index(fields=["accounts_cleared"]),
        ]


class ClosureBlocker(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="closure_blockers"
    )
    blocking_reason = models.CharField(max_length=255)
    responsible_role = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "closure_blocker"


class CompletedActivitySnapshot(TimeStampedModel):
    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="completed_snapshot"
    )
    final_budget_amount = models.BigIntegerField(default=0)
    disbursed_amount = models.BigIntegerField(default=0)
    actual_spend_amount = models.BigIntegerField(default=0)
    netsuite_expense_id = models.CharField(max_length=128, null=True, blank=True)
    evidence_count = models.IntegerField(default=0)
    snapshot_taken_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "completed_activity_snapshot"


class ActivityReopenRequest(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="reopen_requests"
    )
    reopened_by = models.CharField(max_length=30)
    reason = models.TextField()
    category = models.CharField(
        max_length=64
    )  # wrong_evidence, wrong_salesforce_id, wrong_school, wrong_finance_clearance, duplicate_discovered, audit_correction, analytics_correction, other
    requested_at = models.DateTimeField(default=timezone.now)
    approved = models.BooleanField(default=False)

    class Meta:
        db_table = "activity_reopen_request"


class AnalyticsPublishRecord(TimeStampedModel):
    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="analytics_publish_record"
    )
    status = models.CharField(
        max_length=32, default="pending"
    )  # pending, published, failed, recalculation_required, excluded
    published_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "analytics_publish_record"
        indexes = [
            models.Index(fields=["status"]),
        ]


class ActivityTimelineEvent(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="timeline_events"
    )
    event_name = models.CharField(max_length=128)
    actor_id = models.CharField(max_length=30, default="system")
    actor_role = models.CharField(max_length=64, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "activity_timeline_event"
