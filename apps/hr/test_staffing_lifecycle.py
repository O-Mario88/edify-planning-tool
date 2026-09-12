"""Staffing, recruiting and retention, worked from the screens (2026-09-13).

The Regional HR Director "works with Country leadership to identify staffing
and recruiting needs, including planning ahead for growth and quick reaction
for replacement due to turnover". Every step existed as a service and no
screen called one. These tests walk a replacement hire end to end through the
drawers: request, approval by the Country Director, candidate, offer, hire,
onboarding, and the exit that caused it.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.hr.models import (
    Application,
    ApplicationStage,
    OffboardingPlan,
    OnboardingPlan,
    OnboardingStatus,
    Vacancy,
    VacancyStatus,
)


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


class StaffingLifecycleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("life-hr@edify.test", "HumanResources")
        cls.cd, cls.cd_sp = _person("life-cd@edify.test", "CountryDirector")
        cls.leaver, cls.leaver_sp = _person("life-leaver@edify.test", "CCEO")
        cls.kenya_cd, _ = _person(
            "life-kenya-cd@edify.test", "CountryDirector", "Kenya"
        )

    def _as(self, user):
        self.client.force_login(user)

    def test_a_replacement_hire_runs_end_to_end(self):
        # 1. The leaver resigns; HR starts the offboarding with a reason.
        self._as(self.hr)
        self.assertEqual(self.client.get("/offboarding/new").status_code, 200)
        self.client.post(
            "/offboarding/start",
            {
                "staff_id": self.leaver_sp.id,
                "last_working_day": "2026-10-31",
                "exit_reason": "resignation",
                "handover_owner_id": self.cd_sp.id,
                "note": "Relocating.",
            },
        )
        plan = OffboardingPlan.objects.get(staff=self.leaver_sp)
        self.assertEqual(plan.exit_reason, "resignation")
        page = self.client.get("/offboarding")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        self.assertEqual(metrics["Voluntary exits"], "1")

        # 2. HR requests the replacement; HR cannot approve their own request.
        self.client.post(
            "/recruitment/request",
            {
                "country": "Uganda",
                "role": "CCEO",
                "department": "Programmes",
                "replacement_or_new_role": "replacement",
                "reason": "Replacing a resignation.",
            },
        )
        vacancy = Vacancy.objects.get()
        self.assertEqual(vacancy.status, VacancyStatus.PENDING_APPROVAL)
        self.client.post(f"/recruitment/{vacancy.id}/decide", {"decision": "approve"})
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, VacancyStatus.PENDING_APPROVAL)

        page = self.client.get("/recruitment")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        self.assertEqual(metrics["Pending approval"], "1")
        self.assertEqual(metrics["Replacements"], "1")

        # 3. The Country Director approves it.
        self._as(self.cd)
        self.assertEqual(self.client.get(f"/recruitment/{vacancy.id}").status_code, 200)
        self.client.post(
            f"/recruitment/{vacancy.id}/decide",
            {"decision": "approve", "reason": "Budgeted replacement."},
        )
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, VacancyStatus.OPEN)

        # 4. HR records a candidate and moves them through selection.
        self._as(self.hr)
        self.client.post(
            "/candidate-pipeline/record",
            {
                "vacancy_id": vacancy.id,
                "name": "New Officer",
                "email": "new.officer@edify.test",
                "consent": "1",
            },
        )
        application = Application.objects.get()
        url = f"/candidate-pipeline/{application.id}/advance"
        for stage in ("screening", "interview", "reference_check"):
            self.client.post(url, {"to_stage": stage})
        self.client.post(url, {"to_stage": "offer"})
        application.refresh_from_db()
        self.assertEqual(
            application.stage, ApplicationStage.REFERENCE_CHECK, "offer needs a reason"
        )
        self.client.post(url, {"to_stage": "offer", "reason": "Strongest panel score."})
        self.client.post(url, {"to_stage": "accepted"})
        application.refresh_from_db()
        self.assertEqual(application.stage, ApplicationStage.ACCEPTED)

        # 5. Hire: the account is provisioned and onboarding opens.
        drawer = self.client.get(f"/candidate-pipeline/{application.id}")
        self.assertContains(drawer, "Hire and invite")
        self.client.post(
            f"/candidate-pipeline/{application.id}/hire",
            {"role": "CCEO", "supervisor_staff_id": ""},
        )
        application.refresh_from_db()
        self.assertEqual(application.stage, ApplicationStage.HIRED)
        hire = User.objects.get(email="new.officer@edify.test")
        onboarding = OnboardingPlan.objects.get(staff__user=hire)
        self.assertEqual(onboarding.status, OnboardingStatus.IN_PROGRESS)

        # 6. HR works the checklist and closes onboarding.
        task = onboarding.tasks.first()
        self.client.post(
            f"/onboarding/{onboarding.id}/record",
            {"action": "complete_tasks", f"task_{task.id}": "1"},
        )
        task.refresh_from_db()
        self.assertTrue(task.is_completed)
        self.client.post(
            f"/onboarding/{onboarding.id}/record", {"action": "close", "force": "1"}
        )
        onboarding.refresh_from_db()
        self.assertEqual(onboarding.status, OnboardingStatus.CLOSED)

        # 7. The leaver's offboarding closes and their account is disabled.
        self.client.post(f"/offboarding/{plan.id}/close", {"force": "1"})
        plan.refresh_from_db()
        self.leaver.refresh_from_db()
        self.assertEqual(plan.status, "Closed")
        self.assertFalse(self.leaver.is_active)

    def test_another_countrys_vacancy_does_not_exist_for_the_director(self):
        vacancy = Vacancy.objects.create(
            country="Kenya",
            department="Programmes",
            role="CCEO",
            status=VacancyStatus.PENDING_APPROVAL,
        )
        self._as(self.hr)
        self.assertEqual(self.client.get(f"/recruitment/{vacancy.id}").status_code, 404)
        self._as(self.cd)
        self.client.post(f"/recruitment/{vacancy.id}/decide", {"decision": "approve"})
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, VacancyStatus.PENDING_APPROVAL)

    def test_an_offboarding_needs_a_reason(self):
        self._as(self.hr)
        self.client.post(
            "/offboarding/start",
            {"staff_id": self.leaver_sp.id, "last_working_day": "2026-10-31"},
        )
        self.assertFalse(OffboardingPlan.objects.exists())
