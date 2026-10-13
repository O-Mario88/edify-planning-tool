"""An announcement reads only what the save does not already have in hand.

A day's re-pricing saves every visit on it, and each save announces. The
audience of each was worked out from scratch: the school's holder, the
officer's line two levels up and the country's readers, four or five
statements a visit after the commit, forty for a day of nine. The line and
the country's readers are now remembered for as long as an audience is, and
a school already loaded on the record gives its holder without a read
(apps.activities.live).
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, User
from apps.activities import live
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


class AudienceInHandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Live Region")
        cls.district = District.objects.create(name="Live District", region=cls.region)
        cls.user = User.objects.create_user(
            email="live-holder@test.com",
            name="Live Holder",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, title="CCEO", country="Uganda"
        )
        cls.schools = [
            School.objects.create(
                school_id=f"LIVE-{n}",
                name=f"Live School {n}",
                region=cls.region,
                district=cls.district,
                school_type="client",
                account_owner_id=cls.staff.id,
            )
            for n in range(3)
        ]

    def setUp(self):
        live.reset()
        self.addCleanup(live.reset)

    def test_the_holder_in_hand_gives_the_same_audience_without_a_read(self):
        school = self.schools[0]
        read = live.audience(school_id=school.id)
        with CaptureQueriesContext(connection) as queries:
            in_hand = live.audience(
                school_id=school.id, school_holder=(str(school.account_owner_id),)
            )
        self.assertEqual(in_hand, read)
        self.assertIn(self.user.id, in_hand)
        self.assertFalse(
            [q for q in queries.captured_queries if 'FROM "school"' in q["sql"]]
        )

    def test_a_record_loaded_with_its_school_says_who_holds_it(self):
        activity = Activity.objects.create(
            school=self.schools[0],
            responsible_staff_id=self.staff.id,
            activity_type="school_visit",
            fy="2026",
            status="scheduled",
        )
        loaded = Activity.objects.select_related("school").get(pk=activity.pk)
        self.assertEqual(live._school_holder_in_hand(loaded), (str(self.staff.id),))
        bare = Activity.objects.get(pk=activity.pk)
        self.assertIsNone(live._school_holder_in_hand(bare))

    def test_the_line_and_the_country_are_read_once_for_a_day_of_schools(self):
        def key(school):
            return (
                (str(self.staff.id),),
                str(school.id),
                "",
                "",
                (),
                (str(self.staff.id),),
            )

        first = live._audience_for(key(self.schools[0]))
        with CaptureQueriesContext(connection) as queries:
            others = [live._audience_for(key(school)) for school in self.schools[1:]]
        self.assertEqual(others, [first, first])
        self.assertEqual(len(queries), 0, [q["sql"] for q in queries.captured_queries])

    def test_asked_directly_the_audience_is_always_read(self):
        with CaptureQueriesContext(connection) as first:
            live.audience(staff_ids=(self.staff.id,))
        with CaptureQueriesContext(connection) as second:
            live.audience(staff_ids=(self.staff.id,))
        self.assertEqual(len(first), len(second))
        self.assertGreater(len(second), 0)
