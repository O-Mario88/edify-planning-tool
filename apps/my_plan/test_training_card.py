"""An in-school training sits on the Trainings card under its school.

Owner, 2026-09-12: "When in-school training is selected in the school visit
scheduling form, it should create a training and visits for the same day but
the training should go to the training card on My Plan and the visit remains
on the Visit card."

The pair was already split that way; what the card said was the problem. It
was titled Cluster Trainings, its first column was Cluster Name, and a training
with a school and no cluster read "Unknown Cluster".
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class TrainingCardTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="TC Region")
        district = District.objects.create(name="TC District", region=region)
        self.user = User.objects.create(
            id="tc-cceo",
            email="tc-cceo@edify.org",
            name="TC Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            id="tc-cceo-sp", user=self.user, title="CCEO", country="Uganda"
        )
        self.school = School.objects.create(
            school_id="TC-1",
            name="Nakaseke Hill Primary",
            region=region,
            district=district,
            account_owner_id=self.profile.id,
        )
        today = date.today()
        common = dict(
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            status="scheduled",
            planned_date=today,
            fy=get_operational_fy(),
            quarter=get_quarter_for_date(today),
        )
        self.visit = Activity.objects.create(
            activity_type="school_visit",
            activity_purpose_text="School visit accompanying Biblical Integration",
            **common,
        )
        self.training = Activity.objects.create(
            activity_type="in_school_training", paired_school_visit=self.visit, **common
        )
        self.client.force_login(self.user)

    def _cards(self):
        html = self.client.get("/my-plan?period=week").content.decode()
        v = html.index("School Visits Planned")
        t = html.index("Trainings Planned")
        return html, html[v:t] if v < t else html[v:], html[t : t + 20000]

    def test_the_training_sits_on_the_trainings_card_under_its_school(self):
        html, visits, trainings = self._cards()
        self.assertIn("Trainings Planned for This Week", html)
        self.assertIn("School / Cluster", trainings)
        self.assertIn(self.training.id, trainings)
        self.assertIn(f'href="/schools/{self.school.id}"', trainings)
        self.assertIn("Nakaseke Hill Primary", trainings)
        self.assertIn("In-school Training", trainings)
        self.assertNotIn("Unknown Cluster", html)
        self.assertNotIn("Cluster Trainings Planned", html)

    def test_the_visit_stays_on_the_visits_card(self):
        _html, visits, trainings = self._cards()
        self.assertIn(self.visit.id, visits)
        self.assertNotIn(self.visit.id, trainings)
        self.assertNotIn(self.training.id, visits)
