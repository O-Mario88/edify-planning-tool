"""A client school's partner work, from handover to confirmation (2026-09-27).

The owner asked for the partner assignment, the partner's scheduling, the
evidence upload and the automatic costing to be inspected for client schools
"and work on it properly". Two defects the walk-through found are pinned here:

* the Partner chose a date without being told what the work pays — the
  Schedule drawer now reads the Cost Catalogue's price for it;
* work the Partner had submitted with its visit form read "Missing Salesforce
  ID" on Partner Monitoring, though a Partner never enters one — the reviewer
  does, in the Verify drawer — so it now reads Verification;
* work delivered on another day than planned stayed dated and costed on the
  planned day; asked, the owner chose "Move to delivery date".

The one-partner-activity-per-school-per-year allowance was also raised; the
owner chose to keep it.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.test_partner_oversight import PartnerOversightFixture
from apps.schools.models import School

User = get_user_model()


def _client_partner_rate(amount: int) -> None:
    catalogue = CostCatalogue.objects.filter(is_active=True).first()
    if catalogue is None:
        catalogue = CostCatalogue.objects.create(
            country="Uganda", fy=get_operational_fy(), version=1, is_active=True
        )
    CostSetting.objects.update_or_create(
        key="client_partner_visit",
        catalogue=catalogue,
        defaults={
            "label": "Client Partner Visit",
            "unit_cost": amount,
            "fy": get_operational_fy(),
            "version": catalogue.version,
        },
    )


class TheScheduleDrawerSaysWhatTheWorkPaysTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Pay Region")
        district = District.objects.create(name="Pay District", region=region)
        self.school = School.objects.create(
            school_id="PAY-1",
            name="Pay Client Primary",
            school_type="client",
            region=region,
            district=district,
        )
        self.partner_user = User.objects.create(
            email="pay-partner@edify.org",
            name="Pay Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            status="active",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            name="Pay Partner", user=self.partner_user, active_status=True
        )
        self.assignment = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="pay-staff",
            expected_activity_type="school_visit_ssa_collection",
            purpose_of_visit="ssa_support",
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
            ),
            status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
        )

    def _drawer(self):
        self.client.force_login(self.partner_user)
        response = self.client.get(
            f"/partner/assignments/{self.assignment.id}/schedule-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        match = re.search(r"data-partner-cost-preview[^>]*>(.*?)</p>", html, re.S)
        self.assertIsNotNone(match, "the drawer names the payment")
        return re.sub(r"<[^>]+>|\s+", " ", match.group(1))

    def test_it_reads_the_client_partner_visit_rate(self):
        _client_partner_rate(42_000)
        self.assertIn("UGX 42,000", self._drawer())


class SubmittedPartnerWorkAwaitsTheReviewerTest(PartnerOversightFixture):
    def test_submitted_with_its_visit_form_it_reads_verification(self):
        assignment = self.assign()
        activity = self.schedule(assignment, status="awaiting_ia_verification")
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="visit-form.pdf",
            uploaded_by="partner-user",
        )
        self.client.force_login(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}"
        ).content.decode()
        start = body.index(f'data-assignment="{assignment.id}"')
        row = body[start : body.index('<tr id="partner-row-details-', start)]

        self.assertNotIn("Missing Salesforce ID", row)
        self.assertIn(">Verification<", row)


class EarlyDeliveryMovesToItsDayTest(TestCase):
    """Owner, 2026-09-27: partner work delivered on another day than planned
    is dated and costed on the day it was delivered ("Move to delivery
    date") — across a fiscal year if that is where the day falls."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        region = Region.objects.create(name="Early Region")
        district = District.objects.create(name="Early District", region=region)
        self.school = School.objects.create(
            school_id="EARLY-1",
            name="Early Client Primary",
            school_type="client",
            region=region,
            district=district,
        )
        self.partner = Partner.objects.create(name="Early Partner", active_status=True)
        _client_partner_rate(40_000)
        self.planned = timezone.localdate() + timedelta(days=9)
        self.delivered = timezone.localdate() - timedelta(days=1)

    def _partner_activity(self, delivery_type="partner"):
        from datetime import datetime, time

        from django.utils import timezone

        from apps.activities.models import Activity
        from apps.activities.services import _apply_schedule_cost_snapshot

        activity = Activity.objects.create(
            activity_type="school_visit_ssa_collection",
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
            ),
            school=self.school,
            fy=get_operational_fy(self.planned),
            quarter="Q1",
            planned_date=self.planned,
            scheduled_date=timezone.make_aware(datetime.combine(self.planned, time(9))),
            status="completion_started",
            delivery_type=delivery_type,
            assigned_partner_id=self.partner.id if delivery_type == "partner" else None,
        )
        _apply_schedule_cost_snapshot(activity, {})
        return activity

    def test_the_visit_its_handover_and_its_cost_move_to_the_delivery_day(self):
        from apps.activities.models import ActivityScheduleCostLine
        from apps.activities.services import _move_partner_work_to_delivery_date

        activity = self._partner_activity()
        handover = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id="early-staff",
            status="partner_scheduled",
            scheduled_date=self.planned,
            scheduled_activity=activity,
        )
        activity.actual_delivery_date = self.delivered
        activity.save(update_fields=["actual_delivery_date"])

        _move_partner_work_to_delivery_date(activity)

        activity.refresh_from_db()
        handover.refresh_from_db()
        self.assertEqual(activity.planned_date, self.delivered)
        self.assertEqual(activity.fy, get_operational_fy(self.delivered))
        self.assertEqual(handover.scheduled_date, self.delivered)
        lines = list(ActivityScheduleCostLine.objects.filter(activity=activity))
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(line.planned_date, self.delivered)
            self.assertEqual(line.fiscal_year, get_operational_fy(self.delivered))
        self.assertEqual(sum(line.amount for line in lines), 40_000)

    def test_staff_work_keeps_its_planned_day(self):
        from apps.activities.services import _move_partner_work_to_delivery_date

        activity = self._partner_activity(delivery_type="staff")
        activity.actual_delivery_date = self.delivered
        activity.save(update_fields=["actual_delivery_date"])

        _move_partner_work_to_delivery_date(activity)

        activity.refresh_from_db()
        self.assertEqual(activity.planned_date, self.planned)
