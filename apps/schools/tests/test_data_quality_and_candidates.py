"""Current partner types remain routable through school workflows."""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.test import TestCase

from apps.core_schools.services import list_candidates
from apps.geography.models import District, Region
from apps.core.enums import SchoolType
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

    def test_core_trained_appears_in_core_candidates_pipeline(self):
        school = self._school("SCH-CORE-TRAINED", SchoolType.CORE_TRAINED)
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
        self.assertIn("SCH-CORE-TRAINED", ids)

    def test_every_current_partner_type_is_classified(self):
        for value, _label in SchoolType.choices:
            school = self._school(f"SCH-{value.upper()}", value)
            self.assertFalse(
                DataQualityIssue.objects.filter(
                    school=school, issue_type="unclassified_school_type"
                ).exists()
            )
