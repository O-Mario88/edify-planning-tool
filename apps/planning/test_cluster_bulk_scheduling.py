"""A day of visits across a cluster: one to five schools, four purposes, one door.

The owner's rule of 2026-09-21, pinned where it is enforced
(apps.planning.cluster_bulk_scheduling) rather than only in the drawer that
shows it — a browser can post whatever it likes.

Five was first read as a floor, and the floor was the wrong end of the number
(owner, 2026-09-22): "the staff can plan from 1 to 5 but it cannot exceed 5 ...
some people are planning 4, other 3, other 2 and other 1 — make sure every
plan." So one school is a day, and six is not.

And one SSA intervention for the whole day, chosen in the drawer (owner,
2026-09-26): "for group scheduling, SSA intervention should be the same."
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.partners.purposes import CLUSTER_BULK_MAXIMUM_SCHOOLS
from apps.planning.cluster_bulk_scheduling import (
    bulk_schedule_cluster_visits,
    schedulable_members,
)
from apps.schools.models import School


def _next_working_day(start: date) -> date:
    """A day the calendar policy will accept: never a Sunday."""
    when = start
    while when.weekday() == 6:
        when += timedelta(days=1)
    return when


class _ClusterDay(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="CB Region")
        cls.district = District.objects.create(name="CB District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="CB SC", district=cls.district)
        cls.user = User.objects.create(
            id="cb-cceo",
            email="cb-cceo@edify.org",
            name="CB CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            id="cb-cceo-sp", user=cls.user, title="CCEO", country="Uganda"
        )
        cls.cluster = Cluster.objects.create(
            name="CB Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_type="client",
            status="active",
            responsible_staff_id=cls.staff.id,
        )
        cls.schools = [cls._school(f"CB-{index}") for index in range(1, 8)]
        cls.when = _next_working_day(date.today() + timedelta(days=14))
        cls.fy = get_operational_fy(cls.when)

    @classmethod
    def _school(cls, code):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
            account_owner_id=cls.staff.id,
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=school.id)
        return school

    def _payload(self, **overrides):
        payload = {
            "purposeOfVisit": "donor_visit",
            "focusIntervention": "leadership",
            "scheduledDate": self.when.isoformat(),
            "schoolIds": [school.id for school in self.schools[:5]],
        }
        payload.update(overrides)
        return payload


class TheCeilingIsFiveSchoolsTest(_ClusterDay):
    def test_one_school_is_a_day(self):
        # The case the floor refused outright: a planner with one school to
        # visit was sent away to plan nothing (owner, 2026-09-22).
        result = bulk_schedule_cluster_visits(
            self.cluster.id,
            self._payload(schoolIds=[self.schools[0].id]),
            self.user,
        )
        self.assertEqual(result["schools"], 1)
        self.assertEqual(len(result["created"]), 1)

    def test_two_three_and_four_schools_are_days_too(self):
        # Each day after the last one. `when + count` rolled Sunday forward
        # onto the next count's Monday whenever the suite ran on a Thursday,
        # and the same schools were refused as a duplicate on that day.
        day = self.when
        for count in (2, 3, 4):
            day = _next_working_day(day + timedelta(days=1))
            with self.subTest(schools=count):
                result = bulk_schedule_cluster_visits(
                    self.cluster.id,
                    self._payload(
                        schoolIds=[s.id for s in self.schools[:count]],
                        scheduledDate=day.isoformat(),
                    ),
                    self.user,
                )
                self.assertEqual(result["schools"], count)

    def test_six_schools_are_refused_by_number(self):
        with self.assertRaises(BadRequest) as ctx:
            bulk_schedule_cluster_visits(
                self.cluster.id,
                self._payload(schoolIds=[s.id for s in self.schools[:6]]),
                self.user,
            )
        self.assertIn(str(CLUSTER_BULK_MAXIMUM_SCHOOLS), str(ctx.exception.detail))

    def test_nothing_ticked_is_refused(self):
        with self.assertRaises(BadRequest):
            bulk_schedule_cluster_visits(
                self.cluster.id, self._payload(schoolIds=[]), self.user
            )

    def test_the_same_school_ticked_twice_is_still_one_school(self):
        # Six ids, five schools: the duplicate must not spend the ceiling.
        five = [school.id for school in self.schools[:5]]
        result = bulk_schedule_cluster_visits(
            self.cluster.id,
            self._payload(schoolIds=[*five, self.schools[0].school_id]),
            self.user,
        )
        self.assertEqual(result["schools"], 5)

    def test_a_school_outside_the_cluster_is_refused(self):
        # In a sub-county this cluster does not cover, so School.save's
        # geography lookup cannot quietly enrol it on the way in.
        elsewhere = SubCounty.objects.create(name="CB Far SC", district=self.district)
        stranger = School.objects.create(
            school_id="CB-OUT",
            name="School CB-OUT",
            region=self.region,
            district=self.district,
            sub_county=elsewhere,
            school_type="client",
            account_owner_id=self.staff.id,
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=stranger.id)
        with self.assertRaises(BadRequest) as ctx:
            bulk_schedule_cluster_visits(
                self.cluster.id,
                self._payload(
                    schoolIds=[s.id for s in self.schools[:4]] + [stranger.id]
                ),
                self.user,
            )
        self.assertIn("no longer a member", str(ctx.exception.detail))


class OnlyFourPurposesTest(_ClusterDay):
    def test_in_school_training_is_refused_by_name(self):
        with self.assertRaises(BadRequest) as ctx:
            bulk_schedule_cluster_visits(
                self.cluster.id,
                self._payload(purposeOfVisit="in_school_training"),
                self.user,
            )
        self.assertIn("one school at a time", str(ctx.exception.detail))

    def test_a_staff_purpose_outside_the_four_is_refused(self):
        for purpose in ("social_visit", "school_invitation", "in_school_coaching"):
            with self.assertRaises(BadRequest) as ctx:
                bulk_schedule_cluster_visits(
                    self.cluster.id, self._payload(purposeOfVisit=purpose), self.user
                )
            self.assertIn("in bulk", str(ctx.exception.detail))

    def test_no_purpose_at_all_is_refused_rather_than_guessed(self):
        with self.assertRaises(BadRequest):
            bulk_schedule_cluster_visits(
                self.cluster.id, self._payload(purposeOfVisit=""), self.user
            )


class TheSelectionSaysWhyTest(_ClusterDay):
    def test_every_member_is_listed_with_its_own_answer(self):
        selection = schedulable_members(self.cluster, self.user)
        self.assertEqual(len(selection.members), len(self.schools))
        self.assertTrue(selection.any_schools)
        self.assertEqual(selection.shortfall_reason, "")

    def test_one_open_school_is_a_day_and_the_drawer_opens(self):
        # Under the floor this cluster was refused before a press. One school
        # is a day now (owner, 2026-09-22).
        small = Cluster.objects.create(
            name="CB Small",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="client",
            status="active",
            responsible_staff_id=self.staff.id,
        )
        School.objects.filter(id=self.schools[0].id).update(cluster_id=small.id)
        selection = schedulable_members(small, self.user)
        self.assertTrue(selection.any_schools)
        self.assertEqual(selection.shortfall_reason, "")

    def test_a_cluster_with_nothing_open_says_so_before_a_press(self):
        empty = Cluster.objects.create(
            name="CB Empty",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="client",
            status="active",
            responsible_staff_id=self.staff.id,
        )
        selection = schedulable_members(empty, self.user)
        self.assertFalse(selection.any_schools)

    def test_a_school_another_officer_owns_cannot_be_ticked(self):
        other_user = User.objects.create(
            id="cb-other",
            email="cb-other@edify.org",
            name="CB Other",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        other = StaffProfile.objects.create(
            id="cb-other-sp", user=other_user, title="CCEO", country="Uganda"
        )
        StaffSchoolAssignment.objects.filter(school_id=self.schools[0].id).delete()
        StaffSchoolAssignment.objects.create(staff=other, school_id=self.schools[0].id)
        School.objects.filter(id=self.schools[0].id).update(account_owner_id=other.id)
        selection = schedulable_members(self.cluster, self.user)
        blocked = next(
            member for member in selection.members if member.id == self.schools[0].id
        )
        self.assertFalse(blocked.selectable)
        self.assertIn("not in your own portfolio", blocked.reason)


class TheDayIsWrittenOnceTest(_ClusterDay):
    """The happy path: five schools, one purpose, five canonical Activities.

    Costing is patched out — the cost chain has its own suite, and these
    tests are about what bulk scheduling is permitted to write.
    """

    def setUp(self):
        from unittest.mock import patch

        patcher = patch("apps.activities.services._apply_schedule_cost_snapshot")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_five_schools_get_five_activities_on_the_same_day(self):
        from apps.activities.models import Activity

        result = bulk_schedule_cluster_visits(
            self.cluster.id, self._payload(), self.user
        )
        self.assertEqual(result["schools"], 5)
        written = Activity.objects.filter(id__in=result["created"])
        self.assertEqual(written.count(), 5)
        for activity in written:
            self.assertEqual(activity.purpose_type, "donor_visit")
            self.assertEqual(activity.activity_type, "donor_visit")
            self.assertEqual(activity.delivery_type, "staff")
            self.assertEqual(activity.planned_date, self.when)
            # Costed against the approved catalogue, like any single visit.
            self.assertIsNotNone(activity.catalogue_item_id)
        self.assertEqual(
            {activity.school_id for activity in written},
            {school.id for school in self.schools[:5]},
        )

    def test_a_refusal_writes_nothing_at_all(self):
        """One transaction: a day that cannot be planned for one of its
        schools is not half-planned for the rest."""
        from apps.activities.models import Activity

        before = Activity.objects.count()
        stranger_ids = [school.id for school in self.schools[:4]] + ["not-a-school"]
        with self.assertRaises(BadRequest):
            bulk_schedule_cluster_visits(
                self.cluster.id, self._payload(schoolIds=stranger_ids), self.user
            )
        self.assertEqual(Activity.objects.count(), before)


def _seed_ssa_weakest_at(school, fy, weakest):
    """A confirmed SSA whose one weak score is ``weakest``."""
    from apps.core.enums import SsaIntervention
    from apps.ssa.models import SsaRecord, SsaScore

    record = SsaRecord.objects.create(
        school=school,
        fy=fy,
        date_of_ssa=date.today() - timedelta(days=30),
        verification_status="confirmed",
    )
    for intervention in SsaIntervention.values:
        SsaScore.objects.create(
            ssa_record=record,
            intervention=intervention,
            score=2.0 if intervention == weakest else 8.5,
        )


class OneInterventionForTheDayTest(_ClusterDay):
    """Owner, 2026-09-26: "for group scheduling, SSA intervention should be the
    same. it should be chosen from group visit scheduling drawer."

    Each school here is weakest somewhere else, which is what an open field
    used to turn into five different targets.
    """

    WEAKEST = (
        "financial_health",
        "enrolment",
        "christlike_behaviour",
        "government_requirement",
        "exposure_to_word_of_god",
    )

    def setUp(self):
        from unittest.mock import patch

        patcher = patch("apps.activities.services._apply_schedule_cost_snapshot")
        self.addCleanup(patcher.stop)
        patcher.start()
        for school, weakest in zip(self.schools[:5], self.WEAKEST, strict=True):
            _seed_ssa_weakest_at(school, self.fy, weakest)

    def _written(self, result):
        from apps.activities.models import Activity

        return Activity.objects.filter(id__in=result["created"])

    def test_every_school_is_planned_against_the_one_chosen(self):
        for day_offset, purpose in enumerate(
            ("training_follow_up", "donor_visit", "story_gathering")
        ):
            day = _next_working_day(self.when + timedelta(days=day_offset * 2))
            with self.subTest(purpose=purpose):
                result = bulk_schedule_cluster_visits(
                    self.cluster.id,
                    self._payload(
                        purposeOfVisit=purpose,
                        focusIntervention="leadership",
                        scheduledDate=day.isoformat(),
                    ),
                    self.user,
                )
                written = self._written(result)
                self.assertEqual(written.count(), 5)
                self.assertEqual(result["focusIntervention"], "leadership")
                # No school's own weakest score, and no school left without.
                self.assertEqual(
                    set(written.values_list("focus_intervention", flat=True)),
                    {"leadership"},
                )
                self.assertEqual(
                    set(written.values_list("purpose_intervention", flat=True)),
                    {"leadership"},
                )

    def test_a_day_with_no_intervention_is_refused_and_writes_nothing(self):
        from apps.activities.models import Activity

        before = Activity.objects.count()
        for purpose in ("training_follow_up", "donor_visit", "story_gathering"):
            with self.subTest(purpose=purpose):
                with self.assertRaises(BadRequest) as ctx:
                    bulk_schedule_cluster_visits(
                        self.cluster.id,
                        self._payload(purposeOfVisit=purpose, focusIntervention=""),
                        self.user,
                    )
                self.assertIn("same one", str(ctx.exception.detail))
        self.assertEqual(Activity.objects.count(), before)

    def test_an_intervention_outside_the_eight_is_refused(self):
        with self.assertRaises(BadRequest) as ctx:
            bulk_schedule_cluster_visits(
                self.cluster.id,
                self._payload(focusIntervention="attendance"),
                self.user,
            )
        self.assertIn("canonical SSA intervention", str(ctx.exception.detail))

    def test_an_ssa_support_day_names_none_at_any_school(self):
        """Data Gathering, as the per-school drawer shows it: the day collects
        the assessment, so a posted intervention is dropped, not stamped."""
        result = bulk_schedule_cluster_visits(
            self.cluster.id,
            self._payload(purposeOfVisit="ssa_support", focusIntervention="leadership"),
            self.user,
        )
        written = self._written(result)
        self.assertEqual(written.count(), 5)
        self.assertIsNone(result["focusIntervention"])
        for activity in written:
            self.assertIsNone(activity.focus_intervention, activity.school_id)
            # The SSA still informs the plan — read and stamped as the
            # alignment verdict — it simply does not become a target.
            self.assertTrue(activity.ssa_alignment)

    def test_an_ssa_support_day_needs_no_intervention(self):
        result = bulk_schedule_cluster_visits(
            self.cluster.id,
            self._payload(purposeOfVisit="ssa_support", focusIntervention=""),
            self.user,
        )
        self.assertEqual(result["schools"], 5)


class TheDrawerAsksOnceTest(_ClusterDay):
    """The group visit drawer carries the one choice and posts it."""

    BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"

    def setUp(self):
        from unittest.mock import patch

        patcher = patch("apps.activities.services._apply_schedule_cost_snapshot")
        self.addCleanup(patcher.stop)
        patcher.start()
        self.client.force_login(self.user, backend=self.BACKEND)
        for school in self.schools[:3]:
            _seed_ssa_weakest_at(school, self.fy, "financial_health")

    def _url(self):
        return f"/clusters/{self.cluster.id}/bulk-schedule-drawer"

    def test_the_drawer_offers_one_intervention_and_suggests_the_weakest(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertEqual(body.count('name="focus_intervention"'), 1)
        self.assertIn("focusIntervention: 'financial_health'", body)
        self.assertIn("avg 2.0/10", body)
        self.assertIn("Data Gathering", body)

    def test_a_posted_day_plans_every_school_against_the_choice(self):
        from apps.activities.models import Activity

        ticked = self.schools[:3]
        response = self.client.post(
            self._url(),
            {
                "purpose_of_visit": "training_follow_up",
                "focus_intervention": "leadership",
                "scheduled_date": self.when.isoformat(),
                "school_ids": [school.id for school in ticked],
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        self.assertIn("Training Follow Up for Leadership", response.content.decode())
        written = Activity.objects.filter(
            school_id__in=[school.id for school in ticked],
            planned_date=self.when,
            deleted_at__isnull=True,
        )
        self.assertEqual(written.count(), 3)
        self.assertEqual(
            set(written.values_list("focus_intervention", flat=True)), {"leadership"}
        )

    def test_a_day_posted_without_one_reopens_the_drawer_and_says_why(self):
        from apps.activities.models import Activity

        before = Activity.objects.count()
        response = self.client.post(
            self._url(),
            {
                "purpose_of_visit": "training_follow_up",
                "focus_intervention": "",
                "scheduled_date": self.when.isoformat(),
                "school_ids": [school.id for school in self.schools[:3]],
            },
        )
        self.assertEqual(response.status_code, 400)
        body = response.content.decode()
        self.assertIn("Choose the SSA intervention for this day", body)
        # The planner's blank stands; the suggestion does not creep back in.
        self.assertIn("focusIntervention: ''", body)
        self.assertEqual(Activity.objects.count(), before)
