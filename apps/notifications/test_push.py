"""Phone notifications: the bell's notification, pushed to the user's devices.

Owner's brief, 2026-10-10: "implement the notification requirement as a real
mobile notification architecture ... Do not implement a fake notification
system", with its reliability list: permission denied, granted, later
revoked; logged out; another phone; multiple devices; duplicate push; stale
notification; deleted record; expired session; poor network; restored
network.

What a server can prove is proved here: the encryption against the
standard's own worked example, who is sent what and when, that nothing is
sent twice, what happens when a device has gone, and where a tap leads. What
only a phone can show — the tray and the lock screen — is the service
worker's, whose handlers are pinned by name.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ec
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications import push, webpush
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.services import WorkflowNotificationService
from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import drain
from apps.schools.models import School

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
PUBLIC, PRIVATE = webpush.generate_vapid_keys()
KEYS = override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY=PUBLIC,
    WEBPUSH_VAPID_PRIVATE_KEY=PRIVATE,
    WEBPUSH_SUBJECT="mailto:test@edify.org",
    WEBPUSH_EAGER=False,
)
# A browser's two keys, as a subscription hands them over.
P256DH, _unused = webpush.generate_vapid_keys()
AUTH = webpush._b64url(b"0123456789abcdef")
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-one"
OTHER_ENDPOINT = "https://updates.push.services.mozilla.com/wpush/v2/device-two"


class Answer:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def person(email, role="CCEO"):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


def notify(user, *, title="Training assigned to you", context_id="ctx-1", **extra):
    values = {
        "event_type": "push_test",
        "category": "training",
        "priority": "normal",
        "title": title,
        "body": "In-school training at Kasubi Primary.",
        "context_type": "system",
        "context_id": context_id,
        "recipients": [user],
    }
    values.update(extra)
    (notification,) = WorkflowNotificationService.trigger(**values)
    return notification


class EncryptionTest(TestCase):
    def test_a_message_is_encrypted_exactly_as_the_standard_s_example(self):
        """RFC 8291, section 5 and appendix A: the same keys, salt and
        plaintext give the same bytes, so a browser can read what is sent."""
        sender = ec.derive_private_key(
            int.from_bytes(
                webpush._unb64url("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"
            ),
            ec.SECP256R1(),
        )

        body = webpush.encrypt(
            b"When I grow up, I want to be a watermelon",
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6"
            "SRpkNtoIAiw4",
            "BTBZMqHH6r4Tts7J_aSIgg",
            _sender_key=sender,
            _salt=webpush._unb64url("DGv6ra1nlYgDCS1FRnbzlw"),
        )

        self.assertEqual(
            webpush._b64url(body),
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
            "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt"
            "2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
        )

    def test_every_message_is_sealed_with_a_key_and_salt_of_its_own(self):
        first = webpush.encrypt(b"hello", P256DH, AUTH)
        second = webpush.encrypt(b"hello", P256DH, AUTH)

        self.assertNotEqual(first, second)

    def test_only_a_browser_s_push_service_is_ever_posted_to(self):
        """The endpoint is what a browser sent us: it must not point this
        server at anything else."""
        for endpoint in (
            ENDPOINT,
            OTHER_ENDPOINT,
            "https://web.push.apple.com/QGk3",
            "https://wns2-by3p.notify.windows.com/w/?token=1",
        ):
            self.assertTrue(webpush.allowed_endpoint(endpoint), endpoint)
        for endpoint in (
            "http://fcm.googleapis.com/fcm/send/x",
            "https://127.0.0.1/admin",
            "https://internal.service.local/hook",
            "https://fcm.googleapis.com.attacker.example/x",
            "https://user:pass@fcm.googleapis.com/x",
            "",
            "not a url",
        ):
            self.assertFalse(webpush.allowed_endpoint(endpoint), endpoint)

    def test_push_is_off_until_the_deployment_has_its_keys(self):
        self.assertFalse(webpush.configured())
        with KEYS:
            self.assertTrue(webpush.configured())
            self.assertEqual(webpush.application_server_key(), PUBLIC)

    @KEYS
    def test_a_request_is_signed_encrypted_and_never_follows_a_redirect(self):
        import jwt

        with mock.patch("requests.post", return_value=Answer(201)) as post:
            status = webpush.send(
                webpush.Target(ENDPOINT, P256DH, AUTH),
                {"title": "Hello"},
                urgency="high",
                topic="abc123",
            )

        self.assertEqual(status, 201)
        (url,), sent = post.call_args
        self.assertEqual(url, ENDPOINT)
        self.assertFalse(sent["allow_redirects"])
        headers = sent["headers"]
        self.assertEqual(headers["Content-Encoding"], "aes128gcm")
        self.assertEqual((headers["Urgency"], headers["Topic"]), ("high", "abc123"))
        scheme, token, key = headers["Authorization"].replace(",", "").split()
        self.assertEqual((scheme, key), ("vapid", f"k={PUBLIC}"))
        claims = jwt.decode(
            token[2:],
            webpush._private_key().public_key(),
            algorithms=["ES256"],
            audience="https://fcm.googleapis.com",
        )
        self.assertEqual(claims["sub"], "mailto:test@edify.org")
        # The body is ciphertext: the words are not in it.
        self.assertNotIn(b"Hello", sent["data"])

    @KEYS
    def test_what_the_push_service_answers_decides_what_happens_next(self):
        target = webpush.Target(ENDPOINT, P256DH, AUTH)
        for status, error in (
            (404, webpush.PushGone),
            (410, webpush.PushGone),
            (400, webpush.PushRejected),
            (403, webpush.PushRejected),
            (413, webpush.PushRejected),
            (429, webpush.PushUnavailable),
            (503, webpush.PushUnavailable),
        ):
            with self.subTest(status=status):
                with mock.patch("requests.post", return_value=Answer(status)):
                    with self.assertRaises(error):
                        webpush.send(target, {"title": "x"})

    @KEYS
    def test_no_network_is_a_reason_to_try_again(self):
        import requests

        with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(webpush.PushUnavailable):
                webpush.send(webpush.Target(ENDPOINT, P256DH, AUTH), {"title": "x"})


@KEYS
class SubscriptionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.brian = person("brian@edify.org")

    def test_a_device_is_one_row_however_often_it_subscribes(self):
        first, created = push.subscribe(
            self.amina, ENDPOINT, P256DH, AUTH, "Android Chrome"
        )
        again, created_again = push.subscribe(self.amina, ENDPOINT, P256DH, AUTH)

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, again.id)
        self.assertEqual(first.device_label, "Android · Chrome")
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_a_phone_that_changes_hands_stops_telling_the_last_user(self):
        """ "Logged in on another phone": the device belongs to whoever
        subscribed on it last."""
        push.subscribe(self.amina, ENDPOINT, P256DH, AUTH)
        push.subscribe(self.brian, ENDPOINT, P256DH, AUTH)

        self.assertFalse(push.live_subscriptions(self.amina.id).exists())
        self.assertEqual(push.live_subscriptions(self.brian.id).count(), 1)

    def test_a_subscription_that_is_not_one_is_refused(self):
        for endpoint, key, secret in (
            ("https://example.com/hook", P256DH, AUTH),
            (ENDPOINT, "not-a-key", AUTH),
            (ENDPOINT, P256DH, webpush._b64url(b"short")),
            (ENDPOINT, "", ""),
        ):
            with self.subTest(endpoint=endpoint, key=key[:8]):
                with self.assertRaises(push.InvalidSubscription):
                    push.subscribe(self.amina, endpoint, key, secret)

    def test_signing_out_on_a_device_ends_that_device_s_notifications(self):
        push.subscribe(self.amina, ENDPOINT, P256DH, AUTH)
        push.subscribe(self.amina, OTHER_ENDPOINT, P256DH, AUTH)

        push.unsubscribe(self.amina, ENDPOINT, "signed_out")

        live = push.live_subscriptions(self.amina.id)
        self.assertEqual([s.endpoint for s in live], [OTHER_ENDPOINT])
        gone = PushSubscription.objects.get(endpoint=ENDPOINT)
        self.assertEqual(gone.revoked_reason, "signed_out")
        # Turning it on again on the same device brings the row back.
        push.subscribe(self.amina, ENDPOINT, P256DH, AUTH)
        self.assertEqual(push.live_subscriptions(self.amina.id).count(), 2)

    def test_nobody_can_turn_off_somebody_else_s_device(self):
        push.subscribe(self.amina, ENDPOINT, P256DH, AUTH)

        self.assertEqual(push.unsubscribe(self.brian, ENDPOINT), 0)
        self.assertEqual(push.live_subscriptions(self.amina.id).count(), 1)


@KEYS
class DeliveryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.brian = person("brian@edify.org")
        cls.phone, _ = push.subscribe(cls.amina, ENDPOINT, P256DH, AUTH)

    def events(self):
        return OutboxEvent.objects.filter(event_type=push.EVENT)

    def send(self, answer=None, **kwargs):
        answer = answer or Answer(201)
        with mock.patch("requests.post", return_value=answer, **kwargs) as post:
            result = drain()
        return post, result

    def test_every_notification_is_queued_for_each_of_the_user_s_devices(self):
        push.subscribe(self.amina, OTHER_ENDPOINT, P256DH, AUTH)

        notification = notify(self.amina)

        self.assertEqual(self.events().count(), 2)
        post, result = self.send()
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(
            sorted(call.args[0] for call in post.call_args_list),
            sorted([ENDPOINT, OTHER_ENDPOINT]),
        )
        self.phone.refresh_from_db()
        self.assertIsNotNone(self.phone.last_success_at)
        self.assertEqual(notification.status, "unread")

    def test_the_phone_is_told_the_bell_s_own_words_and_where_a_tap_goes(self):
        notification = notify(self.amina, priority="urgent")

        payload = push.payload_for(notification)

        self.assertEqual(payload["title"], "Training assigned to you")
        self.assertEqual(payload["body"], "In-school training at Kasubi Primary.")
        self.assertEqual(payload["url"], f"/notifications/{notification.id}/open")
        self.assertEqual(payload["tag"], f"edify-{notification.id}")
        self.assertEqual(payload["priority"], "urgent")

    def test_a_notification_made_any_other_way_is_pushed_too(self):
        """Not every notice goes through the workflow service."""
        Notification.objects.create(
            recipient_id=self.amina.id, title="Direct", category="general"
        )

        self.assertEqual(self.events().count(), 1)

    def test_somebody_with_no_device_is_sent_nothing(self):
        notify(self.brian)

        self.assertEqual(self.events().count(), 0)

    def test_nothing_is_queued_where_push_is_not_set_up(self):
        with override_settings(WEBPUSH_VAPID_PRIVATE_KEY=""):
            notify(self.amina)

        self.assertEqual(self.events().count(), 0)

    def test_one_notification_is_one_push_however_often_it_is_asked_for(self):
        """ "Duplicate push"."""
        notification = notify(self.amina)
        push.enqueue(notification)
        push.enqueue(notification)

        self.assertEqual(self.events().count(), 1)
        post, _result = self.send()
        self.assertEqual(post.call_count, 1)
        # Draining again sends nothing more.
        post, result = self.send()
        self.assertEqual((post.call_count, result["processed"]), (0, 0))

    def test_a_condition_that_comes_round_again_rings_again_once(self):
        notify(self.amina)
        self.send()

        again = notify(self.amina)  # the same unresolved condition, re-fired

        self.assertEqual(
            Notification.objects.filter(recipient_id=self.amina.id).count(), 1
        )
        self.assertEqual(again.reminder_count, 1)
        self.assertEqual(self.events().count(), 2)
        post, _result = self.send()
        self.assertEqual(post.call_count, 1)

    def test_reading_or_resolving_never_pushes(self):
        notification = notify(self.amina)
        self.events().delete()

        notification.status = "read"
        notification.save(update_fields=["status", "updated_at"])
        notification.priority = "urgent"
        notification.save(update_fields=["priority", "updated_at"])

        self.assertEqual(self.events().count(), 0)

    def test_a_notification_read_before_the_phone_is_told_is_not_sent(self):
        """ "Stale notification"."""
        notification = notify(self.amina)
        Notification.objects.filter(id=notification.id).update(status="read")

        post, result = self.send()

        self.assertEqual(post.call_count, 0)
        self.assertEqual(result["succeeded"], 1)

    def test_yesterday_s_notification_is_not_news(self):
        notification = notify(self.amina)
        Notification.objects.filter(id=notification.id).update(
            created_at=timezone.now() - timedelta(hours=30)
        )

        post, _result = self.send()

        self.assertEqual(post.call_count, 0)

    def test_a_device_that_has_gone_is_forgotten_and_not_tried_again(self):
        """ "Permission later revoked": the push service answers 410."""
        notify(self.amina)

        _post, result = self.send(Answer(410, "expired"))

        self.assertEqual(result["succeeded"], 1)
        self.phone.refresh_from_db()
        self.assertIsNotNone(self.phone.revoked_at)
        self.assertEqual(self.phone.revoked_reason, "gone")
        # The next notification is queued for nobody.
        notify(self.amina, context_id="ctx-2")
        self.assertEqual(self.events().filter(status=OutboxStatus.PENDING).count(), 0)

    def test_poor_network_is_retried_and_restored_network_delivers(self):
        """ "Poor network" then "restored network"."""
        import requests

        notify(self.amina)

        with mock.patch("requests.post", side_effect=requests.ConnectTimeout("slow")):
            result = drain()
        self.assertEqual(result["failed"], 1)
        event = self.events().get()
        self.assertEqual(event.status, OutboxStatus.PENDING)
        self.assertGreater(event.next_attempt_at, timezone.now())
        self.phone.refresh_from_db()
        self.assertIsNone(self.phone.revoked_at)

        # The network is back and the backoff has passed.
        self.events().update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        post, result = self.send()
        self.assertEqual((post.call_count, result["succeeded"]), (1, 1))

    def test_a_refusal_is_recorded_and_not_retried(self):
        notify(self.amina)

        _post, result = self.send(Answer(403, "bad key"))

        self.assertEqual(result["succeeded"], 1)
        self.phone.refresh_from_db()
        self.assertEqual(self.phone.failure_count, 1)
        self.assertIn("403", self.phone.last_error)
        self.assertIsNone(self.phone.revoked_at)

    def test_a_device_someone_else_has_since_signed_in_on_is_not_sent_it(self):
        notify(self.amina)
        push.subscribe(self.brian, ENDPOINT, P256DH, AUTH)

        post, _result = self.send()

        self.assertEqual(post.call_count, 0)

    def test_sending_at_once_and_the_minute_s_drain_never_send_the_same_one(self):
        notification = notify(self.amina)
        keys = [f"push:{notification.id}:0:{self.phone.id}"]

        with mock.patch("requests.post", return_value=Answer(201)) as post:
            sent = push.deliver(keys)
            drained = drain()

        self.assertEqual(sent, {"sent": 1, "failed": 0})
        self.assertEqual(drained["processed"], 0)
        self.assertEqual(post.call_count, 1)

    def test_a_message_s_notification_is_pushed_like_any_other(self):
        notify(
            self.amina,
            event_type="message",
            category="messages",
            title="New message from Mary",
            context_type="Message",
            context_id="msg-1",
        )

        post, _result = self.send()

        self.assertEqual(post.call_count, 1)


class OpenTest(TestCase):
    """What a tap does: on the phone's lock screen and in the app."""

    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.brian = person("brian@edify.org")
        cls.school = School.objects.create(school_id="PUSH-1", name="Kasubi Primary")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.amina, backend=BACKEND)

    def school_notice(self, user=None, context_id=None):
        return notify(
            user or self.amina,
            event_type="critical_school_ssa",
            category="ssa",
            title="School SSA intervention requires follow-up",
            context_type="School",
            context_id=context_id or self.school.id,
        )

    def test_a_tap_marks_it_read_and_lands_on_the_record(self):
        notification = self.school_notice()
        Notification.objects.filter(id=notification.id).update(
            target_route=f"/schools/{self.school.id}"
        )

        response = self.client.get(f"/notifications/{notification.id}/open")

        self.assertRedirects(
            response, f"/schools/{self.school.id}", fetch_redirect_response=False
        )
        notification.refresh_from_db()
        self.assertEqual(notification.status, "read")
        self.assertIsNotNone(notification.read_at)
        # Read is not resolved: it is still in the history.
        self.assertIsNone(notification.resolved_at)

    def test_a_signed_out_reader_signs_in_and_lands_in_the_same_place(self):
        """ "Expired session"."""
        notification = self.school_notice()

        response = Client().get(f"/notifications/{notification.id}/open")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
        self.assertIn(f"notifications/{notification.id}/open", response["Location"])
        notification.refresh_from_db()
        self.assertEqual(notification.status, "unread")

    def test_a_record_that_is_gone_clears_the_notification_and_says_so(self):
        """ "Deleted record"."""
        notification = self.school_notice(context_id="no-such-school")
        Notification.objects.filter(id=notification.id).update(
            target_route="/schools/no-such-school"
        )

        response = self.client.get(
            f"/notifications/{notification.id}/open", follow=True
        )

        self.assertEqual(response.redirect_chain[0][0], "/notifications?gone=1")
        self.assertContains(response, "no longer available")
        notification.refresh_from_db()
        self.assertEqual(notification.status, "read")
        self.assertIsNotNone(notification.resolved_at)
        # Kept as history, not deleted.
        self.assertTrue(Notification.objects.filter(id=notification.id).exists())

    def test_a_destination_outside_the_application_is_never_followed(self):
        for route in (
            "https://evil.example.com/x",
            "//evil.example.com",
            "/no/such/page",
        ):
            with self.subTest(route=route):
                notification = notify(self.amina, context_id=f"ctx-{route}")
                Notification.objects.filter(id=notification.id).update(
                    target_route=route
                )

                response = self.client.get(f"/notifications/{notification.id}/open")

                self.assertEqual(response["Location"], "/notifications?gone=1")

    def test_somebody_else_s_notification_cannot_be_opened(self):
        notification = self.school_notice(user=self.brian)

        response = self.client.get(f"/notifications/{notification.id}/open")

        self.assertEqual(response["Location"], "/notifications")
        notification.refresh_from_db()
        self.assertEqual(notification.status, "unread")

    def test_the_drawer_lists_what_is_unread_and_each_item_opens_its_record(self):
        """ "The notification should open the link direct" (owner,
        2026-10-10): the item's address is the record's own."""
        unread = self.school_notice()
        Notification.objects.filter(id=unread.id).update(
            target_route=f"/schools/{self.school.id}"
        )
        read = notify(self.amina, context_id="ctx-read")
        Notification.objects.filter(id=read.id).update(status="read")

        body = self.client.get("/notifications/drawer").content.decode()

        self.assertIn(f'data-notification-read="{unread.id}"', body)
        self.assertIn(f"window.location.assign('/schools/{self.school.id}')", body)
        self.assertNotIn("/read?redirect=", body)
        # What has been read has left the active drawer.
        self.assertNotIn(read.id, body)
        # Under the bell, not in the middle of the screen.
        self.assertIn("type: 'anchored'", body)
        self.assertIn(".edify-topbar__utility--notifications", body)

    def test_the_drawer_never_lists_a_notice_whose_record_is_gone(self):
        stale = self.school_notice(context_id="no-such-school")

        body = self.client.get("/notifications/drawer").content.decode()

        self.assertNotIn(stale.id, body)
        stale.refresh_from_db()
        self.assertIsNotNone(stale.resolved_at)

    def test_reading_one_from_the_page_clears_it_from_the_bell(self):
        notification = self.school_notice()

        response = self.client.patch(f"/api/notifications/{notification.id}/read")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get("/api/notifications/unread-count").json()["count"], 0
        )

    def test_the_messages_drawer_opens_under_its_own_icon_the_same_way(self):
        body = self.client.get("/messages/drawer").content.decode()

        self.assertIn("type: 'anchored'", body)
        self.assertIn(".edify-topbar__utility--messages", body)

    def test_a_message_notification_opens_the_exact_message(self):
        from apps.messaging.models import Message, MessageParticipant, MessageThread

        thread = MessageThread.objects.create(
            subject="Visit plan", created_by=self.brian.id
        )
        for user in (self.amina, self.brian):
            MessageParticipant.objects.create(thread=thread, user_id=user.id)
        message = Message.objects.create(
            thread=thread,
            sender_id=self.brian.id,
            recipient_id=self.amina.id,
            body="Hi",
        )

        response = self.client.get(f"/messages/{message.id}")

        self.assertEqual(
            response["Location"],
            f"/messages?thread={thread.id}&message={message.id}#message-{message.id}",
        )
        page = self.client.get(response["Location"]).content.decode()
        self.assertIn(f'id="message-{message.id}"', page)
        self.assertIn("data-message-target", page)


class ApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.amina, backend=BACKEND)

    def subscribe(self, **extra):
        return self.client.post(
            "/api/notifications/push/subscribe",
            {"endpoint": ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH}, **extra},
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone) Safari",
        )

    def test_a_browser_is_told_whether_push_is_on_and_with_which_key(self):
        self.assertEqual(
            self.client.get("/api/notifications/push/config").json()["enabled"], False
        )
        with KEYS:
            config = self.client.get("/api/notifications/push/config").json()
        self.assertEqual((config["enabled"], config["key"]), (True, PUBLIC))
        self.assertEqual(config["unread"], [])

    def test_subscribing_where_push_is_not_set_up_says_so(self):
        """ "Permission granted" on a server without keys: refused in words,
        not silently accepted."""
        response = self.subscribe()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "not_configured")

    @KEYS
    def test_the_first_message_a_device_gets_proves_the_path_to_it(self):
        response = self.subscribe()

        self.assertEqual(
            response.json(), {"ok": True, "created": True, "device": "iPhone · Safari"}
        )
        welcome = Notification.objects.get(recipient_id=self.amina.id)
        self.assertEqual(welcome.title, "Phone notifications are on")
        self.assertEqual(welcome.target_route, "/notifications")
        self.assertEqual(OutboxEvent.objects.filter(event_type=push.EVENT).count(), 1)
        # Recording the same device again announces nothing more.
        self.subscribe()
        self.assertEqual(
            Notification.objects.filter(recipient_id=self.amina.id).count(), 1
        )

    @KEYS
    def test_a_bad_subscription_is_refused(self):
        response = self.client.post(
            "/api/notifications/push/subscribe",
            {
                "endpoint": "https://example.com/x",
                "keys": {"p256dh": P256DH, "auth": AUTH},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    @KEYS
    def test_turning_off_and_signing_out_both_end_the_device(self):
        self.subscribe()

        response = self.client.post(
            "/api/notifications/push/unsubscribe",
            {"endpoint": ENDPOINT, "reason": "signed_out"},
            content_type="application/json",
        )

        self.assertEqual(response.json(), {"ok": True, "removed": 1})
        self.assertEqual(PushSubscription.objects.get().revoked_reason, "signed_out")

    def test_none_of_it_is_open_to_a_visitor(self):
        visitor = Client()
        for method, path in (
            ("get", "/api/notifications/push/config"),
            ("post", "/api/notifications/push/subscribe"),
            ("post", "/api/notifications/push/unsubscribe"),
        ):
            with self.subTest(path=path):
                response = getattr(visitor, method)(path)
                self.assertIn(response.status_code, (401, 403))


class ServiceWorkerTest(TestCase):
    """The half only a phone can run, pinned by what it must contain."""

    def worker(self):
        return self.client.get("/sw.js").content.decode()

    def test_it_shows_the_notification_and_a_tap_opens_its_address(self):
        body = self.worker()

        for needed in (
            "addEventListener('push'",
            "self.registration.showNotification(",
            "addEventListener('notificationclick'",
            "event.notification.close()",
            "self.clients.openWindow(url)",
            "client.navigate(url)",
            "addEventListener('pushsubscriptionchange'",
        ):
            self.assertIn(needed, body)
        # One notification is one entry in the tray: a repeat replaces it.
        self.assertIn("tag: data.tag || 'edify'", body)

    def test_it_only_ever_opens_this_application_s_own_pages(self):
        body = self.worker()

        self.assertIn("target.origin === self.location.origin", body)
        self.assertIn("data.url.charAt(0) === '/'", body)

    def test_someone_looking_at_the_app_is_not_told_twice(self):
        body = self.worker()

        self.assertIn("clients.some((client) => client.focused)", body)
        self.assertIn("type: 'edify-notification'", body)

    def test_what_was_read_elsewhere_and_a_signed_out_user_s_are_cleared(self):
        body = self.worker()

        self.assertIn("edify-notifications-sync", body)
        self.assertIn("self.registration.getNotifications()", body)

    def test_the_page_script_handles_every_state_a_device_can_be_in(self):
        from pathlib import Path

        from django.conf import settings

        script = Path(settings.BASE_DIR, "static/js/push-notifications.js").read_text()

        # Denied, not installed on an iPhone, unsupported, not set up, offline.
        for state in (
            "blocked:",
            "install:",
            "unsupported:",
            "unavailable:",
            "offline:",
        ):
            self.assertIn(state, script)
        self.assertIn("Notification.requestPermission()", script)
        self.assertIn("userVisibleOnly: true", script)
        # Signing out ends the device's notifications and clears its tray.
        self.assertIn('form[action="/logout"]', script)
        self.assertIn("disable('signed_out')", script)
        shell = Path(settings.BASE_DIR, "templates/layouts/shell.html").read_text()
        self.assertIn("js/push-notifications.js", shell)
        self.assertEqual(shell.count("data-drawer-anchor"), 2)
