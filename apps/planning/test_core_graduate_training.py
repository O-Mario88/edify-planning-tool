"""Core Graduate, Core Trained and Client schools are planned alike.

Owner, 2026-10-02: "some Core graduate planned are still showing as not
trained on the PL summaries even when they have been planned", and then:
"core graduate should also be planned for so any training they are in should
be counted for and trained when the training is completed. basically core
trained, core graduate and client schools should be treated the same."

From 2026-09-25 a Core Graduate school took its one visit and no training: it
was kept off the Planning page, the cluster lists and every cluster session's
invitations, and the planning rulebook gave it no training slot, so a training
planned for one was counted nowhere and the school read as having none. It
now takes one visit and one training a year, exactly as a Client or a Core
Trained school does. A Champion school still takes neither.
"""

from __future__ import annotations

from apps.activities.cluster_attendance import set_invited_schools
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.planning import coverage_service, urgent_attention
from apps.planning.country_oversight import rules
from apps.planning.planning_monitor import planning_monitor
from apps.planning.test_planning_monitor import DAY, FY, MonitorFixture
from apps.planning.test_school_coverage import FY as COVERAGE_FY
from apps.planning.test_school_coverage import CoverageFixture, _fy_day
from apps.planning.visit_gate import OWN_TABLE_SCHOOL_TYPES
from apps.schools.models import School
from apps.schools.school_status import (
    NO_TRAINING_PLANNED,
    TRAINING_NOT_REQUIRED,
    TRAINING_PLANNED,
    cluster_training_coverage,
)


class TheRulebookTreatsTheThreeAlike(MonitorFixture):
    def test_core_graduate_takes_a_visit_and_a_training_like_a_client(self):
        self.assertEqual(
            set(rules.TRAINED_TYPES),
            {"core", "client", "core_trained", "core_graduate"},
        )
        self.assertEqual(
            rules.requirement_for("core_graduate"), rules.requirement_for("client")
        )
        self.assertEqual(
            rules.requirement_for("core_graduate"),
            rules.requirement_for("core_trained"),
        )
        self.assertFalse(rules.takes_training("champion"))

    def test_only_champion_keeps_its_own_table(self):
        self.assertEqual(OWN_TABLE_SCHOOL_TYPES, ("champion",))


class TheMonitorCountsACoreGraduatesTraining(MonitorFixture):
    def setUp(self):
        self.graduate = self._school("MON-G1", "core_graduate", self.ben)
        Activity.objects.create(
            school=self.graduate,
            activity_type="training_follow_up_visit",
            status="scheduled",
            delivery_type="staff",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.ben.id,
        )

    def _ben(self, **kwargs):
        return self._officer(planning_monitor(self.cd_user, fy=FY, **kwargs), self.ben)

    def test_a_core_graduate_school_with_no_training_is_missing_one(self):
        ben = self._ben()
        # Ben holds a client school with nothing planned and the graduate,
        # visited and not yet planned for a training.
        self.assertEqual(ben.school_count, 2)
        self.assertEqual(ben.training_schools, 2)
        self.assertEqual(ben.no_training, 2)
        self.assertEqual(ben.no_visit, 1)
        monitor = planning_monitor(
            self.cd_user, fy=FY, gap="no_training", officer_id=self.ben.id
        )
        self.assertEqual({s.code for s in monitor["gap_schools"]}, {"MON-B1", "MON-G1"})

    def test_a_training_planned_for_a_core_graduate_school_is_counted(self):
        Activity.objects.create(
            school=self.graduate,
            activity_type="in_school_training",
            purpose_type="in_school_training",
            status="scheduled",
            delivery_type="staff",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.ben.id,
        )
        ben = self._ben()
        self.assertEqual(ben.schools_with_training, 1)
        self.assertEqual(ben.no_training, 1)
        monitor = planning_monitor(
            self.cd_user, fy=FY, gap="no_training", officer_id=self.ben.id
        )
        self.assertEqual({s.code for s in monitor["gap_schools"]}, {"MON-B1"})

    def test_the_lead_s_total_is_read_against_every_school(self):
        totals = planning_monitor(self.pl_user, fy=FY)["totals"]
        self.assertEqual(totals.school_count, 7)
        self.assertEqual(totals.training_schools, 7)
        self.assertEqual(
            totals.no_training, totals.training_schools - totals.schools_with_training
        )


