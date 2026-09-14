"""Lending evidence for Impact Assessment (IA review, owner, 2026-09-13).

Pinned here:
- lending impact reads are bounded to the reader's country (IA, the Country
  Director, Business Transformation); the RVP and a country role with no
  country stay wide; the district spine is the reader's country;
- every IA verification refuses a record whose loan is in another country;
- a loan impact conclusion is prepared by one person and verified by
  another: Business Transformation prepares and IA verifies; where the
  country has no BT officer IA prepares, a second IA officer verifies, and
  the Country Director only where there is none; a return needs a note and
  goes back to the preparer; the classification reaches the loan only on
  verification;
- /ia/lending-evidence/ lists and verifies through one-column drawers, the
  prepare drawer is reachable from Business Transformation's page, other
  roles are refused, and the page and To-Do rows cost a fixed number of
  queries.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.impact.learning_todos import learning_todos
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.schools.models import School

from . import lending_impact as li
from .models import (
    EnrolmentSnapshot,
    ImpactEvidenceStatus,
    LoanImpactAssessment,
    LoanPurpose,
    LoanPurposeAllocation,
    LoanStatus,
    LoanUseFinding,
    LoanUseResult,
    LoanVerificationRequirement,
    MfiLoan,
    MfiOrganization,
    PurposeAllocationStatus,
    PurposeSpecificAssetOutput,
    TeacherDegreeUpgradeBeneficiary,
    TransformationCase,
)

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
BTO = EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value
RVP = EdifyRole.REGIONAL_VICE_PRESIDENT.value
CCEO = EdifyRole.CCEO.value

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-lending-evidence-tests",
    }
}

CONCLUSION = {
    "classification": "positive",
    "narrative": "Enrolment rose after the classroom block opened.",
    "limitations": "Observed after financing; no counterfactual.",
    "evidenceReferences": "SITE-VISIT-1\nREGISTER-2",
}


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    if country is not None:
        StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


@override_settings(CACHES=LOCMEM)
class LendingEvidenceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mfi = MfiOrganization.objects.create(code="LE-MFI", name="LE MFI")
        cls.purpose = LoanPurpose.objects.create(code="LE-CLASS", label="Classrooms")
        cls.ug = Region.objects.create(name="Lending Central", country="Uganda")
        cls.ke = Region.objects.create(name="Lending Coast", country="Kenya")
        cls.tz = Region.objects.create(name="Lending Lake", country="Tanzania")
        cls.ug_loan = cls._loan("LE-UG", cls.ug)
        cls.ke_loan = cls._loan("LE-KE", cls.ke)
        cls.tz_loan = cls._loan("LE-TZ", cls.tz)

        cls.ia = _user("le-ia@t.org", IA)
        cls.ia2 = _user("le-ia2@t.org", IA)
        cls.cd = _user("le-cd@t.org", CD)
        cls.bto = _user("le-bto@t.org", BTO)
        cls.rvp = _user("le-rvp@t.org", RVP, country=None)
        cls.cceo = _user("le-cceo@t.org", CCEO)
        cls.ke_ia = _user("le-ke-ia@t.org", IA, country="Kenya")
        cls.tz_ia = _user("le-tz-ia@t.org", IA, country="Tanzania")
        cls.tz_cd = _user("le-tz-cd@t.org", CD, country="Tanzania")

    @classmethod
    def _loan(cls, code, region):
        district = District.objects.create(name=f"District {code}", region=region)
        school = School.objects.create(
            name=f"School {code}",
            school_id=code,
            region=region,
            district=district,
            enrollment=400,
        )
        case = TransformationCase.objects.create(
            school=school, status="active", opened_fy="2026"
        )
        loan = MfiLoan.objects.create(
            mfi=cls.mfi,
            school=school,
            case=case,
            purpose=cls.purpose,
            external_loan_reference=f"REF-{code}",
            approved_amount=Decimal("1000.00"),
            currency="UGX",
            status=LoanStatus.PROCESSING,
            registered_by="mfi-user",
        )
        return loan

    def _evidence(self, loan):
        """Verified use, baseline and follow-up, and a due assessment."""
        requirement = LoanVerificationRequirement.objects.create(
            loan=loan, due_date=date(2026, 3, 1), status="verified"
        )
        LoanUseResult.objects.create(
            requirement=requirement,
            finding=LoanUseFinding.FULLY_APPROVED,
            recorded_by="mfi-user",
            verification_status="confirmed",
        )
        for kind, day, count in (
            ("baseline", date(2026, 1, 1), 400),
            ("follow_up", date(2026, 6, 1), 450),
        ):
            EnrolmentSnapshot.objects.create(
                loan=loan,
                kind=kind,
                as_of_date=day,
                learner_count=count,
                cohort_definition="All learners",
                evidence_reference=f"REG-{kind}",
                status=ImpactEvidenceStatus.VERIFIED,
                reported_by="mfi-user",
                verified_by="ia-verifier",
                verified_at=timezone.now(),
            )
        return LoanImpactAssessment.objects.create(
            loan=loan, due_date=timezone.localdate() - timedelta(days=1)
        )


class LendingCountryBoundaryTests(LendingEvidenceFixture):
    def test_country_roles_read_their_countrys_loans_only(self):
        for user in (self.ia, self.cd, self.bto):
            with self.subTest(role=user.active_role):
                self.assertEqual(
                    set(li.scoped_impact_loans(user).values_list("id", flat=True)),
                    {self.ug_loan.id},
                )
        self.assertEqual(li.scoped_impact_loans(self.rvp).count(), 3)
        self.assertEqual(
            li.scoped_impact_loans(_user("le-ia-none@t.org", IA, country=None)).count(),
            3,
        )
        self.assertEqual(li.impact_summary(self.ke_ia)["loansInScope"], 1)
        spine = {row["district"] for row in li.geographic_equity(self.ia)["rows"]}
        self.assertIn("District LE-UG", spine)
        self.assertNotIn("District LE-KE", spine)

    def test_ia_cannot_verify_another_countrys_evidence(self):
        snapshot = EnrolmentSnapshot.objects.create(
            loan=self.ke_loan,
            kind="baseline",
            as_of_date=date(2026, 1, 1),
            learner_count=300,
            cohort_definition="All",
            evidence_reference="KE-REG",
            reported_by="mfi-user",
        )
        allocation = LoanPurposeAllocation.objects.create(
            loan=self.ke_loan,
            purpose=self.purpose,
            planned_amount=Decimal("1000.00"),
            reported_amount=Decimal("900.00"),
            intended_output="Classrooms",
            status=PurposeAllocationStatus.REPORTED,
            recorded_by="mfi-user",
        )
        output = PurposeSpecificAssetOutput.objects.create(
            allocation=allocation,
            asset_type="classroom",
            planned_quantity=2,
            reported_quantity=2,
            evidence_reference="PHOTOS",
            status=ImpactEvidenceStatus.REPORTED,
            reported_by="mfi-user",
        )
        teacher = TeacherDegreeUpgradeBeneficiary.objects.create(
            loan=self.ke_loan,
            anonymized_reference="T-1",
            institution="Uni",
            programme="BEd",
            started_on=date(2025, 1, 1),
            completed_on=date(2026, 1, 1),
            evidence_reference="CERT",
            status=ImpactEvidenceStatus.REPORTED,
            reported_by="mfi-user",
        )
        calls = (
            (li.verify_enrolment_snapshot, snapshot.id, {}),
            (li.verify_purpose_use, allocation.id, {"verifiedAmount": "900.00"}),
            (li.verify_asset_output, output.id, {"verifiedQuantity": 2}),
            (li.verify_teacher_completion, teacher.id, {}),
        )
        for fn, record_id, data in calls:
            with self.subTest(fn=fn.__name__), self.assertRaises(NotFoundError):
                fn(record_id, data, self.ia)
        li.verify_enrolment_snapshot(snapshot.id, {}, self.ke_ia)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, "verified")

    def test_a_return_needs_a_note(self):
        allocation = LoanPurposeAllocation.objects.create(
            loan=self.ug_loan,
            purpose=self.purpose,
            planned_amount=Decimal("1000.00"),
            reported_amount=Decimal("900.00"),
            intended_output="Classrooms",
            status=PurposeAllocationStatus.REPORTED,
            recorded_by="mfi-user",
        )
        with self.assertRaises(BadRequest):
            li.verify_purpose_use(allocation.id, {"decision": "returned"}, self.ia)
        li.verify_purpose_use(
            allocation.id, {"decision": "returned", "note": "Invoices missing"}, self.ia
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, PurposeAllocationStatus.RETURNED)
        self.assertIsNone(allocation.verified_amount)


class LoanImpactTwoStepTests(LendingEvidenceFixture):
    def test_business_transformation_prepares_and_ia_verifies(self):
        assessment = self._evidence(self.ug_loan)
        with self.assertRaises(BadRequest):
            li.verify_loan_impact(assessment.id, {}, self.ia)
        with self.assertRaises(Forbidden):  # a BT officer is in Uganda
            li.prepare_loan_impact(assessment.id, CONCLUSION, self.ia)
        li.prepare_loan_impact(assessment.id, CONCLUSION, self.bto)
        assessment.refresh_from_db()
        self.assertEqual(assessment.prepared_by, self.bto.id)
        self.assertEqual(assessment.ia_status, "pending")
        self.ug_loan.refresh_from_db()
        self.assertNotEqual(self.ug_loan.impact_status, "positive")
        self.assertEqual(assessment.evidence_references, ["SITE-VISIT-1", "REGISTER-2"])
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.ia.id, context_id=assessment.id
            ).exists()
        )
        with self.assertRaises(Forbidden):
            li.verify_loan_impact(assessment.id, {}, self.bto)
        with self.assertRaises(Forbidden):  # not the verifying role
            li.verify_loan_impact(assessment.id, {}, self.cd)
        with self.assertRaises(NotFoundError):
            li.verify_loan_impact(assessment.id, {}, self.ke_ia)
        li.verify_loan_impact(assessment.id, {"note": "Checked"}, self.ia)
        assessment.refresh_from_db()
        self.ug_loan.refresh_from_db()
        self.assertEqual(assessment.ia_status, "verified")
        self.assertEqual(assessment.ia_verified_by, self.ia.id)
        self.assertEqual(self.ug_loan.impact_status, "positive")
        self.assertTrue(
            AuditLog.objects.filter(
                action="bt.loan.impact_verified", subject_id=assessment.id
            ).exists()
        )
        with self.assertRaises(BadRequest):
            li.prepare_loan_impact(assessment.id, CONCLUSION, self.bto)

    def test_a_returned_conclusion_goes_back_to_its_preparer(self):
        assessment = self._evidence(self.ug_loan)
        li.prepare_loan_impact(assessment.id, CONCLUSION, self.bto)
        with self.assertRaises(BadRequest):
            li.verify_loan_impact(assessment.id, {"decision": "returned"}, self.ia)
        li.verify_loan_impact(
            assessment.id,
            {"decision": "returned", "note": "Cite the register"},
            self.ia,
        )
        assessment.refresh_from_db()
        self.assertEqual(assessment.ia_status, "returned")
        with self.assertRaises(BadRequest):
            li.verify_loan_impact(assessment.id, {}, self.ia)
        self.assertIn(
            "bt-impact-conclusions-returned",
            [t["id"] for t in learning_todos(self.bto, BTO, timezone.localdate())],
        )
        route, _label = NotificationLinkResolver.resolve(
            li.EVENT_IMPACT_RETURNED, "LoanImpactAssessment", assessment.id, BTO
        )
        self.assertEqual(route, "/business-transformation/impact-reports")
        li.prepare_loan_impact(assessment.id, CONCLUSION, self.bto)
        li.verify_loan_impact(assessment.id, {}, self.ia2)
        assessment.refresh_from_db()
        self.assertEqual(assessment.ia_status, "verified")

    def test_where_no_bt_officer_ia_prepares_and_a_second_reader_verifies(self):
        assessment = self._evidence(self.tz_loan)
        with self.assertRaises(NotFoundError):  # another country's director
            li.prepare_loan_impact(assessment.id, CONCLUSION, self.cd)
        with self.assertRaises(Forbidden):  # the director never prepares
            li.prepare_loan_impact(assessment.id, CONCLUSION, self.tz_cd)
        li.prepare_loan_impact(assessment.id, CONCLUSION, self.tz_ia)
        with self.assertRaises(Forbidden):
            li.verify_loan_impact(assessment.id, {}, self.tz_ia)
        self.assertIn(
            "bt-impact-conclusions-verify",
            [t["id"] for t in learning_todos(self.tz_cd, CD, timezone.localdate())],
        )
        li.verify_loan_impact(assessment.id, {}, self.tz_cd)
        assessment.refresh_from_db()
        self.assertEqual(assessment.ia_status, "verified")
        self.assertTrue(
            AuditLog.objects.filter(
                action="bt.loan.impact_verified", subject_id=assessment.id
            ).exists()
        )

    def test_the_country_director_is_refused_where_a_second_officer_exists(self):
        second = _user("le-tz-ia2@t.org", IA, country="Tanzania")
        assessment = self._evidence(self.tz_loan)
        li.prepare_loan_impact(assessment.id, CONCLUSION, self.tz_ia)
        with self.assertRaises(Forbidden):
            li.verify_loan_impact(assessment.id, {}, self.tz_cd)
        li.verify_loan_impact(assessment.id, {}, second)

    def test_a_conclusion_needs_its_verified_evidence(self):
        assessment = LoanImpactAssessment.objects.create(
            loan=self.ug_loan, due_date=timezone.localdate() - timedelta(days=1)
        )
        with self.assertRaises(BadRequest):
            li.prepare_loan_impact(assessment.id, CONCLUSION, self.bto)


class LendingEvidencePageTests(LendingEvidenceFixture):
    def test_every_tab_renders_and_refuses_other_roles(self):
        self._evidence(self.ug_loan)
        self.client.force_login(self.ia)
        for tab in (
            "use",
            "enrolment",
            "outputs",
            "teachers",
            "conclusions",
            "cohorts",
        ):
            with self.subTest(tab=tab):
                response = self.client.get(f"/ia/lending-evidence/?tab={tab}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-ia-lending-evidence")
        self.client.force_login(self.cceo)
        self.assertEqual(
            self.client.get(
                "/ia/lending-evidence/", HTTP_HX_REQUEST="true"
            ).status_code,
            403,
        )

    def test_business_transformation_prepares_from_its_page_and_ia_verifies(self):
        assessment = self._evidence(self.ug_loan)
        self.client.force_login(self.bto)
        drawer = self.client.get(f"/ia/lending-evidence/conclusions/{assessment.id}/")
        self.assertContains(drawer, "Prepare loan impact conclusion")
        self.client.post(
            f"/ia/lending-evidence/conclusions/{assessment.id}/prepare", CONCLUSION
        )
        assessment.refresh_from_db()
        self.assertEqual(assessment.prepared_by, self.bto.id)
        # The preparer cannot reach the verify route at all.
        self.assertEqual(
            self.client.post(
                f"/ia/lending-evidence/conclusions/{assessment.id}/verify", {}
            ).status_code,
            403,
        )
        self.client.force_login(self.ia)
        drawer = self.client.get(f"/ia/lending-evidence/conclusions/{assessment.id}/")
        self.assertContains(drawer, "Verify loan impact conclusion")
        self.client.post(
            f"/ia/lending-evidence/conclusions/{assessment.id}/verify",
            {"decision": "verified"},
        )
        assessment.refresh_from_db()
        self.assertEqual(assessment.ia_status, "verified")
        self.client.force_login(self.ke_ia)
        self.assertContains(
            self.client.get(f"/ia/lending-evidence/conclusions/{assessment.id}/"),
            "not in your country",
        )

    def test_a_refused_verification_shows_the_service_message(self):
        allocation = LoanPurposeAllocation.objects.create(
            loan=self.ug_loan,
            purpose=self.purpose,
            planned_amount=Decimal("1000.00"),
            reported_amount=Decimal("900.00"),
            intended_output="Classrooms",
            status=PurposeAllocationStatus.REPORTED,
            recorded_by="mfi-user",
        )
        self.client.force_login(self.ia)
        self.assertContains(
            self.client.get(f"/ia/lending-evidence/use/{allocation.id}/"),
            "Verify loan use",
        )
        response = self.client.post(
            f"/ia/lending-evidence/use/{allocation.id}/verify",
            {"decision": "verified", "verifiedAmount": "950.00"},
            follow=True,
        )
        self.assertContains(response, "cannot exceed partner-reported use")
        self.client.post(
            f"/ia/lending-evidence/use/{allocation.id}/verify",
            {"decision": "verified", "verifiedAmount": "850.00"},
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, PurposeAllocationStatus.VERIFIED)

    def test_financed_cohorts_grade_and_flag_maturity(self):
        from apps.frontend.views import ia_lending_views as lv

        today = timezone.localdate()
        rows = [
            {
                "loan_id": self.ug_loan.id,
                "loan__school_id": self.ug_loan.school_id,
                "loan__purpose_id": self.purpose.id,
                "loan__purpose__label": "Classrooms",
                "loan__purpose__follow_up_days": 365,
                "disbursed_on": today - timedelta(days=40),
            }
        ]
        self._evidence(self.ug_loan)
        stub = MagicMock()
        stub.objects.filter.return_value.order_by.return_value.values.return_value = (
            rows
        )
        with patch.object(lv, "LoanDisbursement", stub):
            cohorts = lv.financed_cohorts(self.ia, today=today)
        self.assertEqual(len(cohorts), 1)
        cohort = cohorts[0]
        self.assertTrue(cohort["immature"])
        self.assertEqual(cohort["loans"], 1)
        self.assertEqual(cohort["due"], 1)
        self.assertEqual(cohort["enrolment_pairs"], 1)
        self.assertIsNone(cohort["median_enrolment_change_pct"])
        self.assertEqual(cohort["grade"]["grade"], "insufficient")

    def test_the_page_and_todos_cost_a_fixed_number_of_queries(self):
        self._evidence(self.ug_loan)
        self.client.force_login(self.ia)
        self.client.get("/ia/lending-evidence/?tab=conclusions")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/ia/lending-evidence/?tab=conclusions")
        with CaptureQueriesContext(connection) as todo_small:
            learning_todos(self.ia, IA, timezone.localdate())
        for code in ("LE-UG2", "LE-UG3", "LE-UG4"):
            loan = self._loan(code, self.ug)
            self._evidence(loan)
            li.prepare_loan_impact(
                LoanImpactAssessment.objects.get(loan=loan).id, CONCLUSION, self.bto
            )
        with CaptureQueriesContext(connection) as large:
            self.client.get("/ia/lending-evidence/?tab=conclusions")
        with CaptureQueriesContext(connection) as todo_large:
            rows = learning_todos(self.ia, IA, timezone.localdate())
        self.assertEqual(len(small), len(large))
        self.assertEqual(len(todo_small), len(todo_large))
        self.assertIn("bt-impact-conclusions-verify", [r["id"] for r in rows])
