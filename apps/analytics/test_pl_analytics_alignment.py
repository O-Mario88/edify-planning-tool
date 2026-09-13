"""The Programme Lead cockpit after the alignment (2026-09-13).

Pinned here: the Not Visited and Not Trained tiles open the list they count;
"trained" is one definition, cluster attendance included, on the tile, the risk
list and the drill-down alike; a drill-down carries the cockpit's filters; the
training figures count every training type; and the analytics To-Dos are
worded as supervision and link to pages the lead can act from.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.analytics.pl_analytics_service import PLAnalyticsService, resolve_pl_scope
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()
FY = "2026"


class AlignmentFixture(TestCase):
    """PL-A supervises CCEO-A1, whose portfolio is A1 (visited and trained in
    school), A2 (no SSA, not visited) and A3 (trained only by attending a
    verified cluster session). PL-B's B1 must never surface for PL-A."""

    def setUp(self):
        self.region = Region.objects.create(name="Align Region")
        self.dist_a = District.objects.create(name="Align A", region=self.region)
        self.dist_b = District.objects.create(name="Align B", region=self.region)
        self.cluster_a = Cluster.objects.create(
            id="al-cl-a", name="Align Cluster", region=self.region, district=self.dist_a
        )
        self.pl_a, self.pl_a_sp = self._staff(
            "al-pla@t.org", "Align Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo_a1, self.cceo_a1_sp = self._staff(
            "al-a1@t.org", "Ann Align", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_a_sp, supervisee=self.cceo_a1_sp
        )
        self.pl_b, self.pl_b_sp = self._staff(
            "al-plb@t.org", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo_b1, self.cceo_b1_sp = self._staff(
            "al-b1@t.org", "Ben Other", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_b_sp, supervisee=self.cceo_b1_sp
        )

        self.sch_a1 = self._school("A1", self.dist_a)
        self.sch_a2 = self._school("A2", self.dist_a, ssa_done=False)
        self.sch_a3 = self._school("A3", self.dist_a)
        self.sch_b1 = self._school("B1", self.dist_b)
        for school in (self.sch_a1, self.sch_a2, self.sch_a3):
            StaffSchoolAssignment.objects.create(
                staff=self.cceo_a1_sp, school_id=school.id
            )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_b1_sp, school_id=self.sch_b1.id
        )
        for school in (self.sch_a1, self.sch_a3, self.sch_b1):
            SsaRecord.objects.create(
                school=school,
                date_of_ssa=timezone.now(),
                fy=FY,
                quarter="Q2",
                average_score=7.0,
                verification_status="confirmed",
            )

        self._activity(self.cceo_a1_sp.id, self.sch_a1, "school_visit")
        self._activity(self.cceo_a1_sp.id, self.sch_a1, "in_school_training")
        self._activity(self.cceo_b1_sp.id, self.sch_b1, "school_visit")
        StaffTargetProfile.objects.create(
            staff=self.cceo_a1_sp,
            fy=FY,
            visits_target=2,
            trainings_target=1,
            cluster_meetings_target=1,
            ssa_target=1,
        )

        self.session = Activity.objects.create(
            cluster=self.cluster_a,
            activity_type="cluster_training",
            delivery_type="staff",
            status="ia_verified",
            responsible_staff_id=self.cceo_a1_sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 5, 20),
        )
        ClusterActivityAttendance.objects.create(
            activity=self.session, school=self.sch_a3, invited=True, attended=True
        )

    def _staff(self, email, name, role):
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=role)

    def _school(self, ref, district, ssa_done=True):
        school = School.objects.create(
            school_id=f"AL-{ref}",
            name=f"School {ref}",
            region=self.region,
            district=district,
            school_type="client",
            enrollment=100,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )
        School.objects.filter(id=school.id).update(
            cluster_id="al-cl-a" if district == self.dist_a else None
        )
        return school

    def _activity(self, owner_id, school, activity_type):
        return Activity.objects.create(
            school=school,
            activity_type=activity_type,
            delivery_type="staff",
            status="completed",
            responsible_staff_id=owner_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            evidence_status="accepted",
        )

    def _kpi(self, label, filters=None):
        pls = resolve_pl_scope(self.pl_a, filters or {})
        items = PLAnalyticsService.kpis(pls, FY, None, filters or {})["items"]
        return next(item for item in items if item["label"] == label)

    def _drill(self, drill, **params):
        return PLAnalyticsService.drilldown(
            self.pl_a, drill, {"drill": drill, **params}, fy=FY
        )


