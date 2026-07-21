"""The CD→RVP escalation channel, and approval delegation through coverage.

Two gaps this covers:
  • The CD cockpit offered "Escalate to RVP" with no mechanism behind it, and
    the RVP had no inbound surface at all.
  • PD and leave approver resolution ignored TemporaryCoverageAssignment, so an
    approver going on leave froze their own queue.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.flags import escalation_service
from apps.flags.models import EscalationSeverity, EscalationStatus, LeadershipEscalation


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class EscalationChannelTests(TestCase):
    def setUp(self):
        self.cd = _user("cd-esc@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.rvp = _user(
            "rvp-esc@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.pl = _user("pl-esc@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def _raise(self, **overrides):
        payload = {
            "category": "funding_gap",
            "severity": EscalationSeverity.HIGH.value,
            "subject": "Q3 funding shortfall in Northern region",
            "detail": "Partner costs are 30% above the approved envelope.",
            "requested_decision": "Approve reallocation from Q4",
        }
        payload.update(overrides)
        return escalation_service.raise_escalation(payload, self.cd)

    def test_cd_can_escalate(self):
        esc = self._raise()
        self.assertEqual(esc.status, EscalationStatus.OPEN)
        self.assertEqual(esc.raised_by_user_id, self.cd.id)

    def test_only_the_cd_may_escalate(self):
        with self.assertRaises(Forbidden):
            escalation_service.raise_escalation(
                {"subject": "x", "detail": "y", "category": "other"}, self.pl
            )

    def test_subject_and_detail_are_required(self):
        with self.assertRaises(BadRequest):
            self._raise(subject="")
        with self.assertRaises(BadRequest):
            self._raise(detail="")

    def test_rvp_is_notified(self):
        from apps.notifications.models import Notification

        esc = self._raise()
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.rvp.id, context_id=esc.id
            ).exists()
        )

    def test_rvp_acknowledges_then_decides(self):
        esc = self._raise()
        escalation_service.acknowledge(esc.id, self.rvp)
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.ACKNOWLEDGED)

        escalation_service.resolve(
            esc.id,
            {"decision": "approved", "decision_note": "Reallocation approved for Q3."},
            self.rvp,
        )
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(esc.decision, "approved")
        self.assertIn("Reallocation approved", esc.decision_note)

    def test_a_decision_must_carry_its_reasoning(self):
        esc = self._raise()
        with self.assertRaises(BadRequest) as ctx:
            escalation_service.resolve(esc.id, {"decision": "declined"}, self.rvp)
        self.assertIn("why", str(ctx.exception).lower())

    def test_cd_cannot_decide_their_own_escalation(self):
        esc = self._raise()
        with self.assertRaises(Forbidden):
            escalation_service.resolve(
                esc.id, {"decision": "approved", "decision_note": "self"}, self.cd
            )

    def test_cd_sees_only_their_own_escalations(self):
        self._raise()
        other_cd = _user("cd2-esc@t.org", "Cara", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=other_cd, title="CD", country="Uganda")
        self.assertEqual(escalation_service.visible_to(other_cd).count(), 0)
        self.assertEqual(escalation_service.visible_to(self.cd).count(), 1)
        self.assertEqual(escalation_service.visible_to(self.rvp).count(), 1)

    def test_unrelated_roles_see_nothing(self):
        self._raise()
        self.assertEqual(escalation_service.visible_to(self.pl).count(), 0)

    def test_decisions_are_audited(self):
        from apps.audit.models import AuditLog

        esc = self._raise()
        escalation_service.resolve(
            esc.id,
            {"decision": "declined", "decision_note": "Not this quarter."},
            self.rvp,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="escalation_resolve", subject_id=esc.id
            ).exists()
        )

    def test_sla_marks_ageing_items_overdue(self):
        esc = self._raise(severity=EscalationSeverity.CRITICAL.value)
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        esc.refresh_from_db()
        board = escalation_service.board(self.rvp)
        self.assertEqual(board["overdue_count"], 1)
        self.assertTrue(board["open"][0]["isOverdue"])

    def test_sweep_pushes_overdue_items(self):
        esc = self._raise(severity=EscalationSeverity.CRITICAL.value)
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        self.assertEqual(escalation_service.sweep_overdue(), 1)

    def test_resolved_items_are_not_overdue(self):
        esc = self._raise(severity=EscalationSeverity.CRITICAL.value)
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        escalation_service.resolve(
            esc.id, {"decision": "noted", "decision_note": "Handled offline."}, self.rvp
        )
        self.assertEqual(escalation_service.board(self.rvp)["overdue_count"], 0)


class EscalationPageTests(TestCase):
    def setUp(self):
        self.cd = _user("cd-pg-esc@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.rvp = _user(
            "rvp-pg-esc@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.client = Client()

    def test_cd_page_renders_with_raise_form(self):
        self.client.force_login(self.cd)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_raise"])
        self.assertFalse(resp.context["is_rvp"])

    def test_rvp_page_renders_as_decider(self):
        self.client.force_login(self.rvp)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_rvp"])
        self.assertFalse(resp.context["can_raise"])

    def test_other_roles_are_denied(self):
        cceo = _user("cceo-esc@t.org", "Cara", EdifyRole.CCEO.value)
        self.client.force_login(cceo)
        resp = self.client.get("/escalations", follow=True)
        self.assertNotIn(
            "escalations", resp.request["PATH_INFO"].lower().split("/")[-1:] or [""]
        )

    def test_cd_can_post_an_escalation_through_the_page(self):
        self.client.force_login(self.cd)
        self.client.post(
            "/escalations",
            {
                "action": "raise",
                "category": "staffing",
                "severity": "high",
                "subject": "Two CCEO vacancies unfilled for a quarter",
                "detail": "Coverage is failing in two districts.",
            },
        )
        self.assertTrue(
            LeadershipEscalation.objects.filter(
                subject__startswith="Two CCEO vacancies"
            ).exists()
        )


class ApprovalDelegationTests(TestCase):
    """Authority must travel with active coverage."""

    def setUp(self):
        self.cceo, self.cceo_sp = self._staff(
            "cceo-cov@t.org", "Cara", EdifyRole.CCEO.value
        )
        self.pl, self.pl_sp = self._staff(
            "pl-cov@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.stand_in, self.stand_in_sp = self._staff(
            "pl2-cov@t.org", "Pia", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )

    def _staff(self, email, name, role):
        u = _user(email, name, role)
        sp = StaffProfile.objects.create(user=u, title=role, country="Uganda")
        return u, sp

    def _pl_leave(self):
        """Coverage hangs off the leave that caused it — that is the point:
        the supervisor is away, so their authority must move."""
        from apps.accounts.models import Leave

        return Leave.objects.create(
            staff=self.pl_sp,
            type="annual",
            start_date=str(date.today() - timedelta(days=1)),
            end_date=str(date.today() + timedelta(days=5)),
            days=6,
            status="approved",
        )

    def _cover(self, days=5):
        now = timezone.now()
        return TemporaryCoverageAssignment.objects.create(
            original_staff=self.pl_sp,
            covering_staff=self.stand_in_sp,
            leave_request=self._pl_leave(),
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=days),
            status="active",
        )

    def test_pd_supervisor_authority_passes_to_active_cover(self):
        from apps.professional_development.approval_service import (
            PDApprovalRoutingService,
        )

        acting = PDApprovalRoutingService.acting_supervisor_ids(self.cceo_sp)
        self.assertEqual(acting, [self.pl.id])

        self._cover()
        acting = PDApprovalRoutingService.acting_supervisor_ids(self.cceo_sp)
        self.assertIn(self.pl.id, acting)
        self.assertIn(
            self.stand_in.id, acting, "an active cover must be able to approve"
        )

    def test_expired_coverage_does_not_confer_authority(self):
        now = timezone.now()
        TemporaryCoverageAssignment.objects.create(
            original_staff=self.pl_sp,
            covering_staff=self.stand_in_sp,
            leave_request=self._pl_leave(),
            start_datetime=now - timedelta(days=30),
            end_datetime=now - timedelta(days=10),
            status="active",
        )
        from apps.professional_development.approval_service import (
            PDApprovalRoutingService,
        )

        acting = PDApprovalRoutingService.acting_supervisor_ids(self.cceo_sp)
        self.assertNotIn(self.stand_in.id, acting)

    def test_leave_approval_passes_to_active_cover(self):
        from apps.accounts.models import Leave
        from apps.hr.leave_services import LeaveApprovalService

        leave = Leave.objects.create(
            staff=self.cceo_sp,
            type="annual",
            start_date=str(date.today() + timedelta(days=10)),
            end_date=str(date.today() + timedelta(days=12)),
            days=3,
            status="pending",
        )
        self.assertTrue(LeaveApprovalService.is_authorized_approver(self.pl, leave))
        self.assertFalse(
            LeaveApprovalService.is_authorized_approver(self.stand_in, leave)
        )

        self._cover()
        self.assertTrue(
            LeaveApprovalService.is_authorized_approver(self.stand_in, leave),
            "an active cover must be able to clear the approval queue",
        )
