"""GOV-01 — the two school-assessment registers, given the write path they lack.

`SchoolComplianceAssessment` and `FinancialPracticeAssessment` were fully
designed and never written to. Both models carry their statuses, their
uniqueness constraints and a complete IA validation lane; three surfaces read
each of them — the transformation portfolio rows, its metric tiles, and the
school detail page — and nothing anywhere could put a row in either. The
government-requirements register that a Country Director opens to see whether
their schools are legally compliant was structurally empty, for every school,
for ever.

That the design exists is not a guess. The permission matrix already carries
both halves of it: `businessTransformation.schoolSupport.manage` sits on the
Country Director, Programme Lead and CCEO — the people who actually visit a
school and see the registration certificate — and
`businessTransformation.ia.validate` sits on Impact Assessment alone. A
recorder and a separate verifier, decided before either service was written.
So this is the missing implementation of a specified design rather than a
product question, and the shape it takes is the one this codebase already uses
for exactly this problem: `lending_impact.capture_enrolment_snapshot` /
`verify_enrolment_snapshot`, where a partner reports and IA verifies.

WHAT THE READERS REQUIRE, AND WHY THAT DECIDES THE DESIGN

The portfolio metrics count `status="compliant"` AND `ia_status="verified"`
together, and count `ia_status="pending"` as awaiting verification. So an
unverified assessment must never count as compliance — it is a claim, not a
finding — and re-recording a changed status has to send the row back for
verification rather than leaving a stale approval attached to a new fact.
Both of those are asserted below.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

from . import services
from .models import (
    ComplianceRequirement,
    ComplianceStatus,
    FinancialPracticeAssessment,
    IAValidationStatus,
    SchoolComplianceAssessment,
    TransformationCase,
)


class AssessmentRegisterFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Register Region")
        cls.district = District.objects.create(
            name="Register District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="UG-REG-001",
            name="Register School",
            region=cls.region,
            district=cls.district,
        )
        cls.case = TransformationCase.objects.create(
            school=cls.school, status="active", opened_fy="2026"
        )

        def _person(email, role):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0],
                roles=[role.value],
                active_role=role.value,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"RG-{email[:6]}", country="Uganda"
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("reg-cceo@edify.org", EdifyRole.CCEO)
        cls.cd, cls.cd_sp = _person("reg-cd@edify.org", EdifyRole.COUNTRY_DIRECTOR)
        cls.ia, cls.ia_sp = _person("reg-ia@edify.org", EdifyRole.IMPACT_ASSESSMENT)
        cls.accountant, _ = _person("reg-acct@edify.org", EdifyRole.PROGRAM_ACCOUNTANT)
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

        cls.requirement = ComplianceRequirement.objects.filter(active=True).first()

        # Both portfolios list schools that carry a governed signal for their
        # intervention. Without one the school is simply not in the list, and
        # every metric below would be asserting zero against an empty page
        # rather than against an unwritten register.
        from apps.core.enums import SsaIntervention

        from .models import (
            CaseRecommendation,
            CaseTrigger,
            RecommendationKind,
            TriggerType,
        )

        trigger = CaseTrigger.objects.create(
            case=cls.case,
            trigger_type=TriggerType.choices[0][0],
            source_id="register-fixture",
        )
        for index, intervention in enumerate(
            (SsaIntervention.GOVERNMENT_REQUIREMENT, SsaIntervention.FINANCIAL_HEALTH)
        ):
            CaseRecommendation.objects.create(
                case=cls.case,
                trigger=trigger,
                kind=RecommendationKind.choices[index][0],
                reason="Register fixture",
                source_intervention=intervention,
            )

    def setUp(self):
        self.today = timezone.localdate()


class ComplianceRegisterIsWritableTest(AssessmentRegisterFixture):
    """GOV-01, first register: the government requirements."""

    def _record(self, actor=None, **overrides):
        payload = {
            "requirementId": self.requirement.id,
            "status": ComplianceStatus.COMPLIANT,
            "registrationNumber": "REG/2026/00417",
            "registrationDate": (self.today - datetime.timedelta(days=30)).isoformat(),
            "evidenceReference": "certificate-2026.pdf",
            "responsiblePerson": "Head Teacher",
        }
        payload.update(overrides)
        return services.record_compliance_assessment(
            self.case.id, payload, actor or self.cceo
        )

    def test_the_register_can_be_written_at_all(self):
        """The whole of GOV-01, in one assertion."""
        assessment = self._record()

        self.assertTrue(
            SchoolComplianceAssessment.objects.filter(id=assessment.id).exists()
        )
        self.assertEqual(assessment.status, ComplianceStatus.COMPLIANT)
        self.assertEqual(assessment.registration_number, "REG/2026/00417")
        self.assertEqual(assessment.assessed_by, str(self.cceo.id))
        self.assertIsNotNone(assessment.assessed_at)

    def test_a_recorded_assessment_is_a_claim_until_ia_verifies_it(self):
        """The portfolio counts compliance only when IA has confirmed it."""
        assessment = self._record()
        self.assertEqual(assessment.ia_status, IAValidationStatus.PENDING)

        metrics = services.government_requirements_context(self.cd, {})["metrics"]
        self.assertEqual(
            metrics["compliant"],
            0,
            "an unverified assessment is what a school says about itself; it "
            "must not be counted as compliance",
        )
        self.assertEqual(metrics["awaitingVerification"], 1)

        services.verify_compliance_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        metrics = services.government_requirements_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["compliant"], 1)
        self.assertEqual(metrics["awaitingVerification"], 0)

    def test_only_impact_assessment_verifies_and_never_the_recorder(self):
        assessment = self._record()
        for actor in (self.cceo, self.cd, self.accountant):
            with self.subTest(actor.active_role):
                with self.assertRaises(Forbidden):
                    services.verify_compliance_assessment(
                        assessment.id, {"decision": "verified"}, actor
                    )

    def test_a_role_with_no_school_support_authority_cannot_record(self):
        with self.assertRaises(Forbidden):
            self._record(actor=self.accountant)

    def test_re_recording_a_changed_status_sends_it_back_for_verification(self):
        """A stale approval must not stay attached to a new fact."""
        assessment = self._record()
        services.verify_compliance_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )

        updated = self._record(status=ComplianceStatus.EXPIRED)
        self.assertEqual(updated.id, assessment.id, "one row per requirement")
        self.assertEqual(updated.status, ComplianceStatus.EXPIRED)
        self.assertEqual(
            updated.ia_status,
            IAValidationStatus.PENDING,
            "the verification was of the old status; a new one has not been "
            "verified by anybody",
        )
        self.assertIsNone(updated.ia_verified_at)

    def test_re_recording_the_same_status_does_not_disturb_its_verification(self):
        """Guard the rule above from over-firing on a no-op re-save."""
        assessment = self._record()
        services.verify_compliance_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        verified_at = SchoolComplianceAssessment.objects.get(
            id=assessment.id
        ).ia_verified_at

        again = self._record()
        self.assertEqual(again.ia_status, IAValidationStatus.VERIFIED)
        self.assertEqual(again.ia_verified_at, verified_at)

    def test_an_unknown_status_is_refused(self):
        with self.assertRaises(BadRequest):
            self._record(status="probably_fine")

    def test_ia_can_return_an_assessment_with_a_reason(self):
        assessment = self._record()
        returned = services.verify_compliance_assessment(
            assessment.id,
            {"decision": "returned", "note": "Certificate is for the wrong year."},
            self.ia,
        )
        self.assertEqual(returned.ia_status, IAValidationStatus.RETURNED)
        self.assertIn("wrong year", returned.ia_note)

        metrics = services.government_requirements_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["compliant"], 0)

    def test_an_expiry_date_is_derived_from_the_requirement_renewal_period(self):
        """The register exists to say when a permit lapses, not only that it exists."""
        self.requirement.renewal_months = 12
        self.requirement.save(update_fields=["renewal_months"])
        registered_on = self.today - datetime.timedelta(days=30)

        assessment = self._record(registrationDate=registered_on.isoformat())

        self.assertEqual(
            assessment.expiry_date,
            registered_on + datetime.timedelta(days=365),
            "a renewal period and a registration date are an expiry date; "
            "leaving the reader to work it out is how a lapsed permit goes "
            "unnoticed",
        )


class FinancialPracticeRegisterIsWritableTest(AssessmentRegisterFixture):
    """GOV-01, second register: operational financial practice."""

    def _record(self, actor=None, **overrides):
        payload = {
            "assessedOn": self.today.isoformat(),
            "practices": {
                "separate_bank_account": True,
                "monthly_reconciliation": True,
                "documented_fee_policy": False,
            },
            "notes": "Reconciliation seen for the last three months.",
        }
        payload.update(overrides)
        return services.record_financial_practice_assessment(
            self.case.id, payload, actor or self.cceo
        )

    def test_the_register_can_be_written_at_all(self):
        assessment = self._record()
        self.assertTrue(
            FinancialPracticeAssessment.objects.filter(id=assessment.id).exists()
        )
        self.assertEqual(assessment.recorded_by, str(self.cceo.id))
        self.assertEqual(assessment.verification_status, IAValidationStatus.PENDING)

    def test_the_portfolio_separates_assessed_from_verified(self):
        assessment = self._record()
        metrics = services.financial_health_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["practiceAssessed"], 1)
        self.assertEqual(
            metrics["practiceVerified"],
            0,
            "assessed and verified are different claims and the tiles show "
            "both; recording one must not fill in the other",
        )

        services.verify_financial_practice_assessment(
            assessment.id, {"decision": "verified"}, self.ia
        )
        metrics = services.financial_health_context(self.cd, {})["metrics"]
        self.assertEqual(metrics["practiceVerified"], 1)

    def test_practices_must_be_a_mapping_of_named_findings(self):
        with self.assertRaises(BadRequest):
            self._record(practices=["separate_bank_account"])
        with self.assertRaises(BadRequest):
            self._record(practices={})

    def test_one_assessment_per_case_per_date(self):
        first = self._record()
        again = self._record(notes="Corrected after a second look.")
        self.assertEqual(first.id, again.id)
        self.assertEqual(again.notes, "Corrected after a second look.")
        self.assertEqual(
            FinancialPracticeAssessment.objects.filter(case=self.case).count(), 1
        )

    def test_only_impact_assessment_verifies(self):
        assessment = self._record()
        with self.assertRaises(Forbidden):
            services.verify_financial_practice_assessment(
                assessment.id, {"decision": "verified"}, self.cceo
            )
