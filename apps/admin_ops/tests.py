"""End-to-end tests for the Admin Platform Operations workflow.

Grouped by the mandate's completion gate: super-role access, the three
operations workspaces, support tickets, incidents and deduplication, detection,
security alerting, deep links, maintenance, and finance execution.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.admin_ops.models import (
    AdminOperationsWorkItem,
    IncidentStatus,
    MaintenanceTemplate,
    Severity,
    SupportTicket,
    SystemIncident,
    TicketStatus,
    WorkItemCategory,
    WorkItemStatus,
)
from apps.admin_ops.services import (
    AdminMyPlanService,
    AdminPlanningService,
    AdminWorkItemService,
    SecurityAlertService,
    SupportTicketService,
    SystemIncidentService,
)
from apps.admin_ops.team_plans import AdminTeamPlansService
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School


def _user(key, role, password=None):
    user = User.objects.create(
        id=f"ao-{key}"[:30],
        email=f"ao-{key}@edify.org",
        name=f"AO {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    if password:
        user.set_password(password)
        user.save()
    return user


class AdminOpsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("admin", "Admin")
        cls.cceo = _user("cceo", "CCEO")


# ── Support tickets (§11, §12) ───────────────────────────────────────────────


class SupportTicketWorkflowTests(AdminOpsTestBase):
    def test_any_user_can_report_a_problem(self):
        ticket = SupportTicketService.create(
            self.cceo,
            {"title": "The Schedule button does nothing", "category": "dead_button"},
            {"route": "/planning", "browser": "Firefox"},
        )
        self.assertTrue(ticket.reference.startswith("TCK-"))
        self.assertEqual(ticket.status, TicketStatus.SUBMITTED)
        self.assertEqual(ticket.route, "/planning")

    def test_a_ticket_notifies_the_admin(self):
        SupportTicketService.create(self.cceo, {"title": "Cannot open my plan"})
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.admin.id, source_event_type="admin_ops.ticket.created"
            ).exists()
        )

    def test_support_context_refuses_to_carry_secrets(self):
        with self.assertRaises(BadRequest):
            SupportTicketService.create(
                self.cceo, {"title": "Login fails"}, {"password": "hunter2"}
            )
        with self.assertRaises(BadRequest):
            SupportTicketService.create(
                self.cceo, {"title": "Login fails"}, {"token": "abc.def"}
            )

    def test_a_ticket_needs_a_summary(self):
        with self.assertRaises(BadRequest):
            SupportTicketService.create(self.cceo, {"title": "   "})

    def test_the_lifecycle_refuses_illegal_jumps(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Slow page"})
        with self.assertRaises(BadRequest):
            SupportTicketService.transition(
                ticket.id, TicketStatus.RESOLVED, self.admin
            )

    def test_a_critical_ticket_lands_in_admin_my_plan_immediately(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Cannot log in"})
        item = SupportTicketService.triage(
            ticket.id, self.admin, severity=Severity.CRITICAL
        )
        self.assertEqual(item.scheduled_date, timezone.localdate())
        self.assertEqual(item.status, WorkItemStatus.SCHEDULED)
        sections = AdminMyPlanService.context(self.admin)["sections"]
        self.assertIn(item.id, [i.id for i in sections["critical_now"]])

    def test_a_normal_ticket_waits_in_admin_planning(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Typo on the page"})
        item = SupportTicketService.triage(ticket.id, self.admin, severity=Severity.LOW)
        self.assertIsNone(item.scheduled_date)
        self.assertEqual(item.status, WorkItemStatus.BACKLOG)
        backlog = AdminPlanningService.context(self.admin)["backlog"]
        self.assertIn(item.id, [i.id for i in backlog])

    def test_scheduling_moves_work_from_planning_to_my_plan(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Broken link"})
        item = SupportTicketService.triage(
            ticket.id, self.admin, severity=Severity.MEDIUM
        )
        when = timezone.localdate() + timedelta(days=1)
        AdminWorkItemService.schedule(item.id, self.admin, when)

        backlog = AdminPlanningService.context(self.admin)["backlog"]
        self.assertNotIn(item.id, [i.id for i in backlog])
        sections = AdminMyPlanService.context(self.admin)["sections"]
        scheduled = [i.id for group in sections.values() for i in group]
        self.assertIn(item.id, scheduled)

    def test_resolving_a_ticket_notifies_the_reporter(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Upload failed"})
        for step in (
            TicketStatus.TRIAGED,
            TicketStatus.IN_PROGRESS,
            TicketStatus.FIX_READY,
            TicketStatus.VERIFICATION,
            TicketStatus.RESOLVED,
        ):
            SupportTicketService.transition(ticket.id, step, self.admin, "Fixed it")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id,
                source_event_type="admin_ops.ticket.resolved",
            ).exists()
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.resolution, "Fixed it")

    def test_only_admin_may_transition_a_ticket(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Anything"})
        with self.assertRaises(Forbidden):
            SupportTicketService.transition(ticket.id, TicketStatus.TRIAGED, self.cceo)


# ── Incidents and deduplication (§13, §14) ───────────────────────────────────


class SystemIncidentTests(AdminOpsTestBase):
    def _report(self, **overrides):
        payload = {
            "title": "Server error on /planning",
            "category": WorkItemCategory.BACKEND_DEFECT,
            "severity": Severity.HIGH,
            "route": "/planning",
            "error": "http_500",
            "environment": "test",
        }
        payload.update(overrides)
        return SystemIncidentService.report(**payload)

    def test_a_failure_creates_one_actionable_incident(self):
        incident = self._report()
        self.assertTrue(incident.reference.startswith("INC-"))
        self.assertEqual(incident.status, IncidentStatus.OPEN)
        self.assertEqual(incident.occurrence_count, 1)

    def test_repeated_identical_failures_update_one_incident(self):
        first = self._report(request_id="r1")
        for i in range(2, 12):
            self._report(request_id=f"r{i}")
        self.assertEqual(SystemIncident.objects.count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.occurrence_count, 11)

    def test_a_different_route_is_a_different_incident(self):
        self._report(route="/planning")
        self._report(route="/my-plan")
        self.assertEqual(SystemIncident.objects.count(), 2)

    def test_repeats_refresh_one_notification_rather_than_flooding(self):
        for i in range(5):
            self._report(request_id=f"r{i}")
        self.assertEqual(
            Notification.objects.filter(
                recipient_id=self.admin.id,
                source_event_type="admin_ops.incident.detected",
            ).count(),
            1,
        )

    def test_a_resolved_incident_that_recurs_reopens(self):
        incident = self._report()
        SystemIncidentService.acknowledge(incident.id, self.admin)
        SystemIncidentService.resolve(incident.id, self.admin, "Query fixed")
        self._report()
        incident.refresh_from_db()
        self.assertEqual(incident.status, IncidentStatus.OPEN)
        self.assertEqual(incident.reopened_count, 1)
        self.assertEqual(SystemIncident.objects.count(), 1)

    def test_a_critical_incident_bypasses_the_planning_backlog(self):
        incident = self._report(severity=Severity.CRITICAL)
        item = AdminOperationsWorkItem.objects.get(incident=incident)
        self.assertEqual(item.scheduled_date, timezone.localdate())
        self.assertEqual(item.next_action, "Acknowledge Incident")
        sections = AdminMyPlanService.context(self.admin)["sections"]
        self.assertIn(item.id, [i.id for i in sections["critical_now"]])

    def test_an_incident_must_be_acknowledged_before_resolution(self):
        incident = self._report()
        with self.assertRaises(BadRequest):
            SystemIncidentService.resolve(incident.id, self.admin)

    def test_resolution_closes_the_admin_notification(self):
        incident = self._report()
        SystemIncidentService.acknowledge(incident.id, self.admin)
        SystemIncidentService.resolve(incident.id, self.admin, "Fixed")
        live = Notification.objects.filter(
            recipient_id=self.admin.id,
            source_event_type="admin_ops.incident.detected",
            status="unread",
        )
        self.assertFalse(live.exists())


class DetectionTests(AdminOpsTestBase):
    def test_a_dead_button_becomes_an_incident(self):
        from apps.admin_ops.detection import report_client_defect

        incident = report_client_defect(
            kind="dead_button",
            route="/planning",
            component="schedule-btn",
            detail={"message": "no handler", "target": "#schedule"},
        )
        self.assertIsNotNone(incident)
        self.assertEqual(incident.category, WorkItemCategory.FRONTEND_DEFECT)
        self.assertEqual(incident.affected_route, "/planning")

    def test_an_unrecognised_defect_kind_is_refused(self):
        from apps.admin_ops.detection import report_client_defect

        self.assertIsNone(
            report_client_defect(kind="anything", route="/x", component="y", detail={})
        )

    def test_a_failed_job_becomes_an_incident(self):
        from apps.admin_ops.detection import report_job_failure

        incident = report_job_failure("weekly_fund_request", "connection reset")
        self.assertEqual(incident.category, WorkItemCategory.JOB_FAILURE)

    def test_an_overdue_job_becomes_an_incident(self):
        from apps.admin_ops.detection import report_job_overdue

        incident = report_job_overdue("daily_digest", 300)
        self.assertEqual(incident.severity, Severity.HIGH)

    def test_client_payloads_never_reach_the_record_verbatim(self):
        """A browser payload is untrusted input."""
        from apps.admin_ops.detection import report_client_defect

        incident = report_client_defect(
            kind="js_exception",
            route="/planning",
            component="chart",
            detail={"message": "boom", "password": "hunter2", "cookie": "session=x"},
        )
        self.assertNotIn("password", incident.detail)
        self.assertNotIn("cookie", incident.detail)
        self.assertEqual(incident.detail["message"], "boom")


# ── Security alerting (§17) ──────────────────────────────────────────────────


class FailedLoginSecurityAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("sec-admin", "Admin")
        cls.victim = _user("sec-victim", "CCEO", password="Correct-Horse-1")

    def _fail(self, times):
        from apps.accounts.lockout_service import AuthenticationLockoutService

        for _ in range(times):
            AuthenticationLockoutService.record_failed_attempt(self.victim.id)

    def test_five_failures_raise_exactly_one_admin_security_alert(self):
        self._fail(5)
        incidents = SystemIncident.objects.filter(category=WorkItemCategory.SECURITY)
        self.assertEqual(incidents.count(), 1)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.admin.id,
                source_event_type="admin_ops.incident.detected",
            ).exists()
        )

    def test_four_failures_raise_nothing(self):
        self._fail(4)
        self.assertFalse(
            SystemIncident.objects.filter(category=WorkItemCategory.SECURITY).exists()
        )

    def test_the_alert_never_carries_password_material(self):
        self._fail(5)
        incident = SystemIncident.objects.get(category=WorkItemCategory.SECURITY)
        blob = f"{incident.title}{incident.detail}{incident.samples}".lower()
        for forbidden in ("correct-horse", "password", "token", "hash"):
            self.assertNotIn(forbidden, blob)

    def test_the_identifier_is_masked(self):
        self.assertEqual(
            SecurityAlertService.mask("mary.jones@edify.org"), "ma********@edify.org"
        )
        self.assertEqual(SecurityAlertService.mask(""), "unknown")

    def test_the_alert_threshold_is_independent_of_the_lockout_policy(self):
        from apps.accounts.lockout_service import _alert_threshold, _max_failed

        self.assertEqual(_alert_threshold(), 5)
        self.assertNotEqual(_alert_threshold(), _max_failed())

    def test_the_public_login_response_stays_generic(self):
        """Five failures alert the Admin; the user still learns nothing."""
        client = Client()
        responses = []
        for _ in range(5):
            responses.append(
                client.post(
                    "/login",
                    {"email": self.victim.email, "password": "wrong"},
                    follow=True,
                )
            )
        unknown = client.post(
            "/login",
            {"email": "nobody@edify.org", "password": "wrong"},
            follow=True,
        )
        known_body = responses[0].content.decode().lower()
        for leak in ("no such account", "account does not exist", "unknown email"):
            self.assertNotIn(leak, known_body)
            self.assertNotIn(leak, unknown.content.decode().lower())


# ── The three workspaces (§5, §8, §9) ────────────────────────────────────────


class AdminWorkspaceTests(AdminOpsTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.region = Region.objects.create(name="Ops Region")
        cls.district = District.objects.create(name="Ops District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-OPS-1",
            name="Ops Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.cceo_profile = StaffProfile.objects.create(
            id="ao-cceo-sp", user=cls.cceo, title="CCEO"
        )

    def _activity(self, **overrides):
        from apps.activities.models import Activity

        today = timezone.localdate()
        payload = {
            "activity_type": "school_visit",
            "delivery_type": "staff",
            "status": "scheduled",
            "fy": get_operational_fy(today),
            "school": self.school,
            "responsible_staff_id": self.cceo_profile.id,
            "planned_date": today,
            "scheduled_date": today,
        }
        payload.update(overrides)
        return Activity.objects.create(**payload)

    def test_team_plans_shows_other_peoples_work(self):
        self._activity()
        result = AdminTeamPlansService.get(self.admin, {})
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["user"], self.cceo.name)
        self.assertTrue(result["read_only"])

    def test_team_plans_uses_the_canonical_my_plan_source(self):
        """The same activity set the user's own My Plan feed returns."""
        from apps.my_plan.services import get as my_plan_get

        self._activity()
        mine = my_plan_get(self.cceo, {"period": "fy"})
        theirs = AdminTeamPlansService.get(self.admin, {})
        self.assertEqual(
            {i["id"] for i in mine["items"]},
            {r["id"] for r in theirs["rows"]},
        )

    def test_team_plans_derives_status_from_the_canonical_helper(self):
        from apps.my_plan.services import get_activity_status_label_and_class

        activity = self._activity()
        expected, _ = get_activity_status_label_and_class(
            activity, timezone.localdate()
        )
        row = AdminTeamPlansService.get(self.admin, {})["rows"][0]
        self.assertEqual(row["status"], expected)

    def test_team_plans_excludes_terminal_activities_like_my_plan_does(self):
        self._activity(status="cancelled")
        self.assertEqual(AdminTeamPlansService.get(self.admin, {})["rows"], [])

    def test_team_plans_is_admin_only(self):
        with self.assertRaises(Forbidden):
            AdminTeamPlansService.get(self.cceo, {})

    def test_team_plans_exposes_no_mutation(self):
        """Read-only is structural: the module offers nothing that writes."""
        import apps.admin_ops.team_plans as module

        for name in dir(module):
            self.assertNotIn(
                name,
                {"start", "complete", "approve", "verify", "disburse", "reschedule"},
            )

    def test_team_plan_health_names_real_platform_defects(self):
        self._activity(planned_date=timezone.localdate() - timedelta(days=5))
        health = AdminTeamPlansService.get(self.admin, {})["health"]
        self.assertEqual(health["overdue"], 1)

    def test_admin_my_plan_holds_only_platform_operations_work(self):
        self._activity()  # a field activity exists
        AdminWorkItemService.create(
            self.admin,
            title="Restore rehearsal",
            category=WorkItemCategory.BACKUP,
            scheduled_date=timezone.localdate(),
        )
        sections = AdminMyPlanService.context(self.admin)["sections"]
        items = [i for group in sections.values() for i in group]
        self.assertEqual(len(items), 1)
        for item in items:
            self.assertIsInstance(item, AdminOperationsWorkItem)

    def test_admin_my_plan_sections_split_by_urgency(self):
        today = timezone.localdate()
        AdminWorkItemService.create(
            self.admin,
            title="Critical outage",
            category=WorkItemCategory.INCIDENT,
            severity=Severity.CRITICAL,
            scheduled_date=today,
        )
        AdminWorkItemService.create(
            self.admin,
            title="Next month's dependency bump",
            category=WorkItemCategory.CONFIGURATION,
            scheduled_date=today + timedelta(days=30),
        )
        sections = AdminMyPlanService.context(self.admin)["sections"]
        self.assertEqual(len(sections["critical_now"]), 1)
        self.assertEqual(len(sections["planned_later"]), 1)

    def test_no_admin_task_disappears_without_verification(self):
        item = AdminWorkItemService.create(
            self.admin,
            title="Rotate storage credentials",
            category=WorkItemCategory.SECURITY,
            scheduled_date=timezone.localdate(),
        )
        AdminWorkItemService.start(item.id, self.admin)
        with self.assertRaises(BadRequest):
            AdminWorkItemService.complete(item.id, self.admin, "   ")
        done = AdminWorkItemService.complete(
            item.id, self.admin, "Rotated and confirmed uploads still succeed."
        )
        self.assertEqual(done.status, WorkItemStatus.DONE)
        self.assertTrue(done.verification_note)

    def test_the_workspaces_are_admin_only(self):
        for service in (AdminPlanningService, AdminMyPlanService):
            with self.assertRaises(Forbidden):
                service.context(self.cceo)


