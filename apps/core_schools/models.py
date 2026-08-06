"""Core-schools models — the Core/Champion pipeline (deterministic IDs)."""

from __future__ import annotations

from django.db import models

from apps.core.cuid import deterministic
from apps.core.models import CuidField, TimeStampedModel


# FY-aware keying. The original ids carried no fiscal year, and
# CorePlan.school_id was globally unique — so on 1 Oct 2026 every Core drawer
# would query fy="2027", find nothing, and Core scheduling died platform-wide;
# self-healing the row in place would have handed FY2027 the FY2026 slot
# statuses. FY2026 keeps the legacy id shape so the 325 live plans and 2925
# slots need no data migration; every later FY gets its own namespace.
_LEGACY_FY = "2026"


def cplan_id(school_id: str, fy: str = _LEGACY_FY) -> str:
    if str(fy) == _LEGACY_FY:
        return deterministic("cplan", school_id)
    return deterministic("cplan", school_id, str(fy))


def cslot_id(school_id: str, kind: str, seq: int, fy: str = _LEGACY_FY) -> str:
    if str(fy) == _LEGACY_FY:
        return deterministic("cslot", school_id, f"{kind}{seq}")
    return deterministic("cslot", school_id, str(fy), f"{kind}{seq}")


def cprof_id(school_id: str) -> str:
    return deterministic("cprof", school_id)


class CorePlan(TimeStampedModel):
    """One core plan per onboarded core school (4 visits + 4 trainings)."""

    id = models.CharField(max_length=64, primary_key=True)  # cplan-{schoolId}
    # One plan per school PER FISCAL YEAR — global uniqueness was the
    # rollover hard stop.
    school_id = models.CharField(max_length=64, db_index=True)
    fy = models.CharField(max_length=16)
    status = models.CharField(max_length=32, default="Active")
    visits_target = models.IntegerField(default=4)
    trainings_target = models.IntegerField(default=4)
    visits_completed = models.IntegerField(default=0)
    trainings_completed = models.IntegerField(default=0)
    assessment_completed = models.IntegerField(default=0)  # 0 or 1
    baseline_average = models.FloatField(null=True, blank=True)
    follow_up_average = models.FloatField(null=True, blank=True)
    baseline_ssa_record_id = models.CharField(max_length=30, null=True, blank=True)
    follow_up_ssa_record_id = models.CharField(max_length=30, null=True, blank=True)
    follow_up_scheduled_for = models.CharField(max_length=32, null=True, blank=True)
    follow_up_assignee = models.CharField(max_length=30, null=True, blank=True)
    interventions = models.JSONField(null=True, blank=True)
    created_by_id = models.CharField(max_length=30, null=True, blank=True)
    created_by_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "core_plan"
        indexes = [models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["school_id", "fy"], name="uniq_core_plan_per_school_fy"
            )
        ]


class CoreActivitySlot(TimeStampedModel):
    """One of the 9 core slots (1 assessment + 4 visit + 4 training).
    Deterministic id. See apps.core_schools.services.CORE_PACKAGE_SPEC."""

    id = models.CharField(max_length=64, primary_key=True)  # cslot-{schoolId}-v1
    core_plan = models.ForeignKey(
        CorePlan, on_delete=models.CASCADE, related_name="slots"
    )
    school_id = models.CharField(max_length=64)
    intervention = models.CharField(max_length=64)
    activity_type = models.CharField(max_length=16)  # visit | training
    sequence_number = models.IntegerField()
    status = models.CharField(max_length=32, default="Planned")
    owner = models.CharField(max_length=16, default="unassigned")
    assigned_staff_id = models.CharField(max_length=30, null=True, blank=True)
    assigned_staff_name = models.CharField(max_length=255, null=True, blank=True)
    assigned_partner_id = models.CharField(max_length=30, null=True, blank=True)
    assigned_partner_name = models.CharField(max_length=255, null=True, blank=True)
    scheduled_month = models.CharField(max_length=16, null=True, blank=True)
    scheduled_week = models.IntegerField(null=True, blank=True)
    scheduled_for = models.CharField(max_length=32, null=True, blank=True)
    salesforce_id = models.CharField(max_length=128, null=True, blank=True)
    activity_id = models.CharField(max_length=30, null=True, blank=True)
    evidence_uri = models.CharField(max_length=512, null=True, blank=True)
    evidence_notes = models.TextField(null=True, blank=True)
    pl_verification_status = models.CharField(max_length=16, null=True, blank=True)
    ia_verification_status = models.CharField(max_length=16, null=True, blank=True)
    accountant_status = models.CharField(max_length=16, null=True, blank=True)
    netsuite_status = models.CharField(max_length=16, null=True, blank=True)
    teachers = models.IntegerField(null=True, blank=True)
    leaders = models.IntegerField(null=True, blank=True)
    participants = models.IntegerField(null=True, blank=True)
    returned_reason = models.CharField(max_length=512, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_activity_slot"
        indexes = [
            models.Index(fields=["core_plan"]),
            models.Index(fields=["school_id"]),
        ]


class CoreSchoolProfile(TimeStampedModel):
    """Champion pipeline + active-plan pointer for an onboarded core school."""

    id = models.CharField(max_length=64, primary_key=True)  # cprof-{schoolId}
    school_id = models.CharField(max_length=64, unique=True)
    core_plan = models.OneToOneField(
        CorePlan, on_delete=models.CASCADE, related_name="profile"
    )
    core_start_fy = models.CharField(max_length=16)
    champion_status = models.CharField(max_length=32, default="Not Eligible")
    status = models.CharField(max_length=32, default="Active")

    class Meta:
        db_table = "core_school_profile"


class CoreCandidateVerification(TimeStampedModel):
    """IA verification of a Potential Core candidate (SSA >= 7.5 gate)."""

    id = CuidField()
    school_id = models.CharField(max_length=64, unique=True)
    ssa_record_id = models.CharField(max_length=30)
    verification_id = models.CharField(max_length=64)
    verified_by_id = models.CharField(max_length=30)
    verified_by_name = models.CharField(max_length=255)
    verified_at = models.DateTimeField()
    status = models.CharField(max_length=64)  # Verified Potential Core | Rejected
    comments = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "core_candidate_verification"


class CoreSchoolOnboarding(TimeStampedModel):
    """Record of Client -> Core transition at onboarding."""

    id = CuidField()
    school_id = models.CharField(max_length=64, unique=True)
    core_plan = models.OneToOneField(
        CorePlan, on_delete=models.CASCADE, related_name="onboarding"
    )
    fy = models.CharField(max_length=16)
    previous_school_type = models.CharField(max_length=32)
    baseline_ssa_record_id = models.CharField(max_length=30)
    baseline_average_score = models.FloatField()
    onboarded_by_id = models.CharField(max_length=30)
    onboarded_by_name = models.CharField(max_length=255)
    onboarded_at = models.DateTimeField()
    onboarding_reason = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=32, default="Onboarded")

    class Meta:
        db_table = "core_school_onboarding"


__all__ = [
    "cplan_id",
    "cslot_id",
    "cprof_id",
    "CorePlan",
    "CoreActivitySlot",
    "CoreSchoolProfile",
    "CoreCandidateVerification",
    "CoreSchoolOnboarding",
]
