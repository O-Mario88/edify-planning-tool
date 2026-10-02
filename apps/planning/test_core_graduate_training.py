"""A Core Graduate school is never a school "with no training planned".

Owner, 2026-10-02: "some Core graduate planned are still showing as not
trained on the PL summaries even when they have been planned."

By the planning rulebook a Core Graduate school takes one visit a year and no
training, and a Champion school neither; both are kept off cluster
invitations. The Programme Lead's summaries read training against every
school in the portfolio, so each of those schools sat in "no training"
however fully it was planned. Training is now read against the types that
take one (``rules.TRAINED_TYPES``): Core, Client and Core Trained.
"""

from __future__ import annotations

from apps.activities.models import Activity
from apps.planning import coverage_service, urgent_attention
from apps.planning.country_oversight import rules
from apps.planning.planning_monitor import planning_monitor
from apps.planning.test_planning_monitor import DAY, FY, MonitorFixture
from apps.planning.test_school_coverage import FY as COVERAGE_FY
from apps.planning.test_school_coverage import CoverageFixture, _fy_day
from apps.schools.models import School
from apps.schools.school_status import (
    NO_TRAINING_PLANNED,
    TRAINING_NOT_REQUIRED,
    cluster_training_coverage,
)


class TheRulebookNamesTheTypesThatTakeATraining(MonitorFixture):
    def test_core_client_and_core_trained_take_a_training(self):
        self.assertEqual(set(rules.TRAINED_TYPES), {"core", "client", "core_trained"})
        self.assertFalse(rules.takes_training("core_graduate"))
        self.assertFalse(rules.takes_training("champion"))


class TheMonitorReadsTrainingAgainstSchoolsThatTakeOne(MonitorFixture):
    def setUp(self):
        self.graduate = self._school("MON-G1", "core_graduate", self.ben)
        # Planned as the rule asks: the Core Graduate school's one visit.
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

    def test_a_planned_core_graduate_school_is_not_missing_training(self):
        ben = self._ben()
        # Ben holds a client school with nothing planned and the graduate.
        self.assertEqual(ben.school_count, 2)
        self.assertEqual(ben.training_schools, 1)
        self.assertEqual(ben.no_training, 1)
        self.assertEqual(ben.no_visit, 1)
        self.assertEqual(ben.no_both, 1)

    def test_the_no_training_list_leaves_it_out(self):
        monitor = planning_monitor(
            self.cd_user, fy=FY, gap="no_training", officer_id=self.ben.id
        )
        self.assertEqual({s.code for s in monitor["gap_schools"]}, {"MON-B1"})

    def test_the_lead_s_total_is_read_against_the_same_schools(self):
        monitor = planning_monitor(self.pl_user, fy=FY)
        totals = monitor["totals"]
        # Six schools take a training (the fixture's five and Ben's client
        # school); the graduate is the seventh school and not one of them.
        self.assertEqual(totals.school_count, 7)
        self.assertEqual(totals.training_schools, 6)
        self.assertEqual(
            totals.no_training, totals.training_schools - totals.schools_with_training
        )


class TheCoverageTabListsOnlySchoolsThatTakeATraining(CoverageFixture):
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

    def test_a_graduate_and_a_champion_are_not_missing_training(self):
        self._visit(self.graduate, _fy_day(11, 6))
        result = self._coverage()
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertNotIn(self.graduate.id, missing)
        self.assertNotIn(self.champion.id, missing)
        self.assertEqual(
            missing, {self.covered.id, self.uncovered.id, self.unclustered.id}
        )
        self.assertEqual(result["missing_count"], 3)

    def test_an_in_school_training_is_a_training_planned(self):
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.uncovered,
            fy=COVERAGE_FY,
            planned_date=_fy_day(11, 6),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        result = self._coverage()
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertNotIn(self.uncovered.id, missing)
        self.assertEqual(result["in_school_count"], 1)

    def test_the_school_s_own_status_says_none_is_required(self):
        states = cluster_training_coverage(
            [self.graduate, self.champion, self.uncovered], fy=COVERAGE_FY
        )
        self.assertEqual(states[self.graduate.id].key, TRAINING_NOT_REQUIRED)
        self.assertEqual(states[self.graduate.id].label, "No Training Required")
        self.assertEqual(states[self.champion.id].key, TRAINING_NOT_REQUIRED)
        self.assertEqual(states[self.uncovered.id].key, NO_TRAINING_PLANNED)

    def test_a_visited_graduate_has_no_urgent_training_issue(self):
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
        self.assertNotEqual(graduate["key"], "no_training")
        self.assertEqual(client["key"], "no_training")
