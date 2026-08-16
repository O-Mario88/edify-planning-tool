"""Planning IS the budget writer — the front half of the money chain, live.

test_planned_budget_to_disbursement proves the back half (budget line →
approval → disbursement queue) but starts from a hand-built cost line, and the
scheduling-permission suites deliberately patch the cost snapshot out. Nothing
proved, in one test, the promise the platform is built on: scheduling an
activity through the real Planning entry point FETCHES its price from the CD
Cost Catalogue and automatically populates every budget surface — cost lines
with provenance, the advance ledger, the weekly request, the monthly draft,
and the budget rollup. This test is that proof (2026-08-12 audit follow-up).
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activity_catalogue.services import resolve_item_for_workflow_kind
from apps.budget.models import CostCatalogue, CostSetting
from apps.budget.services import get_budget_rollup
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import (
    AdvanceRequest,
    FundRequest,
    WeeklyFundRequest,
)
from apps.geography.models import District, Region
from apps.schools.models import School

TRANSPORT = 30_000
LUNCH = 15_000
DAY_POOL = TRANSPORT + LUNCH


def _schedulable_date():
    """The next date the calendar policy will accept (Sundays are blocked)."""
    day = timezone.localdate() + datetime.timedelta(days=3)
    while day.weekday() == 6:
        day += datetime.timedelta(days=1)
    return day


def _at(day):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(9)),
        timezone.get_current_timezone(),
    )


class PlanningPopulatesTheBudgetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="E2E Budget Region")
        cls.district = District.objects.create(
            name="E2E Budget District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-E2E-BUDGET",
            name="E2E Budget Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.user = User.objects.create_user(
            email="e2e-budget-cceo@edify.org",
            name="E2E Budget CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, staff_number="ST-E2E-B", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=cls.school.id)

        # The CD's rate card — the ONLY place a price may come from. The
        # post_migrate reference seed already publishes an active catalogue,
        # so pin OUR rates onto it rather than fighting its unique keys.
        cls.day = _schedulable_date()
        cls.fy = get_operational_fy(cls.day)
        cls.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy=cls.fy,
            is_active=True,
            defaults={"version": 1},
        )
        for key, cost in (
            ("primary_transport_per_day", TRANSPORT),
            ("primary_lunch_per_day", LUNCH),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "fy": cls.fy,
                    "catalogue": cls.catalogue,
                },
            )

    def test_scheduling_fetches_the_cost_and_populates_every_budget_surface(self):
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        self.assertIsNotNone(item, "the seeded catalogue must cost a school visit")

        result = schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "E2E budget-population proof",
            },
            self.user,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.status, "scheduled")

        # 1. The price was FETCHED from the catalogue, never typed by anyone:
        #    a sole primary-district visit carries the full day pool.
        lines = list(ActivityScheduleCostLine.objects.filter(activity=activity))
        self.assertTrue(lines, "scheduling must write budget lines")
        self.assertEqual(sum(line.amount for line in lines), DAY_POOL)
        activity.refresh_from_db()
        self.assertEqual(activity.est_cost_cents, DAY_POOL)
        self.assertFalse(activity.cost_missing)
        for line in lines:
            self.assertEqual(
                line.catalogue_id, self.catalogue.id, line.cost_setting_key
            )
            self.assertEqual(line.currency, "UGX")
            self.assertEqual(line.responsible_user, self.user.id)

        # 2. The advance ledger mirrors the lines, awaiting the owner's choice.
        advances = AdvanceRequest.objects.filter(activity=activity)
        self.assertEqual(advances.count(), len(lines))
        self.assertEqual(
            set(advances.values_list("status", flat=True)),
            {"pending_responsible_confirmation"},
        )
        self.assertEqual(sum(advances.values_list("amount", flat=True)), DAY_POOL)

        # 3. The weekly fund request auto-generated from the same lines.
        week_start = self.day - datetime.timedelta(days=self.day.weekday())
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.user.id, week_start_date=week_start
        )
        self.assertEqual(wfr.status, "pending_responsible_confirmation")
        self.assertEqual(wfr.total_amount, DAY_POOL)
        self.assertEqual(wfr.lines.count(), len(lines))

        # 4. The monthly draft fund request auto-generated too.
        monthly = FundRequest.objects.get(
            submitted_by_user_id=self.user.id,
            period="monthly",
            period_key=f"{self.fy}-M{self.day.month}",
            scope="own",
        )
        self.assertEqual(monthly.status, "draft")
        self.assertEqual(monthly.total_amount, DAY_POOL)
        self.assertEqual(
            set(monthly.items.values_list("activity_schedule_cost_line_id", flat=True)),
            {line.id for line in lines},
        )

        # 5. And the budget rollup reports it as planned spend.
        rollup = get_budget_rollup(self.fy)
        self.assertGreaterEqual(rollup["planned"], DAY_POOL)
        self.assertGreaterEqual(rollup["activity_count"], 1)


class WeeklyAdvanceCompilesThePlanTest(TestCase):
    """The workflow as stated: all of a week's planned work and its costs
    compile into ONE weekly advance request, the owner sends it, the
    supervisor approves it, and the Accountant disburses it."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Weekly Compile Region")
        cls.district = District.objects.create(
            name="Weekly Compile District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-WK-COMPILE",
            name="Weekly Compile Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

        def _person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"ST-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("wk-cceo@edify.org", "Wk CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("wk-pl@edify.org", "Wk PL", "Program Lead")
        cls.accountant, _ = _person("wk-acct@edify.org", "Wk Acct", "Accountant")
        from apps.accounts.models import StaffSupervisorAssignment

        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

        # Two schedulable days in the SAME week (skip Sunday; stay in-week).
        first = _schedulable_date()
        while first.weekday() >= 4:  # land on Mon–Thu so day+1 stays in-week
            first += datetime.timedelta(days=1)
        cls.day_one = first
        cls.day_two = first + datetime.timedelta(days=1)
        cls.fy = get_operational_fy(cls.day_one)
        cls.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy=cls.fy, is_active=True, defaults={"version": 1}
        )
        for key, cost in (
            ("primary_transport_per_day", TRANSPORT),
            ("primary_lunch_per_day", LUNCH),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "fy": cls.fy,
                    "catalogue": cls.catalogue,
                },
            )

    def test_the_week_compiles_routes_approves_and_disburses_as_one(self):
        from apps.planning.services import schedule_school_visit
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            disburse,
            request_advance,
        )

        item = resolve_item_for_workflow_kind("school_visit")
        for day in (self.day_one, self.day_two):
            schedule_school_visit(
                {
                    "schoolId": self.school.school_id,
                    "catalogueItemId": item.id,
                    "scheduledDate": _at(day).isoformat(),
                    "activityPurposeText": f"Weekly compile proof {day}",
                },
                self.cceo,
            )

        # 1. ONE weekly request compiles the whole week's plan and costs.
        week_start = self.day_one - datetime.timedelta(days=self.day_one.weekday())
        requests = WeeklyFundRequest.objects.filter(responsible_user=self.cceo.id)
        self.assertEqual(requests.count(), 1)
        wfr = requests.get()
        self.assertEqual(wfr.week_start_date, week_start)
        self.assertEqual(wfr.total_amount, 2 * DAY_POOL)  # two visit days

        # 2. The owner sends it; a CCEO's request routes to their PL.
        request_advance(wfr.id, self.cceo)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "submitted_to_pl")

        # 3. The supervisor approves; it enters the Accountant's queue.
        approve_weekly_request(wfr.id, self.pl)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")

        # 4. The Accountant disburses the WEEK as one payment; every line's
        #    ledger row settles underneath, summing exactly to the total.
        disburse(wfr.id, {"method": "Bank", "reference": "WK-1"}, self.accountant)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "disbursed")
        advances = AdvanceRequest.objects.filter(
            budget_line__weekly_request_lines__weekly_fund_request=wfr
        )
        self.assertEqual(set(advances.values_list("status", flat=True)), {"disbursed"})
        self.assertEqual(
            sum(advances.values_list("disbursed_amount", flat=True)),
            wfr.total_amount,
        )

    def test_disbursement_receipt_accountability_and_ia_gated_close(self):
        """The full post-disbursement lifecycle as mandated:

        Accountant disburses → the OWNER confirms the funds arrived (nothing
        can be accounted before that) → accountability runs per advance →
        clearance is refused until IA has confirmed the activity's data →
        once every advance is cleared, the week itself closes (accounted)."""
        from apps.core.exceptions import BadRequest
        from apps.fund_requests import advance_service
        from apps.fund_requests.disbursement_dashboard_service import (
            roll_up_accountability,
        )
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            confirm_receipt,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        for day in (self.day_one, self.day_two):
            schedule_school_visit(
                {
                    "schoolId": self.school.school_id,
                    "catalogueItemId": item.id,
                    "scheduledDate": _at(day).isoformat(),
                    "activityPurposeText": f"Lifecycle proof {day}",
                },
                self.cceo,
            )
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "WK-2"}, self.accountant)

        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).select_related("activity")
        )
        self.assertTrue(advances)

        # 1. Accountability is CLOSED until the owner confirms receipt.
        with self.assertRaisesMessage(BadRequest, "Confirm receipt"):
            advance_service.submit_accountability(
                advances[0].id,
                {"amountSpent": advances[0].disbursed_amount, "netsuiteId": "NS-0"},
                self.cceo,
            )

        # 2. The owner confirms the funds arrived — accountability opens, and
        #    each submission routes to the PL first (never straight to the
        #    Accountant).
        confirm_receipt(wfr.id, self.cceo)
        wfr.refresh_from_db()
        self.assertIsNotNone(wfr.receipt_confirmed_at)
        for index, adv in enumerate(advances):
            advance_service.submit_accountability(
                adv.id,
                {
                    "amountSpent": adv.disbursed_amount,
                    "amountReturned": 0,
                    "netsuiteId": f"NS-{index}",
                },
                self.cceo,
            )
            adv.refresh_from_db()
            self.assertEqual(adv.status, "accountability_pl_pending")

        # 2b. The Accountant cannot act before the PL confirms the money is
        #     accounted for; the owner cannot approve their own; the PL can.
        with self.assertRaisesMessage(BadRequest, "not pending accountability"):
            advance_service.approve_accountability(advances[0].id, self.accountant)
        from apps.core.exceptions import Forbidden

        with self.assertRaises(Forbidden):
            advance_service.pl_approve_accountability(advances[0].id, self.cceo)
        for adv in advances:
            advance_service.pl_approve_accountability(adv.id, self.pl)
            adv.refresh_from_db()
            self.assertEqual(adv.status, "accountability_pending")
            self.assertEqual(adv.accountability_pl_approved_by, self.pl.id)

        # 3. Clearance is refused until IA confirms the activity's data.
        with self.assertRaisesMessage(BadRequest, "IA has not verified"):
            advance_service.approve_accountability(advances[0].id, self.accountant)

        for adv in advances:
            adv.activity.ia_verification_status = "confirmed"
            adv.activity.save(update_fields=["ia_verification_status", "updated_at"])

        # 4. With IA confirmed, every advance clears…
        for adv in advances:
            advance_service.approve_accountability(adv.id, self.accountant)
            adv.refresh_from_db()
            self.assertEqual(adv.status, "accounted")

        # 5. …and only then does the WEEK itself close.
        self.assertTrue(roll_up_accountability(wfr, advances))
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "accounted")
        self.assertEqual(wfr.accounted_amount, wfr.total_amount)

    def test_self_funded_week_reimburses_through_pl_ia_and_accountant(self):
        """The self-funded workflow as mandated: staff used their own money →
        at accountability they enter the amount used + NetSuite ID, which
        triggers the reimbursement claim → the PL confirms the money is
        accounted for → the Accountant reimburses only after IA confirms the
        work was done → the staff confirms the money arrived → week closes."""
        from apps.core.exceptions import BadRequest, Forbidden
        from apps.fund_requests import advance_service
        from apps.fund_requests.disbursement_dashboard_service import (
            roll_up_accountability,
        )
        from apps.fund_requests.weekly_service import self_funded
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        for day in (self.day_one, self.day_two):
            schedule_school_visit(
                {
                    "schoolId": self.school.school_id,
                    "catalogueItemId": item.id,
                    "scheduledDate": _at(day).isoformat(),
                    "activityPurposeText": f"Self-funded proof {day}",
                },
                self.cceo,
            )
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)

        # The owner elects to use their own money for the week.
        self_funded(wfr.id, self.cceo)
        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).select_related("activity")
        )
        self.assertTrue(advances)
        self.assertEqual(
            {a.status for a in advances}, {"self_funded_pending_reimbursement"}
        )

        # 1. At accountability, the amount used + NetSuite ID trigger the
        #    reimbursement claim — which goes to the PL, not the Accountant.
        for index, adv in enumerate(advances):
            advance_service.submit_reimbursement(
                adv.id,
                {"amountSpent": adv.amount, "netsuiteId": f"NS-SF-{index}"},
                self.cceo,
            )
            adv.refresh_from_db()
            self.assertEqual(adv.status, "reimbursement_pl_pending")

        # 2. The Accountant cannot pay an unapproved claim; the owner cannot
        #    approve their own; the PL's approval routes it to the Accountant.
        with self.assertRaisesMessage(BadRequest, "submitted reimbursement claim"):
            advance_service.reimburse(advances[0].id, {}, self.accountant)
        with self.assertRaises(Forbidden):
            advance_service.pl_approve_accountability(advances[0].id, self.cceo)
        for adv in advances:
            advance_service.pl_approve_accountability(adv.id, self.pl)
            adv.refresh_from_db()
            self.assertEqual(adv.status, "reimbursement_submitted")

        # 3. Even approved, money moves only after IA confirms the work.
        with self.assertRaisesMessage(BadRequest, "IA has not verified"):
            advance_service.reimburse(advances[0].id, {}, self.accountant)
        for adv in advances:
            adv.activity.ia_verification_status = "confirmed"
            adv.activity.save(update_fields=["ia_verification_status", "updated_at"])

        # 4. The Accountant reimburses; the staff member confirms the money
        #    actually arrived — only that receipt makes it financially cleared.
        for adv in advances:
            advance_service.reimburse(
                adv.id, {"method": "Bank", "reference": "RB-1"}, self.accountant
            )
            adv.refresh_from_db()
            self.assertEqual(adv.status, "reimbursement_disbursed")
            self.assertEqual(adv.reimbursed_amount, adv.accounted_amount)
            advance_service.confirm_reimbursement_receipt(adv.id, {}, self.cceo)
            adv.refresh_from_db()
            self.assertEqual(adv.status, "reimbursed")

        # 5. With every claim settled, the week itself closes.
        self.assertTrue(roll_up_accountability(wfr, advances))
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "accounted")

    def test_pl_sees_and_approves_accountability_on_the_weekly_page(self):
        """Rendered-DOM contract: when a supervised CCEO's disbursed week has
        accountability awaiting PL approval, the PL's weekly page shows the
        approval block, and posting the approve action moves the claim to the
        Accountant."""
        from apps.fund_requests import advance_service
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            confirm_receipt,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day_one).isoformat(),
                "activityPurposeText": "PL approval page proof",
            },
            self.cceo,
        )
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "WK-UI"}, self.accountant)
        confirm_receipt(wfr.id, self.cceo)
        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            )
        )
        for index, adv in enumerate(advances):
            advance_service.submit_accountability(
                adv.id,
                {"amountSpent": adv.disbursed_amount, "netsuiteId": f"NS-UI-{index}"},
                self.cceo,
            )

        self.client.force_login(self.pl)
        week_param = wfr.week_start_date.isoformat()
        page = self.client.get(
            f"/fund-requests/weekly?week={week_param}&staff={self.cceo.id}"
        )
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("Fund accountability awaiting your approval", html)
        self.assertIn(f"/fund-requests/advances/{advances[0].id}/pl-approve", html)

        resp = self.client.post(
            f"/fund-requests/advances/{advances[0].id}/pl-approve?week={week_param}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        advances[0].refresh_from_db()
        self.assertEqual(advances[0].status, "accountability_pending")
