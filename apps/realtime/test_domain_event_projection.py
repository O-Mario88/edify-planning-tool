"""Committed audit/notification events must reach the durable realtime seam."""

from __future__ import annotations

from django.db import transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.audit.models import DomainEventLog
from apps.audit.services import log as audit_log
from apps.notifications.models import Notification
from apps.notifications.services import WorkflowNotificationService
from apps.realtime.bus import bus


class DomainEventProjectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="event-projection@edify.test",
            name="Event Projection",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )

    def test_committed_audit_is_durable_and_realtime_visible_to_its_actor(self):
        subscription = bus.subscribe(self.user.id)
        try:
            with self.captureOnCommitCallbacks(execute=True):
                audit_log(
                    action="school.updated",
                    subject_kind="School",
                    subject_id="SCH-EVENT",
                    actor_id=self.user.id,
                    actor_role="Admin",
                    payload={"field": "name"},
                )

            event = subscription.get_nowait()
            self.assertEqual(event["type"], "school.updated")
            domain_event = DomainEventLog.objects.get(event_type="school.updated")
            self.assertEqual(domain_event.aggregate_id, "SCH-EVENT")
            self.assertEqual(domain_event.payload["data"], {"field": "name"})
        finally:
            bus.unsubscribe(self.user.id, subscription)

    def test_rolled_back_audit_never_reaches_the_event_stream(self):
        with transaction.atomic():
            audit_log(
                action="school.rolled_back",
                subject_kind="School",
                subject_id="SCH-ROLLBACK",
                actor_id=self.user.id,
                actor_role="Admin",
            )
            transaction.set_rollback(True)

        self.assertFalse(
            DomainEventLog.objects.filter(event_type="school.rolled_back").exists()
        )

    def test_notification_delivery_is_deduped_audited_and_pushed_after_commit(self):
        subscription = bus.subscribe(self.user.id)
        try:
            with self.captureOnCommitCallbacks(execute=True):
                notifications = WorkflowNotificationService.trigger(
                    event_type="evidence_returned",
                    category="evidence",
                    priority="high",
                    title="Evidence needs work",
                    body="Please correct the returned evidence.",
                    context_type="Activity",
                    context_id="ACT-EVENT",
                    recipients=[self.user.id, self.user.id],
                )

            self.assertEqual(len(notifications), 1)
            self.assertEqual(Notification.objects.count(), 1)
            event = subscription.get_nowait()
            self.assertEqual(event["type"], "notification.evidence_returned")
            self.assertTrue(
                DomainEventLog.objects.filter(
                    event_type="notification.evidence_returned",
                    aggregate_id="ACT-EVENT",
                ).exists()
            )
        finally:
            bus.unsubscribe(self.user.id, subscription)
