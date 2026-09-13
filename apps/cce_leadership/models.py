"""The Regional Lead for Christ-Centered Education's own records (owner, 2026-09-13).

The role description names the work: meet the country Programme Leads to
coach them, observe and constructively critique trainings, meet Country
Directors every quarter and once a year before the next budget, keep a rhythm
with the VP of CCE, the other Regional Leads and the RVP, stay close to
schools, partners and networks, and send the RVP and the VP of CCE a monthly
report built on the region's metrics.

None of that is planned work. An engagement carries no cost, enters no fund
request and sits on nobody's calendar, which is why the role records it while
still planning, funding and verifying nothing (apps.core.rbac,
apps.planning.test_regional_program_lead).
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import CuidField, TimeStampedModel


class EngagementKind(models.TextChoices):
    PL_COACHING = "pl_coaching", "Programme Lead coaching"
    TRAINING_OBSERVATION = "training_observation", "Training observation"
    CD_QUARTERLY_REVIEW = (
        "cd_quarterly_review",
        "Quarterly review with a Country Director",
    )
    CD_ANNUAL_PLANNING = (
        "cd_annual_planning",
        "Annual programming and budget input",
    )
    VP_CCE_CHECKIN = "vp_cce_checkin", "Check-in with the VP of CCE"
    REGIONAL_LEADS_MEETING = (
        "regional_leads_meeting",
        "Regional Leads and VP of CCE meeting",
    )
    RVP_MEETING = "rvp_meeting", "Meeting with the RVP"
    CROSS_REGION_CONVENING = (
        "cross_region_convening",
        "Cross-region Programme Lead convening",
    )
    SITE_VISIT = "site_visit", "School site visit"
    PARTNER_NETWORK = (
        "partner_network",
        "Training partner or school network meeting",
    )
    PRAYER_EVENT = "prayer_event", "Prayer event"


class ObservationRecommendation(models.TextChoices):
    """What the lead advises after watching a training (role description:
    "replace trainings as needed, provide constructive feedback to training
    partners, economize the delivery of trainings")."""

    CONTINUE = "continue", "Continue as delivered"
    STRENGTHEN = "strengthen", "Strengthen with the training partner"
    REPLACE = "replace", "Replace the training"
    ECONOMIZE = "economize", "Economize the delivery"


# The observation rubric, in the order the drawer asks it. Each criterion is
# one of the role's lenses on a training: Edify's Biblical integration
# framework, the SSA need the training should answer, and the coaching and
# deliberate-practice standards the lead is asked to strengthen.
OBSERVATION_CRITERIA: tuple[tuple[str, str, str], ...] = (
    (
        "rating_biblical_integration",
        "Biblical integration",
        "Christ-centered values are woven through the content, not added on.",
    ),
    (
        "rating_need_alignment",
        "Answers the schools' SSA need",
        "The content targets the needs the schools' SSA results show.",
    ),
    (
        "rating_facilitation",
        "Facilitation quality",
        "Clear, well paced and modelled on good teaching practice.",
    ),
    (
        "rating_participation",
        "Participant engagement",
        "Teachers and leaders practise, question and contribute.",
    ),
    (
        "rating_application",
        "Practical application in schools",
        "Participants leave with practice they can use and be coached on.",
    ),
)

RATING_SCALE: tuple[tuple[int, str], ...] = (
    (1, "1 · Not evident"),
    (2, "2 · Emerging"),
    (3, "3 · Established"),
    (4, "4 · Exemplary"),
)


class RegionalEngagement(TimeStampedModel):
    """One conversation, meeting, visit or observation the lead held."""

    id = CuidField()
    author_id = models.CharField(max_length=30, db_index=True)
    kind = models.CharField(max_length=32, choices=EngagementKind.choices)
    held_on = models.DateField()
    fy = models.CharField(max_length=16, db_index=True)
    # Full country name, the convention every country-scoped table uses.
    country = models.CharField(max_length=64, blank=True, default="")
    # StaffProfile ids of the Programme Leads the engagement concerns.
    program_lead_ids = ArrayField(
        models.CharField(max_length=30), default=list, blank=True
    )
    subject = models.CharField(max_length=255)
    notes = models.TextField(blank=True, default="")
    agreed_actions = models.TextField(blank=True, default="")
    follow_up_due = models.DateField(null=True, blank=True)

    # ── Training observation ────────────────────────────────────────────────
    activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cce_observations",
    )
    rating_biblical_integration = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    rating_need_alignment = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_facilitation = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_participation = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_application = models.PositiveSmallIntegerField(null=True, blank=True)
    recommendation = models.CharField(
        max_length=16,
        choices=ObservationRecommendation.choices,
        blank=True,
        default="",
    )
    feedback = models.TextField(blank=True, default="")
    feedback_shared_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_id = models.CharField(max_length=30, null=True, blank=True)
    lead_response = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cce_regional_engagement"
        ordering = ["-held_on", "-created_at"]
        indexes = [
            models.Index(
                fields=["author_id", "kind", "held_on"],
                name="idx_cce_engagement_author",
            ),
            models.Index(
                fields=["country", "kind", "held_on"],
                name="idx_cce_engagement_country",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(rating_biblical_integration__isnull=True)
                        | Q(rating_biblical_integration__range=(1, 4))
                    )
                    & (
                        Q(rating_need_alignment__isnull=True)
                        | Q(rating_need_alignment__range=(1, 4))
                    )
                    & (
                        Q(rating_facilitation__isnull=True)
                        | Q(rating_facilitation__range=(1, 4))
                    )
                    & (
                        Q(rating_participation__isnull=True)
                        | Q(rating_participation__range=(1, 4))
                    )
                    & (
                        Q(rating_application__isnull=True)
                        | Q(rating_application__range=(1, 4))
                    )
                ),
                name="cce_engagement_ratings_one_to_four",
            ),
        ]

    @property
    def is_observation(self) -> bool:
        return self.kind == EngagementKind.TRAINING_OBSERVATION

    @property
    def ratings(self) -> list[int]:
        return [
            value
            for value in (
                getattr(self, field) for field, _l, _h in OBSERVATION_CRITERIA
            )
            if value
        ]

    @property
    def average_rating(self) -> float | None:
        ratings = self.ratings
        return round(sum(ratings) / len(ratings), 1) if ratings else None


class ReportStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RETURNED = "returned", "Returned for revision"


# The report's written sections, in the order of the RVP and VP of CCE's
# template (role description, Tools): an executive summary, then the key
# metric areas, then what the region needs.
REPORT_SECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "executive_summary",
        "Executive summary",
        "The month in a paragraph: progress, concerns and decisions needed.",
    ),
    (
        "training_programmes",
        "Training programmes",
        "Trainings delivered, observed, replaced or improved, and why.",
    ),
    (
        "cce_impact",
        "Christ-centered education impact",
        "What SSA results and school follow-up show about change in schools.",
    ),
    (
        "curriculum_development",
        "Curriculum development",
        "Training materials reviewed, created or revised with Programme Leads.",
    ),
    (
        "programme_initiatives",
        "Programme initiatives",
        "School networks, PLCs, coaching practice and new strategies.",
    ),
    (
        "partnerships",
        "New partnerships",
        "Training partners and Christian school networks engaged.",
    ),
    (
        "support_needed",
        "Support needed",
        "What the region needs from the RVP and the VP of CCE.",
    ),
)


class RegionalCceReport(TimeStampedModel):
    """The lead's monthly report to the RVP and the VP of CCE."""

    id = CuidField()
    author_id = models.CharField(max_length=30, db_index=True)
    # The first day of the reported month.
    period = models.DateField()
    fy = models.CharField(max_length=16, db_index=True)
    countries = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.DRAFT
    )
    executive_summary = models.TextField(blank=True, default="")
    training_programmes = models.TextField(blank=True, default="")
    cce_impact = models.TextField(blank=True, default="")
    curriculum_development = models.TextField(blank=True, default="")
    programme_initiatives = models.TextField(blank=True, default="")
    partnerships = models.TextField(blank=True, default="")
    support_needed = models.TextField(blank=True, default="")
    # The region's figures for the month, frozen when the report is submitted
    # so a later correction to the data cannot rewrite what was reported.
    metrics = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cce_regional_report"
        ordering = ["-period", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["author_id", "period"], name="uniq_cce_report_author_month"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "period"], name="idx_cce_report_status"),
        ]


# ── The Programme Lead's records, one level down (owner, 2026-09-13) ─────────
# The Programme Lead's role description asks them to supervise, coach and
# review the Christ-Centered Education Officers they line-manage, and to lead
# priority setting and communication for CCE initiatives in the country. The
# Regional Lead's engagement log above coaches Programme Leads; these records
# carry the same practice to the officers, and — like an engagement — none of
# it is planned work: no cost, no fund request, no calendar entry.


class CoachingKind(models.TextChoices):
    ONE_TO_ONE = "one_to_one", "Monthly one-to-one"
    FIELD_OBSERVATION = "field_observation", "School visit observation"
    TRAINING_OBSERVATION = "training_observation", "Training observation"
    PERFORMANCE_CHECKIN = "performance_checkin", "Performance check-in"
    DEBRIEF_FEEDBACK = "debrief_feedback", "Field debrief feedback"
    RECOGNITION = "recognition", "Recognition"
    REGIONAL_FEEDBACK = (
        "regional_feedback",
        "Regional Lead feedback passed on",
    )


