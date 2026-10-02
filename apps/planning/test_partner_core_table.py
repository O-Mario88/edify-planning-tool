"""Partner Monitoring's Core Schools table (owner, 2026-09-27).

"Core Schools assigned to the partner should also appear on partner oversight
page but on its own table and the table should include the columns for
waiting for scheduling from partner and when the partner schedules, it should
change to the planned date and add the column for cost and should fetch the
partner cost of visiting a school. the Action button drop down should
include, Confirm completed work if they have uploaded the visit form and
withdraw the school incase they have not schedule it. Add the evidence column
as well."
"""

from __future__ import annotations

import re

from apps.budget.models import CostCatalogue, CostSetting
from apps.core_schools.core_planning_services import CorePackageSchedulingService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id, cslot_id
from apps.core_schools.services import create_package_slots
from apps.evidence.models import EvidenceRecord
from apps.planning.test_partner_oversight import PartnerOversightFixture
from apps.schools.models import School
from apps.accounts.models import StaffSchoolAssignment

CORE_COLUMNS = [
    "School ID",
    "School Name",
    "Staff Name",
    "Core support",
    "Purpose of Assignment",
    "Planned date",
    "Cost",
    "Salesforce ID",
    "Evidence",
    "Status",
    "Actions",
]

RATE = 55_000


class _CoreTableFixture(PartnerOversightFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.core_school = School.objects.create(
            school_id="CORE-P1",
            name="Core Partner Primary",
            school_type="core",
            district=cls.district,
            region=cls.region,
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo, school_id=cls.core_school.id
        )
        cls.plan = CorePlan.objects.create(
            id=cplan_id("CORE-P1", fy=cls.fy),
            school_id="CORE-P1",
            fy=cls.fy,
            status="Active",
        )
        create_package_slots(cls.plan, "CORE-P1", ["leadership"])
        catalogue = CostCatalogue.objects.filter(is_active=True).first()
        if catalogue is None:
            catalogue = CostCatalogue.objects.create(
                country="Uganda", fy=cls.fy, version=1, is_active=True
            )
        CostSetting.objects.update_or_create(
            key="core_partner_visit",
            catalogue=catalogue,
            defaults={
                "label": "Core Partner Visit",
                "unit_cost": RATE,
                "fy": cls.fy,
                "version": catalogue.version,
            },
        )

    def core_handover(self, **fields):
        """What the Core Schools page's Assign drawer writes: a handover that
        names its package slot, and the slot marked Assigned."""
        handover = self.assign(
            school=self.core_school,
            support_type="Visit",
            visit_number="2",
            purpose_of_visit="ssa_support",
            **fields,
        )
        CorePackageSchedulingService.commit_assign(
            CoreActivitySlot.objects.get(id=cslot_id("CORE-P1", "v", 2, fy=self.fy)),
            partner_id=self.partner.id,
            partner_name=self.partner.name,
        )
        return handover

    def page(self, user=None, work=""):
        self.client.force_login(user or self.pl_user)
        response = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}&work={work}"
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def core_table(self, body):
        start = body.index("data-partner-core-columns")
        return body[start : body.index("</table>", start)]

    def core_row(self, body, handover):
        table = self.core_table(body)
        start = table.index(f'data-assignment="{handover.id}"')
        return table[start : table.index('<tr id="partner-row-details-', start)]


