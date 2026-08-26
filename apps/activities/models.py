"""
Activities models — the operational work ledger (the 21-state lifecycle).

Ports of Activity, ActivityScheduleCostLine (auto-cost breakdown from the CD
rate card at schedule time), and ActivityCompletionVerification (manual
Salesforce SV-/TS- ID confirmation). Payments models (PaymentRequest etc.) live
in the payments app.
"""

from __future__ import annotations

from django.db import models, transaction
from django.contrib.postgres.fields import ArrayField

from apps.core.enums import (
    ActivityStatus,
    ActivityType,
    ClusterMeetingSlot,
    DeliveryType,
    EvidenceStatus,
    ExecutorType,
    PaymentStatus,
    ProgrammeActivityType,
    ProgrammeDeliveryMode,
    SsaIntervention,
    VerificationStatus,
)
from apps.core.models import (
    CuidField,
    SoftDeleteModel,
    TimeStampedModel,
    _normalize_datetime_value,
)


class Activity(SoftDeleteModel):
    """An operational work item (visit / training / cluster meeting / …)."""

    id = CuidField()
    activity_type = models.CharField(max_length=48, choices=ActivityType.choices)
    # Governed master-data provenance.  This is deliberately a FK on the
    # existing canonical Activity, not a second transactional activity model.
    catalogue_item = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activities",
    )
    # For an in-school delivery, ``catalogue_item`` is the operational
    # workflow profile (cost, evidence, Salesforce kind and entitlement),
    # while this field records WHICH of the governed 21 courses was taught.
    # Keeping those two decisions separate lets a course that is normally
    # cluster-delivered still be selected for an in-school session without
    # changing its master-data delivery permissions or costing profile.
    training_course = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="in_school_course_deliveries",
    )
    # One staff action creates two Salesforce facts: a TS- Training and an
    # SVE- School Visit.  This explicit pair is not follow-up lineage — both
    # records describe the same delivery and must complete together.
    paired_school_visit = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paired_in_school_training",
    )
    catalogue_version = models.PositiveIntegerField(null=True, blank=True)
    activity_name_snapshot = models.CharField(max_length=255, null=True, blank=True)
    activity_type_snapshot = models.CharField(max_length=32, null=True, blank=True)
    delivery_method_snapshot = models.CharField(max_length=32, null=True, blank=True)
    evidence_profile_snapshot = models.CharField(max_length=64, null=True, blank=True)
    salesforce_record_type_snapshot = models.CharField(
        max_length=32, null=True, blank=True
    )
    costing_profile_snapshot = models.CharField(max_length=64, null=True, blank=True)
    source_ssa = models.ForeignKey(
        "ssa.SsaRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recommended_activities",
    )
    source_ssa_verification_state = models.CharField(
        max_length=32, null=True, blank=True
    )
    source_score = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )
    source_classification = models.CharField(max_length=32, null=True, blank=True)
    recommendation_reason = models.TextField(blank=True)
    recommendation_source = models.JSONField(default=dict, blank=True)

    # ── Why this activity exists ────────────────────────────────────────────
    # Provenance was spread across ten nullable fields and three external link
    # tables, so "why does this activity exist" had no single answer and every
    # consumer reimplemented a different guess. These two record the ONE reason
    # that caused it, chosen at creation from what the caller already knew.
    #
    # Deliberately not constrained NOT NULL: making it mandatory would refuse
    # activities the platform currently accepts, and blocking field work is a
    # decision for the programme, not a schema default. Unset is reported as a
    # data-quality exception instead of being prevented.
    class Driver(models.TextChoices):
        SSA_RECOMMENDATION = "ssa_recommendation", "SSA recommendation"
        PRIORITY_ALLOCATION = "priority_allocation", "Priority target allocation"
        CORE_PACKAGE = "core_package", "Core school package slot"
        BUSINESS_TRANSFORMATION = (
            "business_transformation",
            "Business Transformation case",
        )
        SPECIAL_PROJECT = "special_project", "Special Project"
        EXTRA_ASSIGNMENT = "extra_assignment", "Extra assigned work"
        COMPLIANCE = "compliance", "Mandatory verification or compliance"
        LEADERSHIP_EXCEPTION = "leadership_exception", "Approved leadership exception"

    primary_driver_type = models.CharField(
        max_length=32, choices=Driver.choices, blank=True, default="", db_index=True
    )
    #: The id of the record named by primary_driver_type. Untyped on purpose —
    #: it points into seven different tables, and seven nullable FKs is the
    #: scatter this replaces.
    primary_driver_id = models.CharField(max_length=30, blank=True, default="")
    driver_reason = models.TextField(blank=True, default="")

    #: The recommendation this answers, now that recommendations are records
    #: rather than a calculation. SET_NULL: retiring a recommendation must not
    #: delete the work that was done about it.
    ssa_recommendation = models.ForeignKey(
        "ssa.SsaRecommendation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    follow_up_of_activity = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="follow_up_activities",
    )
    override_reason = models.TextField(blank=True)
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    cluster = models.ForeignKey(
        "clusters.Cluster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    project_id = models.CharField(max_length=30, null=True, blank=True)
    # Set only for staff-conducted school visits priced via a shared daily cost
    # pool (see apps.daily_visit_batches) — null for every other activity type.
    daily_visit_batch = models.ForeignKey(
        "daily_visit_batches.DailyVisitBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )

    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8)
    month = models.IntegerField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    scheduled_date = models.DateTimeField(null=True, blank=True)
    planned_date = models.DateField(null=True, blank=True)
    # Multi-day programme work: the last service day. Null (or equal to
    # planned_date) means a one-day activity. Budget lines carry their own
    # service dates so cross-period cost lands in the right month.
    end_date = models.DateField(null=True, blank=True)
    # §1: every budget amount originates from a dated plan — this names which
    # planning workflow authorized the activity (see PlanningSource).
    planning_source = models.CharField(max_length=32, blank=True, default="")
    # school / cluster / project / programme / organization
    activity_context_type = models.CharField(max_length=16, blank=True, default="")
    # Non-school work carries a strategic rationale instead of an SSA
    # recommendation (see SupportRationale).
    support_rationale = models.CharField(max_length=48, blank=True, default="")
    venue = models.CharField(max_length=255, blank=True, default="")
    # Planning/reporting attributes specific to non-school programme work.
    # The title itself remains governed by activity_name_snapshot from the
    # approved Activity Catalogue.
    programme_activity_type = models.CharField(
        max_length=48,
        choices=ProgrammeActivityType.choices,
        null=True,
        blank=True,
    )
    programme_delivery_mode = models.CharField(
        max_length=16,
        choices=ProgrammeDeliveryMode.choices,
        null=True,
        blank=True,
    )
    planned_school_count = models.PositiveIntegerField(null=True, blank=True)
    # Location for work that has no school/cluster to inherit one from.
    event_district = models.ForeignKey(
        "geography.District",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="programme_activities",
    )
    week_start_date = models.DateField(null=True, blank=True)
    week_end_date = models.DateField(null=True, blank=True)
    fiscal_year = models.CharField(max_length=16, null=True, blank=True)
    planned_month = models.IntegerField(null=True, blank=True)
    planned_week = models.IntegerField(null=True, blank=True)

    responsible_staff_id = models.CharField(max_length=30, null=True, blank=True)
    # Human being the partner says will perform the visit. This is deliberately
    # a name snapshot rather than a StaffProfile FK: partner field workers do
    # not necessarily hold Edify staff accounts, but the delivery record still
    # needs to say who is expected at the school.
    delivery_contact_name = models.CharField(max_length=255, blank=True, default="")
    monitored_by_staff_id = models.CharField(max_length=30, null=True, blank=True)
    assigned_partner_id = models.CharField(max_length=30, null=True, blank=True)
    delivery_type = models.CharField(
        max_length=16, choices=DeliveryType.choices, default=DeliveryType.STAFF
    )
    # The finer WHO axis. delivery_type stays two-valued because every
    # existing surface keys on it; executor_type separates the two partner
    # workflows that are not the same commitment — an assigned partner that
    # still has to pick a date, versus a certified agency staff booked onto
    # one. See apps.core.enums.ExecutorType.
    executor_type = models.CharField(
        max_length=32,
        choices=ExecutorType.choices,
        default=ExecutorType.STAFF,
    )
    cluster_slot = models.CharField(
        max_length=16, choices=ClusterMeetingSlot.choices, null=True, blank=True
    )

    # Core Schools tracking fields
    visit_number = models.CharField(max_length=16, null=True, blank=True)
    training_number = models.CharField(max_length=16, null=True, blank=True)
    support_type = models.CharField(max_length=32, null=True, blank=True)

    purpose_intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, null=True, blank=True
    )
    activity_purpose_text = models.TextField(null=True, blank=True)
    purpose_type = models.CharField(max_length=64, null=True, blank=True)
    focus_intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, null=True, blank=True
    )
    secondary_focus_interventions = ArrayField(
        base_field=models.CharField(max_length=64, choices=SsaIntervention.choices),
        default=list,
        blank=True,
    )
    expected_outcome = models.TextField(null=True, blank=True)

    # Actuals, captured at delivery — planned fields above are never copied
    # into these; planned, actual and verified information stay separate.
    actual_delivery_date = models.DateField(null=True, blank=True)
    actual_outcome = models.TextField(null=True, blank=True)
    actual_observations = models.TextField(null=True, blank=True)
    follow_up_note = models.TextField(null=True, blank=True)
    # When the executor pressed Start (partner field officers today) — the
    # in-progress moment, distinct from created_at and scheduled_date.
    execution_started_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=32,
        choices=ActivityStatus.choices,
        default=ActivityStatus.NOT_PLANNED,
    )
    evidence_status = models.CharField(
        max_length=16, choices=EvidenceStatus.choices, default=EvidenceStatus.NONE
    )

    # Salesforce-ready (manual ID confirmation, not integrated).
    salesforce_activity_id = models.CharField(max_length=128, null=True, blank=True)
    salesforce_activity_type = models.CharField(
        max_length=16, null=True, blank=True
    )  # visit | training

    # SSA collection integration
    ssa_collection_expected = models.BooleanField(default=False)
    ssa_not_collected_reason = models.CharField(max_length=255, null=True, blank=True)

    ia_verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    # The moment the completion enters IA's queue. This is intentionally
    # distinct from updated_at (which changes throughout review) so SLA
    # reporting is reproducible and never inferred from a mutable timestamp.
    submitted_to_ia_at = models.DateTimeField(null=True, blank=True)
    ia_confirmed_at = models.DateTimeField(null=True, blank=True)
    ia_confirmed_by = models.CharField(max_length=30, null=True, blank=True)
    payment_status = models.CharField(
        max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.NONE
    )

    # Reschedule trail.
    reschedule_count = models.IntegerField(default=0)
    last_reason = models.CharField(max_length=512, null=True, blank=True)

    # Auto-cost from the CD rate card at schedule time. Despite the field
    # name, this holds plain integer UGX (whole shillings), not cents --
    # apps.budget.costing_service is the sole writer and the CD rate card
    # (apps.budget.models.CostSetting) is documented "1 unit = 1 UGX". Do
    # not divide/multiply this value by 100.
    # BigInteger like the ActivityScheduleCostLine amounts — the line columns
    # were widened after overflowing at ~UGX 2.1bn (2026-07-30 audit M-14),
    # and this header total is by definition >= any single line, so the
    # 32-bit column here was the remaining overflow (2026-08-12 audit M-6).
    est_cost_cents = models.BigIntegerField(default=0)
    cost_missing = models.BooleanField(default=False)

    # PL review handoff when a CCEO completes field work.
    pl_review_note = models.CharField(max_length=512, null=True, blank=True)
    pl_reviewed_at = models.DateTimeField(null=True, blank=True)
    pl_reviewed_by = models.CharField(max_length=30, null=True, blank=True)

    # Training/cluster-meeting completion detail.
    # The confirmed headcount at scheduling time.  This remains available for
    # planning, fund requests and budget reporting before actual attendance is
    # recorded after the activity.
    expected_participants = models.IntegerField(null=True, blank=True)
    # Cluster participant planning. The user states how many people to invite
    # from each school; the total is derived, never typed.
    #
    # The school count is SNAPSHOT rather than looked up on read, because
    # cluster membership changes and an approved budget must keep the number it
    # was priced with. A school joining the cluster in November must not
    # silently re-price an activity approved in August.
    participants_per_school = models.IntegerField(null=True, blank=True)
    cluster_school_count_snapshot = models.IntegerField(null=True, blank=True)
    # How many of the cluster's schools were actually INVITED. Not every
    # member qualifies for every session — a Literacy training does not reach
    # the secondary and vocational schools in a mixed cluster — so multiplying
    # by full cluster membership invited, catered and budgeted for people who
    # were never coming. The multiplier for the participant total is this, not
    # the membership snapshot beside it, which stays as the record of how
    # large the cluster was when the activity was priced.
    #
    # Null on rows created before the distinction existed; those are read as
    # "the whole cluster was invited", which is exactly what they meant.
    schools_invited = models.IntegerField(null=True, blank=True)
    # The planned COMPOSITION of the room, stated per member school. A cluster
    # meeting invites the head and one teacher; a Literacy training invites
    # three teachers and nobody else — and "3 per school" cannot tell the two
    # apart, which is what catering, facilitation and reporting all need to
    # know. ``participants_per_school`` is the sum of these three and is
    # derived, never typed.
    #
    # Deliberately separate from the ``*_attended`` fields below: those are
    # what happened, recorded at completion. Storing a plan in an attendance
    # field is how a planned figure gets read as a verified one.
    teachers_per_school = models.IntegerField(null=True, blank=True)
    leaders_per_school = models.IntegerField(null=True, blank=True)
    other_per_school = models.IntegerField(null=True, blank=True)
    teachers_attended = models.IntegerField(null=True, blank=True)
    leaders_attended = models.IntegerField(null=True, blank=True)
    other_participants = models.IntegerField(null=True, blank=True)
    next_meeting_date = models.DateTimeField(null=True, blank=True)
    attended_school_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )

    class Meta:
        db_table = "activity"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school"]),
            models.Index(fields=["cluster"]),
            models.Index(fields=["catalogue_item", "fy", "status"]),
            models.Index(fields=["catalogue_item", "focus_intervention"]),
            models.Index(fields=["fy", "quarter"]),
            models.Index(fields=["responsible_staff_id"]),
            # The exact filter TargetAchievementService.rebuild() runs once
            # per user (CD/PL/RVP Analytics, My/Team Targets) — the
            # responsible_staff_id-only index above still needs a full
            # in-row filter on fy/activity_type for every matching row.
            models.Index(fields=["responsible_staff_id", "fy", "activity_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["scheduled_date"]),
            models.Index(fields=["assigned_partner_id"]),
            models.Index(fields=["ia_verification_status", "payment_status"]),
            models.Index(fields=["evidence_status"]),
            models.Index(fields=["daily_visit_batch"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(status="closed")
                | models.Q(
                    salesforce_record_type_snapshot__in=[
                        "NONE",
                        "SSA_DATA_GATHERING",
                    ]
                )
                | (
                    models.Q(salesforce_activity_id__isnull=False)
                    & ~models.Q(salesforce_activity_id="")
                ),
                name="closed_activity_must_have_sf_id",
            ),
            # The Salesforce Activity ID is the external system's unique key
            # for a piece of work. A hundred duplicate pairs existed with
            # nothing preventing them: two verified activities at one school
            # claiming the same external record, so IA verification and
            # finance could not tell them apart. Partial, so the many rows
            # legitimately awaiting an ID are unaffected.
            models.UniqueConstraint(
                fields=["salesforce_activity_id"],
                condition=models.Q(salesforce_activity_id__isnull=False)
                & ~models.Q(salesforce_activity_id="")
                & models.Q(deleted_at__isnull=True),
                name="uniq_activity_salesforce_id",
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("paired_school_visit")),
                name="activity_pair_cannot_reference_self",
            ),
        ]

    def save(self, *args, **kwargs):
        # ``scheduled_date`` is an instant, not a date-only planning field.
        # Normalize direct model/admin/import writes before Django prepares the
        # database value so a legacy naïve string or datetime cannot leak into
        # analytics, availability, or period boundaries.
        if self.scheduled_date is not None:
            self.scheduled_date = _normalize_datetime_value(self.scheduled_date)
        super().save(*args, **kwargs)
        try:
            from apps.core_schools.models import CoreActivitySlot
            from apps.core_schools.services import resync_plan_completion

            slot = CoreActivitySlot.objects.filter(activity_id=self.id).first()
            if slot:
                with transaction.atomic():
                    slot.status = self.status
                    if self.scheduled_date:
                        slot.scheduled_for = self.scheduled_date.date()
                    slot.save(update_fields=["status", "scheduled_for", "updated_at"])
                    # Keep the CorePlan's 4+4 package counters in lock-step
                    # with the slot's real, mirrored status (this is the real
                    # reachable path — see resync_plan_completion docstring).
                    resync_plan_completion(slot.core_plan)
        except Exception:
            # Never break an Activity save over the core-slot mirror, but a
            # silent pass here hid real drift (stale slots, wrong package
            # counters) — log it so System Health/ops can see the failures.
            import logging

            logging.getLogger(__name__).warning(
                "Core slot mirror resync failed for activity %s",
                self.id,
                exc_info=True,
            )


class ActivityScheduleCostLine(TimeStampedModel):
    """Persisted cost breakdown for a scheduled activity — sourced from
    CostSetting at schedule time so fund requests reconcile to the catalogue.

    This IS the activity budget line: one row per cost item (transport, lunch,
    venue, facilitation, meals...), each tracing to the catalogue version it was
    priced against. Amounts are integer UGX (whole shillings)."""

    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="schedule_cost_lines"
    )
    cost_setting_key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    # BigInteger like CostSetting.unit_cost and total_cost — the 32-bit
    # columns overflowed at ~UGX 2.1bn/line, reachable for a large
    # training × participants (2026-07-30 audit M-14).
    unit_cost = models.BigIntegerField()  # UGX, integer
    quantity = models.IntegerField(default=1)
    amount = models.BigIntegerField()  # UGX, integer
    cost_setting_version = models.IntegerField(default=1)
    # Catalogue provenance — the catalogue + version this line was priced from.
    catalogue_id = models.CharField(max_length=30, null=True, blank=True)
    catalogue_version = models.IntegerField(null=True, blank=True)
    activity_catalogue_item_id = models.CharField(max_length=30, null=True, blank=True)
    activity_catalogue_version = models.PositiveIntegerField(null=True, blank=True)
    costing_profile = models.CharField(max_length=64, null=True, blank=True)
    # Itemized line type (transport / breakfast / lunch / dinner / accommodation
    # / venue / facilitation / participant_meals / mobilisation / lump_sum ...).
    line_item_type = models.CharField(max_length=64, null=True, blank=True)
    # Finance pays this line's provider directly (hotel booked by Finance) —
    # it leaves the owner's staff advance and the owner sees a booking status
    # instead of the vendor amount. School-visit transport is ALWAYS vendor-
    # direct by rule (fund_requests.fundable.vendor_direct_filter); this flag
    # extends the channel to accommodation on Finance's decision.
    vendor_paid = models.BooleanField(default=False)
    currency = models.CharField(max_length=8, default="UGX")
    description = models.CharField(max_length=255, null=True, blank=True)
    total_cost = models.BigIntegerField(null=True, blank=True)
    planned_date = models.DateField(null=True, blank=True)
    week_start_date = models.DateField(null=True, blank=True)
    week_end_date = models.DateField(null=True, blank=True)
    month = models.IntegerField(null=True, blank=True)
    quarter = models.CharField(max_length=8, null=True, blank=True)
    fiscal_year = models.CharField(max_length=16, null=True, blank=True)
    responsible_user = models.CharField(max_length=30, null=True, blank=True)
    responsible_role = models.CharField(max_length=64, null=True, blank=True)
    school = models.ForeignKey(
        "schools.School", on_delete=models.SET_NULL, null=True, blank=True
    )
    cluster = models.ForeignKey(
        "clusters.Cluster", on_delete=models.SET_NULL, null=True, blank=True
    )
    partner = models.ForeignKey(
        "partners.Partner", on_delete=models.SET_NULL, null=True, blank=True
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True
    )

    @property
    def finance_status(self) -> str:
        """Resolve the dynamic financial status of the budget line from the 17-state lifecycle.

        Prefetch contract: list views must prefetch
        ``advance_requests`` and ``weekly_request_lines__weekly_fund_request``
        or every rendered row costs two queries. Access deliberately goes
        through ``list(...all())`` — ``.first()`` issues a fresh query even
        when the relation is prefetched (the audit's known trap)."""
        # 1. Check linked AdvanceRequest status first
        advances = list(self.advance_requests.all())
        adv = advances[0] if advances else None
        if adv:
            status = adv.status
            if status == "accounted":
                # Accountability isn't complete without the NetSuite reference:
                # missing ID is a blocking state, not a terminal one.
                if adv.accountability_netsuite_id:
                    return "Cleared"
                return "NetSuite ID Required"
            elif status == "disbursed":
                if self.activity.status == "ia_verified":
                    return "Accountability Pending"
                return "Disbursed"
            elif status == "confirmed_for_advance":
                return "Ready for Disbursement"
            elif status == "self_funded_pending_reimbursement":
                return "Execution Pending"
            elif status in (
                "accountability_pl_pending",
                "reimbursement_pl_pending",
            ):
                return "Awaiting PL Approval"
            elif status == "reimbursement_submitted":
                return "Reimbursement Pending"
            elif status == "returned":
                return "Returned"
            elif status == "cancelled":
                return "Rejected"

        # 2. Check WeeklyFundRequest status. These labels must track the
        # statuses weekly_service actually writes (submitted_to_pl/_cd,
        # confirmed_for_advance, returned_by_*, self_funded, not_requested…) —
        # an earlier vocabulary here checked names like "pending_pl_approval"
        # that no code ever wrote, so every line under approval displayed as
        # "Draft Costed" (2026-08-12 audit M-5).
        wfr_lines = list(self.weekly_request_lines.all())
        wfr_line = wfr_lines[0] if wfr_lines else None
        if wfr_line:
            wfr = wfr_line.weekly_fund_request
            status = wfr.status
            if status == "pending_responsible_confirmation":
                return "Included in Weekly Request"
            elif status in ("submitted_to_pl", "submitted_to_cd"):
                return "Submitted for Approval"
            elif status == "confirmed_for_advance":
                return "Ready for Disbursement"
            elif status == "disbursed":
                return "Disbursed"
            elif status in (
                "returned_by_pl",
                "returned_by_cd",
                "returned_by_accountant",
            ):
                return "Returned"
            elif status == "self_funded":
                return "Self-funded"
            elif status == "not_requested":
                return "Not Requested"

        # 3. Check Activity execution status
        if self.activity.status == "completed":
            return "Evidence Submitted"
        elif self.activity.status == "ia_verified":
            return "IA Verified"

        return "Draft Costed"

    class Meta:
        db_table = "activity_schedule_cost_line"
        indexes = [models.Index(fields=["activity"])]
        constraints = [
            # One cost component per activity per catalogue key — the writer
            # (apply_to_activity) already guarantees this via delete+rebuild;
            # the constraint makes the database enforce it against any future
            # second writer (2026-07-30 audit M-15).
            models.UniqueConstraint(
                fields=["activity", "cost_setting_key"],
                name="uniq_cost_component_per_activity",
                # Empty-key rows are already their own violation (a cost line
                # without a catalogue source) surfaced by the health checks —
                # excluding them keeps this constraint applyable on legacy
                # data without weakening the real invariant.
                condition=~models.Q(cost_setting_key=""),
            )
        ]


