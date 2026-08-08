"""Partners models — the partner-org directory + self-service link."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class Partner(SoftDeleteModel):
    """A partner organization (trains/supports schools on Edify's behalf)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    region_name = models.CharField(max_length=255, null=True, blank=True)
    trains_on = ArrayField(
        base_field=models.CharField(max_length=128), default=list, blank=True
    )
    notes = models.TextField(null=True, blank=True)
    # CD onboarding profile: eligibility, coverage, contract.
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=64, null=True, blank=True)
    coverage_districts = ArrayField(
        base_field=models.CharField(max_length=255), default=list, blank=True
    )
    contract_status = models.CharField(
        max_length=32, null=True, blank=True
    )  # active|pending|expired|none
    onboarded_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    # Certification (drives staff-vs-certified-partner contribution correlation).
    is_certified = models.BooleanField(default=False)
    certification_status = models.CharField(max_length=32, null=True, blank=True)
    expertise_areas = ArrayField(
        base_field=models.CharField(max_length=128), default=list, blank=True
    )
    ssa_intervention = models.CharField(max_length=64, null=True, blank=True)
    active_status = models.BooleanField(default=True)
    # Backend login link — a partner field officer authenticates as this user.
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner",
    )

    class Meta:
        db_table = "partner"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def ssa_intervention_label(self) -> str:
        if not self.ssa_intervention:
            return "General Support"
        from apps.core.enums import SsaIntervention

        try:
            return SsaIntervention(self.ssa_intervention).label
        except ValueError:
            return self.ssa_intervention.replace("_", " ").title()


class PartnerReturnReason(models.TextChoices):
    """Why a partner cannot take an assignment.

    Deliberately short and closed. The point of the category is to let staff
    triage a queue of returns without reading every explanation — "school
    unavailable" and "outside agreed scope" need different responses from the
    managing staff, and free text alone does not sort.
    """

    SCHEDULE_CONFLICT = "schedule_conflict", "Schedule conflict"
    DISTANCE = "distance", "Distance or travel constraint"
    SCHOOL_UNAVAILABLE = "school_unavailable", "School unavailable"
    CAPACITY = "capacity", "Insufficient capacity"
    OUT_OF_SCOPE = "out_of_scope", "Assignment outside agreed scope"
    DUPLICATE = "duplicate", "Duplicate assignment"
    INCORRECT_DETAILS = "incorrect_details", "Incorrect school or activity"
    SAFETY = "safety", "Safety or access concern"
    OTHER = "other", "Other"


