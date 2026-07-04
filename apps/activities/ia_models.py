from django.db import models
from apps.core.models import CuidField, TimeStampedModel
from apps.core.enums import VerificationStatus

class IAVerification(TimeStampedModel):
    """Authoritative verification status and checklist results for an activity."""
    id = CuidField()
    activity = models.OneToOneField("activities.Activity", on_delete=models.CASCADE, related_name="ia_verification")
    verified_by = models.CharField(max_length=30, null=True, blank=True)  # user ID
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)

    class Meta:
        db_table = "ia_verification"


class VerificationChecklist(TimeStampedModel):
    """Saves the exact checklist items verified by IA for audits."""
    id = CuidField()
    verification = models.OneToOneField(IAVerification, on_delete=models.CASCADE, related_name="checklist")
    evidence_exists = models.BooleanField(default=False)
    attendance_valid = models.BooleanField(default=False)
    ssa_uploaded = models.BooleanField(default=False)
    correct_school = models.BooleanField(default=False)
    correct_cluster = models.BooleanField(default=False)
    correct_intervention = models.BooleanField(default=False)
    sf_id_entered = models.BooleanField(default=False)
    duplicate_check_passed = models.BooleanField(default=False)
    analytics_ready = models.BooleanField(default=False)

    class Meta:
        db_table = "ia_verification_checklist"


class VerificationComment(TimeStampedModel):
    """Comments left during the verification process."""
    id = CuidField()
    verification = models.ForeignKey(IAVerification, on_delete=models.CASCADE, related_name="comments")
    comment = models.TextField()
    created_by = models.CharField(max_length=30)
    
    class Meta:
        db_table = "ia_verification_comment"
        ordering = ["created_at"]


class VerificationDecision(TimeStampedModel):
    """Timeline record of each verify/return decision made by IA."""
    id = CuidField()
    verification = models.ForeignKey(IAVerification, on_delete=models.CASCADE, related_name="decisions")
    decision = models.CharField(max_length=16)  # APPROVE | RETURN
    decided_by = models.CharField(max_length=30)
    decided_at = models.DateTimeField(auto_now_add=True)
    comments = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ia_verification_decision"
        ordering = ["-decided_at"]


class ReturnedReason(TimeStampedModel):
    """Standardized reasons for returning an activity."""
    id = CuidField()
    verification = models.ForeignKey(IAVerification, on_delete=models.CASCADE, related_name="returned_reasons")
    reason = models.CharField(max_length=128)

    class Meta:
        db_table = "ia_returned_reason"


class DuplicateActivity(TimeStampedModel):
    """Stores activities flagged as potential duplicates."""
    id = CuidField()
    activity = models.ForeignKey("activities.Activity", on_delete=models.CASCADE, related_name="duplicate_flags")
    duplicate_of = models.ForeignKey("activities.Activity", on_delete=models.CASCADE, related_name="duplicate_sources")
    status = models.CharField(max_length=32, default="potential")  # potential | ignored | resolved | flagged
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "ia_duplicate_activity"


class VerificationHistory(TimeStampedModel):
    """Immutable audit trail of all approved/verified activities."""
    id = CuidField()
    activity = models.ForeignKey("activities.Activity", on_delete=models.CASCADE, related_name="verification_history")
    verified_by = models.CharField(max_length=30)
    verified_at = models.DateTimeField()
    analytics_included = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "ia_verification_history"
