"""A school's operational lifecycle — closing, and coming back.

Closure is a state transition, never a deletion. A school that closes stops
receiving new work and stops counting toward what the programme currently
reaches; everything it did before that moment stays exactly where it was,
because the enrolment it once had, the visits it received and the money spent
on it are all facts about a period that has already been reported.

Two distinctions carry the design.

**Operational status is not school type.** A school being Client or Core says
what kind of support it gets; being Active or Closed says whether it is
getting any. Overloading one field with both is how a closed Core school ends
up either invisible to Core reporting or still counted as an active
obligation.

**Closed is not deleted.** `deleted_at` already means "this row should never
have existed" — a duplicate, a bad import. Closure means "this was real and
has ended". They need separate answers because the archive shows one and not
the other.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class SchoolOperationalStatus(models.TextChoices):
    """Whether a school is currently receiving programme support."""

    ACTIVE = "active", "Active"
    TEMPORARILY_CLOSED = "temporarily_closed", "Temporarily closed"
    PERMANENTLY_CLOSED = "permanently_closed", "Permanently closed"
    # Distinct from ACTIVE on purpose: a reopened school has a history that
    # changes how its coverage and readiness should be read, and collapsing it
    # to "active" loses the one signal that says so.
    REOPENED = "reopened", "Reopened"


#: The statuses that mean "not currently operating". One tuple, so no caller
#: re-lists them and quietly forgets one.
CLOSED_STATUSES = (
    SchoolOperationalStatus.TEMPORARILY_CLOSED,
    SchoolOperationalStatus.PERMANENTLY_CLOSED,
)

#: The statuses that count toward everything current: active-school counts,
#: active enrolment, planning eligibility, cluster membership.
OPERATING_STATUSES = (
    SchoolOperationalStatus.ACTIVE,
    SchoolOperationalStatus.REOPENED,
)


class ClosureType(models.TextChoices):
    TEMPORARY = "temporary", "Temporarily closed"
    PERMANENT = "permanent", "Permanently closed"


class ClosureReason(models.TextChoices):
    """Why a school stopped operating.

    Closed and specific so a queue of closures can be read without opening
    every one — "low enrolment" and "government closure" call for very
    different follow-up, and free text alone does not sort.
    """

    OWNER_DECISION = "owner_decision", "Owner decision"
    FINANCIAL = "financial", "Financial difficulties"
    LOW_ENROLMENT = "low_enrolment", "Low enrolment"
    LICENSING = "licensing", "Licence or registration issue"
    GOVERNMENT_CLOSURE = "government_closure", "Government closure"
    MERGED = "merged", "Merged with another school"
    RELOCATED = "relocated", "Relocated outside Edify scope"
    FACILITY = "facility", "Building or facility problem"
    SECURITY = "security", "Security or access problem"
    DISASTER = "disaster", "Natural disaster or emergency"
    MANAGEMENT = "management", "School management breakdown"
    TEMPORARY_SUSPENSION = "temporary_suspension", "Temporary suspension of operations"
    # Deliberately here AND handled specially: a duplicate is not a school
    # that closed, it is a record that should not have existed. Closing it as
    # though it were an operational event would report a school loss that
    # never happened.
    DUPLICATE_RECORD = "duplicate_record", "Duplicate or incorrect school record"
    UNCONFIRMED = "unconfirmed", "Unable to confirm continued operation"
    OTHER = "other", "Other"


#: Reasons that mean the record is wrong rather than the school being shut.
#: Routed to data-quality resolution instead of counted as a closure, so the
#: programme does not report losing a school it never had.
DATA_QUALITY_REASONS = frozenset({ClosureReason.DUPLICATE_RECORD})


class SchoolClosure(TimeStampedModel):
    """One closure decision, and everything true at the moment it was made.

    The snapshots are the point. Enrolment, cluster and owner are copied here
    rather than read back through the school, because all three change and the
    question this record answers is what the programme lost on the day — not
    what the school looks like now.
    """

    id = CuidField()
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="closures"
    )

    closure_type = models.CharField(max_length=16, choices=ClosureType.choices)
    reason_category = models.CharField(max_length=32, choices=ClosureReason.choices)
    reason = models.TextField()

    # When the school stopped operating, which is not necessarily when anyone
    # recorded it. Everything prospective keys off this date, so a closure
    # discovered late does not retroactively rewrite last month's reporting.
    effective_date = models.DateField()

    closed_by = models.CharField(max_length=30)
    closed_by_role = models.CharField(max_length=48, blank=True)

    # ── Snapshots ────────────────────────────────────────────────────────────
    # The actual School Enrolment Count, never an SSA Enrolment Score. Those
    # are different numbers that have been conflated before: the score is a
    # 1–10 assessment band, and subtracting it from a learner total would take
    # 7 children off the programme instead of 420.
    enrollment_at_closure = models.IntegerField(null=True, blank=True)
    enrollment_source = models.CharField(max_length=64, blank=True)
    enrollment_record_date = models.DateField(null=True, blank=True)

    cluster_at_closure = models.CharField(max_length=30, null=True, blank=True)
    cluster_name_at_closure = models.CharField(max_length=255, blank=True)
    owner_at_closure = models.CharField(max_length=30, null=True, blank=True)
    owner_name_at_closure = models.CharField(max_length=255, blank=True)

    # What the decision actually did, recorded so the audit does not have to be
    # reconstructed by re-querying a world that has since moved on.
    activities_cancelled = models.IntegerField(default=0)
    partner_assignments_withdrawn = models.IntegerField(default=0)
    budget_released = models.BigIntegerField(default=0)
    locked_activities_for_review = models.IntegerField(default=0)

    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.CharField(max_length=30, null=True, blank=True)
    reopening_reason = models.TextField(blank=True)

    class Meta:
        db_table = "school_closure"
        ordering = ["-effective_date", "-created_at"]
        indexes = [
            models.Index(fields=["school", "reopened_at"]),
            models.Index(fields=["effective_date"]),
            models.Index(fields=["reason_category"]),
        ]
        constraints = [
            # One open closure per school. A second would double-count the
            # enrolment removed and leave two records disagreeing about when
            # the school stopped.
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(reopened_at__isnull=True),
                name="one_open_closure_per_school",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_closure_type_display()} — {self.school_id}"

    @property
    def is_open(self) -> bool:
        return self.reopened_at is None

    @property
    def is_data_quality(self) -> bool:
        """A wrong record rather than a school that shut.

        Kept out of closure counts: reporting a duplicate as a school loss
        would say the programme reaches one fewer school than it does.
        """
        return self.reason_category in DATA_QUALITY_REASONS
