"""Policy and compliance for the Regional HR Director (2026-09-13).

"Monitors and ensures the organization's compliance with country/regional
employment laws" and "reviews and modifies policies". The compliance register
had no writer, the policies page listed nothing real and denied that
acknowledgements were tracked, and a KPI panel before a table rendered its
labels white on white.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import StaffProfile, User
from apps.hr.models import ComplianceRequirement, EmployeeComplianceRecord

ROOT = Path(__file__).resolve().parents[2]


def _person(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="pwd",
        is_active=True,
        status="active",
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=email.split("@")[0].upper(), country=country
    )
    return user, profile


class EmploymentComplianceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, _ = _person("pc-hr@edify.test", "HumanResources")
        cls.officer, cls.officer_sp = _person("pc-officer@edify.test", "CCEO")
        cls.kenyan, cls.kenyan_sp = _person("pc-kenyan@edify.test", "CCEO", "Kenya")

    def setUp(self):
        self.client.force_login(self.hr)

    def _requirement(self, country="Uganda", name="Signed employment contract"):
        self.client.post(
            "/compliance-register/requirement/add",
            {"country": country, "name": name, "is_mandatory": "1"},
        )
        return ComplianceRequirement.objects.filter(country=country, name=name).first()

    def _evidence(self, staff, requirement, **extra):
        data = {"staff_id": staff.id, "requirement_id": requirement.id}
        data.update(extra)
        self.client.post("/compliance-register/save", data)
        return EmployeeComplianceRecord.objects.filter(
            staff=staff, requirement=requirement
        ).first()

    def test_requirements_are_limited_to_the_countries_overseen(self):
        self.assertIsNotNone(self._requirement())
        self.assertIsNone(self._requirement(country="Kenya"))
        self.assertIsNone(self._requirement(country="All"), "every country is Admin's")

    def test_the_status_follows_the_evidence_and_its_expiry(self):
        requirement = self._requirement(name="Work permit")
        record = self._evidence(self.officer_sp, requirement)
        self.assertEqual(record.status, "Missing")

        later = (date.today() + timedelta(days=200)).isoformat()
        record = self._evidence(
            self.officer_sp, requirement, document_url="HR file 12", expiry_date=later
        )
        self.assertEqual(record.status, "Compliant")

        soon = (date.today() + timedelta(days=10)).isoformat()
        record = self._evidence(
            self.officer_sp, requirement, document_url="HR file 12", expiry_date=soon
        )
        self.assertEqual(record.status, "Due Soon")

        past = (date.today() - timedelta(days=1)).isoformat()
        record = self._evidence(
            self.officer_sp,
            requirement,
            document_url="HR file 12",
            expiry_date=past,
            verified="1",
        )
        self.assertEqual(record.status, "Expired")
        self.assertEqual(record.verified_by_id, self.hr.id)

        page = self.client.get("/compliance-register")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        # The officer's expired permit, and the director's own profile, which
        # has no record against the mandatory requirement at all.
        self.assertEqual(metrics["Missing or expired"], "2")

    def test_an_employee_with_no_record_is_listed_as_missing(self):
        requirement = self._requirement(name="Signed employment contract")
        page = self.client.get("/compliance-register")
        self.assertContains(page, "No evidence on file")
        self.assertContains(
            page,
            f"/compliance-register/new?staff={self.officer_sp.id}"
            f"&amp;requirement={requirement.id}",
        )
        self.assertNotContains(page, "Pc Kenyan", msg_prefix="outside the reach")

        drawer = self.client.get(
            "/compliance-register/new",
            {"staff": self.officer_sp.id, "requirement": requirement.id},
        )
        self.assertContains(
            drawer, f'<option value="{self.officer_sp.id}" selected>', html=False
        )

        self._evidence(self.officer_sp, requirement, document_url="HR file 3")
        page = self.client.get("/compliance-register", {"q": "officer"})
        self.assertNotContains(page, "No evidence on file")

    def test_evidence_is_refused_outside_the_reach_and_the_requirement_country(self):
        uganda = self._requirement()
        self.assertIsNone(self._evidence(self.kenyan_sp, uganda))
        kenya = ComplianceRequirement.objects.create(country="Kenya", name="KRA PIN")
        self.assertIsNone(self._evidence(self.officer_sp, kenya))


class PoliciesHubTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.documents.models import (
            AcknowledgementState,
            DocumentAcknowledgement,
            DocumentAsset,
            DocumentStatus,
            DocumentType,
            DocumentVersion,
        )

        cls.hr, _ = _person("ph-hr@edify.test", "HumanResources")
        cls.agreed, _ = _person("ph-agreed@edify.test", "CCEO")
        cls.pending, _ = _person("ph-pending@edify.test", "CCEO")
        cls.kenyan, _ = _person("ph-kenyan@edify.test", "CCEO", "Kenya")
        cls.document = DocumentAsset.objects.create(
            title="Staff Code of Conduct",
            slug="staff-code-of-conduct",
            document_type=DocumentType.POLICY,
            status=DocumentStatus.PUBLISHED,
            acknowledgement_required=True,
        )
        version = DocumentVersion.objects.create(
            document=cls.document,
            version_number=2,
            uri="documents/code.pdf",
            original_filename="code.pdf",
            review_date=date.today() + timedelta(days=30),
        )
        cls.document.current_version = version
        cls.document.save(update_fields=["current_version"])
        for user, state in (
            (cls.agreed, AcknowledgementState.AGREED),
            (cls.pending, AcknowledgementState.PENDING),
            (cls.kenyan, AcknowledgementState.AGREED),
        ):
            DocumentAcknowledgement.objects.create(
                document=cls.document, version=version, user_id=user.id, state=state
            )

    def test_the_hub_lists_real_policies_with_reach_limited_acknowledgements(self):
        self.client.force_login(self.hr)
        page = self.client.get("/policies")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Staff Code of Conduct")
        self.assertContains(
            page, "1 of 2", msg_prefix="the Kenyan agreement is not counted"
        )
        self.assertContains(page, "/documents/staff-code-of-conduct/manage")
        self.assertNotContains(page, "acknowledgement model exists")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        self.assertEqual(metrics["Acknowledgement rate"], "50%")
        self.assertEqual(metrics["Policy reviews due"], "1")


class AuditAndTitleBarTest(SimpleTestCase):
    def test_audit_actions_read_as_words(self):
        from apps.frontend.views.hr_views import _audit_action_label

        self.assertEqual(
            _audit_action_label("hr.er_case_opened"), "HR · Er case opened"
        )
        self.assertEqual(
            _audit_action_label("documents.acknowledgement_agreed"),
            "Policy · Acknowledgement agreed",
        )

    def test_a_kpi_panel_is_never_a_tables_title_bar(self):
        js = (ROOT / "static/js/micro-ux.js").read_text()
        self.assertIn("[data-context-metrics], .context-metrics", js)
