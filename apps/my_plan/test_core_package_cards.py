"""Core package work gets its own two cards on My Plan.

Owner, 2026-09-17: "on my plan page, core planned activities should have a
separate core school visits planned table and a separate table for core school
[trainings]. on each table show the count of how many visits based on the
completed planned activities."

What decides a row belongs here is the CoreActivitySlot it was booked into —
the package's own record — not the school's type. Two consequences worth
pinning:

* A Core TRAINING is delivered by the standard In-school Training workflow, so
  there is no activity of type "core_training" to look for. Reading the slot is
  what makes the training visible at all; the type-based query that preceded it
  matched nothing and the card would have been permanently empty.
* A core school's NON-package work — a social visit, a donor visit — is not
  part of the 4 + 4 and stays on the cards it shares with every other school.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id, cslot_id
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class CorePackageCardsTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="CP Region")
        district = District.objects.create(name="CP District", region=region)
        self.user = User.objects.create(
            id="cp-cceo",
            email="cp-cceo@edify.org",
            name="CP Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            id="cp-cceo-sp", user=self.user, title="CCEO", country="Uganda"
        )
        self.fy = get_operational_fy()
        self.school = School.objects.create(
            school_id="CP-1",
            name="Kyanja Core Primary",
            region=region,
            district=district,
            school_type="core",
            account_owner_id=self.profile.id,
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id(self.school.school_id),
            school_id=self.school.school_id,
            fy=self.fy,
            status="Active",
        )
        today = date.today()
        self.common = dict(
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            planned_date=today,
            fy=self.fy,
            quarter=get_quarter_for_date(today),
        )
        self.client.force_login(self.user)

    def _slot(self, activity, kind, sequence, status="Scheduled"):
        prefix = "v" if kind == "visit" else "t"
        return CoreActivitySlot.objects.create(
            id=cslot_id(self.school.school_id, prefix, sequence, fy=self.fy),
            core_plan=self.plan,
            school_id=self.school.school_id,
            intervention="leadership",
            activity_type=kind,
            sequence_number=sequence,
            status=status,
            activity_id=activity.id if activity else None,
        )

    def _cards(self):
        """The four cards in the order the workspace renders them.

        Sliced by heading rather than "everything before the core card",
        because an activity id appears higher up the page too — the priority
        queue and the attention rail both list live work.
        """
        html = self.client.get("/my-plan").content.decode()
        shared_v = html.index("School Visits Planned for")
        shared_t = html.index("Trainings Planned for", shared_v + 1)
        core_v = html.index("Core School Visits Planned")
        core_t = html.index("Core School Trainings Planned", core_v + 1)
        return {
            "html": html,
            "shared_visits": html[shared_v:shared_t],
            "shared_trainings": html[shared_t:core_v],
            "core_visits": html[core_v:core_t],
            "core_trainings": html[core_t:],
        }

    def test_a_core_visit_and_a_core_training_get_a_card_each(self):
        visit = Activity.objects.create(
            activity_type="core_visit", status="scheduled", **self.common
        )
        self._slot(visit, "visit", 1)
        # Delivered by the In-school Training workflow — the slot is what
        # makes it a Core training.
        training = Activity.objects.create(
            activity_type="in_school_training", status="scheduled", **self.common
        )
        self._slot(training, "training", 2)

        cards = self._cards()
        self.assertIn(visit.id, cards["core_visits"])
        self.assertIn(training.id, cards["core_trainings"])
        self.assertNotIn(training.id, cards["core_visits"])
        # The slot's own sequence, so every surface says the same V1 and T2.
        self.assertIn("V1", cards["core_visits"])
        self.assertIn("T2", cards["core_trainings"])
        # Neither is left on the shared cards they used to be filed under.
        self.assertNotIn(visit.id, cards["shared_visits"])
        self.assertNotIn(training.id, cards["shared_trainings"])

    def test_each_card_counts_the_ones_that_are_done(self):
        for sequence, status, slot_status in (
            (1, "ia_verified", "IA Verified"),
            (2, "scheduled", "Scheduled"),
        ):
            visit = Activity.objects.create(
                activity_type="core_visit", status=status, **self.common
            )
            self._slot(visit, "visit", sequence, slot_status)

        self.assertIn("1 completed", self._cards()["core_visits"])

    def test_non_package_work_at_a_core_school_stays_on_the_shared_cards(self):
        social = Activity.objects.create(
            activity_type="social_visit", status="scheduled", **self.common
        )
        html = self.client.get("/my-plan").content.decode()
        # No slot, so no core card at all — and the visit is still listed.
        self.assertNotIn("Core School Visits Planned", html)
        self.assertIn(social.id, html)
