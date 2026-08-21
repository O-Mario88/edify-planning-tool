"""The durable outbox's delivery guarantees under test.

Pins: transactional enqueue (the event dies with a rolled-back business
write), enqueue-time idempotency, claim exclusivity, per-event isolation
(one poisoned event never takes the batch), deterministic backoff,
dead-lettering with a visible error, crash-claim recovery, and replay.
"""

from datetime import timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from .models import OutboxEvent, OutboxStatus
from .services import (
    _HANDLERS,
    _backoff_seconds,
    _claim_batch,
    drain,
    enqueue,
    register,
    requeue_dead,
)


class HandlerHarness(TestCase):
    """Registers scratch handlers for the duration of one test."""

    def setUp(self):
        self._snapshot = dict(_HANDLERS)
        self.calls = []

        @register("test.ok", idempotency_note="Appends to a test list.")
        def _ok(payload):
            self.calls.append(payload)

        @register("test.boom", idempotency_note="Raises for the test.")
        def _boom(payload):
            raise RuntimeError("boom")

    def tearDown(self):
        _HANDLERS.clear()
        _HANDLERS.update(self._snapshot)


class EnqueueTests(HandlerHarness):
    def test_enqueue_rides_the_business_transaction(self):
        try:
            with transaction.atomic():
                enqueue("test.ok", {"n": 1})
                raise RuntimeError("business write failed")
        except RuntimeError:
            pass
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_an_explicit_key_converges_instead_of_duplicating(self):
        first = enqueue("test.ok", {"n": 1}, idempotency_key="converge:1")
        second = enqueue("test.ok", {"n": 2}, idempotency_key="converge:1")
        self.assertEqual(first.id, second.id)
        self.assertEqual(OutboxEvent.objects.count(), 1)
        # The original payload stands — the event is a state to reach.
        self.assertEqual(OutboxEvent.objects.get().payload, {"n": 1})

    def test_a_handler_requires_an_idempotency_note(self):
        with self.assertRaises(ValueError):
            register("test.undocumented", idempotency_note="  ")


class DrainTests(HandlerHarness):
    def test_success_path_delivers_once_and_records_it(self):
        enqueue("test.ok", {"n": 1})
        result = drain(worker_id="w1")
        self.assertEqual(result["succeeded"], 1)
        event = OutboxEvent.objects.get()
        self.assertEqual(event.status, OutboxStatus.SUCCEEDED)
        self.assertIsNotNone(event.succeeded_at)
        self.assertEqual(self.calls, [{"n": 1}])
        # A second drain finds nothing due.
        self.assertEqual(drain(worker_id="w1")["processed"], 0)

    def test_a_poisoned_event_fails_alone_and_backs_off(self):
        enqueue("test.boom", {})
        enqueue("test.ok", {"n": 2})
        result = drain(worker_id="w1")
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        poisoned = OutboxEvent.objects.get(event_type="test.boom")
        self.assertEqual(poisoned.status, OutboxStatus.PENDING)
        self.assertEqual(poisoned.attempts, 1)
        self.assertIn("boom", poisoned.last_error)
        self.assertGreater(poisoned.next_attempt_at, timezone.now())

    def test_backoff_doubles_and_caps(self):
        self.assertEqual(_backoff_seconds(1), 60)
        self.assertEqual(_backoff_seconds(2), 120)
        self.assertEqual(_backoff_seconds(10), 3600)

    def test_exhausted_events_dead_letter_with_the_error(self):
        event = enqueue("test.boom", {})
        OutboxEvent.objects.filter(id=event.id).update(max_attempts=1)
        drain(worker_id="w1")
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.DEAD)
        self.assertIn("boom", event.last_error)

    def test_an_unregistered_event_type_is_a_visible_failure(self):
        event = enqueue("test.unknown", {})
        OutboxEvent.objects.filter(id=event.id).update(max_attempts=1)
        drain(worker_id="w1")
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.DEAD)
        self.assertIn("No handler registered", event.last_error)

    def test_a_crashed_workers_claim_is_reclaimable(self):
        event = enqueue("test.ok", {"n": 3})
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxStatus.PROCESSING,
            locked_by="dead-worker",
            locked_until=timezone.now() - timedelta(minutes=1),
        )
        result = drain(worker_id="w2")
        self.assertEqual(result["succeeded"], 1)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.SUCCEEDED)

    def test_a_live_claim_is_not_stolen(self):
        event = enqueue("test.ok", {"n": 4})
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxStatus.PROCESSING,
            locked_by="busy-worker",
            locked_until=timezone.now() + timedelta(minutes=4),
        )
        result = drain(worker_id="w2")
        self.assertEqual(result["processed"], 0)

    def test_handler_side_effects_roll_back_with_the_failed_attempt(self):
        # A handler that writes then raises must leave nothing behind —
        # each attempt runs in its own transaction.
        @register(
            "test.partial",
            idempotency_note="Writes a marker event then raises (test only).",
        )
        def _partial(payload):
            OutboxEvent.objects.create(
                event_type="test.marker",
                idempotency_key="marker:1",
                next_attempt_at=timezone.now(),
            )
            raise RuntimeError("after write")

        enqueue("test.partial", {})
        drain(worker_id="w1")
        self.assertFalse(OutboxEvent.objects.filter(event_type="test.marker").exists())


