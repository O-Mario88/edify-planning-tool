"""Phase 2c: the integration framework's contracts under test.

Pins: flags off means nothing enqueues (the manual flow remains the law);
a manually pasted reference always wins and is never overwritten; the full
loop (enqueue → drain → external id stored → sync ledger) works when the
transport succeeds; and an enabled-but-unconfigured integration fails
loudly into the dead-letter queue instead of pretending.
"""

from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.activities.models import Activity
from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import drain

from .models import IntegrationSync, IntegrationSyncStatus
from .services import (
    IntegrationNotConfigured,
    enqueue_activity_salesforce_sync,
    push_to_external,
)


def _activity(**overrides):
    defaults = dict(
        activity_type="school_visit",
        status="ia_verified",
        planned_date=date(2026, 10, 20),
        fy="2027",
    )
    defaults.update(overrides)
    return Activity.objects.create(**defaults)


# Other apps (Business Transformation's SSA/Activity bridge, for one) put
# their own events on the shared outbox from model signals, so these tests
# assert on the salesforce event type they own, never the global table.
SF_EVENT = "integrations.salesforce.activity"


class FlagGateTests(TestCase):
    def test_disabled_means_nothing_enqueues(self):
        activity = _activity()
        enqueue_activity_salesforce_sync(activity.id)
        self.assertEqual(OutboxEvent.objects.filter(event_type=SF_EVENT).count(), 0)

    @override_settings(SALESFORCE_SYNC_ENABLED=True)
    def test_enabled_enqueues_one_converging_event(self):
        activity = _activity()
        enqueue_activity_salesforce_sync(activity.id)
        enqueue_activity_salesforce_sync(activity.id)
        self.assertEqual(OutboxEvent.objects.filter(event_type=SF_EVENT).count(), 1)
        event = OutboxEvent.objects.get(event_type=SF_EVENT)
        self.assertEqual(event.idempotency_key, f"sf:activity:{activity.id}")


@override_settings(SALESFORCE_SYNC_ENABLED=True)
class SyncLoopTests(TestCase):
    def test_a_manual_reference_always_wins(self):
        activity = _activity(salesforce_activity_id="SF-MANUAL-1")
        enqueue_activity_salesforce_sync(activity.id)
        with patch("apps.integrations.services.push_to_external") as push:
            drain(worker_id="t")
            push.assert_not_called()
        activity.refresh_from_db()
        self.assertEqual(activity.salesforce_activity_id, "SF-MANUAL-1")
        sync = IntegrationSync.objects.get()
        self.assertEqual(sync.status, IntegrationSyncStatus.RECONCILED_MANUAL)
        self.assertEqual(sync.external_id, "SF-MANUAL-1")

    def test_a_successful_push_stores_the_returned_reference(self):
        activity = _activity()
        enqueue_activity_salesforce_sync(activity.id)
        with patch(
            "apps.integrations.services.push_to_external",
            return_value="SF-API-42",
        ):
            result = drain(worker_id="t")
        # The drain also processes whatever other apps enqueued (storing the
        # reference re-saves the Activity, which enqueues the BT bridge's
        # event mid-cycle), so pin the salesforce event's own outcome.
        self.assertGreaterEqual(result["succeeded"], 1)
        self.assertEqual(
            OutboxEvent.objects.get(event_type=SF_EVENT).status,
            OutboxStatus.SUCCEEDED,
        )
        activity.refresh_from_db()
        self.assertEqual(activity.salesforce_activity_id, "SF-API-42")
        sync = IntegrationSync.objects.get()
        self.assertEqual(sync.status, IntegrationSyncStatus.SUCCEEDED)
        self.assertIsNotNone(sync.synced_at)

    def test_enabled_but_unconfigured_fails_loudly_never_silently(self):
        activity = _activity()
        enqueue_activity_salesforce_sync(activity.id)
        OutboxEvent.objects.update(max_attempts=1)
        result = drain(worker_id="t")
        self.assertGreaterEqual(result["failed"], 1)
        event = OutboxEvent.objects.get(event_type=SF_EVENT)
        self.assertEqual(event.status, OutboxStatus.DEAD)
        self.assertIn("transport is not configured", event.last_error)
        # The activity inside Edify is untouched: verified work never
        # un-verifies because an external system was unreachable. (The
        # ledger's FAILED row rolls back with the failed attempt by design —
        # the dead-lettered event carries the error and the replay path.)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(activity.salesforce_activity_id, None)

    def test_the_transport_seam_refuses_without_credentials(self):
        with self.assertRaises(IntegrationNotConfigured):
            push_to_external("salesforce", "activity", {})
