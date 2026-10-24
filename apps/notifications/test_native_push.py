"""Push to the Edify app on phones, and the rules every push now keeps.

The brief of 2026-10-23: notifications reach people outside the open page,
on a laptop's browser (Web Push, apps.notifications.webpush) and in the
Capacitor app on Android and iPhone (Firebase Cloud Messaging, which carries
an iPhone's messages through Apple's push service). Both go through the one
path: a notification is saved, each of the recipient's devices gets a
durable outbox event and a `NotificationDelivery` row, and the outbox sends.

Every push keeps the same rules whatever the device: the recipient's own
"push" setting (urgent notices excepted, as for email), never to a
deactivated account, never to someone whose role can no longer open what the
notification is about, and a device the provider says is gone is not tried
again.
"""

from __future__ import annotations

import json
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client, TestCase, override_settings

from apps.accounts.models import User
from apps.notifications import fcm, push, webpush
from apps.notifications.models import (
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    PushKind,
    PushSubscription,
)
from apps.notifications.services import WorkflowNotificationService
from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import drain

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"

# A service account shaped like the one the Firebase console hands over.
_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "edify-test",
    "private_key_id": "key-1",
    "private_key": _RSA.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
    "client_email": "push@edify-test.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
}
FIREBASE = override_settings(FCM_SERVICE_ACCOUNT_JSON=json.dumps(SERVICE_ACCOUNT))
PUBLIC, PRIVATE = webpush.generate_vapid_keys()
WEB_KEYS = {
    "WEBPUSH_VAPID_PUBLIC_KEY": PUBLIC,
    "WEBPUSH_VAPID_PRIVATE_KEY": PRIVATE,
    "WEBPUSH_EAGER": False,
}
P256DH, _unused = webpush.generate_vapid_keys()
AUTH = webpush._b64url(b"0123456789abcdef")
BROWSER = "https://fcm.googleapis.com/fcm/send/laptop-one"
# What an FCM registration token looks like: an instance id, a colon, a key.
ANDROID_TOKEN = "dGVzdC1hbmRyb2lk:APA91b" + "A" * 140
IPHONE_TOKEN = "dGVzdC1pcGhvbmUx:APA91b" + "B" * 140
# What an iPhone hands over when the app was built without Firebase: the
# raw APNs token, which FCM cannot address.
RAW_APNS_TOKEN = "a1" * 32
SEND_URL = "https://fcm.googleapis.com/v1/projects/edify-test/messages:send"


class Answer:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


SIGNED_IN = Answer(200, {"access_token": "ya29.test-token", "expires_in": 3599})
SENT = Answer(200, {"name": "projects/edify-test/messages/0:1"})


def firebase_error(
    status, code="", error_code="", message="Requested entity was not found."
):
    details = (
        [
            {
                "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                "errorCode": error_code,
            }
        ]
        if error_code
        else []
    )
    return Answer(
        status,
        {
            "error": {
                "code": status,
                "message": message,
                "status": code,
                "details": details,
            }
        },
    )


def google(*answers):
    """``requests.post`` answering Google's token endpoint with a token and
    FCM with ``answers`` in turn (a browser push service always takes it)."""
    queue = list(answers)

    def post(url, *args, **kwargs):
        if url == "https://oauth2.googleapis.com/token":
            return SIGNED_IN
        if url == SEND_URL:
            return queue.pop(0) if queue else SENT
        return Answer(201)

    return mock.patch("requests.post", side_effect=post)


def person(email, role="CCEO", **extra):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
        **extra,
    )


def notify(
    user,
    *,
    title="Training assigned to you",
    context_id="ctx-1",
    target_route="/my-plan",
    **extra,
):
    """A notification about ``target_route``, raised the way the workflows
    raise one."""
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
    # The service picks the route by role; the test names the page it leads
    # to (checked when the push is sent, not when it is queued).
    Notification.objects.filter(id=notification.id).update(target_route=target_route)
    notification.target_route = target_route
    return notification