# Kinds that watch the officer deliver, and so take the observation rubric.
OBSERVED_COACHING_KINDS = frozenset(
    {
        CoachingKind.FIELD_OBSERVATION,
        CoachingKind.TRAINING_OBSERVATION,
        CoachingKind.REGIONAL_FEEDBACK,
    }
)


def _ratings_one_to_four(prefix: str) -> models.CheckConstraint:
    condition = Q()
    for field, _label, _help in OBSERVATION_CRITERIA:
        condition &= Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__range": (1, 4)})
    return models.CheckConstraint(condition=condition, name=f"{prefix}_one_to_four")


class CceoCoaching(TimeStampedModel):
    """One coaching conversation, observation or piece of feedback a Programme
    Lead gives an officer they supervise. Shared records reach the officer, who
    acknowledges them with a response."""

    id = CuidField()
    # User id of the Programme Lead who held it.
    author_id = models.CharField(max_length=30, db_index=True)
    cceo_staff_id = models.CharField(max_length=30, db_index=True)
    cceo_user_id = models.CharField(max_length=30, db_index=True)
    kind = models.CharField(max_length=32, choices=CoachingKind.choices)
    held_on = models.DateField()
    fy = models.CharField(max_length=16, db_index=True)
    country = models.CharField(max_length=64, blank=True, default="")
    subject = models.CharField(max_length=255)
    strengths = models.TextField(blank=True, default="")
    growth_areas = models.TextField(blank=True, default="")
    agreed_actions = models.TextField(blank=True, default="")
    follow_up_due = models.DateField(null=True, blank=True)

    # What was observed or answered, when there is a record to point at.
    activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cceo_coaching",
    )
    debrief = models.ForeignKey(
        "debriefs.DailyDebrief",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coaching",
    )
    source_engagement = models.ForeignKey(
        RegionalEngagement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="passed_to_cceos",
    )

    rating_biblical_integration = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    rating_need_alignment = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_facilitation = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_participation = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_application = models.PositiveSmallIntegerField(null=True, blank=True)

    shared_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    cceo_response = models.TextField(blank=True, default="")
    follow_up_done_at = models.DateTimeField(null=True, blank=True)
    follow_up_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cce_cceo_coaching"
        ordering = ["-held_on", "-created_at"]
        indexes = [
            models.Index(
                fields=["author_id", "held_on"], name="idx_cceo_coaching_author"
            ),
            models.Index(
                fields=["cceo_staff_id", "held_on"], name="idx_cceo_coaching_cceo"
            ),
            models.Index(
                fields=["country", "held_on"], name="idx_cceo_coaching_country"
            ),
        ]
        constraints = [_ratings_one_to_four("cceo_coaching_ratings")]

    @property
    def is_observation(self) -> bool:
        return self.kind in OBSERVED_COACHING_KINDS

    @property
    def is_shared(self) -> bool:
        return self.shared_at is not None

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None

    @property
    def ratings(self) -> list[int]:
        return [
            value
            for value in (
                getattr(self, field) for field, _l, _h in OBSERVATION_CRITERIA
            )
            if value
        ]

    @property
    def average_rating(self) -> float | None:
        ratings = self.ratings
        return round(sum(ratings) / len(ratings), 1) if ratings else None


class TeamGuidance(TimeStampedModel):
    """Priority guidance a Programme Lead issues to the officers they supervise:
    what to do about a country priority, and the change expected in schools.
    Each recipient acknowledges it (TeamGuidanceReceipt)."""

    id = CuidField()
    author_id = models.CharField(max_length=30, db_index=True)
    fy = models.CharField(max_length=16, db_index=True)
    country = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=200)
    priority = models.ForeignKey(
        "hr.StrategicPriority",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_guidance",
    )
    milestone = models.ForeignKey(
        "hr.PriorityMilestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="team_guidance",
    )
    instruction = models.TextField()
    expected_change = models.TextField(blank=True, default="")
    review_on = models.DateField(null=True, blank=True)
    # Null while the lead is still drafting; set once it reaches the team.
    issued_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cce_team_guidance"
        ordering = ["-issued_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["author_id", "issued_at"], name="idx_team_guidance_author"
            ),
        ]

    @property
    def is_issued(self) -> bool:
        return self.issued_at is not None and self.withdrawn_at is None


class TeamGuidanceReceipt(TimeStampedModel):
    id = CuidField()
    guidance = models.ForeignKey(
        TeamGuidance, on_delete=models.CASCADE, related_name="receipts"
    )
    recipient_staff_id = models.CharField(max_length=30, db_index=True)
    recipient_user_id = models.CharField(max_length=30, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    response = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cce_team_guidance_receipt"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["guidance", "recipient_staff_id"],
                name="uniq_team_guidance_recipient",
            ),
        ]
