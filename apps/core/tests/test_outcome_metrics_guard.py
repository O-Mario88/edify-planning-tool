"""OUTCOME means change in schools, not delivered work (IA review, 2026-09-13).

The role description asks Impact Assessment to move the platform from tracking
daily activities to measuring long-term impact. The reconciled registry had
labelled nineteen reach and delivery counts — teachers trained, schools
"impacted", enrolment at reached schools — as OUTCOME metrics, the category
whose question is "what verified outcome has been achieved". They are SCALE
and PROGRESS now; this guard keeps a delivery count from being filed as an
outcome again.
"""

from __future__ import annotations

import re

from django.test import SimpleTestCase

from apps.core.metrics.reconciled_registry import RECONCILED_METRIC_ROWS

#: Models that count delivered work or attendance. An OUTCOME metric may read
#: them beside outcome evidence, never on their own.
DELIVERY_MODELS = {
    "apps.activities.models.Activity",
    "apps.activities.models.ActivityScheduleCostLine",
    "apps.activities.models.ClusterActivityAttendance",
    "apps.activities.models.ActivityAttendance",
}

#: Words that name a delivery count rather than a change.
DELIVERY_WORDS = re.compile(r"\b(trained|reached|impacted|attend\w*|delivered)\b", re.I)

#: Known rows owned by another track's metrics module, recorded for the lead
#: (IA-F report, lead_changes_needed). Remove an entry when its row is fixed.
PENDING_LEAD_CHANGE: set[str] = set()


class OutcomeMetricGuardTests(SimpleTestCase):
    def _outcomes(self):
        return [
            row
            for row in RECONCILED_METRIC_ROWS
            if row["category"] == "outcome" and row["key"] not in PENDING_LEAD_CHANGE
        ]

    def test_no_outcome_metric_is_sourced_from_delivery_records_alone(self):
        for row in self._outcomes():
            with self.subTest(metric=row["key"]):
                models = set(row["source_models"])
                self.assertFalse(
                    models and models <= DELIVERY_MODELS,
                    "an OUTCOME metric reads only activity or attendance records",
                )

    def test_no_outcome_metric_counts_who_was_trained_reached_or_attended(self):
        for row in self._outcomes():
            with self.subTest(metric=row["key"]):
                self.assertIsNone(
                    DELIVERY_WORDS.search(row["label"]),
                    f"{row['label']!r} names a delivery count; file it as scale or progress",
                )

    def test_the_recategorised_reach_counts_stay_out_of_outcome(self):
        by_key = {row["key"]: row for row in RECONCILED_METRIC_ROWS}
        for key in (
            "analytics_analytics_dashboard_service_teachers_trained",
            "analytics_analytics_dashboard_service_students_impacted",
            "analytics_analytics_dashboard_service_schools_impacted",
            "country_schools_impacted_count",
            "projects_impact_service_teachers_impacted",
            "projects_impact_service_school_leaders_impacted",
        ):
            with self.subTest(metric=key):
                self.assertIn(by_key[key]["category"], ("scale", "progress"))