def sends(post):
    """The FCM messages ``post`` was asked to send."""
    return [
        call.kwargs["json"]["message"]
        for call in post.call_args_list
        if call.args and call.args[0] == SEND_URL
    ]


def send_once(**extra):
    fcm.send(
        ANDROID_TOKEN,
        {"id": "n1", "title": "t"},
        ttl=60,
        urgent=False,
        collapse="n1",
        **extra,
    )


class FirebaseSenderTest(TestCase):
    """The wire half: one message to one app on one phone."""

    def setUp(self):
        fcm.forget_token()

    def test_app_push_is_off_until_the_server_has_its_firebase_key(self):
        self.assertFalse(fcm.configured())
        with FIREBASE:
            self.assertTrue(fcm.configured())
        with override_settings(FCM_SERVICE_ACCOUNT_JSON='{"project_id": "x"}'):
            self.assertFalse(fcm.configured())
        with override_settings(FCM_SERVICE_ACCOUNT_JSON="not json"):
            self.assertFalse(fcm.configured())

    def test_the_key_may_be_given_base64_encoded(self):
        """A hosting dashboard takes one line more happily than a JSON file."""
        import base64

        encoded = base64.b64encode(json.dumps(SERVICE_ACCOUNT).encode()).decode()
        with override_settings(FCM_SERVICE_ACCOUNT_JSON=encoded):
            self.assertTrue(fcm.configured())

    @FIREBASE
    def test_a_message_is_signed_in_once_and_says_what_the_bell_says(self):
        payload = {
            "id": "n1",
            "title": "Training assigned to you",
            "body": "In-school training at Kasubi Primary.",
            "url": "/notifications/n1/open",
            "tag": "edify-n1",
            "category": "training",
            "priority": "urgent",
        }

        with google() as post:
            fcm.send(ANDROID_TOKEN, payload, ttl=3600, urgent=True, collapse="n1")
            fcm.send(IPHONE_TOKEN, payload, ttl=3600, urgent=False, collapse="n1")

        token_calls = [c for c in post.call_args_list if c.args[0] != SEND_URL]
        self.assertEqual(len(token_calls), 1)  # the access token is reused
        first, second = sends(post)
        self.assertEqual(first["token"], ANDROID_TOKEN)
        self.assertEqual(
            first["notification"],
            {
                "title": "Training assigned to you",
                "body": "In-school training at Kasubi Primary.",
            },
        )
        # Every data value is a string: FCM refuses anything else.
        self.assertEqual(first["data"]["url"], "/notifications/n1/open")
        self.assertTrue(all(isinstance(v, str) for v in first["data"].values()))
        self.assertEqual(first["android"]["priority"], "HIGH")
        self.assertEqual(first["android"]["notification"]["tag"], "edify-n1")
        self.assertEqual(first["android"]["notification"]["visibility"], "PRIVATE")
        self.assertEqual(first["apns"]["headers"]["apns-priority"], "10")
        self.assertEqual(first["apns"]["headers"]["apns-collapse-id"], "n1")
        self.assertEqual(second["android"]["priority"], "NORMAL")
        call = next(c for c in post.call_args_list if c.args[0] == SEND_URL)
        self.assertEqual(
            call.kwargs["headers"]["Authorization"], "Bearer ya29.test-token"
        )
        self.assertFalse(call.kwargs["allow_redirects"])

    @FIREBASE
    def test_what_firebase_answers_decides_what_happens_next(self):
        cases = (
            (firebase_error(404, "NOT_FOUND", "UNREGISTERED"), webpush.PushGone),
            (
                firebase_error(
                    400,
                    "INVALID_ARGUMENT",
                    "INVALID_ARGUMENT",
                    "The registration token is not a valid FCM registration token",
                ),
                webpush.PushGone,
            ),
            (
                firebase_error(403, "PERMISSION_DENIED", "SENDER_ID_MISMATCH"),
                webpush.PushGone,
            ),
            # Apple refused Firebase's APNs key: the server's set-up, not the
            # phone, so the device is kept.
            (
                firebase_error(401, "UNAUTHENTICATED", "THIRD_PARTY_AUTH_ERROR"),
                webpush.PushRejected,
            ),
            (
                firebase_error(
                    400, "INVALID_ARGUMENT", "INVALID_ARGUMENT", "Bad payload"
                ),
                webpush.PushRejected,
            ),
            (
                firebase_error(429, "RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"),
                webpush.PushUnavailable,
            ),
            (
                firebase_error(503, "UNAVAILABLE", "UNAVAILABLE"),
                webpush.PushUnavailable,
            ),
            (Answer(502, text="<html>Bad gateway</html>"), webpush.PushUnavailable),
        )
        for answer, outcome in cases:
            with self.subTest(status=answer.status_code, outcome=outcome.__name__):
                with google(answer), self.assertRaises(outcome):
                    send_once()

    @FIREBASE
    def test_an_expired_access_token_is_dropped_and_tried_again_later(self):
        with google(firebase_error(401, "UNAUTHENTICATED")):
            with self.assertRaises(webpush.PushUnavailable):
                send_once()

        with google() as post:
            send_once()
        token_calls = [c for c in post.call_args_list if c.args[0] != SEND_URL]
        self.assertEqual(len(token_calls), 1)

    @FIREBASE
    def test_no_network_is_a_reason_to_try_again(self):
        import requests

        with mock.patch("requests.post", side_effect=requests.ConnectTimeout("slow")):
            with self.assertRaises(webpush.PushUnavailable):
                send_once()

    @FIREBASE
    def test_google_refusing_the_key_is_a_set_up_fault_not_a_device_fault(self):
        refused = Answer(
            400,
            {"error": "invalid_grant", "error_description": "Invalid JWT Signature."},
        )
        with mock.patch("requests.post", return_value=refused):
            with self.assertRaises(webpush.PushRejected):
                send_once()

    def test_only_a_device_token_is_accepted(self):
        self.assertTrue(fcm.valid_token(ANDROID_TOKEN))
        for bad in (
            "",
            "short",
            RAW_APNS_TOKEN,
            "https://example.com/" + "a" * 40,
            "has spaces " + "a" * 40,
            "a" * 5000,
        ):
            with self.subTest(token=bad[:24]):
                self.assertFalse(fcm.valid_token(bad))


