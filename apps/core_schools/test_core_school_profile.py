"""The Core School tab on a Core school's profile.

Owner, 2026-10-17, the Core School Intelligence brief (4-6, 15): one school's
SSA by intervention, its package, participation, outcomes and Champion
readiness, from apps.core_schools.intelligence — the reading Core School
Oversight shows for the same school.
"""

from __future__ import annotations

from apps.core_schools import intelligence
from apps.core_schools.test_core_intelligence import _CoreCase
from apps.schools.models import School
from apps.ssa.change_rules import IMPROVED, NOT_COMPARABLE


class InterventionDetailTest(_CoreCase):
    def test_each_intervention_has_its_two_years_change_and_verdict(self):
        detail = intelligence.interventions(self.rising, fy=self.fy)
        rows = {r["key"]: r for r in detail["rows"]}

        self.assertEqual(
            (rows["leadership"]["previous"], rows["leadership"]["latest"]),
            (5.0, 7.0),
        )
        self.assertEqual(rows["leadership"]["change"], 2.0)
        self.assertEqual(rows["leadership"]["verdict"], IMPROVED)
        self.assertEqual(rows["financial_health"]["change"], 3.0)
        # An intervention scored in neither year is said, not zeroed.
        self.assertIsNone(rows["enrolment"]["latest"])
        self.assertEqual(rows["enrolment"]["verdict"], NOT_COMPARABLE)

    def test_strongest_weakest_and_largest_moves_are_kept_apart(self):
        detail = intelligence.interventions(self.rising, fy=self.fy)

        self.assertEqual(detail["strongest"]["key"], "financial_health")
        self.assertEqual(detail["weakest"]["key"], "teaching_environment")
        self.assertEqual(detail["largest_gain"]["key"], "financial_health")
        self.assertIsNone(detail["largest_drop"])

    def test_one_assessment_gives_latest_scores_and_no_verdicts(self):
        detail = intelligence.interventions(self.single, fy=self.fy)
        rows = {r["key"]: r for r in detail["rows"]}

        self.assertEqual(rows["leadership"]["latest"], 4.0)
        self.assertIsNone(rows["leadership"]["change"])
        self.assertEqual(rows["leadership"]["verdict"], NOT_COMPARABLE)


class CoreSchoolTabTest(_CoreCase):
    def _tab(self, school, user=None):
        self.client.force_login(user or self.james)
        response = self.client.get(
            f"/schools/{school.id}", {"tab": "core", "fy": self.fy}
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_tab_reads_the_same_figures_as_oversight(self):
        body = self._tab(self.rising)
        row = intelligence.performance([self.rising], fy=self.fy)[self.rising.id]

        self.assertIn('data-core-school-tab="CI-1"', body)
        self.assertIn("Improved", body)
        self.assertIn(row.champion, body)

    def test_the_tab_leaves_the_school_s_ssa_to_its_ssa_tab(self):
        """One place for each SSA figure (owner, 2026-10-19: "ssa [scores]
        are duplicated more than 2 times"): the tab says the Core trajectory
        and opens the SSA tab for the scores, rather than drawing each
        intervention a fifth time."""
        body = self._tab(self.rising)

        self.assertIn("data-core-ssa-link", body)
        self.assertIn("tab=ssa", body)
        self.assertNotIn("data-core-intervention=", body)
        self.assertNotIn("data-core-highlights", body)
        self.assertNotIn("Previous SSA", body)

    def test_the_champion_checklist_names_each_criterion(self):
        body = self._tab(self.rising)

        for criterion in (
            "Latest SSA average 8.0 or more",
            "No intervention below 7.0",
            "All package visits and trainings done",
        ):
            self.assertIn(criterion, body)

    def test_a_school_outside_the_core_lifecycle_has_no_core_tab(self):
        from apps.accounts.models import StaffSchoolAssignment

        client_school = School.objects.create(
            school_id="CI-CLIENT",
            name="Client school",
            school_type="client",
            region=self.region,
            district=self.north,
            account_owner_id=self.james.staff_profile.id,
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=self.james.staff_profile, school_id=client_school.id
        )
        self.client.force_login(self.james)

        body = self.client.get(f"/schools/{client_school.id}").content.decode()

        self.assertNotIn("tab=core", body)
