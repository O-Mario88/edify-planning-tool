"""INTG-03 — one notification writer, and every notice knows how it closes.

The platform claims one centralized notification service, but six live paths
inserted `Notification` rows directly. A raw insert leaves `source_event_type`
empty, and `resolve_condition` filters on `source_event_type__in=[...]` — so
none of those notices could ever be auto-closed. They stayed "Action Required"
forever and the 48-hour escalation job then promoted each one to urgent, which
is how HR's urgent count stopped meaning anything (2026-08-20 HR audit).

Two halves of the same contract are held here: the six conditions must be
resolvable by the transition that satisfies them, and no seventh raw writer may
appear outside the notifications app.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.notifications.models import Notification
from apps.notifications.services import resolve_condition

User = get_user_model()

APPS_ROOT = Path(__file__).resolve().parents[3] / "apps"


class _Principal:
    def __init__(self, user):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = None
        self.name = user.name
        self.id = user.id


def _user(uid, role, email=None):
    return User.objects.create(
        id=uid,
        email=email or f"{uid}@edify.org",
        name=uid.replace("-", " ").title(),
        roles=[role],
        active_role=role,
        is_active=True,
        status="active",
    )


def _rows(**filters):
    return list(Notification.objects.filter(**filters))


def _assert_closable(case, rows, note):
    """Every row must carry the provenance `resolve_condition` matches on, and
    must actually close when that condition is named."""
    case.assertTrue(rows, f"{note}: no notification was created at all")
    for row in rows:
        case.assertTrue(
            (row.source_event_type or "").strip(),
            f"{note}: a raw insert left source_event_type empty, so "
            f"resolve_condition can never match this row (INTG-03)",
        )
        case.assertTrue(
            (row.context_id or "").strip(),
            f"{note}: no context_id, so nothing can address this row",
        )
        closed = resolve_condition(
            row.source_event_type, row.context_type, row.context_id
        )
        case.assertGreater(
            closed, 0, f"{note}: resolve_condition closed 0 rows (INTG-03)"
        )


class PDReminderNoticeTests(TestCase):
    """apps/professional_development/reminders.py — course reminders."""

    def setUp(self):
        self.staff = _user("pd-rem-staff", "CCEO")
        self.req = SimpleNamespace(id="pdreq0000000000000000000001")

    def test_course_reminders_are_closable(self):
        from apps.professional_development import reminders

        reminders._notify(
            self.staff.id, "Your course starts soon", "In 3 days.", self.req
        )
        _assert_closable(
            self,
            _rows(recipient_id=self.staff.id),
            "PD course reminder",
        )


class PDReminderCloseTests(TestCase):
    """The overdue chase reaches the employee, their supervisor and HR — three
    permanent rows each, before INTG-03 was fixed."""

    def setUp(self):
        from apps.professional_development.models import (
            PDStatus,
            ProfessionalDevelopmentRequest,
        )

        self.staff = _user("pd-close-staff", "CCEO")
        self.supervisor = _user("pd-close-sup", "Program Lead")
        self.req = ProfessionalDevelopmentRequest.objects.create(
            fy="2026",
            staff_id="sp-pd-close",
            staff_name="PD Close Staff",
            course_name="Data for Decisions",
            course_category="Analytics",
            course_type="online",
            institution="Coursera",
            start_date=date.today() - timedelta(days=60),
            end_date=date.today() - timedelta(days=20),
            status=PDStatus.ENDED,
        )

    def test_marking_complete_closes_the_overdue_chase_for_everyone(self):
        from apps.professional_development import reminders
        from apps.professional_development.completion_service import (
            PDCourseTrackingService,
        )

        for recipient in (self.staff.id, self.supervisor.id):
            reminders._notify(
                recipient,
                "PD course overdue for completion",
                "Ended 20 days ago.",
                self.req,
                reminders.PD_COMPLETION_OVERDUE,
            )
        self.assertEqual(
            Notification.objects.filter(resolved_at__isnull=True).count(), 2
        )

        owner = _Principal(self.staff)
        owner.staff_profile_id = self.req.staff_id
        PDCourseTrackingService.mark_complete(
            self.req.id,
            owner,
            actual_completion_date=date.today(),
            course_outcome="Completed with distinction.",
        )
        self.assertEqual(
            Notification.objects.filter(resolved_at__isnull=True).count(),
            0,
            "marking complete must clear the chase from the supervisor and HR too",
        )


class PDFundRequestNoticeTests(TestCase):
    """apps/professional_development/fund_service.py — disbursement queue."""

    def setUp(self):
        from apps.professional_development.models import (
            ProfessionalDevelopmentRequest,
        )

        self.staff = _user("pd-fund-staff", "CCEO")
        self.accountant = _user("pd-fund-acct", "Accountant")
        self.req = ProfessionalDevelopmentRequest.objects.create(
            fy="2026",
            staff_id="sp-pd-fund",
            staff_name="PD Fund Staff",
            course_name="Finance for Leaders",
            course_category="Leadership Development",
            course_type="online",
            institution="Coursera",
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=40),
            requested_amount_cents=250_000,
            currency="USD",
        )

    def test_pending_disbursement_notice_is_closable(self):
        from apps.professional_development.fund_service import PDFundRequestService

        PDFundRequestService.create(self.req)
        _assert_closable(
            self,
            _rows(recipient_id=self.accountant.id),
            "PD fund request awaiting disbursement",
        )

    def test_disbursing_closes_the_accountants_queue_item(self):
        from apps.professional_development.fund_service import (
            PD_FUND_PENDING_DISBURSEMENT,
            PDFundRequestService,
        )
        from apps.professional_development.models import PDStatus

        fr = PDFundRequestService.create(self.req)
        queue_item = Notification.objects.get(
            recipient_id=self.accountant.id,
            source_event_type=PD_FUND_PENDING_DISBURSEMENT,
        )
        self.assertIsNone(queue_item.resolved_at)

        self.req.status = PDStatus.APPROVED_PENDING_FUNDING
        self.req.save(update_fields=["status"])
        PDFundRequestService.disburse(
            fr.id,
            _Principal(self.accountant),
            method="bank_transfer",
            reference="TRX-1",
        )
        queue_item.refresh_from_db()
        self.assertIsNotNone(
            queue_item.resolved_at, "paying it is what ends 'awaiting disbursement'"
        )
        self.assertFalse(queue_item.action_required)


class TeamTargetRiskNoticeTests(TestCase):
    """apps/targets/team_targets.py:1383 — staff off-pace notices."""

    def setUp(self):
        self.pl = _user("tt-pl", "Program Lead")
        self.member = _user("tt-member", "CCEO")

    def _member_row(self, status="High Risk"):
        return {
            "user_id": self.member.id,
            "name": "TT Member",
            "status": status,
            "month_pct": 20,
            "pace": 75,
        }

    def test_risk_notices_are_closable(self):
        from apps.targets.team_targets import PLTeamTargetsService

        at_risk = self._member_row()
        PLTeamTargetsService._notify_risk(self.pl, [at_risk], "2026", 5)
        _assert_closable(
            self,
            _rows(recipient_id=self.pl.id),
            "Program Lead staff-at-risk notice",
        )
        _assert_closable(
            self,
            _rows(recipient_id=self.member.id),
            "Own-targets-at-risk notice",
        )

    def test_recovery_closes_both_risk_notices(self):
        from apps.targets.team_targets import PLTeamTargetsService

        at_risk = self._member_row()
        PLTeamTargetsService._notify_risk(
            self.pl, [at_risk], "2026", 5, all_members=[at_risk]
        )
        live = Notification.objects.filter(resolved_at__isnull=True)
        self.assertEqual(live.count(), 2)

        recovered = self._member_row(status="On Track")
        PLTeamTargetsService._notify_risk(
            self.pl, [], "2026", 6, all_members=[recovered]
        )
        self.assertEqual(
            Notification.objects.filter(resolved_at__isnull=True).count(),
            0,
            "a member who recovered must not leave the PL a permanent notice",
        )

    def test_an_unchanged_risk_level_is_not_re_announced_on_every_render(self):
        from apps.targets.team_targets import PLTeamTargetsService

        at_risk = self._member_row()
        for _ in range(3):
            PLTeamTargetsService._notify_risk(
                self.pl, [at_risk], "2026", 5, all_members=[at_risk]
            )
        row = Notification.objects.get(recipient_id=self.pl.id)
        self.assertEqual(row.reminder_count, 0)

    def test_a_worsening_risk_level_is_announced_again(self):
        from apps.targets.team_targets import PLTeamTargetsService

        PLTeamTargetsService._notify_risk(
            self.pl, [self._member_row()], "2026", 5, all_members=[self._member_row()]
        )
        worse = self._member_row(status="Critical")
        PLTeamTargetsService._notify_risk(
            self.pl, [worse], "2026", 5, all_members=[worse]
        )
        row = Notification.objects.get(recipient_id=self.pl.id)
        self.assertIn("Critical", row.title)


class CatchUpPlanNoticeTests(TestCase):
    """apps/targets/team_targets.py:1833 — catch-up plan lifecycle notices."""

    def setUp(self):
        self.staff = _user("cu-staff", "CCEO")
        self.plan = SimpleNamespace(id="catchup00000000000000000001")

    def test_catchup_plan_notices_are_closable(self):
        from apps.targets.team_targets import PLCatchUpPlanService

        PLCatchUpPlanService._notify(
            self.staff.id, "Catch-up plan proposed", "Recovery proposed.", self.plan
        )
        _assert_closable(
            self,
            _rows(recipient_id=self.staff.id),
            "Catch-up plan notice",
        )


class EscalationRaiserNoticeTests(TestCase):
    """apps/flags/escalation_service.py:292 — the CD-facing half of the
    CD→RVP channel (the RVP-facing half was fixed first)."""

    def setUp(self):
        self.cd = _user("esc-cd", "CountryDirector")
        self.rvp = _user("esc-rvp", "RegionalVicePresident")
        self.cd_p = _Principal(self.cd)
        self.rvp_p = _Principal(self.rvp)

    def _raise(self):
        from apps.flags import escalation_service

        return escalation_service.raise_escalation(
            {
                "subject": "Funding gap in Q3",
                "detail": "The district envelope cannot cover the plan.",
                "category": "funding_gap",
                "severity": "high",
            },
            self.cd_p,
        )

    def test_acknowledgement_notice_is_closable(self):
        from apps.flags import escalation_service

        esc = self._raise()
        escalation_service.acknowledge(esc.id, self.rvp_p)
        _assert_closable(
            self,
            _rows(recipient_id=self.cd.id),
            "Escalation acknowledged notice",
        )

    def test_the_decision_closes_the_acknowledgement_it_answered(self):
        from apps.flags import escalation_service

        esc = self._raise()
        escalation_service.acknowledge(esc.id, self.rvp_p)
        ack = Notification.objects.get(
            recipient_id=self.cd.id,
            source_event_type=escalation_service.ESCALATION_ACKNOWLEDGED,
        )
        self.assertIsNone(ack.resolved_at)

        escalation_service.resolve(
            esc.id,
            {"decision": "approved", "decision_note": "Funded from contingency."},
            self.rvp_p,
        )
        ack.refresh_from_db()
        self.assertIsNotNone(
            ack.resolved_at, "the decision must close the acknowledgement"
        )
        self.assertFalse(ack.action_required)

    def test_the_decision_closes_the_rvp_queue_item(self):
        from apps.flags import escalation_service

        esc = self._raise()
        rvp_item = Notification.objects.get(
            recipient_id=self.rvp.id,
            source_event_type=escalation_service.ESCALATION_OPEN,
        )
        escalation_service.resolve(
            esc.id,
            {"decision": "declined", "decision_note": "Out of envelope."},
            self.rvp_p,
        )
        rvp_item.refresh_from_db()
        self.assertIsNotNone(rvp_item.resolved_at)


class RVPDecisionNoticeTests(TestCase):
    """apps/monthly_work_plan/services.py:217 — the RVP decision channel."""

    def setUp(self):
        self.rvp = _user("mwp-rvp", "RegionalVicePresident")
        self.cd = _user("mwp-cd", "CountryDirector")
        self.rvp_p = _Principal(self.rvp)

    def test_strategy_note_notice_is_closable(self):
        from apps.monthly_work_plan.services import create_strategy_note

        create_strategy_note(
            {
                "priority": "Regional Growth",
                "instruction": "Rebalance the western cluster.",
                "responsible_cd_id": self.cd.id,
            },
            self.rvp_p,
        )
        _assert_closable(
            self,
            _rows(recipient_id=self.cd.id),
            "RVP strategy note notice",
        )

    def test_monthly_budget_decision_notice_is_closable(self):
        from apps.monthly_work_plan.models import (
            MonthlyWorkPlanBudget,
            MonthlyWorkPlanBudgetStatus,
        )
        from apps.monthly_work_plan.services import rvp_approve

        b = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-05",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP,
            submitted_by_user_id=self.cd.id,
        )
        rvp_approve(b.id, {}, self.rvp_p)
        _assert_closable(
            self,
            _rows(recipient_id=self.cd.id),
            "Monthly budget approved-by-RVP notice",
        )

    def test_sending_to_the_accountant_closes_the_approval_notice(self):
        from apps.monthly_work_plan.models import (
            MonthlyWorkPlanBudget,
            MonthlyWorkPlanBudgetStatus,
        )
        from apps.monthly_work_plan.services import (
            COUNTRY_BUDGET_APPROVED,
            mark_sent_to_accountant,
            rvp_approve,
        )

        b = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-06",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP,
            submitted_by_user_id=self.cd.id,
        )
        rvp_approve(b.id, {}, self.rvp_p)
        notice = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type=COUNTRY_BUDGET_APPROVED
        )
        self.assertIsNone(notice.resolved_at)

        cd_p = _Principal(self.cd)
        mark_sent_to_accountant(b.id, cd_p)
        notice.refresh_from_db()
        self.assertIsNotNone(
            notice.resolved_at,
            "handing the budget to the Accountant is what 'approved by RVP' asked for",
        )
        self.assertFalse(notice.action_required)

    def test_deciding_closes_the_rvp_own_queue_item(self):
        """The queue item country_budget_service raises for the RVP is closed
        by this path too — both emit `country_budget_submitted` deliberately."""
        from apps.monthly_work_plan.models import (
            MonthlyWorkPlanBudget,
            MonthlyWorkPlanBudgetStatus,
        )
        from apps.monthly_work_plan.services import (
            COUNTRY_BUDGET_SUBMITTED,
            rvp_return,
        )
        from apps.notifications.services import WorkflowNotificationService

        b = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-07",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP,
            submitted_by_user_id=self.cd.id,
        )
        WorkflowNotificationService.trigger(
            event_type=COUNTRY_BUDGET_SUBMITTED,
            category="finance",
            priority="high",
            title="Monthly Fund Request ready for approval",
            body="Awaiting your approval.",
            context_type="MonthlyWorkPlanBudget",
            context_id=b.id,
            recipients=[self.rvp.id],
        )
        rvp_return(b.id, {"note": "Trim the admin lines."}, self.rvp_p)
        queue_item = Notification.objects.get(
            recipient_id=self.rvp.id, source_event_type=COUNTRY_BUDGET_SUBMITTED
        )
        self.assertIsNotNone(queue_item.resolved_at)


# `Notification.objects.create` and friends mint a row from whatever kwargs the
# caller happens to pass — the INTG-03 shape. `update_or_create` is listed
# separately: several planning/partner paths use it and DO supply
# `source_event_type`, so their notices can still be closed. They bypass the
# service's audit row, realtime publish and role-aware routing, which is its own
# debt, but they are not this defect — so they are held to the one rule that is.
_MINTING_METHODS = {"create", "get_or_create", "bulk_create"}
_UPSERT_METHODS = {"update_or_create"}


def _notification_manager_write(node: ast.Call) -> str | None:
    """The method name for `Notification.objects.<method>(…)`, else None."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in (_MINTING_METHODS | _UPSERT_METHODS):
        return None
    manager = func.value
    if not isinstance(manager, ast.Attribute) or manager.attr != "objects":
        return None
    model = manager.value
    name = (
        model.id
        if isinstance(model, ast.Name)
        else model.attr
        if isinstance(model, ast.Attribute)
        else ""
    )
    return func.attr if name == "Notification" else None