class SalesforceEntrySource(models.TextChoices):
    """Who supplied an Activity Salesforce ID, for audit and duplicate-
    investigation purposes (2026-07-15 preventive-verification mandate)."""

    STAFF_SELF_ENTRY = "staff_self_entry", "Staff self-entry"
    MANAGING_STAFF_FOR_PARTNER = (
        "managing_staff_for_partner",
        "Managing staff (for Partner activity)",
    )
    LEGACY_IMPORT = "legacy_import", "Legacy import"
    ADMIN_EXCEPTION = "admin_exception", "Admin exception"


class ActivitySalesforceReference(TimeStampedModel):
    """The duplicate-prevention registry for Activity Salesforce IDs — proof
    a completed field activity (visit or training) was entered into
    Salesforce. Never to be confused with the platform School ID (SSA CSV
    matching), a School's own Salesforce ID, or the NetSuite Expense ID
    (financial accountability) — those are separate identifiers on separate
    models.

    normalized_value carries the single-Salesforce-organization global
    uniqueness constraint (see apps.activities.salesforce module docstring
    for why); raw_value preserves exactly what was typed/pasted, for audit.
    Only apps.activities.salesforce.reserve_salesforce_id() may write this
    model — no other code path should create or update a row here."""

    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="salesforce_reference"
    )
    raw_value = models.CharField(max_length=128)
    normalized_value = models.CharField(max_length=128, unique=True)
    activity_type = models.CharField(max_length=48)
    expected_prefix = models.CharField(max_length=8)
    entry_source = models.CharField(
        max_length=32, choices=SalesforceEntrySource.choices
    )
    entered_by = models.CharField(max_length=30)
    entered_at = models.DateTimeField()

    class Meta:
        db_table = "activity_salesforce_reference"
        indexes = [models.Index(fields=["normalized_value"])]