class DrilldownsOpenWhatTheTileCountsTest(AlignmentFixture):
    def test_not_visited_lists_the_schools_the_tile_counts(self):
        tile = self._kpi("Schools Not Visited")
        drawer = self._drill("kpi", metric="not_visited")

        names = {school.name for school in drawer["schools"]}
        self.assertEqual(drawer["title"], "Schools Not Visited")
        self.assertEqual(len(names), int(tile["value"]))
        self.assertNotIn("School A1", names)  # visited
        self.assertIn("School A2", names)
        self.assertNotIn("School B1", names)  # another lead's portfolio

    def test_not_trained_counts_cluster_attendance(self):
        tile = self._kpi("Schools Not Trained")
        drawer = self._drill("kpi", metric="not_trained")

        names = {school.name for school in drawer["schools"]}
        self.assertEqual(len(names), int(tile["value"]))
        self.assertNotIn("School A1", names)  # trained in school
        self.assertNotIn("School A3", names)  # trained at the cluster session
        self.assertIn("School A2", names)

    def test_the_risk_list_agrees_about_cluster_training(self):
        pls = resolve_pl_scope(self.pl_a, {})
        rows = {
            row["school"]: row
            for row in PLAnalyticsService.risk_list(pls, FY, None, {}, limit=50)["rows"]
        }

        self.assertIn("no_training", rows["School A2"]["issue_keys"])
        if "School A3" in rows:
            self.assertNotIn("no_training", rows["School A3"]["issue_keys"])

    def test_a_risk_drilldown_filters_before_it_pages(self):
        pls = resolve_pl_scope(self.pl_a, {})
        page = PLAnalyticsService.risk_list(
            pls, FY, None, {}, limit=1, issue="not_visited"
        )
        everything = PLAnalyticsService.risk_list(pls, FY, None, {}, limit=50)

        expected = [r for r in everything["rows"] if "no_visit" in r["issue_keys"]]
        self.assertEqual(page["total"], len(expected))
        self.assertTrue(all("no_visit" in r["issue_keys"] for r in page["rows"]))

    def test_a_trained_school_on_the_risk_list_shows_when_it_was_trained(self):
        from apps.ssa.models import SsaRecord

        # Give A3 a reason to be listed that is not training.
        SsaRecord.objects.filter(school=self.sch_a3).delete()
        type(self.sch_a3).objects.filter(id=self.sch_a3.id).update(
            current_fy_ssa_status="not_done"
        )
        pls = resolve_pl_scope(self.pl_a, {})
        rows = {
            row["school"]: row
            for row in PLAnalyticsService.risk_list(pls, FY, None, {}, limit=50)["rows"]
        }

        self.assertIn("School A3", rows)
        self.assertTrue(rows["School A3"]["last_training"].endswith("days ago"))

    def test_the_drilldown_carries_the_cockpit_filters(self):
        filters = {"district": self.dist_a.id}
        tile = self._kpi("Schools Not Visited", filters)

        self.assertIn(f"&district={self.dist_a.id}", tile["link"])
        self.assertTrue(tile["link"].startswith("?drill=kpi&metric=not_visited"))


class TrainingFiguresCountEveryTrainingTest(AlignmentFixture):
    def test_the_activity_tracking_card_counts_every_training_type(self):
        pls = resolve_pl_scope(self.pl_a, {})
        cards = {
            card["label"]: card
            for card in PLAnalyticsService.activity_tracking(pls, FY, None, {})["cards"]
        }

        self.assertNotIn("Cluster Trainings", cards)
        # A1's in-school training and the verified cluster session.
        self.assertEqual(cards["Trainings"]["planned"], 2)
        self.assertEqual(cards["Trainings"]["done"], 2)

    def test_the_training_tile_counts_every_training_type(self):
        tile = self._kpi("Cluster Trainings Completed")
        self.assertEqual(tile["value"], "100%")


class SupervisionTodosTest(AlignmentFixture):
    def test_the_todos_do_not_fold_the_insights_they_discard(self):
        with patch.object(PLAnalyticsService, "insights") as insights:
            PLAnalyticsService.pl_todos(self.pl_a, fy=FY)
        insights.assert_not_called()

    def test_the_todos_are_follow_ups_that_land_somewhere_actionable(self):
        from apps.accounts.models import StaffTargetProfile

        # Push A1 into High risk: a target nobody has met, and a backlog of
        # returned work.
        StaffTargetProfile.objects.filter(staff=self.cceo_a1_sp, fy=FY).update(
            visits_target=400, trainings_target=400
        )
        for _ in range(4):
            Activity.objects.create(
                school=self.sch_a2,
                activity_type="school_visit",
                status="returned_by_pl",
                responsible_staff_id=self.cceo_a1_sp.id,
                fy=FY,
                quarter="Q3",
            )
        todos = {t["id"]: t for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)}

        ssa = todos["pl-analytics-ssa"]
        self.assertEqual(ssa["title"], "Follow up SSA collection with CCEOs")
        self.assertEqual(ssa["action_url"], "/programme-rollout?view=ssa")
        for todo in todos.values():
            with self.subTest(todo=todo["id"]):
                self.assertNotIn("Schedule", todo["title"])
                self.assertNotEqual(todo["action_url"], "/analytics/program-lead")
        follow_up = todos[f"pl-analytics-cceo-{self.cceo_a1_sp.id}"]
        self.assertEqual(follow_up["title"], "Follow up Ann Align's delivery")
        self.assertEqual(
            follow_up["action_url"],
            f"/team-planning-oversight/?owner={self.cceo_a1_sp.id}",
        )

    def test_the_ssa_follow_up_counts_the_officers_schools_not_the_leads(self):
        from apps.accounts.models import StaffSchoolAssignment
        from apps.schools.models import School

        own = School.objects.create(
            school_id="SCH-PL-OWN",
            name="Lead's Own School",
            region=self.region,
            district=self.dist_a,
            current_fy_ssa_status="not_done",
        )
        StaffSchoolAssignment.objects.create(staff=self.pl_a_sp, school_id=own.id)

        todo = next(
            t
            for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)
            if t["id"] == "pl-analytics-ssa"
        )
        # A2 is the only officer school without a verified SSA.
        self.assertTrue(todo["description"].startswith("1 school "))
