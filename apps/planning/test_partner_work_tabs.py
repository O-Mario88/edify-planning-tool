"""One Partner's work, one kind a tab (owner, 2026-10-02).

"The Partners Assigned schools should appear on partner oversight as tabs not
drop-down. PLs should see every activities assigned to partners. Activities
(visits, trainings - list of clusters the partners will facilitate) should be
grouped in tabs ... It should be easy for the users to toggle between tabs."

The tables used to sit one under another behind an Activity drop-down. These
hold which tab each kind of work sits in, what each tab counts and which one
opens.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.planning import partner_oversight_service as svc


def _item(**fields):
    base = dict(
        partner_assignment_id=None,
        partner_activity_id=None,
        school_id=None,
        cluster_id=None,
        activity_type="",
        is_core_school_work=False,
    )
    base.update(fields)
    return SimpleNamespace(**base)


class WhichTabTest(SimpleTestCase):
    def test_a_visit_at_a_school_is_a_visit(self):
        for activity_type in (
            "training_follow_up_visit",
            "school_visit_ssa_collection",
        ):
            with self.subTest(activity_type=activity_type):
                item = _item(school_id="s1", activity_type=activity_type)
                self.assertEqual(svc.work_tab_of(item), svc.TAB_VISITS)

    def test_a_training_at_a_school_is_a_training(self):
        item = _item(school_id="s1", activity_type="in_school_training")
        self.assertEqual(svc.work_tab_of(item), svc.TAB_TRAININGS)

    def test_work_for_a_cluster_is_cluster_work(self):
        for activity_type in ("cluster_training", "cluster_meeting"):
            with self.subTest(activity_type=activity_type):
                item = _item(cluster_id="c1", activity_type=activity_type)
                self.assertEqual(svc.work_tab_of(item), svc.TAB_CLUSTERS)


class TablesAndTabsTest(SimpleTestCase):
    def _tables(self, *items):
        return svc.workspace_tables(list(items))

    def test_every_piece_of_work_is_on_a_tab(self):
        handover = _item(partner_assignment_id="a1", school_id="s1")
        core = _item(
            partner_assignment_id="a2", school_id="s2", is_core_school_work=True
        )
        cluster = _item(partner_assignment_id="a3", cluster_id="c1")
        visit = _item(
            partner_activity_id="v1", school_id="s1", activity_type="school_visit"
        )
        training = _item(
            partner_activity_id="t1", school_id="s1", activity_type="in_school_training"
        )
        session = _item(
            partner_activity_id="m1", cluster_id="c1", activity_type="cluster_meeting"
        )
        tables = self._tables(handover, core, cluster, visit, training, session)
        by_tab: dict[str, list] = {}
        for table in tables:
            by_tab.setdefault(table["tab"], []).extend(table["items"])

        self.assertEqual(by_tab[svc.TAB_SCHOOLS], [handover])
        self.assertEqual(by_tab[svc.TAB_CORE], [core])
        self.assertEqual(by_tab[svc.TAB_VISITS], [visit])
        self.assertEqual(by_tab[svc.TAB_TRAININGS], [training])
        self.assertEqual(by_tab[svc.TAB_CLUSTERS], [cluster, session])

    def test_the_tabs_count_their_rows_and_the_facilitated_trainings(self):
        tables = self._tables(
            _item(partner_assignment_id="a1", school_id="s1"),
            _item(
                partner_activity_id="v1", school_id="s1", activity_type="school_visit"
            ),
        )
        tabs, active = svc.work_tabs(tables, trainings=[object(), object()])
        counts = {tab["key"]: tab["count"] for tab in tabs}
        self.assertEqual(
            counts,
            {
                svc.TAB_SCHOOLS: 1,
                svc.TAB_VISITS: 1,
                svc.TAB_TRAININGS: 0,
                svc.TAB_CLUSTERS: 2,
            },
        )
        self.assertEqual(active, svc.TAB_SCHOOLS)

    def test_core_schools_is_a_tab_only_for_a_partner_who_holds_one(self):
        without, _ = svc.work_tabs(self._tables(), trainings=[])
        self.assertNotIn(svc.TAB_CORE, [tab["key"] for tab in without])
        core = _item(
            partner_assignment_id="a2", school_id="s2", is_core_school_work=True
        )
        with_core, active = svc.work_tabs(self._tables(core), trainings=[])
        self.assertIn(svc.TAB_CORE, [tab["key"] for tab in with_core])
        self.assertEqual(active, svc.TAB_CORE)

    def test_it_opens_on_the_first_tab_holding_anything(self):
        visit = _item(
            partner_activity_id="v1", school_id="s1", activity_type="school_visit"
        )
        _tabs, active = svc.work_tabs(self._tables(visit), trainings=[])
        self.assertEqual(active, svc.TAB_VISITS)
        _tabs, active = svc.work_tabs(self._tables(), trainings=[object()])
        self.assertEqual(active, svc.TAB_CLUSTERS)

    def test_the_tab_asked_for_opens_even_when_it_is_empty(self):
        visit = _item(
            partner_activity_id="v1", school_id="s1", activity_type="school_visit"
        )
        tabs, active = svc.work_tabs(self._tables(visit), [], svc.TAB_TRAININGS)
        self.assertEqual(active, svc.TAB_TRAININGS)
        self.assertEqual(
            [t["key"] for t in tabs if t["is_active"]], [svc.TAB_TRAININGS]
        )

    def test_an_unknown_tab_falls_back(self):
        _tabs, active = svc.work_tabs(self._tables(), [], "nonsense")
        self.assertEqual(active, svc.TAB_SCHOOLS)
