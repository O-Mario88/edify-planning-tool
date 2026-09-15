"""The governed per-country, per-fiscal-year planning policy (2026-09-15).

One row per (country, fiscal year). It answers the questions the owner asked
to stop being hard-coded:

* **When may staff plan a fiscal year, and when may its work be delivered?**
  ``planning_open_at`` opens planning (dates, schedules, costs, budgets and
  work plans for that year); ``execution_start`` and ``execution_end`` bound
  delivery. FY2027 is planned from September 2026 while FY2026 is still being
  closed, and nothing in FY2027 is delivered before 1 October 2026.
* **Does a school visit follow-up need a prior training?**
  ``follow_up_visit_requires_prior_training``. Off for Uganda FY2026 and
  FY2027 by the owner's brief; every other safeguard stands.

A fiscal year with no row keeps the platform's standing behaviour: the
operational year and earlier years are plannable, a later year is not, and a
follow-up needs a prior training.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class FiscalYearPlanningPolicy(TimeStampedModel):
    id = CuidField()
    country = models.CharField(max_length=64, default="Uganda")
    fy = models.CharField(max_length=16)
    planning_open_at = models.DateTimeField(null=True, blank=True)
    execution_start = models.DateField()
    execution_end = models.DateField()
    follow_up_visit_requires_prior_training = models.BooleanField(default=True)
    opened_by = models.CharField(max_length=30, blank=True, default="")
    updated_by = models.CharField(max_length=30, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fiscal_year_planning_policy"
        ordering = ["country", "fy"]
        constraints = [
            models.UniqueConstraint(
                fields=["country", "fy"], name="uniq_fy_planning_policy"
            ),
            models.CheckConstraint(
                condition=models.Q(execution_end__gte=models.F("execution_start")),
                name="fy_policy_execution_window_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.country} FY{self.fy} planning policy"
