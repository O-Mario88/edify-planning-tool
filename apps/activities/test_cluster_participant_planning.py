"""Participants are planned per school; the total is derived.

Asking a planner for the total participant count made them do arithmetic the
system already had both inputs for — and a typed total is unverifiable. 47 for
a 30-school cluster might be a considered figure or a slipped keystroke, and
nothing downstream can tell the difference. It multiplies straight into a
budget line either way.

So the drawer takes one number, per school, and the backend does the rest:
counts the cluster's live schools, multiplies, and overwrites whatever total
the request happened to carry. The browser's arithmetic is a preview.

The school count is snapshotted on the activity rather than looked up on read,
because cluster membership changes. A school joining in November must not
re-price work approved in August.
"""

from __future__ import annotations

from django.test import TestCase

from apps.activities.services import (
    CLUSTER_PARTICIPANT_ACTIVITY_TYPES,
    _validated_participants_per_school,
)
from apps.clusters.models import Cluster
from apps.clusters.services import active_school_count
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ActiveSchoolCountTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="CPP Region")
        self.district = District.objects.create(name="CPP District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="CPP Sub County", district=self.district
        )
        self.cluster = Cluster.objects.create(
            name="CPP Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )

    def _school(self, ref, **kwargs):
        defaults = dict(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        defaults.update(kwargs)
        return School.objects.create(**defaults)

    def _member(self, ref):
        school = self._school(ref)
        School.objects.filter(id=school.id).update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        return school

    def test_it_counts_the_clusters_live_schools(self):
        for i in range(30):
            self._member(f"CPP-{i}")
        self.assertEqual(active_school_count(self.cluster.id), 30)

    def test_a_soft_deleted_school_is_not_a_participant_source(self):
        for i in range(3):
            self._member(f"CPP-DEL-{i}")
        gone = self._member("CPP-DEL-X")
        School.objects.filter(id=gone.id).update(deleted_at="2026-01-01T00:00:00Z")
        self.assertEqual(active_school_count(self.cluster.id), 3)

    def test_a_stale_cluster_pointer_does_not_inflate_the_count(self):
        """School.cluster_id is a CharField, not a foreign key, so a school can
        point at a cluster while its status says otherwise. Requiring both is
        what stops a stale pointer becoming extra invited people — and extra
        money."""
        self._member("CPP-OK")
        stale = self._school("CPP-STALE")
        School.objects.filter(id=stale.id).update(
            cluster_id=self.cluster.id, cluster_status="unclustered"
        )
        self.assertEqual(active_school_count(self.cluster.id), 1)

    def test_an_empty_cluster_counts_zero_rather_than_failing(self):
        self.assertEqual(active_school_count(self.cluster.id), 0)
        self.assertEqual(active_school_count(""), 0)


class ParticipantsPerSchoolValidationTest(TestCase):
    def test_a_whole_positive_number_is_accepted(self):
        self.assertEqual(_validated_participants_per_school("2"), 2)
        self.assertEqual(_validated_participants_per_school(3), 3)

    def test_a_decimal_is_refused_rather_than_rounded(self):
        """2.5 across 30 schools is 75 people rounded up and 60 truncated.
        Neither is a number anybody chose, so it is refused."""
        with self.assertRaises(BadRequest) as caught:
            _validated_participants_per_school("2.5")
        self.assertIn("whole number", str(caught.exception))

    def test_zero_and_negative_are_refused(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(BadRequest):
                    _validated_participants_per_school(value)

    def test_blank_is_refused(self):
        with self.assertRaises(BadRequest):
            _validated_participants_per_school("")

    def test_text_is_refused(self):
        with self.assertRaises(BadRequest):
            _validated_participants_per_school("two")

    def test_an_absurd_figure_is_refused(self):
        with self.assertRaises(BadRequest):
            _validated_participants_per_school("5000")


class TheArithmeticTest(TestCase):
    """The worked example from the specification."""

    def test_thirty_schools_at_two_each_is_sixty(self):
        self.assertEqual(30 * _validated_participants_per_school("2"), 60)

    def test_only_cluster_activities_use_this_basis(self):
        """A school visit or a conference has no cluster membership to
        multiply by, and must keep its own participant semantics."""
        for included in ("cluster_meeting", "cluster_training"):
            with self.subTest(activity_type=included):
                self.assertIn(included, CLUSTER_PARTICIPANT_ACTIVITY_TYPES)
        for excluded in (
            "school_visit",
            "in_school_training",
            "donor_visit",
            "programme_event",
        ):
            with self.subTest(activity_type=excluded):
                self.assertNotIn(excluded, CLUSTER_PARTICIPANT_ACTIVITY_TYPES)


class DrawerAsksForOneNumberTest(TestCase):
    def test_the_drawer_no_longer_offers_a_total_participant_field(self):
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR)
            / "templates/partials/planning/schedule_cluster_drawer.html"
        ).read_text()
        self.assertIn('name="participants_per_school"', source)
        self.assertNotIn(
            'name="expected_participants"',
            source,
            "a manually typed total is the thing this replaces",
        )

    def test_the_drawer_shows_the_calculation_rather_than_hiding_it(self):
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR)
            / "templates/partials/planning/schedule_cluster_drawer.html"
        ).read_text()
        self.assertIn("Active schools in cluster", source)
        self.assertIn("per school", source)