class AppDeviceTest(TestCase):
    """An app on a phone is a device like a browser: one row, one owner."""

    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.brian = person("brian@edify.org")

    def test_an_app_is_one_row_however_often_it_registers(self):
        first, created = push.register_app(
            self.amina,
            ANDROID_TOKEN,
            "android",
            "Mozilla/5.0 (Linux; Android 15) EdifyApp",
        )
        again, created_again = push.register_app(
            self.amina, ANDROID_TOKEN, "android", ""
        )

        self.assertEqual((created, created_again), (True, False))
        self.assertEqual(first.id, again.id)
        self.assertEqual(first.kind, PushKind.ANDROID)
        self.assertEqual(first.device_label, "Android · Edify app")

    def test_a_phone_that_changes_hands_stops_telling_the_last_user(self):
        push.register_app(self.amina, IPHONE_TOKEN, "ios", "")

        push.register_app(self.brian, IPHONE_TOKEN, "ios", "")

        device = PushSubscription.objects.get()
        self.assertEqual(device.user_id, self.brian.id)
        self.assertEqual(device.device_label, "iPhone · Edify app")

    def test_something_that_is_not_a_device_token_is_refused(self):
        for token, platform in (
            ("", "android"),
            (RAW_APNS_TOKEN, "ios"),
            (ANDROID_TOKEN, "windows"),
        ):
            with self.subTest(token=token[:12], platform=platform):
                with self.assertRaises(push.InvalidSubscription):
                    push.register_app(self.amina, token, platform, "")
        self.assertEqual(PushSubscription.objects.count(), 0)


class AppDeviceApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.amina, backend=BACKEND)

    def register(self, token=ANDROID_TOKEN, platform="android"):
        return self.client.post(
            "/api/notifications/push/app/register",
            {"token": token, "platform": platform},
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 15) EdifyApp",
        )

    def test_registering_where_firebase_is_not_set_up_says_so(self):
        response = self.register()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "not_configured")
        self.assertEqual(PushSubscription.objects.count(), 0)

    @FIREBASE
    def test_an_app_registers_and_its_first_message_proves_the_path(self):
        response = self.register()

        self.assertEqual(
            response.json(),
            {"ok": True, "created": True, "device": "Android · Edify app"},
        )
        welcome = Notification.objects.get(recipient_id=self.amina.id)
        self.assertEqual(welcome.title, "Phone notifications are on")
        self.assertEqual(OutboxEvent.objects.filter(event_type=push.EVENT).count(), 1)
        self.register()
        self.assertEqual(
            Notification.objects.filter(recipient_id=self.amina.id).count(), 1
        )

    @FIREBASE
    def test_an_iphone_app_built_without_firebase_is_refused(self):
        response = self.register(RAW_APNS_TOKEN, "ios")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushSubscription.objects.count(), 0)

    @FIREBASE
    def test_signing_out_in_the_app_ends_that_phone_s_notifications(self):
        self.register()

        response = self.client.post(
            "/api/notifications/push/app/unregister",
            {"token": ANDROID_TOKEN, "reason": "signed_out"},
            content_type="application/json",
        )

        self.assertEqual(response.json(), {"ok": True, "removed": 1})
        self.assertEqual(PushSubscription.objects.get().revoked_reason, "signed_out")

    @FIREBASE
    def test_the_config_says_whether_the_app_can_be_told(self):
        config = self.client.get("/api/notifications/push/config").json()

        self.assertEqual((config["enabled"], config["app"]), (False, True))

    def test_none_of_it_is_open_to_a_visitor(self):
        visitor = Client()
        for path in (
            "/api/notifications/push/app/register",
            "/api/notifications/push/app/unregister",
        ):
            with self.subTest(path=path):
                self.assertIn(visitor.post(path).status_code, (401, 403))