class PartnerAssignment(TimeStampedModel):
    """Tracks assignment of a school or cluster to a partner organization for interventions."""

    # The states an assignment moves through. `status` was a bare CharField and
    # four spellings of the same idea reached the database from different
    # creation sites — "assigned", "pending_scheduling", "assigned_to_partner",
    # "partner_assigned". Both unscheduled spellings are kept because both are
    # live in production data; UNSCHEDULED_STATUSES is the one place that
    # decides what "not yet scheduled" means, so callers stop re-listing them.
    STATUS_ASSIGNED = "assigned"
    STATUS_PENDING_SCHEDULING = "pending_scheduling"
    STATUS_SCHEDULED = "scheduled"
    STATUS_RETURNED_TO_STAFF = "returned_to_staff"
    UNSCHEDULED_STATUSES = (STATUS_ASSIGNED, STATUS_PENDING_SCHEDULING)

    id = CuidField()
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="partner_assignments",
    )
    cluster = models.ForeignKey(
        "clusters.Cluster",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="partner_assignments",
    )
    partner = models.ForeignKey(
        Partner, on_delete=models.CASCADE, related_name="school_assignments"
    )
    assigning_staff_id = models.CharField(max_length=30, null=True, blank=True)
    # Who watches the delivery, as distinct from who handed it over. These
    # used to be one column, so a PL handing off a CCEO's school made the PL
    # the monitor and the partner's work never reached the owning CCEO's My
    # Plan — the person who actually knows the school saw nothing.
    #
    # Nullable and read with a fallback to assigning_staff_id, so every row
    # written before this existed keeps resolving to exactly what it resolved
    # to before.
    monitoring_staff_id = models.CharField(max_length=30, null=True, blank=True)
    assignment_mode = models.CharField(
        max_length=32,
        choices=[
            ("specific_activity", "Specific Activity"),
            ("intervention_choice", "Intervention-based choice"),
        ],
        default="specific_activity",
    )
    catalogue_item = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="partner_assignments",
    )
    allowed_catalogue_items = models.ManyToManyField(
        "activity_catalogue.ActivityCatalogueItem",
        blank=True,
        related_name="partner_choice_assignments",
    )
    source_ssa = models.ForeignKey(
        "ssa.SsaRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="partner_assignments",
    )
    source_activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="derived_partner_assignments",
    )
    # The activity the PARTNER created when it scheduled this assignment, as
    # distinct from source_activity, which is the staff activity the assignment
    # came FROM. Until this existed the only way to pair the two was to guess:
    # same partner, same school, status looks scheduled. Oversight has to state
    # that an assignment and the activity it became are one item and not two,
    # and a guess cannot carry that — a partner with two assignments at one
    # school made both pairings ambiguous, and every count and every shilling
    # downstream inherited the ambiguity.
    #
    # SET_NULL rather than CASCADE: deleting the activity must not delete the
    # assignment record, which is the history of the handover.
    scheduled_activity = models.OneToOneField(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="originating_partner_assignment",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activity_partner_assignments",
    )
    recommendation_reason = models.TextField(blank=True)
    override_reason = models.TextField(blank=True)
    catalogue_snapshot = models.JSONField(default=dict, blank=True)
    purpose = models.TextField(null=True, blank=True)
    focus_intervention = models.CharField(max_length=64, null=True, blank=True)
    # Plain-language reason selected when staff hand the work to a partner.
    # This is intentionally separate from expected_activity_type, which is
    # the operational/costing classification used by the activity workflow.
    purpose_of_visit = models.CharField(max_length=64, null=True, blank=True)
    expected_activity_type = models.CharField(max_length=64, null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, default="assigned")
    notes = models.TextField(null=True, blank=True)

    # ── Return to staff ──────────────────────────────────────────────────────
    # A partner who cannot take an assignment could previously do nothing with
    # it: the queue offered Schedule and nothing else, so the only ways out
    # were to schedule work that would not happen, or to leave the row sitting
    # there. Staff learnt about it by noticing the silence.
    #
    # These stay on the assignment rather than moving to a separate table: the
    # return is a state of the assignment, and staff triaging the queue need
    # the reason on the row they are looking at. Reassignment creates a new
    # assignment, so the returned one keeps its reason as history.
    return_reason_category = models.CharField(
        max_length=32,
        choices=PartnerReturnReason.choices,
        null=True,
        blank=True,
    )
    return_reason = models.TextField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    # User id of the partner user who returned it, matching the CharField
    # convention already used by assigning_staff_id rather than a FK.
    returned_by = models.CharField(max_length=30, null=True, blank=True)

    # Core Schools tracking fields
    visit_number = models.CharField(max_length=16, null=True, blank=True)
    training_number = models.CharField(max_length=16, null=True, blank=True)
    support_type = models.CharField(max_length=32, null=True, blank=True)

    # ── Reassignment lineage ─────────────────────────────────────────────────
    # When work is taken back from one partner and given to another, the old
    # assignment is NOT edited to name the new partner. It stays exactly as it
    # was — that is the history of what the first partner was asked to do — and
    # a new assignment is created pointing back at it.
    #
    # Two consequences worth stating, because both are the reason for doing it
    # this way rather than in place:
    #
    #   * the school does not acquire a second entitlement. The replacement
    #     carries the same slot identifiers (school, support_type, visit or
    #     training number, project) and the withdrawn one no longer counts, so
    #     exactly one assignment holds the slot at any moment.
    #   * the replacement starts with no activity and no cost. The price
    #     depends on who schedules it and when, so it cannot be known until the
    #     new partner picks a date.
    replaces_assignment = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_by",
    )
    # 0 for an assignment nobody has replaced, 1 for the first replacement, and
    # so on. Denormalised so "this school has been through three partners" is
    # answerable without walking the chain.
    reassignment_sequence = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        """Refuse a NEW assignment to a partner who is on hold.

        At the model rather than at each call site: there are seven places
        that create assignments — planning, clusters, core schools, projects,
        bulk actions — and a guard in six of them is a guard in none. A hidden
        dropdown option is not a rule either; the direct URL and the API reach
        this too.

        Insert only. An existing assignment continues untouched, which is the
        entire distinction between holding a partner and withdrawing their
        work.
        """
        if self._state.adding and self.partner_id:
            from apps.partners.withdrawal_service import (
                assert_partner_accepts_new_work,
            )

            assert_partner_accepts_new_work(self.partner_id)
        return super().save(*args, **kwargs)

    class Meta:
        db_table = "partner_assignment"
        ordering = ["-created_at"]


class PartnerActivityAllowance(TimeStampedModel):
    """Auditable grant of ADDITIONAL partner activities for one school.

    Default policy (production mandate §F): one non-core activity per partner
    per school per FY. Core package slots are governed by the nine-slot
    CorePlan instead and are exempt. Every activity beyond the default
    requires one of these grants — who allowed it, why, and for how long."""

    id = CuidField()
    partner = models.ForeignKey(
        Partner, on_delete=models.CASCADE, related_name="activity_allowances"
    )
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="partner_activity_allowances",
    )
    fy = models.CharField(max_length=16)
    additional_activities = models.PositiveIntegerField(default=1)
    activity_type = models.CharField(max_length=64, null=True, blank=True)
    granted_by = models.CharField(max_length=30)
    reason = models.TextField()
    expires_at = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "partner_activity_allowance"
        ordering = ["-created_at"]


__all__ = ["Partner", "PartnerAssignment", "PartnerActivityAllowance"]


# The withdrawal record and its vocabularies live in their own module — the
# lifecycle of taking work back is a subject of its own, and inlining ~300
# lines of it here would bury the assignment model it hangs off. Imported so
# Django's app registry sees it.
from apps.partners.withdrawal_models import (  # noqa: E402,F401
    OPEN_WITHDRAWAL_STATES,
    REASON_ATTRIBUTION,
    RESTRICTED_PARTNER_MESSAGE,
    RESTRICTED_REASONS,
    PartnerAssignmentWithdrawal,
    PartnerHold,
    WithdrawalAttribution,
    WithdrawalDisposition,
    WithdrawalKind,
    WithdrawalReason,
    WithdrawalState,
)
