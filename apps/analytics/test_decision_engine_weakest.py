"""Missing data is not a bad score.

``decision_engine.intervention_analytics`` ranked interventions with
``-(x[1]["current"] or 0)``. ``current`` is None when no confirmed SSA score
covers an intervention, and ``None or 0`` is 0 — the lowest possible average —
so an intervention nobody had assessed sorted last and was returned as
``weakest``. That value is interpolated into the user-facing ``suggestedAction``
text of ``/api/analytics/recommendations`` and ``/api/analytics/role-overview``,
so the platform recommended work against an assessment that was never
collected.

apps/clusters/services._weakest_from_stats already had this exact bug and
fixed it the same way; this pins the analytics twin.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.analytics import decision_engine
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class WeakestIgnoresUnassessedInterventions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Decision Region")
        cls.district = District.objects.create(
            name="Decision District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="DEC-001",
            name="Decision School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=100,
        )
        cls.principal = User.objects.create_user(
            email="decision-ia@edify.org",
            name="Decision IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(
            user=cls.principal, staff_number="ST-DEC", country="Uganda"
        )
        cls.fy = get_operational_fy()
        cls.record = SsaRecord.objects.create(
            school=cls.school,
            fy=cls.fy,
            date_of_ssa=timezone.localdate() - datetime.timedelta(days=20),
            verification_status="confirmed",
        )
        # Only two of the eight interventions were ever assessed. Leadership
        # is the genuinely weaker of the two.
        SsaScore.objects.create(
            ssa_record=cls.record,
            intervention=SsaIntervention.LEADERSHIP,
            score=3.0,
        )
        SsaScore.objects.create(
            ssa_record=cls.record,
            intervention=SsaIntervention.TEACHING_ENVIRONMENT,
            score=8.0,
        )

    def _analytics(self):
        return decision_engine.intervention_analytics(self.principal, {"fy": self.fy})

    def test_weakest_is_an_assessed_intervention(self):
        result = self._analytics()

        self.assertEqual(
            result["weakest"],
            SsaIntervention.LEADERSHIP.value,
            "An unassessed intervention was ranked weakest, so the suggested "
            "action names work nobody has evidence for.",
        )
        self.assertEqual(
            result["strongest"], SsaIntervention.TEACHING_ENVIRONMENT.value
        )

    def test_unassessed_interventions_are_absent_from_the_ranking(self):
        result = self._analytics()

        self.assertEqual(
            set(result["ranking"]),
            {
                SsaIntervention.LEADERSHIP.value,
                SsaIntervention.TEACHING_ENVIRONMENT.value,
            },
        )
        # They still appear in the detail map, reported honestly as no data.
        self.assertIsNone(
            result["interventions"][SsaIntervention.ENROLMENT.value]["current"]
        )

    def test_no_confirmed_scores_yields_no_weakest(self):
        SsaScore.objects.all().delete()

        result = self._analytics()

        self.assertIsNone(result["weakest"])
        self.assertIsNone(result["strongest"])
        self.assertEqual(result["ranking"], [])

    def test_a_genuine_zero_average_is_kept_not_treated_as_missing(self):
        """`round(curr, 2) if curr else None` discarded a real 0.0."""
        SsaScore.objects.filter(intervention=SsaIntervention.LEADERSHIP).update(
            score=0.0
        )

        result = self._analytics()

        self.assertEqual(
            result["interventions"][SsaIntervention.LEADERSHIP.value]["current"],
            0.0,
            "A real 0.0 average was reported as missing data.",
        )
        self.assertEqual(result["weakest"], SsaIntervention.LEADERSHIP.value)
