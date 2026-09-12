"""Rewards and wellbeing programmes, worked from the screens (2026-09-13).

Compensation and benefits, occupational health and safety, recognition, and
morale are programmes the Regional HR Director administers by name. None had a
writer before this change; these tests drive each one through its drawer.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.hr.models import (
    CompensationRecord,
    PulseResponse,
    PulseSurvey,
    SafetyIncident,
    StaffRecognition,
)
from apps.notifications.models import Notification


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


class RewardsWellbeingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("rw-hr@edify.test", "HumanResources")
        cls.officer, cls.officer_sp = _person("rw-officer@edify.test", "CCEO")
        cls.kenyan, cls.kenyan_sp = _person("rw-kenyan@edify.test", "CCEO", "Kenya")
        cls.staff = [_person(f"rw-staff-{n}@edify.test", "CCEO")[0] for n in range(5)]

    def setUp(self):
        self.client.force_login(self.hr)

    def test_compensation_and_benefits_are_recorded_without_amounts_on_the_register(
        self,
    ):
        self.client.post(
            "/compensation-benefits/save",
            {
                "staff_id": self.officer_sp.id,
                "salary_band": "B2",
                "currency": "UGX",
                "base_salary": "2500000",
                "allowances": "300000",
                "medical_cover": "family",
                "pension_scheme": "NSSF",
                "next_review_date": (date.today() + timedelta(days=10)).isoformat(),
                "status": "Approved",
            },
        )
        record = CompensationRecord.objects.get(staff=self.officer_sp)
        self.assertEqual(record.medical_cover, "family")
        self.assertEqual(int(record.base_salary), 2500000)
        page = self.client.get("/compensation-benefits")
        self.assertContains(page, "Employee and family")
        self.assertNotContains(page, "2500000")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        self.assertEqual(metrics["Pay reviews due"], "1")
        self.assertEqual(metrics["Approved"], "1")

    def test_compensation_outside_the_countries_overseen_is_refused(self):
        self.client.post(
            "/compensation-benefits/save",
            {"staff_id": self.kenyan_sp.id, "salary_band": "B1"},
        )
        self.assertFalse(CompensationRecord.objects.exists())

    def test_a_safety_incident_is_reported_and_closed_with_its_corrective_action(self):
        self.client.post(
            "/health-safety/report",
            {
                "category": "road_traffic",
                "incident_date": date.today().isoformat(),
                "affected_staff_id": self.officer_sp.id,
                "severity": "high",
                "days_lost": "3",
                "location": "Mukono road",
                "description": "Motorbike collision on the way to a school visit.",
            },
        )
        incident = SafetyIncident.objects.get()
        self.assertEqual(incident.country, "Uganda")
        url = f"/health-safety/{incident.id}/advance"
        self.client.post(url, {"to_status": "closed"})
        incident.refresh_from_db()
        self.assertEqual(incident.status, "reported", "no corrective action recorded")
        self.client.post(
            url,
            {"to_status": "closed", "corrective_action": "Helmet refresher training."},
        )
        incident.refresh_from_db()
        self.assertEqual(incident.status, "closed")
        page = self.client.get("/health-safety")
        metrics = {m["label"]: str(m["value"]) for m in page.context["metrics"]}
        self.assertEqual(metrics["Days lost"], "3")

    def test_recognition_is_recorded(self):
        self.client.post(
            "/recognition/award",
            {
                "staff_id": self.officer_sp.id,
                "category": "above_and_beyond",
                "citation": "Covered three extra schools during a colleague's leave.",
            },
        )
        self.assertEqual(StaffRecognition.objects.get().staff_id, self.officer_sp.id)
        page = self.client.get("/recognition")
        self.assertContains(page, "Above and beyond")

    def test_a_pulse_survey_is_anonymous_and_hidden_below_five_answers(self):
        self.client.post(
            "/pulse-surveys/open",
            {
                "title": "Quarter one pulse",
                "country_Uganda": "1",
                "closes_on": (date.today() + timedelta(days=14)).isoformat(),
            },
        )
        survey = PulseSurvey.objects.get()
        self.assertEqual(survey.countries, ["Uganda"])
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.officer.id, target_route=f"/pulse/{survey.id}"
            ).exists()
        )

        answers = {
            "purpose": 5,
            "support": 4,
            "workload": 2,
            "recognition": 3,
            "growth": 4,
        }
        respondents = [self.officer, *self.staff[:3]]
        for person in respondents:
            self.client.force_login(person)
            self.client.post(f"/pulse/{survey.id}", answers)
        # A second answer from the same person is refused.
        self.client.post(f"/pulse/{survey.id}", answers)
        self.assertEqual(PulseResponse.objects.count(), 4)
        self.assertFalse(
            PulseResponse._meta.get_field("respondent_key").null,
        )
        for field in PulseResponse._meta.fields:
            self.assertNotIn(field.name, ("user", "staff", "respondent"))

        self.client.force_login(self.hr)
        drawer = self.client.get(f"/pulse-surveys/{survey.id}")
        self.assertContains(drawer, "Shown once 5 people have answered")

        self.client.force_login(self.staff[3])
        self.client.post(f"/pulse/{survey.id}", answers)
        self.client.force_login(self.hr)
        drawer = self.client.get(f"/pulse-surveys/{survey.id}")
        self.assertContains(drawer, "3.6 of 5")

    def test_staff_in_another_country_cannot_answer(self):
        survey = PulseSurvey.objects.create(
            title="Uganda only",
            countries=["Uganda"],
            opens_on=date.today(),
            closes_on=date.today() + timedelta(days=7),
        )
        self.client.force_login(self.kenyan)
        self.client.post(
            f"/pulse/{survey.id}",
            {"purpose": 5, "support": 5, "workload": 5, "recognition": 5, "growth": 5},
        )
        self.assertFalse(PulseResponse.objects.exists())