# ── Maintenance (§23) ────────────────────────────────────────────────────────


class MaintenanceTests(AdminOpsTestBase):
    def test_a_due_template_generates_scheduled_admin_work(self):
        from apps.admin_ops.services import MaintenanceService

        MaintenanceTemplate.objects.create(
            name="Backup verification",
            frequency_days=7,
            next_due_date=timezone.localdate(),
        )
        self.assertEqual(MaintenanceService.generate_due(), 1)
        item = AdminOperationsWorkItem.objects.get(title="Backup verification")
        self.assertIsNotNone(item.scheduled_date)
        self.assertEqual(item.status, WorkItemStatus.SCHEDULED)

    def test_the_template_advances_so_a_second_run_does_nothing(self):
        from apps.admin_ops.services import MaintenanceService

        template = MaintenanceTemplate.objects.create(
            name="Dead-route scan",
            frequency_days=30,
            next_due_date=timezone.localdate(),
        )
        MaintenanceService.generate_due()
        self.assertEqual(MaintenanceService.generate_due(), 0)
        template.refresh_from_db()
        self.assertEqual(
            template.next_due_date, timezone.localdate() + timedelta(days=30)
        )

    def test_a_future_template_is_not_generated_early(self):
        from apps.admin_ops.services import MaintenanceService

        MaintenanceTemplate.objects.create(
            name="Restore rehearsal",
            frequency_days=90,
            next_due_date=timezone.localdate() + timedelta(days=5),
        )
        self.assertEqual(MaintenanceService.generate_due(), 0)

    def test_the_generation_job_is_registered_and_monitored(self):
        from apps.realtime.registry import get_spec

        spec = get_spec("admin_maintenance_generation")
        self.assertIsNotNone(spec)
        self.assertTrue(spec.idempotent)


