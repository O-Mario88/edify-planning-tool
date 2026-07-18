"""Phase 3 follow-up: school_type workflow dead-ends.

potential_champion and "other" school_type values used to be invisible to
every actionable workflow (Client Planning, Core Planning, Core Dashboard,
Core-candidates, Champion-candidates) — a school uploaded with either value
appeared only in the raw, unfiltered School Directory. Fixed by including
potential_champion in the Core-candidates pipeline (its real next step is
identical to potential_core's — both need a CoreSchoolProfile before
Champion eligibility can even be evaluated) and by flagging "other" with a
critical DataQualityIssue instead of letting it disappear silently.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.test import TestCase

from apps.core_schools.services import list_candidates
from apps.geography.models import District, Region
from apps.schools.models import DataQualityIssue, School
from apps.ssa.models import SsaRecord


class SchoolTypeWorkflowRoutingTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Routing Region")
        self.district = District.objects.create(
            name="Routing District", region=self.region
        )

    def _school(self, school_id, school_type, **kwargs):
        return School.objects.create(
            school_id=school_id,
            name=f"{school_id} Primary",
            region=self.region,
            district=self.district,
            school_type=school_type,
            **kwargs,
        )

    def test_potential_champion_appears_in_core_candidates_pipeline(self):
        school = self._school("SCH-POT-CHAMP", "potential_champion")
        SsaRecord.objects.create(
            school=school,
            date_of_ssa=datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            fy="2026",
            quarter="Q4",
            average_score=8.5,
            verification_status="confirmed",
        )
        candidates = list_candidates(principal=None)
        ids = [c["schoolId"] for c in candidates]
        self.assertIn("SCH-POT-CHAMP", ids)

    def test_other_school_type_is_flagged_critical_not_silently_dropped(self):
        school = self._school("SCH-OTHER", "other")
        issues = DataQualityIssue.objects.filter(
            school=school, issue_type="unclassified_school_type"
        )
        self.assertEqual(issues.count(), 1)
        self.assertEqual(issues.first().severity, "critical")

    def test_client_and_core_school_types_are_not_flagged(self):
        client = self._school("SCH-CLIENT", "client")
        core = self._school("SCH-CORE", "core")
        for school in (client, core):
            self.assertFalse(
                DataQualityIssue.objects.filter(
                    school=school, issue_type="unclassified_school_type"
                ).exists()
            )
