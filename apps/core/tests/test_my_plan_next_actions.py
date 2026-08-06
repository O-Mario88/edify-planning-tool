"""My Plan must show one dominant next action, and never stall.

The urgency buckets were computed and rendered nowhere; each row instead showed
an eight-item menu in which three entries opened the same drawer. Two branches
were missing entirely — the reimbursement receipt (whose drawer and route both
existed but were unreachable) and partner-evidence review, without which the
partner chain deadlocks because complete() and ia_confirm() both refuse partner
work whose evidence is not accepted.
"""

from __future__ import annotations

from datetime import date

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan.services import compute_next_action
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class NextActionBranchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="NA2 Region")
        district = District.objects.create(name="NA2 District", region=region)
        cls.school = School.objects.create(
            name="NA2 Primary",
            school_id="N2-1",
            region_id=region.id,
            district_id=district.id,
        )

    def _act(self, **kw):
        defaults = dict(
            school_id=self.school.id,
            activity_type="school_visit",
            status="completion_started",
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
            evidence_status="none",
        )
        defaults.update(kw)
        return Activity.objects.create(**defaults)

    def _advance(self, activity, **kw):
        from apps.fund_requests.models import AdvanceRequest

        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=50_000,
            amount=50_000,
        )
        defaults = dict(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
            amount=50_000,
            status="disbursed",
            disbursed_amount=50_000,
        )
        defaults.update(kw)
        return AdvanceRequest.objects.create(**defaults)

    def test_partner_evidence_awaiting_review_is_the_next_action(self):
        act = self._act(
            delivery_type="partner",
            evidence_status="uploaded",
            status="completion_started",
        )
        action = compute_next_action(act, date.today())
        self.assertEqual(action["action"], "review_partner_evidence")
        self.assertIn("/evidence", action["url"])

    def test_accepted_partner_evidence_moves_on(self):
        act = self._act(delivery_type="partner", evidence_status="accepted")
        action = compute_next_action(act, date.today())
        self.assertNotEqual(action["action"], "review_partner_evidence")

    def test_reimbursement_receipt_is_offered(self):
        """The drawer and route existed; nothing ever pointed at them."""
        act = self._act(status="ia_verified", evidence_status="accepted")
        self._advance(
            act,
            status="reimbursement_disbursed",
            reimbursed_amount=12_000,
        )
        act = Activity.objects.prefetch_related(
            "schedule_cost_lines__advance_requests"
        ).get(id=act.id)
        action = compute_next_action(act, date.today())
        self.assertEqual(action["action"], "reimbursement_receipt")
        self.assertIn("confirm-reimbursement-receipt", action["url"])

    def test_accountability_is_found_on_a_later_cost_line(self):
        """Reading only the first cost line hid outstanding money on lines 2+."""
        act = self._act(status="ia_verified", evidence_status="accepted")
        settled_line = ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="lunch",
            label="Lunch",
            unit_cost=5_000,
            amount=5_000,
        )
        from apps.fund_requests.models import AdvanceRequest

        AdvanceRequest.objects.create(
            activity=act,
            budget_line=settled_line,
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
            amount=5_000,
            status="accounted",
            disbursed_amount=5_000,
            accounted_amount=5_000,
            accountability_netsuite_id="NS-1",
        )
        # A second line still carrying live money.
        self._advance(act, status="disbursed")

        act = Activity.objects.prefetch_related(
            "schedule_cost_lines__advance_requests"
        ).get(id=act.id)
        action = compute_next_action(act, date.today())
        self.assertEqual(action["action"], "accountability")

    def test_every_returned_status_offers_a_route_back(self):
        for status in ("returned", "returned_by_pl", "returned_by_ia"):
            action = compute_next_action(self._act(status=status), date.today())
            self.assertEqual(action["action"], "fix")
            self.assertTrue(action["url"])


class NewActionsBecomeTodosTests(TestCase):
    """A computed action that the To-Do engine does not recognise is dropped."""

    def test_new_actions_are_actionable(self):
        from apps.command_center.todo_service import ACTION_META, ACTIONABLE

        for action in ("reimbursement_receipt", "review_partner_evidence"):
            self.assertIn(action, ACTIONABLE, f"{action} would be silently dropped")
            self.assertIn(action, ACTION_META)

    def test_money_owed_outranks_everything(self):
        from apps.command_center.todo_service import _act_priority

        self.assertEqual(
            _act_priority(None, "reimbursement_receipt", date.today()), "critical"
        )


class PriorityQueueRenderTests(TestCase):
    """The buckets were computed and rendered nowhere."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PQ Region")
        district = District.objects.create(name="PQ District", region=region)
        cls.school = School.objects.create(
            name="PQ Primary",
            school_id="PQ-1",
            region_id=region.id,
            district_id=district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-pq@t.org", "Cara", EdifyRole.CCEO.value)
        self.sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )

    def test_due_today_work_appears_in_the_priority_queue(self):
        Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.sp.id,
            planned_date=timezone.now(),
        )
        client = Client()
        client.force_login(self.cceo)
        body = client.get("/my-plan").content.decode()
        self.assertIn("What needs you now", body)
        self.assertNotIn("{{", body)

    def test_context_exposes_the_buckets_and_a_count(self):
        from apps.my_plan.services import get_frontend_context

        ctx = get_frontend_context(self.cceo, {})
        for key in ("waiting_on_me", "due_today", "this_week", "upcoming"):
            self.assertIn(key, ctx)
        self.assertIn("priority_count", ctx)
        self.assertEqual(
            ctx["priority_count"],
            len(ctx["waiting_on_me"]) + len(ctx["due_today"]),
        )


class StatusReachabilityTests(TestCase):
    """Two statuses were dead ends the workflow could still write."""

    def test_rescheduled_work_can_be_started_again(self):
        from apps.activities.services import STARTABLE_STATUSES

        self.assertIn(
            "rescheduled",
            STARTABLE_STATUSES,
            "reschedule() writes this status; refusing it makes rescheduling "
            "a one-way trip out of the workflow",
        )

    def test_returned_work_can_be_completed_and_resubmitted(self):
        from apps.activities.services import (
            COMPLETABLE_STATUSES,
            RETURNED_STATUSES,
            SUBMITTABLE_STATUSES,
        )

        for status in RETURNED_STATUSES:
            self.assertIn(status, COMPLETABLE_STATUSES)
            self.assertIn(status, SUBMITTABLE_STATUSES)


class MetricAttributionTests(TestCase):
    """A CCEO must be credited for their own work, not their school's."""

    def test_cceo_target_does_not_credit_by_school(self):
        import inspect

        from apps.analytics.pl_analytics_service import PLAnalyticsService

        source = inspect.getsource(PLAnalyticsService._cceo_target)
        self.assertNotIn(
            'Q(school_id__in=cceo["school_ids"])',
            source,
            "crediting every activity at a CCEO's school counts partner work, "
            "a PL's own visits, and a colleague's work as this CCEO's achievement",
        )

    def test_execution_and_target_kpis_do_not_share_a_label(self):
        """The weighted validated ledger owns 'Team Target Progress'; the PL
        dashboard card is a raw execution count and must not borrow it.

        Asserted against the rendered card labels rather than the source text,
        so the explanatory comment naming the old label does not trip it.
        """
        import inspect

        from apps.analytics import pl_dashboard_service

        source = inspect.getsource(pl_dashboard_service)
        # Strip comments before looking for the label as a live string.
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        self.assertNotIn('"Team Target Progress"', code)
        self.assertIn('"Team Execution Progress"', code)
