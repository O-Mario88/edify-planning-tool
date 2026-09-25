"""School-type planning rules (owner, 2026-09-25).

* Core Trained schools are planned from the Planning page and the cluster
  lists like client schools, without the Core package.
* Champion and Core Graduate schools leave the Planning page and the cluster
  lists for their own tables on Core Schools; they receive no training or
  assessment and are planned only for a Donor Visit or a Content/Story
  Collection visit.
* A cluster meeting a school is invited to is training planned for it: the
  Training badge and the Planning training filters read it as planned.
"""

from __future__ import annotations

from apps.activities.cluster_attendance import set_invited_schools
from apps.activities.services import _assert_schedule_entitlement
from apps.clusters.services import active_school_count, active_schools, cluster_schools
from apps.core.exceptions import BadRequest
from apps.planning.planning_service import PlanningDashboardService
from apps.planning.planning_support import filter_queryset
from apps.planning.test_school_planning_badges import FY, BadgeFixture
from apps.planning.visit_gate import assert_outreach_activity_allowed
from apps.schools.models import School


class ClusterMeetingIsTrainingTest(BadgeFixture):
    def test_a_meeting_invitation_reads_as_training_planned(self):
        self._session(invited=[self.hope], kind="cluster_meeting")
        badges = self.badges(self.hope, self.grace)

        hope = badges[self.hope.id]
        self.assertNotIn("Not Planned", [c["label"] for c in hope.training_chips])
        self.assertEqual(
            hope.cluster_meeting_chips,
            [{"label": "1 Cluster Meeting Planned", "tone": "planned"}],
        )
        self.assertEqual(
            badges[self.grace.id].training_chips,
            [{"label": "Not Planned", "tone": "none"}],
        )

    def test_the_training_filters_count_a_meeting(self):
        self._session(invited=[self.hope], kind="cluster_meeting")
        self._activity(self.hope)
        schools = School.objects.filter(id__in=[self.hope.id, self.grace.id])

        not_planned = filter_queryset(schools, "training_not_planned", fy=FY)
        both = filter_queryset(schools, "both_planned", fy=FY)

        self.assertEqual(set(not_planned.values_list("id", flat=True)), {self.grace.id})
        self.assertEqual(set(both.values_list("id", flat=True)), {self.hope.id})


class SchoolTypePlanningTest(BadgeFixture):
    def setUp(self):
        super().setUp()
        self.trained = self._school("BDG-4", "Trained Primary")
        School.objects.filter(id=self.trained.id).update(school_type="core_trained")
        School.objects.filter(id=self.grace.id).update(school_type="core_graduate")
        School.objects.filter(id=self.victory.id).update(school_type="champion")
        for school in (self.trained, self.grace, self.victory):
            school.refresh_from_db()

    def _planning_ids(self, tab):
        data = PlanningDashboardService.get_dashboard_data(
            self.user, {"fy": FY, "tab": tab, "per_page": 50}
        )
        return {row["id"] for row in data["schools"]}

    def test_core_trained_is_planned_with_the_client_schools(self):
        client_tab = self._planning_ids("client")
        self.assertIn(self.trained.id, client_tab)
        self.assertIn(self.hope.id, client_tab)

    def test_champion_and_core_graduate_are_on_no_planning_tab(self):
        for tab in ("client", "core", "all", "scheduled"):
            with self.subTest(tab=tab):
                ids = self._planning_ids(tab)
                self.assertNotIn(self.victory.id, ids)
                self.assertNotIn(self.grace.id, ids)

    def test_the_cluster_lists_leave_them_out(self):
        members = {s.id for s in active_schools(self.cluster.id)}
        self.assertEqual(members, {self.hope.id, self.trained.id})
        self.assertEqual(active_school_count(self.cluster.id), 2)
        listed = {row["id"] for row in cluster_schools(self.cluster.id, self.user)}
        self.assertEqual(listed, {self.hope.id, self.trained.id})

    def test_they_are_never_invited_to_a_cluster_session(self):
        session = self._session(invited=[self.hope])
        with self.assertRaises(BadRequest):
            set_invited_schools(session, [self.hope.id, self.victory.id])
        with self.assertRaises(BadRequest):
            set_invited_schools(session, [self.grace.id])

    def test_only_donor_and_story_visits_are_planned_for_them(self):
        for school in (self.victory, self.grace):
            for kind in (
                "training",
                "in_school_training",
                "school_visit",
                "baseline_ssa_visit",
                "school_visit_ssa_collection",
                "core_visit",
            ):
                with self.subTest(school=school.school_type, kind=kind):
                    with self.assertRaises(BadRequest):
                        _assert_schedule_entitlement(kind, school, FY, {})
            for kind in ("donor_visit", "story_gathering_visit"):
                assert_outreach_activity_allowed(school, kind)

    def test_client_and_core_trained_schools_are_unaffected(self):
        for school in (self.hope, self.trained):
            assert_outreach_activity_allowed(school, "in_school_training")
            assert_outreach_activity_allowed(school, "school_visit")

    def test_the_schedule_drawer_offers_only_the_two_visits(self):
        self.client.force_login(self.user)
        html = self.client.get(
            f"/planning/schedule-modal?school_id={self.victory.id}"
        ).content.decode()
        self.assertIn("data-outreach-only", html)
        self.assertIn('value="donor_visit"', html)
        self.assertIn('value="story_gathering"', html)
        self.assertNotIn('value="in_school_training"', html)
        self.assertNotIn('value="social_visit"', html)
