"""Interaction telemetry — the measurement behind the Staff Time Standard.

The platform is governed by a measured ceiling on staff administration time
(docs/STAFF_TIME_STANDARD.md): at least 95% of routine field-staff days must
need no more than 15 minutes of active platform interaction. These models
are that instrument and nothing more.

Privacy is structural, not procedural:

- Events store the RESOLVED ROUTE PATTERN (``schools/<str:pk>``), never the
  concrete path, query string, payload, IP address or user agent — nothing
  an event row holds can identify a school, a search term or a form value.
- Raw events exist only to compute per-day aggregates and are pruned after
  ``RAW_EVENT_RETENTION_DAYS`` by the daily rollup job.
- No surface anywhere may present a named individual's minutes to a manager;
  the report layer (services.interaction_report) emits role-level
  percentiles only. The per-person-day rows exist for the percentile math,
  exactly as the standard's §5.3 allows.

Neither model uses TimeStampedModel: events are append-only measurements
(the AuditLog precedent) and the day rows are wholly rewritten by their
rollup, so audit timestamps would only masquerade as meaning.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField

RAW_EVENT_RETENTION_DAYS = 14


class InteractionEvent(models.Model):
    """One authenticated request — the atom of active-interaction time."""

    id = CuidField()
    user_id = models.CharField(max_length=30, db_index=True)
    role = models.CharField(max_length=64)
    occurred_at = models.DateTimeField(db_index=True)
    method = models.CharField(max_length=8)
    # The URL pattern the resolver matched, not the concrete path — the
    # telemetry must never be able to say WHICH school was opened.
    route = models.CharField(max_length=255)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "interaction_event"
        indexes = [
            models.Index(
                fields=["user_id", "occurred_at"], name="idx_interaction_user_time"
            ),
        ]


class InteractionDay(models.Model):
    """One person-day's sessionised active time — the SLO's unit of account.

    Written only by the daily rollup (services.rollup_interaction_days),
    which recomputes a day idempotently from its raw events. Consumed only
    in aggregate: the report layer reduces these rows to role-population
    percentiles and never exposes a row individually.
    """

    id = CuidField()
    user_id = models.CharField(max_length=30)
    role = models.CharField(max_length=64)
    day = models.DateField(db_index=True)
    active_seconds = models.PositiveIntegerField(default=0)
    # The §3a split: planning is the platform's work, execution is the
    # staff's. Time on planning surfaces should trend to zero as the
    # preparation layer lands; execution-and-proof time (schedule, assign,
    # debrief, evidence, SF/NetSuite proof) is what legitimately remains.
    # other = active − planning − execution (dashboards, messages, settings).
    planning_seconds = models.PositiveIntegerField(default=0)
    execution_seconds = models.PositiveIntegerField(default=0)
    request_count = models.PositiveIntegerField(default=0)
    write_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "interaction_day"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "day"], name="uniq_interaction_user_day"
            )
        ]
        indexes = [
            models.Index(fields=["role", "day"], name="idx_interaction_role_day"),
        ]
