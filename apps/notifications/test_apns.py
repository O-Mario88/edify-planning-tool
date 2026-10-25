"""The iPhone app told straight through Apple's push service (APNs).

An iPhone app built without Firebase hands over Apple's own device token,
which Firebase cannot address (test_native_push.py refuses it where only
Firebase is set up). Where the deployment has the team's APNs key, that token
is accepted and each notification goes to Apple directly, through the same
path and rules as every other device: one outbox event and one delivery row
per device, the same skips, and the same three outcomes (gone, refused, try
again).

Whether the phone shows it is the phone's own setting (Settings → Edify →
Notifications): the server sends, the phone decides.
"""

from __future__ import annotations

import json
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.notifications import apns, push
from apps.notifications.models import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    PushKind,
    PushSubscription,
)
from apps.notifications.test_native_push import (
    ANDROID_TOKEN,
    BACKEND,
    notify,
    person,
)
from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import drain

_KEY = ec.generate_private_key(ec.SECP256R1())
PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
APPLE = override_settings(
    APNS_KEY_ID="ABC123DEFG",
    APNS_TEAM_ID="TEAM123456",
    APNS_PRIVATE_KEY=PEM,
    APNS_TOPIC="app.edifyplanning.mobile",
    APNS_ENVIRONMENT="production",
    WEBPUSH_EAGER=False,
)
TOKEN = "a1" * 32


def answer(status, reason=""):
    return status, json.dumps({"reason": reason}) if reason else ""


def apple(status=200, reason=""):
    return mock.patch.object(apns, "_post", return_value=answer(status, reason))


class AppleSenderTest(TestCase):
    """The wire half: one message to one iPhone."""

    def setUp(self):
        apns.forget_token()

    def send(self, status=200, reason="", **kwargs):
        with apple(status, reason) as post:
            apns.send(TOKEN, {"title": "T", "body": "B", "url": "/x"}, **kwargs)
        return post

    def test_apple_push_is_off_until_the_deployment_has_the_team_s_key(self):
        self.assertFalse(apns.configured())
        with APPLE:
            self.assertTrue(apns.configured())

    def test_only_an_iphone_s_device_token_is_accepted(self):
        self.assertTrue(apns.valid_token(TOKEN))
        for token in (
            "",
            "zz" * 32,
            "a1" * 8,
            TOKEN + "/../x",
            "a1" * 101,
            "abc:APA91b" + "A" * 140,
        ):
            with self.subTest(token=token[:20]):
                self.assertFalse(apns.valid_token(token))

    @APPLE
    def test_a_request_is_signed_with_the_team_s_key_and_names_the_app(self):
        post = self.send(collapse_id="n1", priority="high", expires_in=3600)

        url, headers, body = post.call_args.args
        self.assertEqual(url, f"https://api.push.apple.com/3/device/{TOKEN}")
        scheme, token = headers["authorization"].split(" ")
        self.assertEqual(scheme, "bearer")
        claims = jwt.decode(token, _KEY.public_key(), algorithms=["ES256"])
        self.assertEqual(claims["iss"], "TEAM123456")
        self.assertEqual(jwt.get_unverified_header(token)["kid"], "ABC123DEFG")
        self.assertEqual(headers["apns-topic"], "app.edifyplanning.mobile")
        self.assertEqual(headers["apns-push-type"], "alert")
        self.assertEqual(headers["apns-priority"], "10")
        # One notification is one entry on the phone: a re-send replaces it.
        self.assertEqual(headers["apns-collapse-id"], "n1")
        self.assertGreater(int(headers["apns-expiration"]), timezone.now().timestamp())
        sent = json.loads(body)
        self.assertEqual(sent["aps"]["alert"], {"title": "T", "body": "B"})
        self.assertEqual(sent["aps"]["sound"], "default")
        self.assertEqual(sent["url"], "/x")

    @APPLE
    def test_a_build_run_from_xcode_is_sent_through_apple_s_sandbox(self):
        with override_settings(APNS_ENVIRONMENT="development"):
            post = self.send()
        self.assertTrue(
            post.call_args.args[0].startswith("https://api.sandbox.push.apple.com/")
        )

    @APPLE
    def test_an_ordinary_notification_is_sent_at_the_phone_s_convenience(self):
        post = self.send(priority="normal")
        self.assertEqual(post.call_args.args[1]["apns-priority"], "5")

    @APPLE
    def test_one_signature_serves_many_messages_until_it_is_old(self):
        first = self.send().call_args.args[1]["authorization"]
        again = self.send().call_args.args[1]["authorization"]
        self.assertEqual(first, again)
        later = apns.time.time() + 51 * 60
        with mock.patch.object(apns.time, "time", return_value=later):
            renewed = self.send().call_args.args[1]["authorization"]
        self.assertNotEqual(first, renewed)

    @APPLE
    def test_what_apple_answers_decides_what_happens_next(self):
        self.send(200)
        for status, reason in ((410, "Unregistered"), (400, "BadDeviceToken")):
            with self.subTest(status=status), self.assertRaises(apns.PushGone):
                self.send(status, reason)
        for status, reason in (
            (400, "PayloadTooLarge"),
            (403, "BadCertificateEnvironment"),
        ):
            with self.subTest(status=status), self.assertRaises(apns.PushRejected):
                self.send(status, reason)
        for status, reason in (
            (429, "TooManyRequests"),
            (500, ""),
            (503, "ServiceUnavailable"),
        ):
            with self.subTest(status=status), self.assertRaises(apns.PushUnavailable):
                self.send(status, reason)

    @APPLE
    def test_an_expired_signature_is_made_afresh_and_the_message_retried_later(
        self,
    ):
        first = self.send().call_args.args[1]["authorization"]
        later = apns.time.time() + 1
        with mock.patch.object(apns.time, "time", return_value=later):
            with self.assertRaises(apns.PushUnavailable):
                self.send(403, "ExpiredProviderToken")
            renewed = self.send().call_args.args[1]["authorization"]
        self.assertNotEqual(renewed, first)

    @APPLE
    def test_no_network_is_a_reason_to_try_again(self):
        import httpx

        offline = httpx.ConnectError("offline")
        with mock.patch.object(apns, "_post", side_effect=offline):
            with self.assertRaises(apns.PushUnavailable):
                apns.send(TOKEN, {"title": "T", "body": "B", "url": "/x"})


class AppleDeviceApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.amina, backend=BACKEND)

    def register(self, token=TOKEN, platform="ios"):
        return self.client.post(
            "/api/notifications/push/app/register",
            {"token": token, "platform": platform},
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone) AppleWebKit EdifyApp",
        )

    @APPLE
    def test_an_iphone_registers_with_apple_s_own_token(self):
        response = self.register()

        self.assertEqual(response.status_code, 200)
        device = PushSubscription.objects.get()
        self.assertEqual((device.kind, device.endpoint), (PushKind.IOS, TOKEN))
        self.assertEqual(device.device_label, "iPhone · Edify app")

    @APPLE
    def test_the_app_is_told_this_server_can_reach_it(self):
        config = self.client.get("/api/notifications/push/config").json()
        self.assertTrue(config["app"])

    def test_an_iphone_is_refused_where_apple_s_key_is_not_set(self):
        self.assertEqual(self.register().status_code, 409)
        self.assertFalse(PushSubscription.objects.exists())

    @APPLE
    def test_an_android_phone_still_needs_firebase(self):
        # Apple's key reaches iPhones only. An Android phone with a good
        # Firebase token is told notifications are not set up, the page says
        # so, and no device is kept that nothing could ever reach.
        response = self.register(ANDROID_TOKEN, "android")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "not_configured")
        self.assertFalse(PushSubscription.objects.exists())

    @APPLE
    def test_the_config_says_which_phones_can_be_told(self):
        config = self.client.get("/api/notifications/push/config").json()
        self.assertEqual(config["apps"], {"android": False, "ios": True})


@APPLE
class AppleSendPathTest(TestCase):
    """One notification to an iPhone through Apple, by the shared path."""

    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.brian = person("brian@edify.org")
        cls.iphone, _ = push.register_app(cls.amina, TOKEN, "ios", "")

    def setUp(self):
        apns.forget_token()

    def events(self):
        return OutboxEvent.objects.filter(event_type=push.EVENT)

    def copy(self):
        return NotificationDelivery.objects.get(channel=DeliveryChannel.PUSH)

    def test_a_notification_reaches_the_iphone_through_apple(self):
        notification = notify(self.amina, priority="urgent")

        with apple() as post:
            drain()

        # One message to Apple (an urgent notice is emailed too, by its own
        # event).
        self.assertEqual(post.call_count, 1)
        url, headers, body = post.call_args.args
        self.assertEqual(url, f"https://api.push.apple.com/3/device/{TOKEN}")
        self.assertEqual(headers["apns-collapse-id"], notification.id)
        self.assertEqual(headers["apns-priority"], "10")
        sent = json.loads(body)
        self.assertEqual(sent["aps"]["alert"]["title"], "Training assigned to you")
        self.assertEqual(sent["url"], f"/notifications/{notification.id}/open")
        self.assertEqual(self.copy().status, DeliveryStatus.ACCEPTED)

    def test_an_iphone_waits_until_apple_s_key_is_set(self):
        with override_settings(APNS_PRIVATE_KEY=""):
            notify(self.amina)
        pending = self.events().filter(status=OutboxStatus.PENDING)
        self.assertFalse(pending.exists())

    def test_an_iphone_apple_says_is_gone_is_forgotten(self):
        """The app was deleted, or the phone reset: Apple answers 410."""
        notify(self.amina)

        with apple(410, "Unregistered"):
            drain()

        self.iphone.refresh_from_db()
        self.assertIsNotNone(self.iphone.revoked_at)
        self.assertEqual(self.iphone.revoked_reason, "gone")

    def test_a_busy_apple_is_retried(self):
        notify(self.amina)

        with apple(503, "ServiceUnavailable"):
            result = drain()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.events().get().status, OutboxStatus.PENDING)

    def test_a_phone_someone_else_has_since_signed_in_on_is_not_sent_it(self):
        notify(self.amina)
        push.register_app(self.brian, TOKEN, "ios", "")

        with apple() as post:
            drain()

        post.assert_not_called()
