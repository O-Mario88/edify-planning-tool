"""Plan-derived ledgers and the owner → supervisor → accountant → owner workflow."""

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.services import budget_workspace, weekly_request_budget
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests.weekly_service import (
    approve_weekly_request,
    confirm_receipt,
    disburse,
    generate_weekly_fund_request,
    request_advance,
    return_weekly_request,
)
from apps.geography.models import District, Region
from apps.schools.models import School


class BudgetAdvanceWorkflowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Budget QA Region")
        district = District.objects.create(name="Budget QA District", region=region)
        cls.school = School.objects.create(
            school_id="BUD-QA",
            name="Budget QA School",
            region=region,
            district=district,
        )
        cls.profiles = {}
        for key, name, role in (
            ("owner", "Alice Requester", "CCEO"),
            ("pl", "Paul Supervisor", "Program Lead"),
            ("outsider", "Una Other Team", "Program Lead"),
            ("cd", "Diana Director", "CountryDirector"),
            ("accountant", "Alex Accountant", "Accountant"),
        ):
            person = User.objects.create_user(
                email=f"{key}@budget-qa.example",
                name=name,
                roles=[role],
                active_role=role,
                password="test-only",
            )
            setattr(cls, key, person)
            cls.profiles[key] = StaffProfile.objects.create(user=person, title=role)
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.profiles["pl"], supervisee=cls.profiles["owner"]
        )
        cls.week = date(2026, 7, 6)

    def cost(self, day=None, amount=600_000, owner=None, status="scheduled"):
        day = day or self.week + timedelta(days=2)
        owner = owner or self.owner
        activity = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            status=status,
            fy="2026",
            school=self.school,
            responsible_staff_id=owner.id,
            scheduled_date=day,
            planned_date=day,
            expected_participants=50,
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="group_training_participant_meal_cost_per_head",
            line_item_type="participant_meals",
            label="Participant meals",
            quantity=50,
            unit_cost=amount // 50,
            amount=amount,
            planned_date=day,
            month=day.month,
            fiscal_year="2026",
            responsible_user=owner.id,
        )

        from apps.fund_requests.advance_service import sync_for_activity

        sync_for_activity(activity, owner.id)
        return line

    def request(self, owner=None):
        owner = owner or self.owner
        return generate_weekly_fund_request(owner.id, self.week.isoformat())

    def page(self, user, wfr, **query):
        self.client.force_login(user)
        return self.client.get(
            "/fund-requests/weekly",
            {
                "fy": "2026",
                "week": self.week.isoformat(),
                "staff": wfr.responsible_user,
                "period_tab": "week",
                **query,
            },
        )

    def test_horizons_sum_only_the_planned_dates_in_their_period(self):
        self.cost(amount=600_000)
        self.cost(day=date(2026, 7, 20), amount=200_000)
        self.cost(day=date(2026, 8, 10), amount=300_000)
        self.cost(day=date(2026, 4, 6), amount=100_000)
        self.cost(amount=900_000, status="cancelled")
        expected = {
            "week": 600_000,
            "month": 800_000,
            "quarter": 1_100_000,
            "fy": 1_200_000,
        }
        for period, total in expected.items():
            with self.subTest(period=period):
                budget = budget_workspace(
                    self.owner, {"fy": "2026", "date": "2026-07-08", "period": period}
                )
                self.assertEqual(budget["total"], total)
        wfr = self.request()
        self.assertEqual(wfr.total_amount, 600_000)

    def test_reviewer_sees_snapshot_until_return_and_plan_resubmission(self):
        line = self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        ActivityScheduleCostLine.objects.filter(pk=line.pk).update(
            amount=700_000, unit_cost=14_000
        )
        budget = weekly_request_budget(wfr)
        self.assertEqual(budget["total"], 600_000)
        self.assertEqual(budget["groups"][0]["rows"][0]["rate"], 12_000)
        return_weekly_request(
            wfr.id, {"reason": "Correct the participant allowance."}, self.pl
        )
        wfr = self.request()
        self.assertEqual(wfr.total_amount, 700_000)
        self.assertEqual(wfr.return_reason, "Correct the participant allowance.")
        request_advance(wfr.id, self.owner)
        self.assertEqual(weekly_request_budget(wfr)["total"], 700_000)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "submitted_to_pl")

    def test_approval_disbursement_and_bank_message_receipt(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        with self.assertRaises(BadRequest):
            disburse(wfr.id, {}, self.accountant)
        approve_weekly_request(wfr.id, self.pl)
        disburse(
            wfr.id,
            {"amount": 600_000, "method": "bank_transfer", "reference": "QA-only"},
            self.accountant,
        )
        with self.assertRaises(BadRequest):
            confirm_receipt(wfr.id, self.owner)
        # A broad country scope must never grant authority to attest receipt.
        self.cd.country_scope = True
        with self.assertRaises(Forbidden):
            confirm_receipt(wfr.id, self.cd, bank_message_received=True)
        wfr.refresh_from_db()
        self.assertIsNone(wfr.receipt_confirmed_at)
        confirm_receipt(wfr.id, self.owner, bank_message_received=True)
        wfr.refresh_from_db()
        stamp = wfr.receipt_confirmed_at
        self.assertIsNotNone(stamp)
        confirm_receipt(wfr.id, self.owner, bank_message_received=True)
        wfr.refresh_from_db()
        self.assertEqual(wfr.receipt_confirmed_at, stamp)
        with self.assertRaises(BadRequest):
            return_weekly_request(wfr.id, {"reason": "Too late"}, self.accountant)

    def test_accountant_return_requires_reason_and_restarts_supervisor_approval(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        approve_weekly_request(wfr.id, self.pl)
        for reason in ("", "  ", "x" * 501):
            with self.assertRaises(BadRequest):
                return_weekly_request(wfr.id, {"reason": reason}, self.accountant)
        with self.assertRaises(Forbidden):
            return_weekly_request(
                wfr.id, {"reason": "Cannot bypass accountant"}, self.pl
            )
        return_weekly_request(
            wfr.id, {"reason": "Please correct the allowance."}, self.accountant
        )
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "returned_by_accountant")
        self.assertEqual(wfr.returned_by_user_id, self.accountant.id)
        self.assertIsNotNone(wfr.returned_at)
        request_advance(wfr.id, self.owner)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "submitted_to_pl")
        with self.assertRaises(BadRequest):
            disburse(wfr.id, {}, self.accountant)

    def test_named_tabs_scope_and_matching_six_column_ledger(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        for reviewer in (self.pl, self.cd, self.accountant):
            response = self.page(reviewer, wfr)
            self.assertContains(response, 'aria-label="Team member requests"')
            self.assertContains(response, "Alice Requester")
            self.assertContains(response, "Staff cost")
            self.assertContains(response, "UGX 600,000")
            self.assertContains(response, 'href="/budget"')
        self.assertNotContains(response, 'aria-label="Budget period"')
        self.assertContains(self.page(self.pl, wfr), "Approve")
        self.assertNotContains(self.page(self.outsider, wfr), "UGX 600,000")
        self.assertNotContains(
            self.page(self.outsider, wfr), f"/weekly/{wfr.id}/approve?"
        )

    def test_return_drawer_and_reason_remain_visible_to_owner(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        self.client.force_login(self.pl)
        url = f"/fund-requests/weekly/{wfr.id}/return"
        response = self.client.get(url + "-drawer")
        self.assertContains(response, 'name="reason" required maxlength="500"')
        self.assertContains(response, 'role="dialog"')
        response = self.client.post(url, {"reason": "  "}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "A return reason is required.")
        response = self.client.post(
            url + "?fy=2026&week=2026-07-06&staff=" + self.owner.id,
            {"reason": "Use the planned attendance."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        self.assertContains(self.page(self.owner, wfr), "Use the planned attendance.")
        self.assertNotContains(self.page(self.pl, wfr), "Send for Approval")

    def test_return_regular_form_redirects_to_the_internal_request(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        self.client.force_login(self.pl)
        response = self.client.post(
            f"/fund-requests/weekly/{wfr.id}/return?next=https://example.org/",
            {"reason": "Correct the attendance."},
        )
        self.assertRedirects(
            response, f"/fund-requests/weekly/{wfr.id}", fetch_redirect_response=False
        )
        wfr.refresh_from_db()
        self.assertEqual(wfr.return_reason, "Correct the attendance.")

    def test_receipt_http_requires_checkbox_and_only_owner_sees_control(self):
        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {}, self.accountant)
        self.assertNotContains(
            self.page(self.accountant, wfr), 'name="bank_message_received"'
        )
        self.assertContains(self.page(self.owner, wfr), 'name="bank_message_received"')
        url = f"/fund-requests/weekly/{wfr.id}/confirm-receipt?fy=2026&week=2026-07-06"
        self.client.post(url, {}, HTTP_HX_REQUEST="true")
        wfr.refresh_from_db()
        self.assertIsNone(wfr.receipt_confirmed_at)
        self.client.post(url, {"bank_message_received": "yes"}, HTTP_HX_REQUEST="true")
        wfr.refresh_from_db()
        self.assertIsNotNone(wfr.receipt_confirmed_at)

    def test_pl_month_quarter_and_annual_stay_on_one_page(self):
        self.cost()
        self.client.force_login(self.pl)
        for period in ("month", "quarter", "fy"):
            response = self.client.get(
                "/budget",
                {"fy": "2026", "month": 7, "period": period},
            )
            self.assertContains(response, 'aria-label="Budget period"')
            self.assertContains(response, "Staff cost")
            self.assertContains(response, "UGX 600,000")
            self.assertContains(response, "Annual Budget")

    def test_api_receipt_rejects_missing_or_string_acknowledgement(self):
        from rest_framework.test import APIClient

        self.cost()
        wfr = self.request()
        request_advance(wfr.id, self.owner)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {}, self.accountant)
        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/fund-requests/weekly/{wfr.id}/confirm-receipt"
        for data in (
            {},
            {"bankMessageReceived": "true"},
            {"bankMessageReceived": False},
        ):
            self.assertEqual(client.post(url, data, format="json").status_code, 400)
        client.force_authenticate(self.accountant)
        self.assertEqual(
            client.post(url, {"bankMessageReceived": True}, format="json").status_code,
            403,
        )
        client.force_authenticate(self.owner)
        self.assertEqual(
            client.post(url, {"bankMessageReceived": True}, format="json").status_code,
            200,
        )

    def test_selected_staff_carries_through_filters_and_request_totals(self):
        self.cost()
        self.cost(owner=self.pl, amount=120_000)
        wfr = self.request()
        self.request(owner=self.pl)
        response = self.page(self.pl, wfr)
        self.assertContains(response, f'value="{self.owner.id}" selected')
        self.assertNotContains(response, self.outsider.name)
        self.assertEqual(response.context["breakdown"]["week"]["total"], 600_000)
        self.assertEqual(response.context["breakdown"]["fy"]["total"], 600_000)
