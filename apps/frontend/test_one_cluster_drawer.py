"""One cluster planning drawer, wherever the planning starts.

Owner, 2026-09-17: "The cluster meeting drawer should be the same even when
navigated from the planning page. I noticed they are different. Use the same
cluster list on the cluster page everywhere. use the same cluster meeting
planning drawer on the cluster meeting page everywhere there is cluster
planning." And: "make sure that the cluster planning (group training and
meeting) scheduling is uniform irrespective of where the user is planning
from. some users prefer planning from the cluster profile others prefer
planning from the cluster page list(Schedule button)".

There were two drawers on two endpoints. The Planning one carried certified
agency delivery, the cluster's SSA need, the deviation reason and the session's
goals; the Clusters one carried a cluster chooser, a responsible-staff picker
and a live cost preview. Whichever door you came through, you got a different
form — and the Clusters one could not hand a session to an agency at all.

The Planning drawer survives, because it is the governed one, and it gained the
three things it lacked. The Clusters page's own entry points now open it.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
DRAWER = ROOT / "templates/partials/planning/schedule_cluster_drawer.html"
RETIRED = ROOT / "templates/partials/clusters/cluster_action_planner_drawer.html"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text()


class EveryClusterEntryPointOpensOneDrawerTest(SimpleTestCase):
    def test_the_clusters_page_opens_the_planning_drawer(self):
        """Both cluster-less buttons, which name the session but not the
        cluster, so they are the two that need the chooser."""
        index = _read("templates/pages/clusters/index.html")

        self.assertIn("/planning/schedule-modal?action=training", index)
        self.assertIn("/planning/schedule-modal?action=meeting", index)
        self.assertNotIn("/clusters/planner-drawer", index)

    def test_a_cluster_card_and_a_cluster_profile_open_it_too(self):
        """These name the cluster, so they open it fixed — no chooser."""
        for relative in (
            "templates/partials/clusters/cluster_card.html",
            "templates/partials/clusters/cluster_detail_drawer.html",
        ):
            with self.subTest(template=relative):
                markup = _read(relative)
                self.assertIn("/planning/schedule-modal?cluster_id=", markup)
                self.assertNotIn("/clusters/planner-drawer", markup)

    def test_no_template_opens_the_retired_second_drawer(self):
        opens_it = [
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "templates").rglob("*.html")
            if path != RETIRED and "/clusters/planner-drawer" in path.read_text()
        ]
        self.assertEqual(opens_it, [])


class TheSurvivingDrawerCarriesBothFieldSetsTest(SimpleTestCase):
    def setUp(self):
        self.markup = DRAWER.read_text()

    def test_it_keeps_what_only_the_planning_drawer_had(self):
        for field in (
            'name="assigned_partner_id"',  # certified agency delivery
            'name="executor_type"',
            'name="ssa_deviation_reason"',
            'name="expected_outcome"',
            'name="priority_allocation_id"',
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.markup)

    def test_it_gained_what_only_the_clusters_drawer_had(self):
        # The chooser, and the list behind it.
        self.assertIn('id="cluster-picker"', self.markup)
        self.assertIn("{% for c in clusters %}", self.markup)
        # Whose session it is.
        self.assertIn('name="responsible_staff_id"', self.markup)
        # And what it will cost, live.
        self.assertIn('id="cluster-cost-preview"', self.markup)
        self.assertIn("/clusters/cost-preview", self.markup)

    def test_the_chooser_appears_only_when_no_cluster_was_named(self):
        self.assertIn("{% if not fixed_cluster %}", self.markup)

    def test_the_cost_preview_names_its_own_target(self):
        """htmx INHERITS hx-target, and the form above sets #form-errors.

        Without an explicit target the preview was swapped into the form's
        error box and the container stayed empty — which is how this was
        found. The assertion is here because the symptom is invisible: the
        request succeeds, the page just puts the answer somewhere else.
        """
        preview = self.markup.split('id="cluster-cost-preview"')[1].split(">")[0]
        self.assertIn('hx-target="#cluster-cost-preview"', preview)
