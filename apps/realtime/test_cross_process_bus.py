import queue
from collections import defaultdict
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.realtime.bus import _EventBus


class _Broker:
    def __init__(self):
        self.subscribers = defaultdict(list)

    def client(self):
        return _FakeRedis(self)


class _FakeRedis:
    def __init__(self, broker):
        self.broker = broker

    def pubsub(self, **_kwargs):
        return _FakePubSub(self.broker)

    def publish(self, channel, payload):
        for subscriber in list(self.broker.subscribers[channel]):
            subscriber.messages.put(
                {"type": "message", "channel": channel, "data": payload}
            )


class _FakePubSub:
    def __init__(self, broker):
        self.broker = broker
        self.channels = []
        self.messages = queue.Queue()

    def subscribe(self, *channels):
        for channel in channels:
            self.channels.append(channel)
            self.broker.subscribers[channel].append(self)

    def get_message(self, **_kwargs):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        for channel in self.channels:
            self.broker.subscribers[channel].remove(self)
        self.channels.clear()


class _UnavailableRedis:
    def pubsub(self, **_kwargs):
        raise ConnectionError("cache unavailable")

    def publish(self, *_args, **_kwargs):
        raise ConnectionError("cache unavailable")


class CrossProcessEventBusTests(SimpleTestCase):
    def test_transport_failure_after_a_control_message_keeps_local_delivery(self):
        event_bus = _EventBus(redis_client=_Broker().client(), source_id="local")
        subscription = event_bus.subscribe("user-1")
        try:
            with patch.object(
                subscription.pubsub,
                "get_message",
                side_effect=[{"type": "subscribe"}, ConnectionError("cache lost")],
            ):
                with self.assertRaises(queue.Empty):
                    subscription.get_nowait()
            self.assertIsNone(subscription.pubsub)
            event_bus.publish("user-1", {"type": "local-after-outage"})
            self.assertEqual(subscription.get_nowait(), {"type": "local-after-outage"})
        finally:
            event_bus.unsubscribe("user-1", subscription)

    def test_event_created_on_one_replica_reaches_another_replica(self):
        broker = _Broker()
        first = _EventBus(redis_client=broker.client(), source_id="first")
        second = _EventBus(redis_client=broker.client(), source_id="second")
        subscription = second.subscribe("user-1")
        try:
            first.publish("user-1", {"type": "activity.updated", "value": 1})
            self.assertEqual(
                subscription.get_nowait(),
                {"type": "activity.updated", "value": 1},
            )
        finally:
            second.unsubscribe("user-1", subscription)

    def test_source_replica_receives_one_copy_not_local_plus_shared(self):
        broker = _Broker()
        event_bus = _EventBus(redis_client=broker.client(), source_id="source")
        subscription = event_bus.subscribe("user-1")
        try:
            event_bus.publish("user-1", {"type": "one-copy"})
            self.assertEqual(subscription.get_nowait(), {"type": "one-copy"})
            with self.assertRaises(queue.Empty):
                subscription.get_nowait()
        finally:
            event_bus.unsubscribe("user-1", subscription)

    def test_shared_transport_failure_keeps_bounded_local_delivery(self):
        event_bus = _EventBus(redis_client=_UnavailableRedis(), source_id="local")
        subscription = event_bus.subscribe("user-1")
        try:
            for number in range(300):
                event_bus.publish("user-1", {"number": number})
            received = []
            while True:
                try:
                    received.append(subscription.get_nowait())
                except queue.Empty:
                    break
            self.assertEqual(len(received), 256)
            self.assertEqual(received[0], {"number": 44})
            self.assertEqual(received[-1], {"number": 299})
        finally:
            event_bus.unsubscribe("user-1", subscription)
