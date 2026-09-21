"""The per-person folds behind the Programme Lead's charts.

A lead reads their team as people, so every chart on their oversight pages
carries one series per person. Each series is folded from the same rows the
tables draw, so a bar and the rows under it cannot disagree.
"""

from datetime import date

from django.test import SimpleTestCase

from apps.clusters.oversight_service import cluster_activity_by_person
from apps.frontend.views.core_schools_views import _core_rows_by_person, _core_totals
from apps.frontend.views.oversight_views import WHOLE_TEAM_TAB, _team_progress_rows
from apps.planning.cluster_performance_service import ClusterRow
from apps.planning.oversight_service import (
    STAGE_PARTNER_AWAITING_SCHEDULE,
    STAGE_STAFF_SCHEDULED,
    PlanningOversightItem,
)


def _item(activity_type, *, done=False, stage=STAGE_STAFF_SCHEDULED):
    return PlanningOversightItem(
        stage=stage,
        activity_type=activity_type,
        planned_date=date(2026, 3, 4),
        activity_status="completed" if done else "scheduled",
    )


class TeamProgressRowsTest(SimpleTestCase):
    def test_the_lead_comes_first_then_each_officer_and_the_team_tab_is_not_drawn(self):
        tabs = [
            {
                "key": WHOLE_TEAM_TAB,
                "label": "Whole team",
                "items": [_item("school_visit")] * 3,
            },
            {
                "key": "mine",
                "label": "My Work",
                "items": [_item("school_visit", done=True)],
            },
            {
                "key": "s1",
                "label": "Deo M.",
                "items": [_item("school_visit"), _item("cluster_meeting")],
            },
            {"key": "s2", "label": "Ruth N.", "items": []},
        ]

        rows = _team_progress_rows(tabs, "all", own_label="Mary A. (you)")

        self.assertEqual(
            [r["name"] for r in rows], ["Mary A. (you)", "Deo M.", "Ruth N."]
        )
        self.assertEqual(rows[0]["total_planned"], 1)
        self.assertEqual(rows[0]["completed"], 1)
        self.assertEqual(rows[1]["total_planned"], 2)
        self.assertEqual(rows[1]["scheduled_total"], 2)
        self.assertEqual(rows[2]["total_planned"], 0)

    def test_rows_follow_the_activity_family_strip(self):
        tabs = [
            {"key": "mine", "label": "My Work", "items": []},
            {
                "key": "s1",
                "label": "Deo M.",
                "items": [
                    _item("school_visit"),
                    _item("cluster_meeting"),
                    _item("cluster_meeting"),
                ],
            },
        ]

        meetings = _team_progress_rows(tabs, "meetings", own_label="Lead (you)")

        self.assertEqual(meetings[1]["total_planned"], 2)
        self.assertEqual(
            _team_progress_rows(tabs, "visits", own_label="Lead (you)")[1][
                "total_planned"
            ],
            1,
        )

    def test_partner_work_awaiting_a_schedule_is_planned_but_not_scheduled(self):
        tabs = [
            {
                "key": "s1",
                "label": "Deo M.",
                "items": [_item("school_visit", stage=STAGE_PARTNER_AWAITING_SCHEDULE)],
            }
        ]

        row = _team_progress_rows(tabs, "all", own_label="Lead (you)")[0]

        self.assertEqual(row["total_planned"], 1)
        self.assertEqual(row["scheduled_total"], 0)


def _school(owner, name, visits=0, trainings=0):
    return {
        "account_owner_id": owner,
        "responsible_cceo": name,
        "scheduled_visit_count": visits,
        "visits_target": 4,
        "scheduled_training_count": trainings,
        "trainings_target": 4,
    }


def _by_owner(row):
    return (row["account_owner_id"], row["responsible_cceo"])


