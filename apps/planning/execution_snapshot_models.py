"""ExecutionPeriodSnapshot — a period's execution figures, locked when it ends.

Country Execution & Completion Oversight reads live figures: a correction made
next month through the governed workflow (a late verification, a return, a
closure) changes what last month shows. That is right for the work and wrong
for a leadership report, which must not be rewritten silently (owner spec
2026-09-28, §22). So when each week, month, quarter and financial year ends,
its figures are written down once, as they stood at the close:

* the original committed plan and the plan's movements (added, rescheduled in
  and out, cancelled), and the current executable plan;
* what was started, executed, PL-reviewed, verified and fully closed, what was
  overdue, carried over and cancelled;
* staff and Partner contribution kept apart;
* the Programme Lead → CCEO → Partner hierarchy with the same figures;
* the execution follow-ups open at the close.

A row is never changed or deleted. A later correction may be recorded as a
revision — a new row (version 2, 3, …) that names the one it revises, with the
reason, the person and the date — and the original stays beside it.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.models import CuidField


class SnapshotKind(models.TextChoices):
    ORIGINAL = "original", "Original"
    REVISION = "revision", "Revision"


class LockedSnapshotError(Exception):
    """A locked period snapshot was asked to change."""


class ExecutionPeriodSnapshot(models.Model):
    id = CuidField()
    country = models.CharField(max_length=100)
    fy = models.CharField(max_length=10)
    period_type = models.CharField(max_length=10)  # week | month | quarter | fy
    period_start = models.DateField()
    period_end = models.DateField()  # exclusive
    period_label = models.CharField(max_length=80)
    version = models.PositiveIntegerField(default=1)
    kind = models.CharField(
        max_length=12, choices=SnapshotKind.choices, default=SnapshotKind.ORIGINAL
    )
    revises = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    reason = models.TextField(blank=True, default="")
    # The reporting day the figures were read on: the day after the period's
    # last day, so work due in it and not done by its end reads as overdue.
    as_of = models.DateField()
    taken_at = models.DateTimeField(default=timezone.now)
    # Empty for the scheduled close; the person for a revision.
    taken_by_id = models.CharField(max_length=30, blank=True, default="")
    taken_by_name = models.CharField(max_length=200, blank=True, default="")
    stage_policy = models.CharField(max_length=40, blank=True, default="")
    figures = models.JSONField(default=dict)
    channels = models.JSONField(default=dict)
    hierarchy = models.JSONField(default=list)
    follow_ups = models.JSONField(default=list)

    class Meta:
        db_table = "execution_period_snapshot"
        ordering = ["-period_start", "period_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["country", "period_type", "period_start", "version"],
                name="uniq_execution_snapshot_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["country", "period_type", "period_start"],
                name="idx_exec_snapshot_period",
            ),
            models.Index(fields=["taken_at"], name="idx_exec_snapshot_taken"),
        ]

    def __str__(self) -> str:
        return f"{self.country} · {self.period_label} · v{self.version}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise LockedSnapshotError(
                "A locked period snapshot is never changed; record a revision instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise LockedSnapshotError("A locked period snapshot is never deleted.")

    @property
    def is_revision(self) -> bool:
        return self.kind == SnapshotKind.REVISION