class TheCoverageTabReadsACoreGraduateLikeAClient(CoverageFixture):
    def setUp(self):
        super().setUp()
        self.graduate = self._school("COV-G", "Graduate Primary", cluster=self.cluster)
        self.champion = self._school("COV-CH", "Champion Primary", cluster=self.cluster)
        School.objects.filter(id=self.graduate.id).update(school_type="core_graduate")
        School.objects.filter(id=self.champion.id).update(school_type="champion")
        self.graduate.refresh_from_db()
        self.champion.refresh_from_db()

    def _coverage(self):
        return coverage_service.training_coverage(
            self.pl_user, fy=COVERAGE_FY, period="fy"
        )

    def _train(self, school):
        return Activity.objects.create(
            activity_type="in_school_training",
            school=school,
            fy=COVERAGE_FY,
            planned_date=_fy_day(11, 6),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )

    def test_a_graduate_with_no_training_is_listed_and_a_champion_is_not(self):
        self._visit(self.graduate, _fy_day(11, 6))
        result = self._coverage()
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertIn(self.graduate.id, missing)
        self.assertNotIn(self.champion.id, missing)
        self.assertEqual(
            missing,
            {
                self.covered.id,
                self.uncovered.id,
                self.unclustered.id,
                self.graduate.id,
            },
        )
        self.assertEqual(result["missing_count"], 4)

    def test_a_training_planned_for_a_graduate_takes_it_off_the_list(self):
        self._train(self.graduate)
        result = self._coverage()
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertNotIn(self.graduate.id, missing)
        self.assertEqual(result["in_school_count"], 1)

    def test_an_in_school_training_is_a_training_planned(self):
        self._train(self.uncovered)
        result = self._coverage()
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertNotIn(self.uncovered.id, missing)
        self.assertEqual(result["in_school_count"], 1)

    def test_a_graduate_is_invited_to_a_group_training_and_a_champion_is_not(self):
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=COVERAGE_FY,
            planned_date=_fy_day(11, 6),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
        )
        set_invited_schools(session, [self.graduate.id])
        states = cluster_training_coverage([self.graduate], fy=COVERAGE_FY)
        self.assertEqual(states[self.graduate.id].key, TRAINING_PLANNED)
        with self.assertRaisesMessage(BadRequest, "Champion schools receive no"):
            set_invited_schools(session, [self.graduate.id, self.champion.id])

    def test_the_school_s_own_status_reads_a_graduate_like_a_client(self):
        states = cluster_training_coverage(
            [self.graduate, self.champion, self.uncovered], fy=COVERAGE_FY
        )
        self.assertEqual(states[self.graduate.id].key, NO_TRAINING_PLANNED)
        self.assertEqual(states[self.uncovered.id].key, NO_TRAINING_PLANNED)
        self.assertEqual(states[self.champion.id].key, TRAINING_NOT_REQUIRED)
        self.assertEqual(states[self.champion.id].label, "No Training Required")

    def test_a_visited_graduate_with_no_training_is_an_urgent_training_issue(self):
        facts = {
            "ssa": {self.graduate.id, self.uncovered.id},
            "visited": {self.graduate.id, self.uncovered.id},
            "trained": set(),
        }
        graduate = urgent_attention.resolve_urgent_issue(
            self.graduate, COVERAGE_FY, [], facts=facts
        )
        client = urgent_attention.resolve_urgent_issue(
            self.uncovered, COVERAGE_FY, [], facts=facts
        )
        self.assertEqual(graduate["key"], "no_training")
        self.assertEqual(client["key"], "no_training")
        # Trained once the training is completed.
        facts["trained"] = {self.graduate.id}
        trained = urgent_attention.resolve_urgent_issue(
            self.graduate, COVERAGE_FY, [], facts=facts
        )
        self.assertNotEqual(trained["key"], "no_training")
