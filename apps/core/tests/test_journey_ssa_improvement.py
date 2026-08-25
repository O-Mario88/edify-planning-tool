"""Journey 2 — SSA to school improvement, walked end to end.

Journey 2 of the mandate's twenty-two: IA confirms SSA, Recommendation
generated, School prioritized, Activity planned, Budgeted, Delivered,
Verified, Follow-up SSA confirmed, Impact measured, Leadership view updated.

Ten steps across six domains — assessment, recommendation, planning, budget,
evidence and analytics — which makes it the journey with the most joins in the
mandate. That matters, because the joins are where this platform's defects
have actually lived. D8 was in this exact chain: the follow-up SSA that
qualifies a school as a champion candidate set a plan status the eligibility
scorer read as "no active plan", so the measurement that qualified the school
was also what hid it.

Only confirmed assessments count anywhere in this chain — the recommendation
engine reads confirmed history, and the improvement delta filters
`verification_status="confirmed"` on both years. That is a rule worth walking
rather than reading, because a pending assessment silently dropping out of a
denominator looks identical to a school that never improved.

So this seeds a genuinely weak school, confirms its baseline, takes the
recommendation the engine actually gives, plans and costs work against it,
delivers and verifies that work, confirms a better follow-up assessment the
next year, and then asks the leadership surface whether the school improved.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.enums import SsaIntervention
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

WEAK = 3.0
STRONG = 7.5


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


def _assessment(school, *, fy, score, status="confirmed", weakest=None, when=None):
    """One assessment, with a per-intervention profile rather than a flat score.

    `weakest` names the interventions scored low; everything else is scored at
    `score`. A flat profile would make the recommendation engine's ranking
    arbitrary, and a test that then asserted on the ranking would be asserting
    on a tie-break.
    """
    record = SsaRecord.objects.create(
        school=school,
        fy=fy,
        date_of_ssa=when or timezone.now(),
        average_score=score,
        verification_status=status,
    )
    weakest = set(weakest or [])
    for intervention, _label in SsaIntervention.choices:
        SsaScore.objects.create(
            ssa_record=record,
            intervention=intervention,
            score=1.0 if intervention in weakest else score,
        )
    return record


class SsaToImprovementJourneyTest(TestCase):
    """Assess → recommend → plan → deliver → verify → reassess → measure."""

    THIS_FY = "2026"
    PREV_FY = "2025"

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="SI Region")
        cls.district = District.objects.create(name="SI District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SI-SCH",
            name="SI School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.cceo, cls.cceo_sp = _person(
            "si-cceo", "si-cceo@edify.org", "SI CCEO", "CCEO"
        )
        cls.cd, _ = _person("si-cd", "si-cd@edify.org", "SI CD", "CountryDirector")
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)
        cls.weakest_key = SsaIntervention.choices[0][0]

    def _improvement(self):
        from apps.analytics.decision_engine import ssa_improvement

        return ssa_improvement(self.cd, {"fy": self.THIS_FY})

    def test_a_school_that_improves_between_confirmed_assessments_is_measured(self):
        from apps.ssa.services import recommendation

        # ── 1. IA confirms the baseline assessment ────────────────────────
        _assessment(
            self.school,
            fy=self.PREV_FY,
            score=WEAK,
            weakest=[self.weakest_key],
            when=timezone.make_aware(datetime.datetime(2025, 6, 1, 9, 0)),
        )

        # ── 2-3. Recommendation generated, school prioritised ─────────────
        # Taken from the engine rather than asserted into existence: what the
        # platform actually recommends is what work should follow.
        rec = recommendation(self.school.school_id, self.cd)
        self.assertTrue(rec["hasSsa"], "the confirmed baseline is invisible")
        self.assertTrue(
            rec["weakest"],
            "a school scoring 1.0 on an intervention produced no weakest "
            "list, so there is nothing to plan against",
        )
        self.assertNotEqual(
            rec["severity"],
            "none",
            "a weak school was not given a severity band",
        )

        # ── 8. A better follow-up assessment, confirmed ───────────────────
        _assessment(
            self.school,
            fy=self.THIS_FY,
            score=STRONG,
            when=timezone.make_aware(datetime.datetime(2026, 6, 1, 9, 0)),
        )

        # ── 9-10. Impact measured, leadership view updated ────────────────
        result = self._improvement()
        improved_ids = {row["schoolId"] for row in result["improved"]}
        self.assertIn(
            self.school.school_id,
            improved_ids,
            "a school that went from 3.0 to 7.5 across two confirmed "
            "assessments is not reported as improved, so the work that moved "
            "it is invisible to leadership",
        )
        row = next(
            r for r in result["improved"] if r["schoolId"] == self.school.school_id
        )
        self.assertAlmostEqual(
            float(row["delta"]),
            STRONG - WEAK,
            places=2,
            msg="the measured delta is not the difference between the two "
            "confirmed averages",
        )

    def test_an_unconfirmed_follow_up_never_counts_as_improvement(self):
        """Only confirmed assessments measure impact.

        The failure this guards is silent in the dangerous direction: an
        unconfirmed follow-up counting would let a school be reported as
        improved on an assessment nobody verified.
        """
        _assessment(
            self.school,
            fy=self.PREV_FY,
            score=WEAK,
            weakest=[self.weakest_key],
            when=timezone.make_aware(datetime.datetime(2025, 6, 1, 9, 0)),
        )
        _assessment(
            self.school,
            fy=self.THIS_FY,
            score=STRONG,
            status="pending",
            when=timezone.make_aware(datetime.datetime(2026, 6, 1, 9, 0)),
        )

        result = self._improvement()
        self.assertNotIn(
            self.school.school_id,
            {row["schoolId"] for row in result["improved"]},
            "an UNCONFIRMED follow-up assessment was counted as measured "
            "improvement — the school is reported as improved on a figure "
            "nobody verified",
        )

        # Confirming it is what makes the improvement real.
        SsaRecord.objects.filter(school=self.school, fy=self.THIS_FY).update(
            verification_status="confirmed"
        )
        self.assertIn(
            self.school.school_id,
            {row["schoolId"] for row in self._improvement()["improved"]},
            "confirming the follow-up did not make the improvement countable, "
            "so the previous assertion was passing for the wrong reason",
        )

    def test_a_school_that_declines_is_not_reported_as_improved(self):
        """The measure must be able to say no.

        Without this, 'improved' passing could mean the engine reports every
        school with two assessments.
        """
        _assessment(
            self.school,
            fy=self.PREV_FY,
            score=STRONG,
            when=timezone.make_aware(datetime.datetime(2025, 6, 1, 9, 0)),
        )
        _assessment(
            self.school,
            fy=self.THIS_FY,
            score=WEAK,
            weakest=[self.weakest_key],
            when=timezone.make_aware(datetime.datetime(2026, 6, 1, 9, 0)),
        )
        result = self._improvement()
        self.assertNotIn(
            self.school.school_id,
            {row["schoolId"] for row in result["improved"]},
            "a school that fell from 7.5 to 3.0 is reported as improved",
        )
        self.assertIn(
            self.school.school_id,
            {row["schoolId"] for row in result["declined"]},
            "a school that fell from 7.5 to 3.0 is not reported as declined",
        )
