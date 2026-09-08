"""The escalation channel, and approval delegation through coverage.

Three gaps this covers:
  • The CD cockpit offered "Escalate to RVP" with no mechanism behind it, and
    the RVP had no inbound surface at all.
  • The field had no route at all: a CCEO facing a blocker could not put it in
    front of their Programme Lead, nor a PL in front of the Country Director.
    The channel now runs one level up from every raiser, with the addressee
    resolved from supervision.
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
from apps.flags.models import (
    EscalationAddressee,
    EscalationSeverity,
    EscalationStatus,
    LeadershipEscalation,
)


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

    def test_roles_outside_the_reporting_line_may_not_escalate(self):
        for role in (
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.PROGRAM_ACCOUNTANT.value,
            EdifyRole.IMPACT_ASSESSMENT.value,
        ):
            with self.assertRaises(Forbidden, msg=role):
                escalation_service.raise_escalation(
                    {"subject": "x", "detail": "y", "category": "other"},
                    _user(f"{role.lower()}-noesc@t.org", role, role),
                )

    def test_cd_to_rvp_path_is_unchanged(self):
        esc = self._raise()
        self.assertEqual(
            esc.addressed_role, EscalationAddressee.REGIONAL_VICE_PRESIDENT.value
        )
        self.assertIsNone(esc.assigned_to_user_id, "the RVP is addressed by role")
        self.assertEqual(escalation_service.visible_to(self.rvp).count(), 1)
        self.assertTrue(escalation_service.can_decide(esc, self.rvp))
        self.assertFalse(escalation_service.can_decide(esc, self.pl))

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

    def test_cd_sees_only_their_own_countrys_escalations(self):
        # Owner, 2026-09-03: the board belongs to the country, not the raiser,
        # so a second Uganda CD account sees it and a Kenya CD does not.
        self._raise()
        other_cd = _user("cd2-esc@t.org", "Cara", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=other_cd, title="CD", country="Kenya")
        same_country = _user("cd3-esc@t.org", "Cyril", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=same_country, title="CD", country="Uganda")
        self.assertEqual(escalation_service.visible_to(other_cd).count(), 0)
        self.assertEqual(escalation_service.visible_to(same_country).count(), 1)
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
        accountant = _user("acct-esc@t.org", "Abe", EdifyRole.PROGRAM_ACCOUNTANT.value)
        self.client.force_login(accountant)
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


class FieldEscalationTests(TestCase):
    """The same channel one level down: CCEO/PC → PL, PL → CD."""

    def setUp(self):
        self.cceo, self.cceo_sp = self._staff(
            "cceo-fe@t.org", "Cara", EdifyRole.CCEO.value
        )
        self.pc, self.pc_sp = self._staff(
            "pc-fe@t.org", "Percy", EdifyRole.PROJECT_COORDINATOR.value
        )
        self.pl, self.pl_sp = self._staff(
            "pl-fe@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.other_pl, self.other_pl_sp = self._staff(
            "pl2-fe@t.org", "Pia", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cd, self.cd_sp = self._staff(
            "cd-fe@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.rvp, self.rvp_sp = self._staff(
            "rvp-fe@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.pl_sp, supervisor=self.cd_sp
        )

    def _staff(self, email, name, role, country="Uganda"):
        u = _user(email, name, role)
        sp = StaffProfile.objects.create(user=u, title=role, country=country)
        return u, sp

    def _raise(self, principal, **overrides):
        payload = {
            "category": "school_blocker",
            "severity": EscalationSeverity.HIGH.value,
            "subject": "Partner has missed three cluster trainings",
            "detail": "Two clusters have had no training since June.",
            "requested_decision": "Reassign the partner",
        }
        payload.update(overrides)
        return escalation_service.raise_escalation(payload, principal)

    def _notified(self, user, esc):
        from apps.notifications.models import Notification

        return Notification.objects.filter(
            recipient_id=user.id, context_id=esc.id
        ).exists()

    # ── raising ──────────────────────────────────────────────────────────

    def test_cceo_raises_to_their_programme_lead(self):
        esc = self._raise(self.cceo)
        self.assertEqual(esc.addressed_role, EscalationAddressee.PROGRAM_LEAD.value)
        self.assertEqual(
            esc.assigned_to_user_id, self.pl.id, "resolved from supervision"
        )
        self.assertEqual(esc.country_id, "Uganda")
        self.assertTrue(self._notified(self.pl, esc), "the addressee is told")
        self.assertFalse(self._notified(self.other_pl, esc), "another PL is not")
        self.assertFalse(self._notified(self.rvp, esc), "the RVP is not")

    def test_project_coordinator_raises_to_the_pl_role_when_unsupervised(self):
        esc = self._raise(self.pc)
        self.assertEqual(esc.addressed_role, EscalationAddressee.PROGRAM_LEAD.value)
        self.assertIsNone(esc.assigned_to_user_id, "no supervisor → the role")
        # Every PL in the country is a candidate decider and is told.
        self.assertTrue(self._notified(self.pl, esc))
        self.assertTrue(self._notified(self.other_pl, esc))
        self.assertTrue(escalation_service.can_decide(esc, self.pl))
        self.assertTrue(escalation_service.can_decide(esc, self.other_pl))

    def test_pl_raises_to_the_country_director(self):
        esc = self._raise(self.pl, subject="Two CCEO vacancies for a quarter")
        self.assertEqual(esc.addressed_role, EscalationAddressee.COUNTRY_DIRECTOR.value)
        self.assertEqual(esc.assigned_to_user_id, self.cd.id)
        self.assertTrue(self._notified(self.cd, esc))
        self.assertFalse(self._notified(self.rvp, esc))

    def test_the_resolved_addressee_is_exposed_to_the_raise_form(self):
        self.assertEqual(
            escalation_service.resolve_addressee(self.cceo),
            ("PL", self.pl.id, "Pat"),
        )
        self.assertEqual(
            escalation_service.resolve_addressee(self.pc), ("PL", None, None)
        )
        self.assertEqual(
            escalation_service.resolve_addressee(self.cd), ("RVP", None, None)
        )

    # ── deciding ─────────────────────────────────────────────────────────

    def test_pl_decides_and_the_raiser_is_notified(self):
        from apps.notifications.models import Notification

        esc = self._raise(self.cceo)
        escalation_service.acknowledge(esc.id, self.pl)
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.ACKNOWLEDGED)
        escalation_service.resolve(
            esc.id,
            {"decision": "approved", "decision_note": "Partner reassigned."},
            self.pl,
        )
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(esc.decision, "approved")
        decided = Notification.objects.filter(
            recipient_id=self.cceo.id,
            context_id=esc.id,
            source_event_type=escalation_service.ESCALATION_DECIDED,
        ).first()
        self.assertIsNotNone(decided)
        self.assertIn("Programme Lead decision", decided.title)

    def test_cd_decides_a_pl_escalation(self):
        from apps.notifications.models import Notification

        esc = self._raise(self.pl)
        escalation_service.resolve(
            esc.id, {"decision": "deferred", "decision_note": "Next quarter."}, self.cd
        )
        esc.refresh_from_db()
        self.assertEqual(esc.decision, "deferred")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id,
                context_id=esc.id,
                source_event_type=escalation_service.ESCALATION_DECIDED,
            ).exists()
        )

    def test_cceo_cannot_acknowledge_or_resolve(self):
        esc = self._raise(self.cceo)
        with self.assertRaises(Forbidden):
            escalation_service.acknowledge(esc.id, self.cceo)
        with self.assertRaises(Forbidden):
            escalation_service.resolve(
                esc.id, {"decision": "approved", "decision_note": "me"}, self.cceo
            )
        other = self._raise(self.pc)
        with self.assertRaises(Forbidden):
            escalation_service.resolve(
                other.id, {"decision": "approved", "decision_note": "me"}, self.cceo
            )

    def test_a_pl_cannot_see_or_decide_another_pls_items(self):
        esc = self._raise(self.cceo)
        self.assertEqual(escalation_service.visible_to(self.other_pl).count(), 0)
        self.assertFalse(escalation_service.can_decide(esc, self.other_pl))
        with self.assertRaises(Forbidden):
            escalation_service.resolve(
                esc.id,
                {"decision": "approved", "decision_note": "not mine"},
                self.other_pl,
            )
        self.assertEqual(escalation_service.visible_to(self.pl).count(), 1)

    def test_pl_addressed_items_stay_inside_the_country(self):
        kenya_pl, _ = self._staff(
            "pl-ke@t.org", "Kip", EdifyRole.COUNTRY_PROGRAM_LEAD.value, country="Kenya"
        )
        esc = self._raise(self.pc)  # addressed to the PL role, Uganda
        self.assertEqual(escalation_service.visible_to(kenya_pl).count(), 0)
        self.assertFalse(escalation_service.can_decide(esc, kenya_pl))

    def test_cd_reads_what_their_pls_received_but_cannot_act(self):
        esc = self._raise(self.cceo)
        self.assertEqual(escalation_service.visible_to(self.cd).count(), 1)
        self.assertFalse(escalation_service.can_decide(esc, self.cd))
        with self.assertRaises(Forbidden):
            escalation_service.resolve(
                esc.id, {"decision": "approved", "decision_note": "cd"}, self.cd
            )
        board = escalation_service.board(self.cd)
        self.assertEqual([r["id"] for r in board["watching"]], [esc.id])
        self.assertEqual(board["inbox"], [])

    def test_rvp_does_not_see_field_escalations(self):
        self._raise(self.cceo)
        self._raise(self.pl)
        self.assertEqual(escalation_service.visible_to(self.rvp).count(), 0)
        self._raise(self.cd, subject="Above the country")
        self.assertEqual(escalation_service.visible_to(self.rvp).count(), 1)

    def test_admin_may_decide_at_any_level(self):
        admin = _user("admin-fe@t.org", "Ada", EdifyRole.ADMIN.value)
        esc = self._raise(self.cceo)
        escalation_service.resolve(
            esc.id, {"decision": "noted", "decision_note": "Handled."}, admin
        )
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)

    def test_the_raiser_sees_their_own_with_the_decision(self):
        esc = self._raise(self.cceo)
        escalation_service.resolve(
            esc.id, {"decision": "declined", "decision_note": "Not now."}, self.pl
        )
        board = escalation_service.board(self.cceo)
        self.assertEqual(len(board["raised"]), 1)
        row = board["raised"][0]
        self.assertTrue(row["mine"])
        self.assertFalse(row["canDecide"])
        self.assertEqual(row["decisionLabel"], "Declined")
        self.assertEqual(row["decisionNote"], "Not now.")
        self.assertEqual(board["inbox"], [])

    def test_overdue_sweep_pushes_to_the_addressee(self):
        from apps.notifications.models import Notification

        esc = self._raise(self.cceo, severity=EscalationSeverity.CRITICAL.value)
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        self.assertEqual(escalation_service.sweep_overdue(), 1)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id, context_id=esc.id
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient_id=self.rvp.id, context_id=esc.id
            ).exists()
        )


class FieldEscalationPageTests(TestCase):
    """The one page, rendered for every level of the chain."""

    def setUp(self):
        self.client = Client()
        self.cceo = _user("cceo-fpg@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        self.pl = _user("pl-fpg@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.pl_sp = StaffProfile.objects.create(
            user=self.pl, title="PL", country="Uganda"
        )
        self.cd = _user("cd-fpg@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        self.cd_sp = StaffProfile.objects.create(
            user=self.cd, title="CD", country="Uganda"
        )
        self.rvp = _user(
            "rvp-fpg@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.pl_sp, supervisor=self.cd_sp
        )

    def _cceo_item(self):
        return escalation_service.raise_escalation(
            {
                "category": "school_blocker",
                "subject": "Cluster 4 has no partner",
                "detail": "Nobody is delivering in cluster 4.",
            },
            self.cceo,
        )

    def test_cceo_page_renders_with_a_raise_form_to_the_pl(self):
        self.client.force_login(self.cceo)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_raise"])
        self.assertFalse(resp.context["can_decide"])
        self.assertFalse(resp.context["is_rvp"])
        self.assertEqual(resp.context["board"]["raise_to_label"], "Programme Lead")
        self.assertEqual(resp.context["board"]["raise_to_name"], "Pat")
        self.assertContains(resp, "Send to Programme Lead")
        self.assertContains(resp, '<header class="edify-page-header">')

    def test_pl_page_renders_as_decider_and_raiser(self):
        esc = self._cceo_item()
        self.client.force_login(self.pl)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_decide"])
        self.assertTrue(resp.context["can_raise"])
        self.assertEqual(resp.context["decider_level"], "PL")
        self.assertEqual([r["id"] for r in resp.context["board"]["inbox"]], [esc.id])
        self.assertContains(resp, "Awaiting your decision")
        self.assertContains(resp, "Send to Country Director")

    def test_cd_page_shows_the_pl_inbox_read_only(self):
        esc = self._cceo_item()
        self.client.force_login(self.cd)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_raise"])
        self.assertTrue(resp.context["can_decide"])
        self.assertEqual([r["id"] for r in resp.context["board"]["watching"]], [esc.id])
        self.assertContains(resp, "Received by your Programme Leads")

    def test_rvp_page_is_unchanged(self):
        self._cceo_item()
        self.client.force_login(self.rvp)
        resp = self.client.get("/escalations")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_rvp"])
        self.assertFalse(resp.context["can_raise"])
        self.assertEqual(resp.context["board"]["open_count"], 0)

    def test_cceo_can_post_an_escalation_through_the_page(self):
        self.client.force_login(self.cceo)
        resp = self.client.post(
            "/escalations",
            {
                "action": "raise",
                "category": "school_blocker",
                "severity": "high",
                "subject": "Partner absent in cluster 2",
                "detail": "No sessions for six weeks.",
            },
            follow=True,
        )
        esc = LeadershipEscalation.objects.get(subject="Partner absent in cluster 2")
        self.assertEqual(esc.assigned_to_user_id, self.pl.id)
        self.assertContains(resp, "Escalated to the Programme Lead")

    def test_pl_can_decide_through_the_page_and_cceo_cannot(self):
        esc = self._cceo_item()
        self.client.force_login(self.cceo)
        self.client.post(
            "/escalations",
            {
                "action": "resolve",
                "escalation_id": esc.id,
                "decision": "approved",
                "decision_note": "self-approved",
            },
        )
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.OPEN)

        self.client.force_login(self.pl)
        self.client.post(
            "/escalations",
            {
                "action": "resolve",
                "escalation_id": esc.id,
                "decision": "approved",
                "decision_note": "New partner assigned.",
            },
        )
        esc.refresh_from_db()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)


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
