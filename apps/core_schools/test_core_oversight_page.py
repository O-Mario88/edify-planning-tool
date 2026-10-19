"""Core School Oversight: the Core schools analysed, for each reader's scope.

Owner, 2026-10-17, the Core School Intelligence brief (10.1-11): CCEOs open
Core School Oversight for their own Core schools only; a Programme Lead reads
their team, grouped by CCEO, sub-region or district; the country roles their
country. The page is analysis (owner: "Anything to do with planning goes on
MY Plan or Planning oversight"), every figure from
apps.core_schools.intelligence, and the export holds the same scope.
"""

from __future__ import annotations

from apps.accounts.models import StaffSupervisorAssignment
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.rbac import EdifyRole
from apps.core_schools.test_core_intelligence import _CoreCase

URL = "/core-schools-oversight/"


class CoreOversightPageTest(_CoreCase):
    def setUp(self):
        super().setUp()
        self.cd = _create_user("cd@core-oversight.test", EdifyRole.COUNTRY_DIRECTOR)

    def _page(self, user, **query):
        self.client.force_login(user)
        response = self.client.get(URL, {"fy": self.fy, **query})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _rows(self, body):
        return {
            code
            for code in ("CI-1", "CI-2", "CI-3")
            if f'data-core-school-row="{code}"' in body
        }

    def test_a_cceo_reads_only_their_own_core_schools(self):
        self.assertEqual(self._rows(self._page(self.james)), {"CI-1", "CI-2"})
        self.assertEqual(self._rows(self._page(self.mary)), {"CI-3"})

    def test_a_lead_reads_their_team_grouped_by_cceo(self):
        lead = _create_user("lead@core-oversight.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.james.staff_profile, supervisor=lead.staff_profile
        )

        self.assertEqual(self._rows(self._page(lead)), {"CI-1", "CI-2"})
        groups = self._page(lead, tab="groups", group="cceo")
        self.assertIn(f'data-core-group="{self.james.name}"', groups)
        self.assertNotIn(f'data-core-group="{self.mary.name}"', groups)

    def test_the_country_reads_every_core_school_with_its_denominators(self):
        body = self._page(self.cd)

        self.assertEqual(self._rows(body), {"CI-1", "CI-2", "CI-3"})
        # Compared, with the schools it rests on.
        self.assertIn(">2 of 3</strong>", body)
        self.assertIn('data-core-drill="improved">Improved (1)', body)
        self.assertIn('data-core-drill="declined">Declined (1)', body)
        self.assertIn('data-core-drill="not_compared">Not compared (1)', body)

    def test_a_filter_narrows_the_schools(self):
        body = self._page(self.cd, trajectory="declined")

        self.assertEqual(self._rows(body), {"CI-3"})

    def test_the_page_is_analysis_not_planning(self):
        body = self._page(self.cd)

        self.assertNotIn("Planned Core Work", body)
        self.assertNotIn("data-core-work", body)

    def test_the_attention_tab_names_each_school_and_its_reason(self):
        body = self._page(self.cd, tab="attention")

        declined = body[body.index('data-core-reason="SSA declined"') :]
        self.assertIn("Core school CI-3", declined[: declined.index("</section>")])

    def test_the_export_holds_the_readers_scope(self):
        self.client.force_login(self.cd)
        download = self.client.get(URL, {"fy": self.fy, "format": "csv"})
        lines = download.content.decode().splitlines()

        self.assertEqual(download["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(lines[0].startswith("School ID,School,Type,District"))
        self.assertEqual(len(lines) - 1, 3)

        # A CCEO's role holds no data export.
        self.client.force_login(self.james)
        refused = self.client.get(URL, {"fy": self.fy, "format": "csv"})
        self.assertNotEqual(refused.get("Content-Type"), "text/csv; charset=utf-8")

    def test_a_cceo_has_the_sidebar_entry(self):
        from apps.core.navigation import build_sidebar_for_user

        labels = [
            item["label"]
            for section in build_sidebar_for_user(self.james, "/dashboard")
            for item in section["items"]
        ]
        self.assertIn("Core School Oversight", labels)
