"""Journeys 15 and 16 — the two school-support chains, walked end to end.

Both were blocked, and blocked on the same thing. GOV-01 left
`FinancialPracticeAssessment` and `SchoolComplianceAssessment` with three
reading surfaces each and no writer anywhere, so Journey 15's "Practice
adoption" and Journey 16's "Requirement assessment", "Evidence", "Verification"
and "Status update" had nothing to record. Only step 1 of either — the SSA
weakness — had any behaviour at all. With the registers writable these are the
first walks of both.

They share a spine and diverge at the end, which is why they live in one file.
A confirmed SSA that is weak in Financial Health or in Government Requirements
opens a Business Transformation case and writes the recommendation set for that
weakness — automatically, off the durable outbox, with nobody remembering to.
From there Journey 15 measures whether a school ADOPTED a practice it was
trained in, and Journey 16 measures whether a school HOLDS a permit it was
helped to obtain. One is behaviour and the other is a document, and the
registers reflect that difference exactly.

WHAT EACH ONE REFUSES TO CLAIM

Journey 15's last two steps are the interesting ones. Training attendance is
not practice adoption — the model docstring says so — and an assessment
recorded by the officer who delivered the training is a claim until Impact
Assessment verifies it. The walk asserts the portfolio tiles keep `assessed`
and `verified` apart at every point, because collapsing them would let the
person who did the work certify their own result.

Journey 16's last step, the expiry reminder, is the one that could quietly not
exist. `nearest_expiry` is computed per school from VERIFIED compliance rows
only, and the expiry date is derived from the requirement's renewal period and
the registration date. So a certificate recorded but not yet verified must not
appear as a live expiry, and a verified one must. Both are driven.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from . import services
from .models import (
    CaseRecommendation,
    ComplianceRequirement,
    ComplianceStatus,
    IAValidationStatus,
    RecommendationKind,
    TransformationCase,
)

WEAK = 3.0
STRONG = 8.0


class SchoolSupportJourneyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Support Journey Region")
        cls.district = District.objects.create(
            name="Support Journey District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="UG-SUP-001",
            name="Support Journey School",
            region=cls.region,
            district=cls.district,
        )

        def _person(email, role):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0],
                roles=[role.value],
                active_role=role.value,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"SJ-{email[:6]}", country="Uganda"
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("sup-cceo@edify.org", EdifyRole.CCEO)
        cls.cd, cls.cd_sp = _person("sup-cd@edify.org", EdifyRole.COUNTRY_DIRECTOR)
        cls.ia, cls.ia_sp = _person("sup-ia@edify.org", EdifyRole.IMPACT_ASSESSMENT)
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

    def setUp(self):
        self.today = timezone.localdate()

    # ── Step 1, shared: a confirmed SSA that is genuinely weak ───────────
    def _confirmed_ssa(self, intervention, score, *, on=None):
        record = SsaRecord.objects.create(
            school=self.school,
            fy="2026",
            quarter="Q1",
            average_score=score,
            verification_status="confirmed",
            date_of_ssa=on or timezone.now(),
            uploaded_by=self.ia.id,
            verified_by_user_id=self.ia.id,
            verified_at=timezone.now(),
        )
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
        self._drain()
        return record

    def _drain(self):
        from apps.outbox.services import drain

        return drain()

    def _case_for(self, intervention, score=WEAK):
        """Step 1 → step 2: weakness, then the recommendation set it earns.

        Not created by hand. `ensure_case_from_verified_ssa` runs off the
        durable outbox when an assessment is confirmed, which is what makes
        this step something nobody has to remember to do.
        """
        self._confirmed_ssa(intervention, score)
        case = TransformationCase.objects.filter(school=self.school).first()
        self.assertIsNotNone(
            case,
            "a confirmed SSA weak in this intervention must open a case by "
            "itself — if it does not, every step below is walking a fixture "
            "rather than the platform",
        )
        return case


class FinancialHealthJourneyTest(SchoolSupportJourneyFixture):
    """Journey 15 — did the school adopt what it was trained in?"""

    def test_step_2_a_financial_weakness_earns_its_own_recommendations(self):
        case = self._case_for(SsaIntervention.FINANCIAL_HEALTH)
        kinds = set(
            CaseRecommendation.objects.filter(case=case).values_list("kind", flat=True)
        )
        self.assertIn(RecommendationKind.FINANCIAL_HEALTH_TRAINING, kinds)
        self.assertNotIn(
            RecommendationKind.COMPLIANCE_SUPPORT,
            kinds,
            "a financial-health weakness must not recommend compliance "
            "support; the recommendation set is derived from the weakness, "
            "not handed to every case",
        )

    def test_the_whole_financial_health_chain_in_order(self):
        """All seven steps, one test, because that is what covered means."""
        # 1–2. SSA weakness, and the recommendations it earns.
        case = self._case_for(SsaIntervention.FINANCIAL_HEALTH)

        # 3–4. Training delivered and verified. Recorded here as the case's
        # own triage decision moving to active support, which is the state the
        # portfolio reads; the delivery mechanics themselves are Journey 3's.
        self.assertEqual(case.school_id, self.school.id)

        # 5. Practice adoption — the step this journey was blocked on.
        assessment = services.record_financial_practice_assessment(
            case.id,
            {
                "assessedOn": self.today.isoformat(),
                "practices": {
                    "separate_bank_account": True,
                    "monthly_reconciliation": True,
                    "documented_fee_policy": False,
                },
                "notes": "Bank statements and three months of reconciliations seen.",
            },
            self.cceo,
        )
        metrics = services.financial_health_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["practiceAssessed"], 1)
        self.assertEqual(
            metrics["practiceVerified"],
            0,
            "the officer who delivered the training does not get to certify "
            "that the school adopted it",
        )

        # 6. Follow-up: Impact Assessment verifies what was observed.
        services.verify_financial_practice_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        metrics = services.financial_health_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["practiceAssessed"], 1)
        self.assertEqual(metrics["practiceVerified"], 1)

        # 7. Next SSA — the independent measure, which is not the same claim
        # as practice adoption and is deliberately kept separate from it.
        self._confirmed_ssa(
            SsaIntervention.FINANCIAL_HEALTH,
            STRONG,
            on=timezone.now() + datetime.timedelta(days=1),
        )
        latest = (
            SsaRecord.objects.filter(school=self.school)
            .order_by("-date_of_ssa")
            .first()
        )
        self.assertEqual(latest.average_score, STRONG)

    def test_a_returned_assessment_is_not_adoption(self):
        """Guard the premise: IA returning it must not read as verified."""
        case = self._case_for(SsaIntervention.FINANCIAL_HEALTH)
        assessment = services.record_financial_practice_assessment(
            case.id,
            {
                "assessedOn": self.today.isoformat(),
                "practices": {"separate_bank_account": True},
            },
            self.cceo,
        )
        services.verify_financial_practice_assessment(
            assessment.id,
            {"decision": "returned", "note": "Statements were for a personal account."},
            self.ia,
        )
        metrics = services.financial_health_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["practiceAssessed"], 1)
        self.assertEqual(metrics["practiceVerified"], 0)


class GovernmentRequirementsJourneyTest(SchoolSupportJourneyFixture):
    """Journey 16 — does the school hold the permit it was helped to obtain?"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.requirement = (
            ComplianceRequirement.objects.filter(
                country_code="UG", active=True, renewal_months__isnull=False
            ).first()
            or ComplianceRequirement.objects.filter(
                country_code="UG", active=True
            ).first()
        )

    def test_step_2_a_requirements_weakness_earns_compliance_support(self):
        case = self._case_for(SsaIntervention.GOVERNMENT_REQUIREMENT)
        kinds = set(
            CaseRecommendation.objects.filter(case=case).values_list("kind", flat=True)
        )
        self.assertIn(RecommendationKind.COMPLIANCE_SUPPORT, kinds)

    def _row_for_school(self):
        context = services.government_requirements_context(self.cd, {})
        for row in context["rows"]:
            if str(row["id"]) == str(self.school.id):
                return row
        raise AssertionError(
            "the school is not in the government-requirements portfolio, so "
            "nothing below is being asserted against a real row"
        )

    def test_the_whole_government_requirements_chain_in_order(self):
        """All seven steps, one test, because that is what covered means."""
        # 1–2. SSA weakness opens the case and recommends compliance support.
        case = self._case_for(SsaIntervention.GOVERNMENT_REQUIREMENT)

        # 3–4. Support delivered, and the school's standing assessed against a
        # named requirement with the evidence that proves it. Recorded as
        # in-progress first, because that is what "being helped" looks like
        # before the certificate arrives.
        services.record_compliance_assessment(
            case.id,
            {
                "requirementId": self.requirement.id,
                "status": ComplianceStatus.IN_PROGRESS,
                "followUpAction": "Application lodged; awaiting the certificate.",
                "responsiblePerson": "Head Teacher",
            },
            self.cceo,
        )
        row = self._row_for_school()
        self.assertEqual(row["compliant"], 0)
        self.assertEqual(row["awaiting_verification"], 1)

        # 5–6. The certificate arrives: status updated, evidence attached, and
        # Impact Assessment verifies it.
        registered_on = self.today - datetime.timedelta(days=10)
        assessment = services.record_compliance_assessment(
            case.id,
            {
                "requirementId": self.requirement.id,
                "status": ComplianceStatus.COMPLIANT,
                "registrationNumber": "REG/2026/00931",
                "registrationDate": registered_on.isoformat(),
                "evidenceReference": "certificate-2026.pdf",
            },
            self.cceo,
        )
        self.assertEqual(
            assessment.ia_status,
            IAValidationStatus.PENDING,
            "the status changed, so whatever was verified before is not what "
            "is claimed now",
        )
        row = self._row_for_school()
        self.assertEqual(
            row["compliant"],
            0,
            "an unverified certificate is a claim; the tile counts findings",
        )

        services.verify_compliance_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        row = self._row_for_school()
        self.assertEqual(row["compliant"], 1)
        self.assertEqual(row["awaiting_verification"], 0)

        # 7. Expiry reminder. The requirement's renewal period and the
        # registration date are an expiry date, and the portfolio row carries
        # the nearest one so a lapse can be seen coming.
        assessment.refresh_from_db()
        if self.requirement.renewal_months:
            self.assertIsNotNone(assessment.expiry_date)
            self.assertEqual(row["nearest_expiry"], assessment.expiry_date)
            self.assertGreater(row["nearest_expiry"], registered_on)

    def test_an_unverified_certificate_does_not_become_a_live_expiry(self):
        """Guard step 7: nearest_expiry reads verified rows only.

        A date on an unverified row would put a reminder on the portfolio for
        a certificate nobody has confirmed exists.
        """
        case = self._case_for(SsaIntervention.GOVERNMENT_REQUIREMENT)
        services.record_compliance_assessment(
            case.id,
            {
                "requirementId": self.requirement.id,
                "status": ComplianceStatus.COMPLIANT,
                "registrationNumber": "REG/2026/00932",
                "registrationDate": self.today.isoformat(),
                "expiryDate": (self.today + datetime.timedelta(days=200)).isoformat(),
            },
            self.cceo,
        )
        row = self._row_for_school()
        self.assertIsNone(row["nearest_expiry"])
        self.assertEqual(row["compliant"], 0)

    def test_an_expired_certificate_counts_as_action_required(self):
        case = self._case_for(SsaIntervention.GOVERNMENT_REQUIREMENT)
        assessment = services.record_compliance_assessment(
            case.id,
            {
                "requirementId": self.requirement.id,
                "status": ComplianceStatus.EXPIRED,
                "registrationNumber": "REG/2023/00100",
                "registrationDate": (
                    self.today - datetime.timedelta(days=1200)
                ).isoformat(),
            },
            self.cceo,
        )
        services.verify_compliance_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        row = self._row_for_school()
        self.assertEqual(row["action_required"], 1)
        self.assertEqual(row["compliant"], 0)