@FIREBASE
@override_settings(**WEB_KEYS)
class SendPathTest(TestCase):
    """One notification, every device, the same rules."""

    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")
        cls.laptop, _ = push.subscribe(cls.amina, BROWSER, P256DH, AUTH)
        cls.android, _ = push.register_app(cls.amina, ANDROID_TOKEN, "android", "")
        cls.iphone, _ = push.register_app(cls.amina, IPHONE_TOKEN, "ios", "")

    def setUp(self):
        fcm.forget_token()

    def events(self):
        return OutboxEvent.objects.filter(event_type=push.EVENT)

    def copies(self):
        return NotificationDelivery.objects.filter(channel=DeliveryChannel.PUSH)

    def statuses(self):
        return set(self.copies().values_list("status", flat=True))

    def test_a_notification_reaches_the_laptop_and_both_phones(self):
        notification = notify(self.amina)

        self.assertEqual(self.events().count(), 3)
        self.assertEqual(
            sorted(self.copies().values_list("target", "status")),
            sorted(
                (d.id, DeliveryStatus.QUEUED)
                for d in (self.laptop, self.android, self.iphone)
            ),
        )
        with google() as post:
            result = drain()

        self.assertEqual(result["succeeded"], 3)
        self.assertIn(BROWSER, [c.args[0] for c in post.call_args_list])
        self.assertEqual(
            sorted(m["token"] for m in sends(post)),
            sorted([ANDROID_TOKEN, IPHONE_TOKEN]),
        )
        # A tap opens the address that marks it read and goes to the record.
        self.assertEqual(
            {m["data"]["url"] for m in sends(post)},
            {f"/notifications/{notification.id}/open"},
        )
        # Accepted by the provider: never claimed as "delivered".
        self.assertEqual(self.statuses(), {DeliveryStatus.ACCEPTED})

    def test_app_devices_wait_until_firebase_is_set_up(self):
        with override_settings(FCM_SERVICE_ACCOUNT_JSON=""):
            notify(self.amina)

        self.assertEqual(self.copies().get().target, self.laptop.id)

    def test_turning_push_off_is_respected_and_recorded(self):
        NotificationPreference.objects.create(user_id=self.amina.id, push_enabled=False)

        notify(self.amina)

        self.assertEqual(self.events().count(), 0)
        self.assertEqual(self.statuses(), {DeliveryStatus.SUPPRESSED})

    def test_turning_push_off_after_it_was_queued_is_respected_too(self):
        notify(self.amina)
        NotificationPreference.objects.create(user_id=self.amina.id, push_enabled=False)

        with google() as post:
            drain()

        self.assertEqual(post.call_count, 0)
        self.assertEqual(self.statuses(), {DeliveryStatus.SUPPRESSED})

    def test_an_urgent_notice_still_rings_when_push_is_off(self):
        NotificationPreference.objects.create(user_id=self.amina.id, push_enabled=False)

        notify(self.amina, priority="urgent")

        self.assertEqual(self.events().count(), 3)

    def test_a_deactivated_account_is_never_pushed(self):
        notify(self.amina)
        User.objects.filter(id=self.amina.id).update(is_active=False)

        with google() as post:
            result = drain()

        self.assertEqual((post.call_count, result["succeeded"]), (0, 3))
        self.assertEqual(self.statuses(), {DeliveryStatus.SKIPPED})
        self.assertIn("no longer active", self.copies().first().last_error)
        # And a notice raised for an account already deactivated queues nothing.
        notify(self.amina, context_id="ctx-2")
        self.assertEqual(self.events().filter(status=OutboxStatus.PENDING).count(), 0)

    def test_a_role_that_can_no_longer_open_the_record_is_not_pushed(self):
        """A CCEO is told about their plan; by the time it is sent they are
        Human Resources, whose role cannot open My Plan."""
        notify(self.amina)
        User.objects.filter(id=self.amina.id).update(
            roles=["HumanResources"], active_role="HumanResources"
        )

        with google() as post:
            drain()

        self.assertEqual(post.call_count, 0)
        self.assertEqual(self.statuses(), {DeliveryStatus.SKIPPED})
        self.assertIn("cannot open", self.copies().first().last_error)

    def test_a_notice_about_a_page_the_role_still_opens_is_sent(self):
        notify(self.amina, target_route="/schools")

        with google() as post:
            drain()

        self.assertEqual(len(sends(post)), 2)

    def test_a_phone_firebase_says_is_gone_is_forgotten(self):
        """The app was removed, or its token replaced."""
        notify(self.amina)

        with google(firebase_error(404, "NOT_FOUND", "UNREGISTERED"), SENT):
            result = drain()

        self.assertEqual(result["succeeded"], 3)
        gone = PushSubscription.objects.filter(revoked_reason="gone")
        self.assertEqual(gone.count(), 1)
        failed = self.copies().get(status=DeliveryStatus.FAILED)
        self.assertEqual(failed.target, gone.get().id)
        # The next notification is not queued for it.
        notify(self.amina, context_id="ctx-2")
        self.assertEqual(self.events().filter(status=OutboxStatus.PENDING).count(), 2)

    def test_a_busy_firebase_is_retried_and_then_delivers(self):
        from datetime import timedelta

        from django.utils import timezone

        notify(self.amina)

        busy = firebase_error(503, "UNAVAILABLE")
        with google(busy, busy):
            result = drain()

        self.assertEqual(result["failed"], 2)
        self.assertEqual(
            self.copies().filter(status=DeliveryStatus.RETRY_SCHEDULED).count(), 2
        )
        self.events().update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        with google() as post:
            result = drain()
        self.assertEqual((len(sends(post)), result["succeeded"]), (2, 2))
        self.assertEqual(self.statuses(), {DeliveryStatus.ACCEPTED})

    def test_one_notification_is_one_message_per_phone_however_often_asked(self):
        notification = notify(self.amina)
        push.enqueue(notification)

        self.assertEqual(self.events().count(), 3)
        self.assertEqual(self.copies().count(), 3)
        with google() as post:
            drain()
            drain()
        self.assertEqual(len(sends(post)), 2)


