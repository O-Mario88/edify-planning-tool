"""Phase 4 — leadership becomes the most audited tier, not the least.

A tamper-evident hash chain already existed. What was missing: PD and leave
decisions never called it, and no leadership role could open any surface that
reads it (audit_log is Admin-only, hr_audit_log HR-only, finance history
Accountant-only).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import Leave, StaffProfile, StaffSupervisorAssignment, User
from apps.audit.models import AuditLog
from apps.core.rbac import EdifyRole


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class LeaveDecisionAuditTests(TestCase):
    """Only the coverage side-effect was logged; the decision itself was not."""

    def setUp(self):
        self.cceo = _user("cceo-aud@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        self.pl = _user("pl-aud@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.pl_sp = StaffProfile.objects.create(
            user=self.pl, title="PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )

    def _leave(self):
        return Leave.objects.create(
            staff=self.cceo_sp,
            type="annual",
            start_date=str(date.today() + timedelta(days=20)),
            end_date=str(date.today() + timedelta(days=22)),
            days=3,
            status="pending",
        )

    def test_approval_is_audited(self):
        from apps.hr.leave_services import LeaveApprovalService

        leave = self._leave()
        LeaveApprovalService.approve_request(leave.id, self.pl)
        entry = AuditLog.objects.filter(
            action="leave.approved", subject_id=leave.id
        ).first()
        self.assertIsNotNone(entry, "a leave approval must be recorded")
        self.assertEqual(entry.actor_id, self.pl.id)
        self.assertEqual(entry.actor_role, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def test_rejection_is_audited_with_its_reason(self):
        from apps.hr.leave_services import LeaveApprovalService

        leave = self._leave()
        LeaveApprovalService.reject_request(leave.id, self.pl, "Peak visit week")
        entry = AuditLog.objects.filter(
            action="leave.rejected", subject_id=leave.id
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.reason, "Peak visit week")


class DecisionLogScopeTests(TestCase):
    """Who may read whose decisions."""

    def setUp(self):
        self.cd = _user("cd-log@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.foreign_cd = _user(
            "cd-ke-log@t.org", "Kofi", EdifyRole.COUNTRY_DIRECTOR.value
        )
        StaffProfile.objects.create(user=self.foreign_cd, title="CD", country="Kenya")
        self.rvp = _user(
            "rvp-log@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.cceo = _user("cceo-log@t.org", "Cara", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=self.cceo, title="CCEO", country="Uganda")

        from apps.audit.services import log as audit_log

        audit_log(
            action="leave.approved",
            subject_kind="Leave",
            subject_id="L1",
            actor_id=self.cd.id,
            actor_role=EdifyRole.COUNTRY_DIRECTOR.value,
            payload={"staffName": "Someone"},
        )
        audit_log(
            action="rvp_annual_approve",
            subject_kind="CountryAnnualBudget",
            subject_id="B1",
            actor_id=self.rvp.id,
            actor_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            payload={"monthKey": "2026-05"},
        )

    def test_rvp_sees_the_whole_deployment(self):
        from apps.audit.decision_log_service import decision_log

        log = decision_log(self.rvp, {})
        self.assertGreaterEqual(log["total"], 2)
        self.assertIn("deployment", log["scopeLabel"])

    def test_cd_sees_their_own_country(self):
        from apps.audit.decision_log_service import decision_log

        log = decision_log(self.cd, {})
        self.assertGreaterEqual(log["total"], 1)
        self.assertIn("country", log["scopeLabel"])

    def test_foreign_cd_does_not_see_another_countrys_decisions(self):
        from apps.audit.decision_log_service import decision_log

        log = decision_log(self.foreign_cd, {})
        actor_ids = {r["actorId"] for r in log["rows"]}
        self.assertNotIn(self.cd.id, actor_ids)
        self.assertNotIn(self.rvp.id, actor_ids)

    def test_field_role_sees_only_its_own_decisions(self):
        from apps.audit.decision_log_service import decision_log

        log = decision_log(self.cceo, {})
        self.assertEqual(log["total"], 0)
        self.assertIn("own", log["scopeLabel"])

    def test_group_filter_narrows_the_stream(self):
        from apps.audit.decision_log_service import decision_log

        log = decision_log(self.rvp, {"group": "Money"})
        self.assertTrue(all(r["group"] == "Money" for r in log["rows"]))

    def test_page_renders_for_leadership(self):
        client = Client()
        for user in (self.cd, self.rvp):
            client.force_login(user)
            resp = client.get("/decision-log")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Decision Log", resp.content.decode())

    def test_every_decision_action_has_a_human_label(self):
        """An audit action name is a developer's word; directors read this."""
        from apps.audit.decision_log_service import (
            ACTION_LABELS,
            ALL_DECISION_ACTIONS,
        )

        missing = [a for a in ALL_DECISION_ACTIONS if a not in ACTION_LABELS]
        self.assertEqual(missing, [], f"unlabelled decision actions: {missing}")


class AuditCoverageTests(TestCase):
    """The decision points that move money or change a person's record must
    all reach the chain."""

    def test_pd_and_leave_services_call_the_audit_log(self):
        import inspect

        from apps.hr import leave_services
        from apps.professional_development import approval_service

        for module in (approval_service, leave_services):
            source = inspect.getsource(module)
            self.assertIn(
                "audit",
                source,
                f"{module.__name__} makes accountable decisions and must audit them",
            )

    def test_escalation_decisions_reach_the_chain(self):
        import inspect

        from apps.flags import escalation_service

        source = inspect.getsource(escalation_service)
        for action in ("escalation_raise", "escalation_resolve"):
            self.assertIn(action, source)
