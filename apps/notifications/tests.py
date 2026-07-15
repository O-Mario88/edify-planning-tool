from django.test import TestCase
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.services import (
    NotificationLinkResolver,
    WorkflowNotificationService,
)


class NotificationsWorkflowTest(TestCase):
    def setUp(self):
        # Create users with different roles
        self.cceo = User.objects.create_user(
            email="cceo@edify.test",
            name="CCEO User",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.pl = User.objects.create_user(
            email="pl@edify.test",
            name="PL User",
            roles=["ProjectLeader"],
            active_role="ProjectLeader",
            password="x",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="cd@edify.test",
            name="CD User",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        self.ia = User.objects.create_user(
            email="ia@edify.test",
            name="IA User",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )

    def test_notification_link_resolver(self):
        """Verify that the resolver returns role-scoped routes to prevent role leaks."""
        # Critical School SSA
        cceo_route, _ = NotificationLinkResolver.resolve(
            "critical_school_ssa", "School", "S1", "CCEO"
        )
        pl_route, _ = NotificationLinkResolver.resolve(
            "critical_school_ssa", "School", "S1", "ProjectLeader"
        )
        cd_route, _ = NotificationLinkResolver.resolve(
            "critical_school_ssa", "School", "S1", "CountryDirector"
        )
        ia_route, _ = NotificationLinkResolver.resolve(
            "critical_school_ssa", "School", "S1", "ImpactAssessment"
        )

        self.assertEqual(cceo_route, "/planning")
        self.assertEqual(pl_route, "/my-team")
        self.assertEqual(cd_route, "/analytics")
        self.assertEqual(ia_route, "/ia/dashboard/")

        # Partner Scheduled Activity
        partner_route, _ = NotificationLinkResolver.resolve(
            "partner_scheduled_activity", "Activity", "A1", "PartnerFieldOfficer"
        )
        cceo_act_route, _ = NotificationLinkResolver.resolve(
            "partner_scheduled_activity", "Activity", "A1", "CCEO"
        )
        self.assertEqual(partner_route, "/my-plan")
        self.assertEqual(cceo_act_route, "/my-plan")

    def test_field_debrief_event_types_link_to_the_debrief_not_the_dashboard(self):
        """Every field_debrief_* event must deep-link to the real debrief (or,
        for the escalated-insight event, the dashboard where insights are
        surfaced) — not fall through to the generic /dashboard."""
        debrief_scoped_events = (
            "field_debrief_routed",
            "field_debrief_clarification_requested",
            "field_debrief_action_update",
            "field_debrief_peer_solution",
            "field_debrief_recurring_issue",
        )
        for event_type in debrief_scoped_events:
            route, label = NotificationLinkResolver.resolve(
                event_type, "field_debrief", "DEBRIEF123", "ProjectLeader"
            )
            self.assertEqual(
                route,
                "/debriefs/DEBRIEF123",
                f"{event_type} should deep-link to the debrief",
            )
            self.assertNotEqual(route, "/dashboard")
            self.assertEqual(label, "Open Debrief")

        # The escalated cross-team insight has no per-insight detail page —
        # it must land on the Field Debrief Dashboard (Intelligence
        # Highlights), not the generic dashboard.
        insight_route, insight_label = NotificationLinkResolver.resolve(
            "field_debrief_recurring_issue_escalated",
            "field_debrief_insight",
            "INSIGHT1",
            "CountryDirector",
        )
        self.assertEqual(insight_route, "/debriefs")
        self.assertNotEqual(insight_route, "/dashboard")

    def test_field_debrief_notification_trigger_sets_real_target_route(self):
        """End-to-end: WorkflowNotificationService.trigger() for a field
        debrief event must persist a Notification pointing at the debrief,
        not the generic dashboard fallback."""
        WorkflowNotificationService.trigger(
            event_type="field_debrief_clarification_requested",
            category="field_debrief",
            priority="high",
            title="Clarification needed",
            body="Your supervisor requested clarification.",
            context_type="field_debrief",
            context_id="DEBRIEF456",
            recipients=[self.cceo],
        )
        notif = Notification.objects.get(
            recipient_id=self.cceo.id,
            source_event_type="field_debrief_clarification_requested",
        )
        self.assertEqual(notif.target_route, "/debriefs/DEBRIEF456")
        self.assertEqual(notif.action_label, "Open Debrief")

    def test_workflow_notification_service_trigger(self):
        """Verify WorkflowNotificationService triggers target-scoped notifications with role-scoped attributes."""
        WorkflowNotificationService.trigger(
            event_type="critical_school_ssa",
            category="planning",
            priority="urgent",
            title="School SSA Critical",
            body="SSA score is critical for Goma Academy",
            context_type="School",
            context_id="S123",
            recipients=[self.cceo, self.pl, self.cd, self.ia],
        )

        # Assert 4 notifications created
        self.assertEqual(Notification.objects.count(), 4)

        # Assert CD's notification has country insights link
        cd_notif = Notification.objects.get(recipient_id=self.cd.id)
        self.assertEqual(cd_notif.target_route, "/analytics")
        self.assertEqual(cd_notif.action_label, "Country Insights")
        self.assertEqual(cd_notif.category, "planning")
        self.assertTrue(cd_notif.action_required)

        # Assert CCEO's notification has planning link
        cceo_notif = Notification.objects.get(recipient_id=self.cceo.id)
        self.assertEqual(cceo_notif.target_route, "/planning")
        self.assertEqual(cceo_notif.action_label, "Open Planning")

    def test_notifications_page_view(self):
        """Verify that the notification dashboard filters and KPIs render correctly."""
        # Create dummy notifications
        Notification.objects.create(
            recipient_id=self.cceo.id,
            title="Alert 1",
            priority="low",
            category="leave",
            status="unread",
        )
        Notification.objects.create(
            recipient_id=self.cceo.id,
            title="Alert 2",
            priority="urgent",
            category="finance",
            status="unread",
            action_required=True,
        )

        self.client.force_login(self.cceo)
        response = self.client.get("/notifications")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notifications Center")

        # Check KPIs
        self.assertEqual(response.context["kpis"]["total"], 2)
        self.assertEqual(response.context["kpis"]["unread"], 2)
        self.assertEqual(response.context["kpis"]["action_required"], 1)
        self.assertEqual(response.context["kpis"]["critical"], 1)

        # Apply category filter
        response_filtered = self.client.get("/notifications?category=leave")
        self.assertEqual(response_filtered.status_code, 200)
        self.assertEqual(len(response_filtered.context["notifications"]), 1)
        self.assertEqual(
            response_filtered.context["notifications"][0].category, "leave"
        )