class DefaultIncidentOwnerTests(AdminOpsTestBase):
    def test_a_new_incident_is_owned_by_the_named_operator(self):
        with override_settings(INCIDENT_OWNER_EMAIL=self.admin.email):
            incident = SystemIncidentService.report(
                title="Database latency",
                category=WorkItemCategory.PERFORMANCE,
                severity=Severity.HIGH,
                route="/api/health/ready",
                error="latency_threshold",
                environment="test",
            )

        self.assertEqual(incident.owner_id, self.admin.id)


# ── Deep links (§20) ─────────────────────────────────────────────────────────


class NotificationDeepLinkTests(AdminOpsTestBase):
    def test_an_incident_notification_opens_that_exact_incident(self):
        incident = SystemIncidentService.report(
            title="Storage unavailable",
            category=WorkItemCategory.BACKUP,
            severity=Severity.CRITICAL,
            route="/evidence",
            error="storage_down",
        )
        notification = Notification.objects.filter(
            recipient_id=self.admin.id,
            source_event_type="admin_ops.incident.detected",
        ).first()
        self.assertEqual(
            notification.target_route, f"/admin-ops/incidents/{incident.id}"
        )

    def test_a_ticket_notification_opens_the_support_queue(self):
        SupportTicketService.create(self.cceo, {"title": "Broken filter"})
        notification = Notification.objects.filter(
            recipient_id=self.admin.id, source_event_type="admin_ops.ticket.created"
        ).first()
        self.assertEqual(notification.target_route, "/admin-ops/support")

    def test_a_resolution_notification_opens_the_reporters_own_list(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Cannot upload"})
        for step in (
            TicketStatus.TRIAGED,
            TicketStatus.IN_PROGRESS,
            TicketStatus.FIX_READY,
            TicketStatus.VERIFICATION,
            TicketStatus.RESOLVED,
        ):
            SupportTicketService.transition(ticket.id, step, self.admin, "done")
        notification = Notification.objects.filter(
            recipient_id=self.cceo.id,
            source_event_type="admin_ops.ticket.resolved",
        ).first()
        self.assertEqual(notification.target_route, "/support")

    def test_no_admin_ops_notification_lands_on_a_generic_dashboard(self):
        SupportTicketService.create(self.cceo, {"title": "Anything"})
        SystemIncidentService.report(
            title="Slow route",
            category=WorkItemCategory.PERFORMANCE,
            severity=Severity.HIGH,
            route="/analytics",
            error="slo",
        )
        routes = Notification.objects.filter(
            source_event_type__startswith="admin_ops."
        ).values_list("target_route", flat=True)
        self.assertTrue(routes)
        for route in routes:
            self.assertNotEqual(route, "/dashboard")


# ── The finance and field boundary (§27) ─────────────────────────────────────


class AdminWorkFinanceBoundaryTests(AdminOpsTestBase):
    def test_admin_work_creates_no_field_budget_or_fund_request(self):
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.fund_requests.models import FundRequest, WeeklyFundRequest

        AdminWorkItemService.create(
            self.admin,
            title="Hosting upgrade",
            category=WorkItemCategory.CONFIGURATION,
            scheduled_date=timezone.localdate(),
        )
        self.assertEqual(ActivityScheduleCostLine.objects.count(), 0)
        self.assertEqual(FundRequest.objects.count(), 0)
        self.assertEqual(WeeklyFundRequest.objects.count(), 0)
        self.assertEqual(Activity.objects.count(), 0)

    def test_admin_work_items_are_not_field_activities(self):
        item = AdminWorkItemService.create(
            self.admin,
            title="Security patch review",
            category=WorkItemCategory.SECURITY,
        )
        for field in (
            "school",
            "cluster",
            "salesforce_activity_id",
            "ssa_intervention",
        ):
            self.assertFalse(hasattr(item, field))


# ── Admin super-role enforcement ─────────────────────────────────────────────


class AdminSuperRoleRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("ro-admin", "Admin", password="Admin-Pass-99")
        cls.cceo = _user("ro-cceo", "CCEO", password="Cceo-Pass-99")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_admin_post_to_a_business_route_is_not_globally_refused(self):
        response = self.client.post("/planning", {})
        self.assertNotEqual(response.status_code, 403)

    def test_htmx_business_mutation_has_no_read_only_refusal(self):
        response = self.client.post(
            "/my-plan/anything/complete", {}, HTTP_HX_REQUEST="true"
        )
        self.assertNotIn(b"admin support view is read-only", response.content.lower())

    def test_api_mutation_has_no_admin_read_only_refusal(self):
        response = self.client.post(
            "/api/activities", {}, content_type="application/json"
        )
        self.assertNotIn(b"admin support view is read-only", response.content.lower())

    def test_admin_may_still_read_business_pages(self):
        response = self.client.get("/planning")
        self.assertNotEqual(response.status_code, 403)

    def test_admin_may_mutate_its_own_operations_routes(self):
        item = AdminWorkItemService.create(
            self.admin,
            title="Scheduled maintenance",
            category=WorkItemCategory.PREVENTIVE_MAINTENANCE,
            scheduled_date=timezone.localdate(),
        )
        response = self.client.post(f"/admin-ops/work-items/{item.id}/start")
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, WorkItemStatus.IN_PROGRESS)

    def test_business_post_is_not_audited_as_read_only_blocked(self):
        from apps.audit.models import AuditLog

        self.client.post("/planning", {})
        self.assertFalse(
            AuditLog.objects.filter(action="admin_ops.readonly.blocked").exists()
        )

    def test_other_roles_are_unaffected(self):
        client = Client()
        client.force_login(self.cceo)
        response = client.post("/planning", {})
        self.assertNotEqual(response.status_code, 403)

    def test_every_role_may_report_a_problem(self):
        client = Client()
        client.force_login(self.cceo)
        response = client.post(
            "/support", {"title": "Report from a field role", "category": "other"}
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(SupportTicket.objects.filter(reporter_id=self.cceo.id).exists())


class AdminWorkspacePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("page-admin", "Admin")
        cls.cceo = _user("page-cceo", "CCEO")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_every_admin_workspace_renders(self):
        for path in (
            "/admin-ops/team-plans",
            "/admin-ops/planning",
            "/admin-ops/my-plan",
            "/admin-ops/support",
            "/admin-ops/incidents",
            "/admin-ops/maintenance",
            "/support",
        ):
            with self.subTest(path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_the_workspaces_are_closed_to_other_roles(self):
        """The house denial contract: a plain page GET by an unauthorised role
        is redirected away with a flash message rather than shown a 403 page
        (apps.core.permissions.render_access_denied). What matters here is that
        the workspace never renders."""
        client = Client()
        client.force_login(self.cceo)
        for path in (
            "/admin-ops/team-plans",
            "/admin-ops/planning",
            "/admin-ops/my-plan",
            "/data-repair",
        ):
            with self.subTest(path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(path, response["Location"])

    def test_an_unauthorised_role_is_refused_at_the_service_too(self):
        """Route gating is not the only guard -- reaching the service directly
        is refused as well."""
        with self.assertRaises(Forbidden):
            AdminTeamPlansService.get(self.cceo, {})
        with self.assertRaises(Forbidden):
            AdminPlanningService.context(self.cceo)

    def test_team_plans_identifies_itself_as_a_consolidated_view(self):
        body = self.client.get("/admin-ops/team-plans").content.decode()
        self.assertIn("Consolidated Team Plans view", body)

    def test_admin_navigation_includes_platform_and_business_workspaces(self):
        from apps.core.navigation import build_sidebar_for_user

        sidebar = build_sidebar_for_user(self.admin, "/dashboard")
        labels = {i["label"] for s in sidebar for i in s["items"]}
        self.assertIn("Admin My Plan", labels)
        self.assertIn("Team Plans", labels)
        self.assertIn("Planning", labels)
        self.assertIn("Budget", labels)
        self.assertIn("Weekly Advance Request", labels)
        self.assertIn("Disbursement Dashboard", labels)


# ── System Health integration (§37) ──────────────────────────────────────────


class AdminOpsHealthTests(AdminOpsTestBase):
    def _checks(self):
        from apps.admin_ops.health import admin_ops_health

        return {c["key"]: c for c in admin_ops_health()["checks"]}

    def test_health_is_green_on_a_healthy_platform(self):
        for check in self._checks().values():
            with self.subTest(check["key"]):
                self.assertEqual(check["severity"], "ok")

    def test_an_unacknowledged_critical_incident_turns_health_critical(self):
        incident = SystemIncidentService.report(
            title="Database unavailable",
            category=WorkItemCategory.INCIDENT,
            severity=Severity.CRITICAL,
            route="/dashboard",
            error="db_down",
        )
        SystemIncident.objects.filter(id=incident.id).update(
            first_detected_at=timezone.now() - timedelta(hours=3)
        )
        self.assertEqual(
            self._checks()["admin_ops_unacknowledged_critical"]["severity"], "critical"
        )

    def test_a_stale_untriaged_ticket_raises_a_warning(self):
        ticket = SupportTicketService.create(self.cceo, {"title": "Old problem"})
        SupportTicket.objects.filter(id=ticket.id).update(
            created_at=timezone.now() - timedelta(days=3)
        )
        self.assertEqual(
            self._checks()["admin_ops_untriaged_tickets"]["severity"], "warning"
        )

    def test_the_super_role_check_reports_a_missing_permission(self):
        from unittest.mock import patch

        from apps.core.rbac import ROLE_PERMISSIONS, EdifyRole, Permission

        # Not IA_VERIFY: that is one of the three reserved authorities Admin
        # is now expected NOT to hold, so removing it is a no-op and the check
        # correctly stays green. This needs a permission Admin really holds.
        incomplete = [
            permission
            for permission in ROLE_PERMISSIONS[EdifyRole.ADMIN]
            if permission != Permission.SYSTEM_ADMIN
        ]
        with patch.dict(ROLE_PERMISSIONS, {EdifyRole.ADMIN: incomplete}):
            check = self._checks()["admin_ops_super_role_permissions"]
        self.assertEqual(check["severity"], "critical")
        self.assertIn("system.admin", check["current_state"])

    def test_the_super_role_check_is_green_as_shipped(self):
        self.assertEqual(
            self._checks()["admin_ops_super_role_permissions"]["severity"], "ok"
        )

    def test_the_check_goes_critical_if_admin_regains_a_reserved_authority(self):
        """The drift nobody reports, because nothing visibly breaks."""
        from unittest import mock

        from apps.core.rbac import Permission, ROLE_PERMISSIONS, EdifyRole

        drifted = dict(ROLE_PERMISSIONS)
        drifted[EdifyRole.ADMIN] = list(ROLE_PERMISSIONS[EdifyRole.ADMIN]) + [
            Permission.PAYMENT_ACT
        ]
        with mock.patch.dict("apps.core.rbac.ROLE_PERMISSIONS", drifted, clear=True):
            check = self._checks()["admin_ops_super_role_permissions"]
        self.assertEqual(check["severity"], "critical")
        self.assertIn("payment.act", check["current_state"])

    def test_the_checks_reach_the_system_health_report(self):
        from apps.system_health.services import report

        self.assertIn("adminOps", report())

    def test_every_check_carries_an_owner_and_a_resolution_link(self):
        for check in self._checks().values():
            with self.subTest(check["key"]):
                self.assertTrue(check["owner"])
                self.assertTrue(check["recommended_action"])
                self.assertTrue(check["resolution_link"])


# ── Admin dashboard (§21) ────────────────────────────────────────────────────


class AdminDashboardTests(AdminOpsTestBase):
    def test_the_summary_counts_platform_work_not_programme_work(self):
        from apps.admin_ops.services import AdminOpsDashboardService

        SupportTicketService.create(self.cceo, {"title": "A problem"})
        SystemIncidentService.report(
            title="Critical outage",
            category=WorkItemCategory.INCIDENT,
            severity=Severity.CRITICAL,
            route="/dashboard",
            error="outage",
        )
        summary = AdminOpsDashboardService.summary(self.admin)
        self.assertEqual(summary["critical_incidents"], 1)
        self.assertEqual(summary["untriaged_tickets"], 1)
        self.assertEqual(len(summary["critical_now"]), 1)

    def test_the_summary_is_admin_only(self):
        from apps.admin_ops.services import AdminOpsDashboardService

        with self.assertRaises(Forbidden):
            AdminOpsDashboardService.summary(self.cceo)

    def test_the_dashboard_leads_with_platform_operations(self):
        client = Client()
        client.force_login(self.admin)
        body = client.get("/dashboard").content.decode()
        self.assertIn("Platform Operations", body)
        self.assertIn("Critical Incidents", body)
        self.assertIn("/admin-ops/my-plan", body)

    def test_every_role_sees_the_report_a_problem_control(self):
        client = Client()
        client.force_login(self.cceo)
        body = client.get("/dashboard").content.decode()
        self.assertIn("/support?route=", body)


# ── The detection edge itself (§13, §16) ─────────────────────────────────────


class DetectionMiddlewareTests(TestCase):
    """The middleware is off under test by default, so these switch it on."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("det-admin", "Admin")
        cls.cceo = _user("det-cceo", "CCEO")

    def test_it_is_off_under_test_by_default(self):
        from django.conf import settings

        self.assertFalse(settings.ADMIN_OPS_DETECTION_ENABLED)

    def test_a_correct_refusal_is_not_treated_as_drift(self):
        """Refusing a role that was never authorised is the guard working."""
        from apps.admin_ops.detection import _is_permission_drift

        request = type(
            "R", (), {"user": self.cceo, "path": "/admin-panel/roles-permissions"}
        )()
        self.assertFalse(_is_permission_drift(request))

    def test_an_admin_refusal_on_a_business_page_is_drift(self):
        """Admin carries full authority, so PAGE_PERMISSIONS grants it
        /planning and a 403 there means the guard and the matrix disagree --
        which is precisely the drift this detector exists to report.

        While Admin was a read-only support view the same 403 was the system
        working as designed, and this asserted the opposite.
        """
        from apps.admin_ops.detection import _is_permission_drift

        request = type("R", (), {"user": self.admin, "path": "/planning"})()
        self.assertTrue(_is_permission_drift(request))

    def test_a_refusal_on_an_authorised_page_is_drift(self):
        from apps.admin_ops.detection import _is_permission_drift

        # PAGE_PERMISSIONS grants the CCEO /planning, so a 403 there means the
        # guard and the matrix disagree.
        request = type("R", (), {"user": self.cceo, "path": "/planning"})()
        self.assertTrue(_is_permission_drift(request))

    def test_static_assets_are_never_route_defects(self):
        from apps.admin_ops.detection import _is_application_route

        self.assertFalse(_is_application_route("/static/css/main.css"))
        self.assertFalse(_is_application_route("/favicon.ico"))

    def test_an_unregistered_url_is_not_a_route_defect(self):
        from apps.admin_ops.detection import _is_application_route

        self.assertFalse(_is_application_route("/nothing-here-at-all"))

    def test_a_registered_route_is_watched(self):
        from apps.admin_ops.detection import _is_application_route

        self.assertTrue(_is_application_route("/dashboard"))


# ── Data Repair Center (§26) ─────────────────────────────────────────────────


class DataRepairTests(AdminOpsTestBase):
    def _resolved_incident_with_a_live_notification(self):
        incident = SystemIncidentService.report(
            title="Storage blip",
            category=WorkItemCategory.BACKUP,
            severity=Severity.HIGH,
            route="/evidence",
            error="storage_blip",
        )
        SystemIncidentService.acknowledge(incident.id, self.admin)
        # Resolve without the service so the notification is deliberately left
        # behind — the inconsistency the repair exists to correct.
        SystemIncident.objects.filter(id=incident.id).update(
            status=IncidentStatus.RESOLVED, resolved_at=timezone.now()
        )
        return incident

    def test_a_dry_run_changes_nothing(self):
        from apps.admin_ops.repair import DataRepairService
        from apps.notifications.models import Notification

        self._resolved_incident_with_a_live_notification()
        before = Notification.objects.filter(status="unread").count()
        preview = DataRepairService.dry_run(self.admin, "stale_incident_notifications")
        self.assertEqual(preview["affected"], 1)
        self.assertEqual(Notification.objects.filter(status="unread").count(), before)

    def test_a_repair_requires_a_reason(self):
        from apps.admin_ops.repair import DataRepairService

        with self.assertRaises(BadRequest):
            DataRepairService.apply(self.admin, "stale_incident_notifications", "  ")

    def test_applying_repairs_and_verifies_in_one_step(self):
        from apps.admin_ops.repair import DataRepairService

        self._resolved_incident_with_a_live_notification()
        result = DataRepairService.apply(
            self.admin, "stale_incident_notifications", "Condition no longer holds"
        )
        self.assertEqual(result["changed"], 1)
        self.assertTrue(result["verified"])

    def test_a_repair_is_idempotent(self):
        from apps.admin_ops.repair import DataRepairService

        self._resolved_incident_with_a_live_notification()
        DataRepairService.apply(self.admin, "stale_incident_notifications", "first")
        second = DataRepairService.apply(
            self.admin, "stale_incident_notifications", "second"
        )
        self.assertEqual(second["changed"], 0)

    def test_a_repair_is_audited(self):
        from apps.audit.models import AuditLog
        from apps.admin_ops.repair import DataRepairService

        self._resolved_incident_with_a_live_notification()
        DataRepairService.dry_run(self.admin, "stale_incident_notifications")
        DataRepairService.apply(self.admin, "stale_incident_notifications", "cleanup")
        actions = set(
            AuditLog.objects.filter(subject_kind="data_repair").values_list(
                "action", flat=True
            )
        )
        self.assertIn("admin_ops.repair.dry_run", actions)
        self.assertIn("admin_ops.repair.applied", actions)

    def test_business_judgement_is_referred_not_invented(self):
        """A repair needing a costing decision raises work, it does not guess."""
        from apps.admin_ops.repair import DataRepairService

        result = DataRepairService.apply(
            self.admin, "uncosted_scheduled_activities", "Chase the owner"
        )
        self.assertTrue(result["referred"])
        self.assertTrue(
            AdminOperationsWorkItem.objects.filter(
                category=WorkItemCategory.DATA_REPAIR
            ).exists()
        )

    def test_an_unknown_repair_is_refused(self):
        from apps.admin_ops.repair import DataRepairService

        with self.assertRaises(BadRequest):
            DataRepairService.dry_run(self.admin, "drop_everything")

    def test_the_repair_centre_is_admin_only(self):
        from apps.admin_ops.repair import DataRepairService

        with self.assertRaises(Forbidden):
            DataRepairService.catalogue(self.cceo)

    def test_the_page_renders(self):
        client = Client()
        client.force_login(self.admin)
        self.assertEqual(client.get("/data-repair").status_code, 200)


# ── Real-time synchronisation (§29) ──────────────────────────────────────────


class RealtimeEventTests(AdminOpsTestBase):
    """The live channel is separate from audit and notifications, so it needs
    its own proof that it actually publishes.

    Pushes are deliberately deferred to ``transaction.on_commit`` -- the UI must
    never be told about a change that has not landed -- so every test here has
    to run the commit callbacks to see them.
    """

    def _publish(self, work):
        from unittest.mock import patch

        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                work()
        return publish

    def test_a_new_ticket_pushes_a_live_event(self):
        publish = self._publish(
            lambda: SupportTicketService.create(self.cceo, {"title": "Live event test"})
        )
        types = [call.args[1]["type"] for call in publish.call_args_list]
        self.assertIn("support.ticket.created", types)

    def test_a_detected_incident_pushes_a_live_event(self):
        publish = self._publish(
            lambda: SystemIncidentService.report(
                title="Live incident",
                category=WorkItemCategory.INCIDENT,
                severity=Severity.HIGH,
                route="/dashboard",
                error="live_test",
            )
        )
        types = [call.args[1]["type"] for call in publish.call_args_list]
        self.assertIn("incident.detected", types)

    def test_a_recurrence_is_distinguishable_from_a_new_incident(self):
        payload = {
            "title": "Recurring",
            "category": WorkItemCategory.INCIDENT,
            "severity": Severity.HIGH,
            "route": "/dashboard",
            "error": "recur_test",
        }
        SystemIncidentService.report(**payload)
        publish = self._publish(lambda: SystemIncidentService.report(**payload))
        types = [call.args[1]["type"] for call in publish.call_args_list]
        self.assertIn("incident.recurred", types)
        self.assertNotIn("incident.detected", types)

    def test_the_push_reaches_admins(self):
        publish = self._publish(
            lambda: SupportTicketService.create(self.cceo, {"title": "Recipient test"})
        )
        recipients = [uid for call in publish.call_args_list for uid in call.args[0]]
        self.assertIn(self.admin.id, recipients)

    def test_nothing_is_pushed_before_the_transaction_commits(self):
        from unittest.mock import patch

        with patch("apps.realtime.bus.bus.publish_many") as publish:
            SupportTicketService.create(self.cceo, {"title": "Uncommitted"})
            self.assertFalse(publish.called)


class AnonymousAccessTests(TestCase):
    """Nothing here is reachable without a session.

    The support intake is open to every *role*, which is not the same as open
    to the public: an unauthenticated POST would have created a ticket with an
    empty reporter, and the defect beacon would have been an open endpoint for
    writing incidents.
    """

    def test_the_workspaces_redirect_an_anonymous_visitor_to_login(self):
        client = Client()
        for path in (
            "/admin-ops/team-plans",
            "/admin-ops/planning",
            "/admin-ops/my-plan",
            "/admin-ops/support",
            "/admin-ops/incidents",
            "/data-repair",
            "/support",
        ):
            with self.subTest(path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response["Location"])

    def test_an_anonymous_post_creates_no_ticket(self):
        client = Client()
        client.post("/support", {"title": "From nowhere"})
        self.assertEqual(SupportTicket.objects.count(), 0)

    def test_the_defect_beacon_is_not_an_open_endpoint(self):
        client = Client()
        client.post(
            "/support/client-defect",
            data='{"kind": "dead_button", "route": "/x", "component": "y"}',
            content_type="application/json",
        )
        self.assertEqual(SystemIncident.objects.count(), 0)


class AdminMutatesBusinessRoutesTests(TestCase):
    """Admin is a full-authority role, not a read-only support view.

    This replaces the refusal tests that guarded the retired Admin Support View
    doctrine. Admin holds every canonical permission (ROLE_PERMISSIONS[ADMIN] is
    list(Permission)), and no middleware now downgrades that to read-only, so a
    business mutation must reach the view and be judged on permissions alone.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("audit-admin", "Admin")

    def test_a_business_mutation_is_not_refused_as_read_only(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            "/activities/cms4titlt00lukcelkg9c/attendance/action", {}
        )

        # 404 here: the activity id is fabricated, so the route resolves and the
        # view runs. What matters is that it is not the blanket 403 the retired
        # middleware returned before any view was reached.
        self.assertNotEqual(
            response.status_code,
            403,
            "Admin must no longer be refused business mutations wholesale",
        )

    def test_no_read_only_refusal_is_audited(self):
        from apps.audit.models import AuditLog

        client = Client()
        client.force_login(self.admin)
        client.post("/activities/cms4titlt00lukcelkg9c/attendance/action", {})

        self.assertFalse(
            AuditLog.objects.filter(action="admin_ops.readonly.blocked").exists(),
            "the read-only refusal path is retired and must write no rows",
        )