class CoreRowsByPersonTest(SimpleTestCase):
    def test_the_roster_comes_first_in_its_own_order_with_zero_rows_for_the_idle(self):
        rows = [
            _school("b", "Ruth N.", visits=1),
            _school("a", "Deo M.", visits=2, trainings=3),
            _school("b", "Ruth N.", visits=4, trainings=1),
        ]

        folded = _core_rows_by_person(
            rows,
            roster=[("a", "Deo M."), ("c", "Mary A."), ("b", "Ruth N.")],
            person_of=_by_owner,
        )

        self.assertEqual([r["name"] for r in folded], ["Deo M.", "Mary A.", "Ruth N."])
        self.assertEqual(folded[1], _core_totals("Mary A.", []))
        self.assertEqual(folded[2]["scheduled_visits"], 5)
        self.assertEqual(folded[2]["visits_target"], 8)
        self.assertEqual(folded[2]["scheduled_trainings"], 1)
        self.assertEqual(folded[0]["trainings_target"], 4)

    def test_people_off_the_roster_follow_in_name_order_and_unowned_schools_fold_last(
        self,
    ):
        rows = [
            _school(None, "", visits=0),
            _school("z", "Zed K.", visits=1),
            _school("a", "Deo M.", visits=1),
            _school("m", "Mary A.", visits=1),
        ]

        folded = _core_rows_by_person(
            rows, roster=[("a", "Deo M.")], person_of=_by_owner
        )

        self.assertEqual(
            [r["name"] for r in folded], ["Deo M.", "Mary A.", "Zed K.", "Unassigned"]
        )
        self.assertEqual(folded[-1]["visits_target"], 4)
        self.assertEqual(_core_rows_by_person([], roster=[], person_of=_by_owner), [])

    def test_a_country_reader_folds_by_the_supervising_lead(self):
        lead_of = {
            "a": ("pl1", "Lead One"),
            "b": ("pl2", "Lead Two"),
            "c": ("pl1", "Lead One"),
        }
        rows = [
            _school("a", "Deo M.", 1),
            _school("b", "Ruth N.", 2),
            _school("c", "Paul N.", 3),
        ]

        folded = _core_rows_by_person(
            rows,
            roster=[("pl1", "Lead One"), ("pl2", "Lead Two"), ("pl3", "Lead Three")],
            person_of=lambda row: lead_of[row["account_owner_id"]],
        )

        self.assertEqual(
            [(r["name"], r["scheduled_visits"]) for r in folded],
            [("Lead One", 4), ("Lead Two", 2), ("Lead Three", 0)],
        )


def _cluster(cluster_id, owner, *, planned=1, done=0, reached=0):
    return ClusterRow(
        cluster_id=cluster_id,
        name=cluster_id,
        district="Wakiso",
        owner_id=owner,
        owner_name=owner,
        lead_id="pl",
        lead_name="Lead",
        schools=5,
        sessions_planned=planned,
        sessions_done=done,
        trainings=0,
        meetings=planned,
        visits_planned=0,
        visits_done=0,
        ssa_schools=0,
        schools_reached=reached,
        last_activity=None,
        budget=0,
    )


class ClusterActivityByPersonTest(SimpleTestCase):
    def test_a_person_carries_their_clusters_active_dormant_sessions_and_reach(self):
        rows = [
            _cluster("c1", "deo", planned=2, done=1, reached=3),
            _cluster("c2", "deo", planned=0),
            _cluster("c3", "ruth", planned=1, done=1, reached=5),
        ]

        deo = cluster_activity_by_person(
            "Deo M.", rows, lambda row: row.owner_id == "deo"
        )

        self.assertEqual(
            deo,
            {
                "name": "Deo M.",
                "clusters": 2,
                "active_clusters": 1,
                "dormant_clusters": 1,
                "sessions_held": 1,
                "schools_reached": 3,
            },
        )
        nobody = cluster_activity_by_person(
            "Mary A.", rows, lambda row: row.owner_id == "mary"
        )
        self.assertEqual(nobody["clusters"], 0)
        self.assertEqual(nobody["dormant_clusters"], 0)
