"""Employee relations, worked from the screen (2026-09-13).

The Regional HR Director oversees "disciplinary matters" and "disputes and
investigations". The service could open and advance a case; no screen called
it, and the register's counts filtered title-case statuses the model never
stores. These tests drive the drawers and the register the way the director
does.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.hr.models import EmployeeRelationsCase, ERCaseStatus, ERCaseType


def _person(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="pwd",
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=email.split("@")[0].upper(), country=country
    )
    return user, profile


class EmployeeRelationsWorkflowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("er-director@edify.test", "HumanResources")
        cls.investigator, _ = _person("er-investigator@edify.test", "HumanResources")
        cls.staff, cls.staff_sp = _person("er-staff@edify.test", "CCEO")
        cls.colleague, cls.colleague_sp = _person("er-colleague@edify.test", "CCEO")
        cls.kenyan, cls.kenyan_sp = _person(
            "er-kenyan@edify.test", "CCEO", country="Kenya"
        )

    def setUp(self):
        self.client.force_login(self.hr)

    def _open(self, **overrides):
        data = {
            "case_type": ERCaseType.DISCIPLINARY,
            "subject_staff_id": self.staff_sp.id,
            "severity": "high",
            "description": "Repeated absence from scheduled school visits.",
            "is_confidential": "1",
            "next": "/employee-relations",
        }
        data.update(overrides)
        return self.client.post("/employee-relations/open", data)

    def test_the_director_opens_a_disciplinary_case_from_the_drawer(self):
        drawer = self.client.get("/employee-relations/new")
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "Disciplinary matter")
        self.assertContains(drawer, "Dispute between staff")

        response = self._open()
        self.assertEqual(response.status_code, 302)
        case = EmployeeRelationsCase.objects.get()
        self.assertEqual(case.country, "Uganda", "the subject's country")
        self.assertEqual(case.status, ERCaseStatus.SUBMITTED)
        self.assertEqual(case.case_owner_id, self.hr.id)

    def test_a_dispute_names_both_parties(self):
        self._open(case_type=ERCaseType.DISPUTE)
        self.assertFalse(EmployeeRelationsCase.objects.exists())
        self._open(
            case_type=ERCaseType.DISPUTE, complainant_staff_id=self.colleague_sp.id
        )
        case = EmployeeRelationsCase.objects.get()
        self.assertEqual(case.complainant_staff_id, self.colleague_sp.id)

    def test_a_case_cannot_be_opened_outside_the_countries_overseen(self):
        self._open(subject_staff_id=self.kenyan_sp.id)
        self.assertFalse(EmployeeRelationsCase.objects.exists())

    def test_the_register_counts_real_statuses(self):
        self._open()
        case = EmployeeRelationsCase.objects.get()
        page = self.client.get("/employee-relations")
        self.assertEqual(page.status_code, 200)
        metrics = {item["label"]: item for item in page.context["metrics"]}
        self.assertEqual(str(metrics["Open cases"]["value"]), "1")
        self.assertEqual(str(metrics["Awaiting triage"]["value"]), "1")
        self.assertEqual(str(metrics["Disciplinary matters"]["value"]), "1")
        self.assertContains(page, "Disciplinary matter · Er Staff")
        self.assertContains(page, f"/employee-relations/{case.id}")
        self.assertNotContains(page, ">disciplinary<")

    def test_the_case_moves_through_its_workflow_with_its_evidence(self):
        self._open()
        case = EmployeeRelationsCase.objects.get()
        url = f"/employee-relations/{case.id}/advance"

        self.assertEqual(
            self.client.get(f"/employee-relations/{case.id}").status_code, 200
        )
        self.client.post(url, {"to_status": ERCaseStatus.TRIAGE})
        self.client.post(url, {"to_status": ERCaseStatus.INVESTIGATION})
        case.refresh_from_db()
        self.assertEqual(case.status, ERCaseStatus.TRIAGE, "no investigator named")

        self.client.post(
            url,
            {
                "to_status": ERCaseStatus.INVESTIGATION,
                "investigator_id": self.investigator.id,
            },
        )
        self.client.post(
            url, {"to_status": ERCaseStatus.FINDINGS, "note": "Confirmed."}
        )
        self.client.post(
            url, {"to_status": ERCaseStatus.ACTION, "note": "Warning issued."}
        )
        case.refresh_from_db()
        self.assertEqual(case.status, ERCaseStatus.FINDINGS, "no sanction recorded")

        self.client.post(
            url,
            {
                "to_status": ERCaseStatus.ACTION,
                "note": "Warning issued.",
                "sanction": "written_warning",
                "hearing_date": "2026-09-20",
            },
        )
        case.refresh_from_db()
        self.assertEqual(case.status, ERCaseStatus.ACTION)
        self.assertEqual(case.sanction, "written_warning")
        self.assertEqual(case.hearing_date.isoformat(), "2026-09-20")
        self.assertEqual(case.investigator_id, self.investigator.id)

    def test_another_countrys_case_does_not_exist_for_the_director(self):
        case = EmployeeRelationsCase.objects.create(
            subject_staff=self.kenyan_sp,
            country="Kenya",
            case_type=ERCaseType.GRIEVANCE,
            description="Kenya case",
            is_confidential=False,
        )
        self.assertEqual(
            self.client.get(f"/employee-relations/{case.id}").status_code, 404
        )