class SettingsTest(TestCase):
    """Where a person finds and sets how they are told."""

    @classmethod
    def setUpTestData(cls):
        cls.amina = person("amina@edify.org")

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.amina, backend=BACKEND)

    def test_a_person_turns_push_off_and_on_beside_email(self):
        self.client.post("/notifications/settings", {"email_enabled": "on"})
        preference = NotificationPreference.objects.get(user_id=self.amina.id)
        self.assertEqual(
            (preference.email_enabled, preference.push_enabled), (True, False)
        )

        self.client.post("/notifications/settings", {"push_enabled": "on"})
        preference.refresh_from_db()
        self.assertEqual(
            (preference.email_enabled, preference.push_enabled), (False, True)
        )

    def test_the_notification_centre_offers_a_switch_per_channel(self):
        page = self.client.get("/notifications/").content.decode()

        self.assertIn('name="push_enabled"', page)
        self.assertIn('name="email_enabled"', page)
        self.assertIn("data-push-toggle", page)

    def test_settings_carries_this_device_s_switch_and_the_way_to_the_rest(self):
        page = self.client.get("/settings").content.decode()

        self.assertIn("data-push-toggle", page)
        self.assertIn('href="/notifications/#delivery-settings"', page)

    def test_the_app_alone_gets_the_native_push_script(self):
        in_browser = self.client.get("/settings").content.decode()
        in_app = self.client.get(
            "/settings", HTTP_USER_AGENT="Mozilla/5.0 (iPhone) AppleWebKit EdifyApp"
        ).content.decode()

        self.assertNotIn("js/native-push.js", in_browser)
        self.assertIn("js/native-push.js", in_app)


class AppScriptTest(TestCase):
    """The half only the app can run, pinned by what it must do."""

    def read(self, name):
        from pathlib import Path

        from django.conf import settings

        return Path(settings.BASE_DIR, "static/js", name).read_text()

    def test_it_asks_after_sign_in_registers_and_tells_the_server(self):
        script = self.read("native-push.js")

        for needed in (
            "PushNotifications.checkPermissions()",
            "PushNotifications.requestPermissions()",
            "PushNotifications.register()",
            "'registration'",
            "'registrationError'",
            "/api/notifications/push/app/register",
        ):
            self.assertIn(needed, script)

    def test_it_explains_before_the_phone_asks_and_keeps_the_lock_screen_quiet(self):
        script = self.read("native-push.js")

        self.assertIn("data-app-push-ask", script)
        self.assertIn("Not now", script)
        # Android's private visibility: contents hidden on a locked phone.
        self.assertIn("visibility: 0", script)

    def test_turned_off_in_the_phone_s_settings_offers_the_way_there(self):
        script = self.read("native-push.js")

        # iPhone: the app's own page in Settings; Android: its notification
        # settings, through the app's small native plugin.
        self.assertIn("'app-settings:'", script)
        self.assertIn("EdifySettings.openNotificationSettings()", script)
        # Coming back from the phone's settings picks the new answer up.
        self.assertIn("visibilitychange", script)
        page = self.read("push-notifications.js")
        self.assertIn("'Open phone settings'", page)
        self.assertIn("app().openSettings()", page)

    def test_a_tap_opens_the_record_in_the_app_and_only_this_site_s_pages(self):
        script = self.read("native-push.js")

        self.assertIn("'pushNotificationActionPerformed'", script)
        self.assertIn("url.charAt(0) === '/'", script)
        self.assertIn("location.assign(", script)

    def test_signing_out_ends_the_phone_s_notifications(self):
        script = self.read("native-push.js")

        self.assertIn("/api/notifications/push/app/unregister", script)
        self.assertIn("removeAllDeliveredNotifications()", script)
        # The page's own sign-out handler hands over to the app's.
        self.assertIn("phone.disable('signed_out')", self.read("push-notifications.js"))

    def test_the_device_switch_in_the_page_drives_the_app(self):
        self.assertIn("window.EdifyAppPush", self.read("push-notifications.js"))
        self.assertIn("window.EdifyAppPush =", self.read("native-push.js"))