class ReplayTests(HandlerHarness):
    def test_requeue_dead_resets_the_attempt_budget(self):
        event = enqueue("test.boom", {})
        OutboxEvent.objects.filter(id=event.id).update(max_attempts=1)
        drain(worker_id="w1")
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.DEAD)

        self.assertEqual(requeue_dead(), 1)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.PENDING)
        self.assertEqual(event.attempts, 0)

        # Fixed cause → the replay delivers.
        _HANDLERS["test.boom"]["func"] = lambda payload: self.calls.append("recovered")
        drain(worker_id="w1")
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxStatus.SUCCEEDED)
        self.assertIn("recovered", self.calls)


class HealthTests(HandlerHarness):
    def test_dead_letters_surface_as_a_critical_check(self):
        from .health import outbox_health

        event = enqueue("test.boom", {})
        OutboxEvent.objects.filter(id=event.id).update(max_attempts=1)
        drain(worker_id="w1")
        health = outbox_health()
        self.assertEqual(health["summary"]["dead"], 1)
        keys = [c["key"] for c in health["checks"]]
        self.assertIn("outbox_dead_letters", keys)

    def test_the_system_health_report_carries_the_outbox_block(self):
        from apps.system_health.services import report

        data = report()
        self.assertIn("outbox", data)
        self.assertIn("summary", data["outbox"])


class SchedulerRegistrationTests(TestCase):
    def test_the_drain_job_is_registered_with_a_matching_function(self):
        from apps.realtime import jobs
        from apps.realtime.registry import JOB_REGISTRY

        spec = next(s for s in JOB_REGISTRY if s.name == "outbox_drain")
        self.assertTrue(spec.idempotent)
        self.assertTrue(callable(jobs.outbox_drain_job))


class CrashReclaimTests(HandlerHarness):
    """A worker that dies mid-handler must still exhaust its retries.

    The reclaim path returned a stranded PROCESSING row to the queue without
    counting the attempt, so an event whose handler hard-kills its worker
    (OOM, SIGKILL, a deploy restart) was retried every five minutes forever:
    `max_attempts` was never reached, so it never dead-lettered, never
    notified an Admin, and never appeared in the dead-letter health check. It
    was invisible except as a backlog that would not drain.
    """

    def _stranded(self, *, attempts, max_attempts=8):
        """An event a dead worker left claimed, with an expired lock."""
        enqueue("test.ok", {"n": attempts})
        event = OutboxEvent.objects.latest("created_at")
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxStatus.PROCESSING,
            locked_by="dead-worker",
            locked_until=timezone.now() - timedelta(minutes=10),
            attempts=attempts,
        )
        return event

    def test_a_crash_reclaim_counts_as_an_attempt(self):
        event = self._stranded(attempts=0)
        _claim_batch(batch_size=10, worker_id="live-worker")
        event.refresh_from_db()
        self.assertEqual(event.attempts, 1)

    def test_a_poison_pill_eventually_dead_letters_instead_of_looping(self):
        event = self._stranded(attempts=7, max_attempts=8)
        _claim_batch(batch_size=10, worker_id="live-worker")
        event.refresh_from_db()
        self.assertEqual(event.attempts, 8)
        self.assertEqual(event.status, OutboxStatus.DEAD)
        self.assertEqual(event.locked_by, "")

    def test_a_healthy_pending_event_is_not_charged_an_attempt(self):
        enqueue("test.ok", {"n": "fresh"})
        event = OutboxEvent.objects.latest("created_at")
        _claim_batch(batch_size=10, worker_id="live-worker")
        event.refresh_from_db()
        self.assertEqual(event.attempts, 0)
        self.assertEqual(event.status, OutboxStatus.PROCESSING)