class ActivityCompletionVerification(TimeStampedModel):
    """Manual Salesforce SV-/TS- ID confirmation (IA verifies the entry)."""

    id = CuidField()
    activity = models.OneToOneField(
        Activity, on_delete=models.CASCADE, related_name="verification"
    )
    salesforce_id = models.CharField(max_length=128)  # SV- or TS-
    entered_by = models.CharField(max_length=30)  # responsible staff userId
    entered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    ia_actor_id = models.CharField(max_length=30, null=True, blank=True)
    ia_action_at = models.DateTimeField(null=True, blank=True)
    ia_note = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "activity_completion_verification"


from .ia_models import (  # noqa: E402 — circular import, must load after Activity is defined
    IAVerification,
    VerificationChecklist,
    VerificationComment,
    VerificationDecision,
    ReturnedReason,
    DuplicateActivity,
    VerificationHistory,
)
from .closure_models import (  # noqa: E402 — circular import, must load after Activity is defined
    ActivityClosure,
    ClosureChecklist,
    ClosureBlocker,
    CompletedActivitySnapshot,
    ActivityReopenRequest,
    AnalyticsPublishRecord,
    ActivityTimelineEvent,
)


class ClusterActivityAttendance(TimeStampedModel):
    """One row per school at a cluster training or meeting.

    A cluster session has no school FK — it belongs to the cluster — so
    without this table the work it delivered is invisible on every school that
    sat in the room. That is the gap this closes: the school profile, the
    trained/not-trained counts and follow-up eligibility all need to know
    which schools were actually there.

    Invitation and attendance are separate columns on purpose. A cluster
    invitation is not attendance, and crediting a school for a session it was
    invited to but never reached would be a planned figure read as a verified
    one. `invited` is ticked when the session is scheduled; `attended` is
    confirmed by the person who delivered it.

    The composition columns default to the activity's uniform per-school
    figures, so the ordinary case stays a tick. They exist per row because a
    guest school from another cluster brings its own numbers, which a single
    activity-level figure cannot express.
    """

    activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.CASCADE,
        related_name="school_attendance",
    )
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="cluster_attendance",
    )

    invited = models.BooleanField(default=False)
    attended = models.BooleanField(default=False)

    #: Outside the activity's own cluster. Kept as a flag rather than derived
    #: on read, because cluster membership changes and a guest at an August
    #: session must still read as a guest in November. It also keeps guests
    #: visible to IA instead of blended into the member list — the review gap
    #: that the server-side member filter was protecting against.
    is_guest = models.BooleanField(default=False)

    teachers = models.IntegerField(null=True, blank=True)
    leaders = models.IntegerField(null=True, blank=True)
    other = models.IntegerField(null=True, blank=True)

    recorded_by = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        db_table = "cluster_activity_attendance"
        ordering = ["school__name"]
        constraints = [
            # One row per school per activity. Attendance is a fact about a
            # school being in a room, and a school cannot be in it twice —
            # ["S1","S1","S1"] must credit S1 once.
            models.UniqueConstraint(
                fields=["activity", "school"],
                name="uniq_cluster_attendance_per_school",
            ),
        ]
        indexes = [
            # "Which schools attended this session?" — the completion drawer
            # and IA's review workspace.
            models.Index(fields=["activity", "attended"]),
            # "Was this school trained this year?" — the school profile and
            # every trained/not-trained count. This is the join that replaces
            # scanning an array column.
            models.Index(fields=["school", "attended"]),
        ]

    def __str__(self) -> str:
        return f"{self.school_id} @ {self.activity_id}"


__all__ = [
    "Activity",
    "ClusterActivityAttendance",
    "ActivityScheduleCostLine",
    "SalesforceEntrySource",
    "ActivitySalesforceReference",
    "ActivityCompletionVerification",
    "IAVerification",
    "VerificationChecklist",
    "VerificationComment",
    "VerificationDecision",
    "ReturnedReason",
    "DuplicateActivity",
    "VerificationHistory",
    "ActivityClosure",
    "ClosureChecklist",
    "ClosureBlocker",
    "CompletedActivitySnapshot",
    "ActivityReopenRequest",
    "AnalyticsPublishRecord",
    "ActivityTimelineEvent",
]
