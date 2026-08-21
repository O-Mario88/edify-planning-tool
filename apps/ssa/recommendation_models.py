"""A recommendation that exists as a record, not only as a calculation.

`recommendation_engine` decides what a school needs, and decides it well:
confirmed assessments only, renormalised weights, min-N honesty, a
deterministic tie-break. But it returned plain dictionaries, recomputed on
every request and kept nowhere. That is enough to DISPLAY a recommendation and
not enough to be accountable for one.

Without a row there is no status, so nothing can be deferred or rejected with
a reason. There is no owner, so nothing is anyone's to answer for. There is no
expiry, so nothing goes stale. There is no dedupe key, so the same
recommendation reappears on every page load after somebody has already acted
on it. And there is no record at all of a recommendation nobody accepted —
which is precisely the one leadership needs to see.

So: "what did we recommend last month, and what happened to it" had no answer.
This gives it one.

The shape follows `planning.TeamAction`, which already solved this exact
problem for school actions: a `condition_key` identifying the NEED rather than
the row, a partial unique constraint so only one live recommendation per need
can exist, and `supersedes` so a genuine recurrence links back instead of
reopening history and destroying its dates.
"""

from __future__ import annotations

from django.db import models

from apps.core.enums import SsaIntervention
from apps.core.models import CuidField, TimeStampedModel


class RecommendationState(models.TextChoices):
    """Lifecycle. GENERATED..PLANNED are all *live* — see LIVE_STATES.

    DEFERRED is deliberately live: postponing a need is a decision about
    timing, not a decision that the need has gone away, and a deferred
    recommendation must keep its place in the queue rather than vanish.
    """

    GENERATED = "generated", "Generated"
    ACCEPTED = "accepted", "Accepted for planning"
    DEFERRED = "deferred", "Deferred"
    PLANNED = "planned", "Planned"
    REJECTED = "rejected", "Rejected"
    SUPERSEDED = "superseded", "Superseded"
    DELIVERED = "delivered", "Delivered and verified"


#: States in which the need is still outstanding, so the engine must NOT emit a
#: second recommendation for it. DELIVERED is absent: the work happened, and if
#: the weakness returns at the next assessment that is a new need with its own
#: detected-at date, linked back through `supersedes`.
#:
#: A tuple, not a set: this feeds the partial unique constraint below, and an
#: unordered collection serialises in a different order every run, so
#: `makemigrations` would propose dropping and recreating the constraint
#: forever.
LIVE_STATES = (
    RecommendationState.GENERATED,
    RecommendationState.ACCEPTED,
    RecommendationState.DEFERRED,
    RecommendationState.PLANNED,
)

#: States that close a recommendation without the work being done. Kept
#: separate from DELIVERED so "we decided not to" and "we did it" never
#: collapse into one number in a report.
CLOSED_UNDONE = (RecommendationState.REJECTED, RecommendationState.SUPERSEDED)


class SsaRecommendation(TimeStampedModel):
    """One intervention this school needs, and what became of it."""

    id = CuidField()

    # ── The need ────────────────────────────────────────────────────────────
    #: Identity of the NEED, not of this row: school + FY + intervention. The
    #: partial unique constraint below uses it so a repeated generation run is
    #: idempotent rather than duplicating, and so two officers cannot both
    #: raise the same need.
    condition_key = models.CharField(max_length=255, db_index=True)

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="ssa_recommendations",
    )
    #: PROTECT, not CASCADE: the assessment is the evidence for the
    #: recommendation, and deleting it would leave a decision with no basis.
    ssa_record = models.ForeignKey(
        "ssa.SsaRecord",
        on_delete=models.PROTECT,
        related_name="recommendations",
    )
    intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, db_index=True
    )
    fy = models.CharField(max_length=16, db_index=True)

    # ── The evidence, frozen ────────────────────────────────────────────────
    # Denormalised on purpose. A later assessment changes the school's scores;
    # it must not retroactively change what this recommendation was made on.
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    score_band = models.CharField(max_length=32, blank=True, default="")
    rank = models.IntegerField(default=0)
    #: Why this ranked where it did, in the user's language. A ranking nobody
    #: can explain is a ranking nobody can challenge.
    reason = models.TextField(blank=True, default="")

    # ── The proposal ────────────────────────────────────────────────────────
    recommended_item = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ssa_recommendations",
    )
    #: Set when the intervention has no school-level catalogue response, so the
    #: gap is visible rather than the recommendation silently not appearing.
    unmapped_reason = models.CharField(max_length=255, blank=True, default="")

    # ── Lifecycle ───────────────────────────────────────────────────────────
    state = models.CharField(
        max_length=32,
        choices=RecommendationState.choices,
        default=RecommendationState.GENERATED,
        db_index=True,
    )
    owner_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    decided_by_id = models.CharField(max_length=30, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    #: Required to defer or reject. A decision not to act on a measured
    #: weakness is exactly the decision that needs a stated reason.
    decision_reason = models.TextField(blank=True, default="")

    #: When this stops being current. An assessment ages; a recommendation
    #: built on it should not sit in a queue forever pretending otherwise.
    expires_on = models.DateField(null=True, blank=True)

    #: The activity that answered it, once one exists.
    planned_activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="answered_ssa_recommendations",
    )

    #: A recurrence points back at the recommendation that closed last time, so
    #: "this school keeps needing the same thing" is answerable.
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    #: The engine build that produced this. Weights change; a provenance record
    #: that cannot say which formula it came from silently reinterprets itself.
    engine_version = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        app_label = "ssa"
        db_table = "ssa_recommendation"
        indexes = [
            models.Index(fields=["school", "state"], name="idx_ssarec_school_state"),
            models.Index(fields=["fy", "state"], name="idx_ssarec_fy_state"),
            models.Index(fields=["owner_id", "state"], name="idx_ssarec_owner_state"),
        ]
        constraints = [
            # One live recommendation per need. This is what makes generation
            # idempotent: running it twice converges instead of duplicating,
            # and a need already being worked never reappears as though new.
            models.UniqueConstraint(
                fields=["condition_key"],
                condition=models.Q(state__in=LIVE_STATES),
                name="uniq_live_ssa_recommendation_per_need",
            ),
            # Declining to act on a measured weakness requires saying why.
            models.CheckConstraint(
                condition=(
                    ~models.Q(state__in=["deferred", "rejected"])
                    | ~models.Q(decision_reason="")
                ),
                name="ssa_recommendation_decline_needs_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_id} · {self.intervention} · {self.state}"

    @property
    def is_live(self) -> bool:
        return self.state in LIVE_STATES


def condition_key_for(*, school_id: str, fy: str, intervention: str) -> str:
    """The identity of a need: this school, this year, this weakness."""
    return f"ssa-rec:{school_id}:{fy}:{intervention}"
