"""Minimum planning prices, operational approval totals, and weekly payment safety."""

from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.db.models import Sum

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing_service import active_catalogue, apply_to_activity, preview
from apps.budget.models import CostSetting, ActivityCostSnapshot
from apps.budget.services import upsert_cost_setting, budget_workspace
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests.weekly_service import (
    self_funded,
    approve_weekly_request,
    disburse,
    confirm_receipt,
    return_weekly_request,
)
from apps.monthly_work_plan import country_budget_service


class BudgetSpecificationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.frontend.test_budget_advance_workflow import BudgetAdvanceWorkflowTest

        BudgetAdvanceWorkflowTest.setUpTestData.__func__(cls)
        cls.rvp = User.objects.create_user(
            email="rvp@budget-spec.test",
            name="Regional VP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
        )

    def cost(self, **kwargs):
        from apps.frontend.test_budget_advance_workflow import BudgetAdvanceWorkflowTest

        return BudgetAdvanceWorkflowTest.cost(self, **kwargs)

    def request(self):
        from apps.frontend.test_budget_advance_workflow import BudgetAdvanceWorkflowTest

        return BudgetAdvanceWorkflowTest.request(self)

    def configure_training(self):
        card = active_catalogue("2026")
        for key, operational, minimum in (
            ("group_training_participant_meal_cost_per_head", 12000, 3000),
            ("group_training_facilitation_fee", 30000, 5000),
            ("group_training_venue_cost", 40000, 10000),
        ):
            CostSetting.objects.filter(catalogue=card, key=key).update(
                unit_cost=operational, approved_minimum=minimum
            )
        return {
            "fy": "2026",
            "activityType": "training",
            "expectedParticipants": 10,
            "days": 1,
            "deliveryType": "staff",
            "plannedDate": "2026-07-08",
        }

    def planned_training(self):
        payload = self.configure_training()
        act = Activity.objects.create(
            activity_type="training",
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            school=self.school,
            responsible_staff_id=self.owner.id,
            expected_participants=10,
            scheduled_date=timezone.make_aware(datetime(2026, 7, 8, 10)),
            planned_date=date(2026, 7, 8),
        )
        apply_to_activity(act, payload, self.owner.id)
        return act, payload

    def test_minimum_preview_and_operational_funding_use_the_same_planned_quantities(
        self,
    ):
        act, payload = self.planned_training()
        minimal = preview(payload, minimum=True)
        self.assertEqual(minimal["amount"], 45000)
        self.assertFalse(minimal["costMissing"])
        self.assertNotIn("operationalCost", minimal)
        self.assertEqual(
            ActivityScheduleCostLine.objects.filter(activity=act).aggregate(
                total=Sum("amount")
            )["total"],
            190000,
        )
        wfr = self.request()
        self.assertEqual(wfr.total_amount, 190000)
        for period in ("month", "quarter", "fy"):
            self.assertEqual(
                budget_workspace(
                    self.cd,
                    {
                        "period": period,
                        "fy": "2026",
                        "date": "2026-07-08",
                        "budget_scope": "country",
                        "plan_only": True,
                    },
                )["total"],
                190000,
            )
        # A larger regional benchmark is metadata, never a top-up to this request.
        ActivityCostSnapshot.objects.filter(activity=act).update(reference_cost=900000)
        ctx = country_budget_service.get_country_monthly_budget(
            self.cd, {"fy": "2026", "month": 7}
        )
        submitted = country_budget_service.send_to_rvp(self.cd, ctx["budget_id"])
        snapshot = submitted.snapshots.get(version=submitted.submission_version)
        self.assertEqual(submitted.total_amount, 190000)
        self.assertEqual(snapshot.total_amount, 190000)
        self.assertEqual(snapshot.strategic_reserve_requested, 0)
        self.assertEqual(sum(line["amount"] for line in snapshot.line_items), 190000)
        country_budget_service.approve(self.rvp, submitted.id)

    def test_unset_minimum_is_not_replaced_by_an_operational_price(self):
        payload = self.configure_training()
        CostSetting.objects.filter(
            catalogue=active_catalogue("2026"), key="group_training_facilitation_fee"
        ).update(approved_minimum=None)
        result = preview(payload, minimum=True)
        self.assertTrue(result["costMissing"])
        self.assertIn("group_training_facilitation_fee", result["missingItems"])
        self.assertTrue(
            any("minimum viable" in blocker for blocker in result["blockers"])
        )

    def test_cd_edits_both_rates_and_preserves_previous_published_version(self):
        payload = self.configure_training()
        old = active_catalogue("2026")
        key = "group_training_participant_meal_cost_per_head"
        upsert_cost_setting(
            {
                "key": key,
                "unitCost": 14000,
                "approvedMinimum": 4000,
                "fy": "2026",
                "reason": "Updated approved meal allowances",
            },
            self.cd,
        )
        self.assertEqual(
            CostSetting.objects.get(catalogue=old, key=key).approved_minimum, 3000
        )
        rate = CostSetting.objects.get(catalogue=active_catalogue("2026"), key=key)
        self.assertEqual((rate.unit_cost, rate.approved_minimum), (14000, 4000))
        self.assertEqual(preview(payload, minimum=True)["amount"], 55000)
        with self.assertRaises(BadRequest):
            upsert_cost_setting(
                {
                    "key": key,
                    "unitCost": 3000,
                    "approvedMinimum": 4000,
                    "reason": "Invalid floor",
                },
                self.cd,
            )
        with self.assertRaises(Forbidden):
            upsert_cost_setting(
                {"key": key, "unitCost": 14000, "reason": "Not the CD"}, self.owner
            )

    def test_cost_settings_form_has_two_prices_and_saves_minimum(self):
        self.configure_training()
        self.client.force_login(self.cd)
        key = "group_training_participant_meal_cost_per_head"
        response = self.client.get("/cost-settings")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Regional standard (UGX)")
        response = self.client.get(f"/cost-settings/row/{key}?mode=edit")
        self.assertContains(response, 'name="approved_minimum"')
        response = self.client.post(
            f"/cost-settings/row/{key}",
            {
                "unit_cost": "13000",
                "approved_minimum": "3500",
                "reason": "Updated approved prices",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CostSetting.objects.get(
                catalogue=active_catalogue("2026"), key=key
            ).approved_minimum,
            3500,
        )
        response = self.client.post(
            f"/cost-settings/row/{key}",
            {
                "unit_cost": "13000",
                "approved_minimum": "-1",
                "reason": "Invalid amount",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")

        invalid_cost = "<script>alert('private input')</script>"
        response = self.client.post(
            f"/cost-settings/row/{key}",
            {
                "unit_cost": invalid_cost,
                "approved_minimum": "3500",
                "reason": "Invalid number",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Enter a valid whole-number cost.")
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertNotIn(invalid_cost, response.content.decode())

    def test_self_fund_follows_approval_disbursement_and_bank_confirmation(self):
        self.cost()
        wfr = self.request()
        with patch(
            "apps.fund_requests.weekly_service._notify_weekly_approver"
        ) as notify:
            self_funded(wfr.id, self.owner)
            notify.assert_called_once()
        wfr.refresh_from_db()
        self.assertEqual(
            (wfr.status, wfr.funding_source, wfr.total_amount),
            ("submitted_to_pl", "self_fund", 600000),
        )
        with self.assertRaises(BadRequest):
            self_funded(wfr.id, self.owner)
        with self.assertRaises(BadRequest):
            disburse(wfr.id, {}, self.accountant)
        approve_weekly_request(wfr.id, self.pl)
        with patch("apps.fund_requests.weekly_service._notify_weekly_owner") as notify:
            disburse(wfr.id, {}, self.accountant)
            self.assertEqual(notify.call_args.args[1], "weekly_fund_request_disbursed")
        with self.assertRaises(BadRequest):
            confirm_receipt(wfr.id, self.owner)
        confirm_receipt(wfr.id, self.owner, bank_message_received=True)
        wfr.refresh_from_db()
        self.assertEqual(wfr.disbursed_amount, 600000)
        self.assertIsNotNone(wfr.receipt_confirmed_at)
        with self.assertRaises(BadRequest):
            disburse(wfr.id, {}, self.accountant)

    def test_self_fund_return_requires_plan_correction_and_resubmission(self):
        line = self.cost()
        wfr = self.request()
        self_funded(wfr.id, self.owner)
        with self.assertRaises(Forbidden):
            approve_weekly_request(wfr.id, self.outsider)
        return_weekly_request(
            wfr.id, {"reason": "Correct attendance in your plan"}, self.pl
        )
        ActivityScheduleCostLine.objects.filter(pk=line.pk).update(
            amount=500000, unit_cost=10000
        )
        self.request()
        self_funded(wfr.id, self.owner)
        wfr.refresh_from_db()
        self.assertEqual((wfr.status, wfr.total_amount), ("submitted_to_pl", 500000))

    def test_unified_budget_periods_scopes_and_legacy_bookmarks(self):
        self.cost()
        self.cost(owner=self.pl, amount=100000)
        self.cost(owner=self.outsider, amount=900000)
        for user, expected in (
            (self.owner, 600000),
            (self.pl, 700000),
            (self.cd, 1600000),
            (self.rvp, 1600000),
        ):
            self.client.force_login(user)
            for period in ("month", "quarter", "fy"):
                response = self.client.get(
                    "/budget", {"fy": "2026", "date": "2026-07-08", "period": period}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["total"], expected)
                for label in ("Monthly Budget", "Quarterly Budget", "Annual Budget"):
                    self.assertContains(response, label)
                self.assertContains(response, "Staff cost")
                self.assertNotContains(response, "Regional Standard Funding Ceiling")
        self.client.force_login(self.pl)
        response = self.client.get(
            "/budget", {"fy": "2026", "date": "2026-07-08", "budget_scope": "my"}
        )
        self.assertEqual(response.context["total"], 100000)
        for url in ("/budgets/monthly", "/accounts/monthly-request/"):
            response = self.client.get(url, {"fy": "2026", "month": "July"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith("/budget?"))
            self.assertIn("month=July", response.url)

    def test_owner_budget_keeps_imported_lines_with_activity_ownership(self):
        line = self.cost()
        ActivityScheduleCostLine.objects.filter(pk=line.pk).update(
            responsible_user=None
        )
        self.cost(owner=self.outsider, amount=900000)
        result = budget_workspace(
            self.owner, {"fy": "2026", "date": "2026-07-08", "period": "month"}
        )
        self.assertEqual(result["total"], 600000)

    def test_minimum_estimate_preserves_shared_cost_splits_and_zero_rates(self):
        act, payload = self.planned_training()
        snapshot = ActivityCostSnapshot.objects.get(activity=act, is_current=True)
        snapshot.operational_breakdown = [
            {
                "key": "group_training_facilitation_fee",
                "unit": 30000,
                "amount": 15000,
                "qty": 1,
                "missing": False,
            }
        ]
        snapshot.save(update_fields=["operational_breakdown"])
        from apps.budget.costing_service import planned_minimum_amounts

        self.assertEqual(planned_minimum_amounts([act])[act.id], 2500)
        CostSetting.objects.filter(
            catalogue=snapshot.operational_rate_card,
            key="group_training_facilitation_fee",
        ).update(approved_minimum=0)
        self.assertEqual(planned_minimum_amounts([act])[act.id], 0)

    def test_old_weekly_budget_link_keeps_the_selected_week_month(self):
        self.cost()
        self.client.force_login(self.owner)
        response = self.client.get(
            "/fund-requests/weekly",
            {"fy": "2026", "week": "2026-07-06", "period_tab": "month"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["anchor"], date(2026, 7, 6))
        self.assertEqual(response.context["total"], 600000)

    def test_team_budget_includes_monitored_partner_work_without_widening_access(self):
        monitored = self.cost(owner=self.outsider, amount=50000)
        Activity.objects.filter(pk=monitored.activity_id).update(
            delivery_type="partner", monitored_by_staff_id=self.profiles["owner"].id
        )
        self.cost(owner=self.outsider, amount=900000)
        query = {
            "fy": "2026",
            "date": "2026-07-08",
            "period": "month",
            "budget_scope": "team",
        }
        self.assertEqual(budget_workspace(self.pl, query)["total"], 50000)
        self.assertEqual(
            budget_workspace(self.pl, {**query, "exclude_partner": True})["total"], 0
        )
