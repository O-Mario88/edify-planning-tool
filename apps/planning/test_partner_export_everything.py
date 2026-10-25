"""Partner Oversight's export holds everything the page lists, and Impact
Assessment exports every partner at once.

Owner, 2026-10-25: "the IA cannot export everything (The trainings and
cluster meeting specifically). it is limiting the IA". Two gaps, both met on
production as the IA:

- The group trainings and cluster meetings a partner facilitates are on the
  page (its "Trainings and meetings facilitated" table, owner 2026-09-26)
  but the export read the hand-overs alone: Annet's team tab counted 3,004,
  its export 1,384.
- The drawer carried the page's partner tab and Programme Lead tab as hidden
  pins with no way to widen them, so the IA's default export was one
  partner's work in one team (0 rows that day). A country reader now chooses
  the partner and whose plans, all partners and everyone by default, as
  Planning Oversight's drawer does (owner, 2026-10-12).
"""

from __future__ import annotations

import csv
import io

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.planning import partner_oversight_service as svc
from apps.planning import test_partner_facilitated_trainings as facilitated
from apps.planning.test_partner_oversight import PartnerOversightFixture

FACILITATED = svc.FACILITATED_SUPPORT_TYPE


class PartnerExportHoldsEverythingTest(PartnerOversightFixture):
    # The facilitated-training fixture's own helper, without its tests.
    FEE = facilitated.FacilitatedTrainingsTest.FEE
    train = facilitated.FacilitatedTrainingsTest.train

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user = User.objects.create(
            email="ia@p.test",
            name="Impact Reader",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.ia_user, title="Impact Reader")

    def setUp(self):
        self.training = self.train()
        self.meeting = self.train(cceo=self.rival_cceo)
        self.meeting.activity_type = "cluster_meeting"
        self.meeting.save(update_fields=["activity_type"])
        self.visit = self.schedule(self.assign())

    def export(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(
            "/partner-oversight/export",
            {
                "fy": self.fy,
                "period_type": "fy",
                "status": "all",
                "activity_type": "all",
                "member": "all",
                "format": "csv",
                **params,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        header, *rows = list(csv.reader(io.StringIO(body)))
        self.assertEqual(tuple(header), svc.EXPORT_HEADER)
        return [dict(zip(header, row)) for row in rows]

    def facilitated(self, rows):
        return [r for r in rows if r["Support Type"] == FACILITATED]

    def test_the_ia_exports_every_partner_facilitation_in_both_teams(self):
        # What the drawer sends for "Everyone" and "All partners".
        rows = self.export(self.ia_user, partner="all", program_lead="all")
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            sorted(r["Managing CCEO"] for r in self.facilitated(rows)),
            ["James", "Rival"],
        )
        self.assertEqual(
            sorted(r["Program Lead"] for r in self.facilitated(rows)),
            ["Mary", "Other Lead"],
        )

    def test_the_intervention_reads_as_its_label_on_every_row(self):
        rows = self.export(self.ia_user, partner="all", activity_type="visits")
        (handover,) = rows
        self.assertEqual(handover["Focus Intervention"], "Financial Health")

    def test_a_facilitated_row_carries_the_tables_facts(self):
        rows = self.export(self.ia_user, partner="all", activity_type="group_trainings")
        (row,) = rows
        self.assertEqual(row["Partner"], "Partner X")
        self.assertEqual(row["Support Type"], FACILITATED)
        self.assertEqual(row["Cluster"], "Kira Cluster")
        self.assertEqual(row["District"], "Kampala")
        self.assertEqual(row["Focus Intervention"], "Financial Health")
        self.assertEqual(row["Scheduled For"], self.training.planned_date.isoformat())
        self.assertEqual(row["Activity Status"], "scheduled")
        # The fee, as the page's Cost column shows it, not the whole budget.
        self.assertEqual(row["Planned Cost (UGX)"], str(self.FEE))
        self.assertEqual(row["School ID"], "")

    def test_cluster_meetings_only_is_the_facilitated_meeting(self):
        rows = self.export(self.ia_user, partner="all", activity_type="meetings")
        self.assertEqual([r["Managing CCEO"] for r in rows], ["Rival"])

    def test_one_partner_and_one_team_still_narrow_it(self):
        self.assertEqual(self.export(self.ia_user, partner=self.other_partner.id), [])
        rows = self.export(self.ia_user, partner="all", program_lead=self.rival_pl.id)
        self.assertEqual([r["Managing CCEO"] for r in rows], ["Rival"])

    def test_a_lead_exports_their_own_teams_facilitations_only(self):
        rows = self.export(self.pl_user, partner="all")
        self.assertEqual(
            [r["Managing CCEO"] for r in self.facilitated(rows)], ["James"]
        )

    def test_the_ia_drawer_offers_every_partner_and_everyone(self):
        self.client.force_login(self.ia_user)
        response = self.client.get(
            "/partner-oversight/export-drawer",
            {
                "fy": self.fy,
                # The page's tabs, as its Export button sends them.
                "partner": self.other_partner.id,
                "program_lead": self.pl.id,
                "member": "all",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn('type="hidden" name="partner"', body)
        self.assertNotIn('type="hidden" name="program_lead"', body)
        self.assertIn('<option value="all" selected>All partners</option>', body)
        self.assertIn(f'<option value="{self.partner.id}">Partner X</option>', body)
        self.assertIn('<option value="all" selected>Everyone</option>', body)