class TheCoreTableTest(_CoreTableFixture):
    def test_it_reads_the_owner_s_columns(self):
        self.core_handover()
        headers = re.findall(
            r'<th scope="col"[^>]*>([^<]+)</th>', self.core_table(self.page())
        )
        self.assertEqual(headers, CORE_COLUMNS)

    def test_core_schools_leave_the_schools_assigned_table(self):
        handover = self.core_handover()
        client_handover = self.assign()
        # Each on a tab of its own (owner, 2026-10-02).
        core = self.page(work="core")
        body = self.page(work="schools")

        self.assertIn(f'data-assignment="{handover.id}"', self.core_table(core))
        self.assertNotIn("data-partner-school-columns", core)
        start = body.index("data-partner-school-columns")
        schools = body[start : body.index("</table>", start)]
        self.assertNotIn(f'data-assignment="{handover.id}"', schools)
        self.assertIn(f'data-assignment="{client_handover.id}"', schools)
        self.assertNotIn("data-partner-core-columns", body)
        self.assertIn("<span>Core schools</span>", body)

    def test_a_partner_with_no_core_schools_has_no_core_tab(self):
        self.assign()
        body = self.page()
        self.assertNotIn("data-partner-core-columns", body)
        self.assertNotIn("<span>Core schools</span>", body)
        self.assertEqual(body.count("data-partner-monitoring-table"), 1)

    def test_waiting_for_the_partner_it_reads_waiting_and_the_partner_rate(self):
        handover = self.core_handover()
        row = self.core_row(self.page(), handover)

        self.assertIn("Waiting for scheduling from partner", row)
        self.assertIn("UGX 55,000", row, "the Cost Catalogue's Core Partner Visit")
        self.assertRegex(row, r"data-core-support>V2<")
        self.assertIn("No Evidence Uploaded", row)

    def test_a_training_waiting_for_the_partner_reads_the_partner_visit_rate(self):
        """An in-school training is priced as a partner school visit at a
        Core School as at any other (owner, 2026-10-01), so that is the rate
        the row shows before the Partner dates it: what scheduling charges."""
        catalogue = CostCatalogue.objects.filter(is_active=True).first()
        CostSetting.objects.update_or_create(
            key="client_partner_visit",
            catalogue=catalogue,
            defaults={
                "label": "Client Partner Visit",
                "unit_cost": 41_000,
                "fy": self.fy,
                "version": catalogue.version,
            },
        )
        handover = self.assign(
            school=self.core_school,
            support_type="Training",
            visit_number="1",
            purpose_of_visit="in_school_training",
        )
        row = self.core_row(self.page(), handover)

        self.assertIn("Waiting for scheduling from partner", row)
        self.assertIn("UGX 41,000", row, "the partner school visit rate")
        self.assertNotIn("UGX 55,000", row)

    def test_once_scheduled_it_reads_the_planned_date_and_the_priced_cost(self):
        handover = self.core_handover()
        activity = self.schedule(handover, cost=180_000)
        CoreActivitySlot.objects.filter(
            id=cslot_id("CORE-P1", "v", 2, fy=self.fy)
        ).update(activity_id=activity.id, status="partner_scheduled")

        row = self.core_row(self.page(), handover)

        self.assertNotIn("Waiting for scheduling from partner", row)
        self.assertIn(activity.planned_date.strftime("%-d %b %Y"), row)
        self.assertIn("UGX 180,000", row)
        self.assertRegex(row, r"data-core-support>V2<")


class TheCoreActionsTest(_CoreTableFixture):
    def test_withdraw_school_only_while_the_partner_has_not_scheduled(self):
        handover = self.core_handover()
        self.assertIn("data-core-withdraw", self.core_row(self.page(), handover))

        self.schedule(handover)
        self.assertNotIn("data-core-withdraw", self.core_row(self.page(), handover))

    def _uploaded_visit_form(self, activity):
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="visit-form.pdf",
            uploaded_by="partner-user",
        )

    def test_confirm_completed_work_once_the_visit_form_is_in(self):
        handover = self.core_handover()
        # Submitted by the Partner: no Salesforce ID yet — the confirmer
        # enters it in the Verify drawer.
        activity = self.schedule(handover, status="awaiting_ia_verification")
        self._uploaded_visit_form(activity)

        row = self.core_row(self.page(self.cceo_user), handover)

        self.assertIn("data-core-confirm", row)
        self.assertIn(f"/partner-oversight/verify?activity_id={activity.id}", row)
        self.assertNotIn("data-core-withdraw", row)

    def test_before_the_partner_submits_confirm_says_what_it_waits_for(self):
        handover = self.core_handover()
        activity = self.schedule(handover, status="partner_scheduled")
        self._uploaded_visit_form(activity)

        row = self.core_row(self.page(self.cceo_user), handover)

        self.assertIn("data-core-confirm-locked", row)
        self.assertIn("Waiting for the partner to submit it", row)
        self.assertNotIn('hx-get="/partner-oversight/verify', row)

    def test_no_visit_form_no_confirm(self):
        handover = self.core_handover()
        self.schedule(handover, status="awaiting_ia_verification")

        row = self.core_row(self.page(self.cceo_user), handover)

        self.assertNotIn("data-core-confirm", row)

    def test_withdrawing_gives_the_package_its_visit_back(self):
        from apps.partners import withdrawal_service

        handover = self.core_handover()
        withdrawal_service.withdraw(
            handover.id,
            {
                "reason_category": "not_scheduled",
                "partner_facing_reason": "The partner has not scheduled this in time.",
                "disposition": "return_to_planning",
            },
            self.pl_user,
        )

        slot = CoreActivitySlot.objects.get(id=cslot_id("CORE-P1", "v", 2, fy=self.fy))
        self.assertEqual((slot.status, slot.assigned_partner_id), ("Planned", None))
        row = self.core_row(self.page(), handover)
        self.assertNotIn("UGX 55,000", row, "work taken back is priced at nothing")
