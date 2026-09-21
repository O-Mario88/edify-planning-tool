"""The per-person folds behind the Programme Lead's charts.

A lead reads their team as people, so every chart on their oversight pages
carries one series per person. Each series is folded from the same rows the
tables draw, so a bar and the rows under it cannot disagree.
"""

from datetime import date

from django.test import SimpleTestCase

from apps.clusters.oversight_service import cluster_activity_by_person
from apps.frontend.views.core_schools_views import _core_rows_by_officer
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


class CoreRowsByOfficerTest(SimpleTestCase):
    def test_school_rows_sum_per_responsible_officer_in_name_order(self):
        rows = [
            {
                "account_owner_id": "b",
                "responsible_cceo": "Ruth N.",
                "scheduled_visit_count": 1,
                "visits_target": 4,
                "scheduled_training_count": 0,
                "trainings_target": 4,
            },
            {
                "account_owner_id": "a",
                "responsible_cceo": "Deo M.",
                "scheduled_visit_count": 2,
                "visits_target": 4,
                "scheduled_training_count": 3,
                "trainings_target": 4,
            },
            {
                "account_owner_id": "b",
                "responsible_cceo": "Ruth N.",
                "scheduled_visit_count": 4,
                "visits_target": 4,
                "scheduled_training_count": 1,
                "trainings_target": 4,
            },
        ]

        folded = _core_rows_by_officer(rows)

        self.assertEqual([r["name"] for r in folded], ["Deo M.", "Ruth N."])
        self.assertEqual(folded[1]["scheduled_visits"], 5)
        self.assertEqual(folded[1]["visits_target"], 8)
        self.assertEqual(folded[1]["scheduled_trainings"], 1)
        self.assertEqual(folded[0]["trainings_target"], 4)

    def test_a_school_with_no_owner_folds_under_unassigned_at_the_end(self):
        rows = [
            {
                "account_owner_id": None,
                "responsible_cceo": "",
                "scheduled_visit_count": 0,
                "visits_target": 4,
                "scheduled_training_count": 0,
                "trainings_target": 4,
            },
            {
                "account_owner_id": "a",
                "responsible_cceo": "Deo M.",
                "scheduled_visit_count": 1,
                "visits_target": 4,
                "scheduled_training_count": 0,
                "trainings_target": 4,
            },
        ]

        self.assertEqual(
            [r["name"] for r in _core_rows_by_officer(rows)], ["Deo M.", "Unassigned"]
        )
        self.assertEqual(_core_rows_by_officer([]), [])


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