def _names_source_event_type(node: ast.Call) -> bool:
    return any(kw.arg == "source_event_type" for kw in node.keywords)


def _is_scanned(path: Path) -> bool:
    parts = path.parts
    if "migrations" in parts or "notifications" in parts:
        return False
    if path.name.startswith("test") or "tests" in parts:
        return False
    return True


class RawNotificationWriterGuardTests(TestCase):
    """One writer, enforced. INTG-03 was six independent regressions of the
    same shape; without this scan a seventh is one merge away."""

    WHY = (
        "A raw insert skips WorkflowNotificationService.trigger, so it carries "
        "no source_event_type. The (recipient_id, source_event_type, "
        "context_type, context_id) dedupe index cannot match it and "
        "resolve_condition() can never close it — the notice becomes a "
        "permanent 'Action Required' row that the 48-hour escalation job "
        "promotes to urgent. That is INTG-03: six such sites are why HR's "
        "urgent count stopped meaning anything. Route it through "
        "WorkflowNotificationService.trigger(event_type=…, context_type=…, "
        "context_id=…) and call resolve_condition() from the transition that "
        "satisfies it."
    )

    def _scan(self):
        minted, unprovenanced_upserts = [], []
        for path in sorted(APPS_ROOT.rglob("*.py")):
            if not _is_scanned(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:  # pragma: no cover — a broken file is not our failure
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                method = _notification_manager_write(node)
                if method is None:
                    continue
                site = f"{path.relative_to(APPS_ROOT)}:{node.lineno}"
                if method in _MINTING_METHODS:
                    minted.append(site)
                elif not _names_source_event_type(node):
                    unprovenanced_upserts.append(site)
        return minted, unprovenanced_upserts

    def test_no_app_mints_notification_rows_directly(self):
        minted, _ = self._scan()
        self.assertEqual(
            minted,
            [],
            "Notification rows may only be created by apps/notifications. "
            + self.WHY
            + " Offending sites: "
            + ", ".join(minted),
        )

    def test_every_direct_notification_write_carries_its_provenance(self):
        _, unprovenanced = self._scan()
        self.assertEqual(
            unprovenanced,
            [],
            "This Notification write names no source_event_type. "
            + self.WHY
            + " Offending sites: "
            + ", ".join(unprovenanced),
        )
