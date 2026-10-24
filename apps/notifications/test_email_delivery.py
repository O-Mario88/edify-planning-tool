"""Email copies of notifications, who sent them, and how each one travelled.

The proposal of 2026-10-21: one notification record, delivered in the app,
to the user's devices and by email, with "accepted by the provider" never
reported as "delivered", and email that "must not falsely report success"
while no provider is set up.

The bell's notification is the one record. An email is a copy of it, made
only for what a person sent (a Send to, a Follow Up, a reminder) and for
urgent notices, queued in the same transaction, sent once however often the
queue retries, and its fate recorded on a `NotificationDelivery` row.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import time
import urllib.error
from unittest import mock

from django.test import Client, TestCase, override_settings

from apps.accounts.models import User
from apps.notifications import email_delivery
from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from apps.notifications.services import (
    WorkflowNotificationService,
    notify_from_person,
)
from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import drain

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
RESEND = {
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_key_not_real",
    "EMAIL_FROM": "Edify <notifications@edify.test>",
    "APP_BASE_URL": "https://planning.edify.test",
}
NO_PROVIDER = {"EMAIL_PROVIDER": "console", "RESEND_API_KEY": ""}
WEBHOOK_SECRET = (
    "whsec_" + base64.b64encode(b"a-webhook-secret-of-32-bytes!!!!").decode()
)


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


class Accepted:
    """What api.resend.com answers when it takes a message."""

    status = 200

    def __init__(self, message_id="re-msg-1"):
        self._body = json.dumps({"id": message_id}).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def refused(code):
    return urllib.error.HTTPError(
        "https://api.resend.com/emails", code, "refused", {}, io.BytesIO(b"{}")
    )


def follow_up(
    sender, recipient, *, context_id="fu-1", title="Follow up: October planning"
):
    notification, _created = notify_from_person(
        sender,
        recipient_id=recipient.id,
        context_type="PlanningOversightFollowUp",
        context_id=context_id,
        source_event_type="planning_followup_assigned",
        defaults={
            "title": title,
            "body": "Please review the outstanding October plans for Kasubi Primary.",
            "category": "planning",
            "target_route": "/team-planning-oversight",
            "action_label": "Follow up",
            "action_required": True,
            "priority": "high",
            "status": "unread",
            "read_at": None,
            "resolved_at": None,
        },
    )
    return notification


def deliveries(notification, channel="email"):
    return NotificationDelivery.objects.filter(
        notification_id=notification.id, channel=channel
    )


@override_settings(NOTIFICATION_EMAIL_EAGER=False)
class WhatIsEmailedTest(TestCase):
    def setUp(self):
        self.cd = person("director@edify.test", "CountryDirector")
        self.pl = person("lead@edify.test", "Program Lead")

    def test_what_a_person_sends_is_queued_for_email_with_its_sender(self):
        notification = follow_up(self.cd, self.pl)

        self.assertEqual(notification.sender_id, self.cd.id)
        (delivery,) = deliveries(notification)
        self.assertEqual(delivery.status, "queued")
        self.assertEqual(delivery.recipient_id, self.pl.id)
        self.assertTrue(
            OutboxEvent.objects.filter(
                event_type=email_delivery.EVENT,
                payload__deliveryId=delivery.id,
            ).exists()
        )

    def test_an_automatic_notice_is_not_emailed(self):
        WorkflowNotificationService.trigger(
            "activity_scheduled",
            "planning",
            "normal",
            "Training scheduled",
            "A training was scheduled.",
            context_type="activity",
            context_id="act-1",
            recipients=[self.pl],
        )

        self.assertFalse(NotificationDelivery.objects.filter(channel="email").exists())

    def test_an_urgent_notice_is_emailed_even_when_nobody_sent_it(self):
        (notification,) = WorkflowNotificationService.trigger(
            "budget_overrun",
            "finance",
            "urgent",
            "Budget line overspent",
            "A budget line is overspent.",
            context_type="system",
            context_id="b-1",
            recipients=[self.pl],
        )

        self.assertEqual(deliveries(notification).get().status, "queued")

    def test_the_sender_is_recorded_when_a_workflow_names_one(self):
        (notification,) = WorkflowNotificationService.trigger(
            "staff_activity.follow_up",
            "staff_activity",
            "normal",
            "Your manager followed up with you",
            "About logins.",
            context_type="StaffUsageFollowUp",
            context_id="s-1",
            recipients=[self.pl],
            sender=self.cd,
        )

        self.assertEqual(notification.sender_id, self.cd.id)
        self.assertEqual(deliveries(notification).count(), 1)

    def test_a_reminder_from_a_person_alerts_again_once(self):
        first = follow_up(self.cd, self.pl)
        Notification.objects.filter(id=first.id).update(status="read")

        again = follow_up(self.cd, self.pl, title="Reminder: October planning")

        self.assertEqual(again.id, first.id)
        again.refresh_from_db()
        self.assertEqual(again.status, "unread")
        self.assertEqual(again.reminder_count, 1)
        self.assertEqual(deliveries(again).count(), 2)
        self.assertEqual(
            sorted(deliveries(again).values_list("round", flat=True)), [0, 1]
        )

    def test_a_reminder_does_not_reopen_another_person_s_notice(self):
        follow_up(self.cd, self.pl)
        other_pl = person("lead2@edify.test", "Program Lead")

        theirs = follow_up(self.cd, other_pl)

        self.assertEqual(theirs.reminder_count, 0)
        self.assertEqual(
            Notification.objects.filter(recipient_id=self.pl.id).count(), 1
        )

    def test_turning_email_off_is_respected_and_recorded(self):
        NotificationPreference.objects.create(user_id=self.pl.id, email_enabled=False)

        notification = follow_up(self.cd, self.pl)

        delivery = deliveries(notification).get()
        self.assertEqual(delivery.status, "suppressed")
        self.assertFalse(
            OutboxEvent.objects.filter(event_type=email_delivery.EVENT).exists()
        )
        # The bell still has it: a preference never loses the notice.
        self.assertEqual(notification.status, "unread")

    def test_a_muted_category_is_not_emailed(self):
        NotificationPreference.objects.create(
            user_id=self.pl.id, email_muted_categories=["planning"]
        )

        notification = follow_up(self.cd, self.pl)

        self.assertEqual(deliveries(notification).get().status, "suppressed")

    def test_an_urgent_notice_is_emailed_even_when_email_is_off(self):
        """Urgent notices are mandatory: an ordinary setting does not silence
        them."""
        NotificationPreference.objects.create(user_id=self.pl.id, email_enabled=False)

        (notification,) = WorkflowNotificationService.trigger(
            "budget_overrun",
            "finance",
            "urgent",
            "Budget line overspent",
            "Overspent.",
            context_type="system",
            context_id="b-2",
            recipients=[self.pl],
        )

        self.assertEqual(deliveries(notification).get().status, "queued")

    def test_reading_or_resolving_never_emails(self):
        notification = follow_up(self.cd, self.pl)
        notification.status = "read"
        notification.save(update_fields=["status", "updated_at"])

        self.assertEqual(deliveries(notification).count(), 1)


@override_settings(NOTIFICATION_EMAIL_EAGER=False)
class SendingTest(TestCase):
    def setUp(self):
        self.cd = person("director@edify.test", "CountryDirector")
        self.pl = person("lead@edify.test", "Program Lead")

    def run_queue(self):
        return drain(time_budget_seconds=5)

    def test_without_a_provider_it_says_so_and_never_claims_success(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, NO_PROVIDER),
            mock.patch("urllib.request.urlopen") as post,
        ):
            self.run_queue()

        post.assert_not_called()
        delivery = deliveries(notification).get()
        self.assertEqual(delivery.status, "not_configured")
        self.assertIsNone(delivery.sent_at)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "unread")

    def test_the_provider_accepting_it_is_recorded_as_accepted_not_delivered(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch(
                "urllib.request.urlopen", return_value=Accepted("re-42")
            ) as post,
        ):
            self.run_queue()

        delivery = deliveries(notification).get()
        self.assertEqual(delivery.status, "accepted")
        self.assertEqual(delivery.provider_message_id, "re-42")
        self.assertIsNotNone(delivery.sent_at)
        self.assertIsNone(delivery.delivered_at)
        request = post.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(
            request.get_header("Idempotency-key"),
            f"edify-notification-{delivery.id}",
        )
        sent = json.loads(request.data)
        self.assertEqual(sent["to"], "lead@edify.test")
        self.assertIn(
            f"https://planning.edify.test/notifications/{notification.id}/open",
            sent["text"],
        )
        self.assertIn("Director", sent["text"])

    def test_the_subject_names_no_school_and_no_message(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()) as post,
        ):
            self.run_queue()

        subject = json.loads(post.call_args.args[0].data)["subject"]
        self.assertNotIn("Kasubi", subject)
        self.assertNotIn("October", subject)
        self.assertEqual(deliveries(notification).get().status, "accepted")

    def test_what_it_says_is_escaped_in_the_html_copy(self):
        follow_up(self.cd, self.pl, title='<img src=x onerror="alert(1)">')

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()) as post,
        ):
            self.run_queue()

        html = json.loads(post.call_args.args[0].data)["html"]
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_an_unreachable_provider_is_retried_and_then_sent(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
            ),
        ):
            self.run_queue()

        delivery = deliveries(notification).get()
        self.assertEqual(delivery.status, "retry_scheduled")
        event = OutboxEvent.objects.get(payload__deliveryId=delivery.id)
        self.assertEqual(event.status, OutboxStatus.PENDING)

        OutboxEvent.objects.filter(id=event.id).update(next_attempt_at=event.created_at)
        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted("re-7")),
        ):
            self.run_queue()

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "accepted")
        self.assertEqual(delivery.attempts, 2)

    def test_a_busy_provider_is_retried(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", side_effect=refused(429)),
        ):
            self.run_queue()

        self.assertEqual(deliveries(notification).get().status, "retry_scheduled")

    def test_a_refused_message_is_recorded_and_not_retried(self):
        notification = follow_up(self.cd, self.pl)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", side_effect=refused(422)),
        ):
            self.run_queue()

        delivery = deliveries(notification).get()
        self.assertEqual(delivery.status, "failed")
        self.assertIn("422", delivery.last_error)
        self.assertEqual(
            OutboxEvent.objects.get(payload__deliveryId=delivery.id).status,
            OutboxStatus.SUCCEEDED,
        )

    def test_retries_stop_after_the_limit_and_say_it_failed(self):
        notification = follow_up(self.cd, self.pl)
        delivery = deliveries(notification).get()
        NotificationDelivery.objects.filter(id=delivery.id).update(
            attempts=email_delivery.MAX_ATTEMPTS - 1
        )

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("down")
            ),
        ):
            self.run_queue()

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "failed")

    def test_a_replay_of_a_finished_delivery_sends_nothing(self):
        notification = follow_up(self.cd, self.pl)
        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()),
        ):
            self.run_queue()
        delivery = deliveries(notification).get()

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()) as post,
        ):
            email_delivery.handle_email({"deliveryId": delivery.id})

        post.assert_not_called()

    def test_work_done_before_the_email_leaves_is_not_emailed(self):
        notification = follow_up(self.cd, self.pl)
        Notification.objects.filter(id=notification.id).update(
            resolved_at=notification.created_at
        )

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()) as post,
        ):
            self.run_queue()

        post.assert_not_called()
        self.assertEqual(deliveries(notification).get().status, "skipped")

    def test_an_inactive_recipient_is_not_emailed(self):
        notification = follow_up(self.cd, self.pl)
        User.objects.filter(id=self.pl.id).update(is_active=False)

        with (
            mock.patch.dict(os.environ, RESEND),
            mock.patch("urllib.request.urlopen", return_value=Accepted()) as post,
        ):
            self.run_queue()

        post.assert_not_called()
        self.assertEqual(deliveries(notification).get().status, "skipped")


def signed(body: bytes, *, secret=WEBHOOK_SECRET, at=None, msg_id="msg_1"):
    at = str(int(at if at is not None else time.time()))
    key = base64.b64decode(secret.split("_", 1)[1])
    signature = base64.b64encode(
        hmac.new(key, f"{msg_id}.{at}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return {
        "HTTP_SVIX_ID": msg_id,
        "HTTP_SVIX_TIMESTAMP": at,
        "HTTP_SVIX_SIGNATURE": f"v1,{signature}",
    }


@override_settings(NOTIFICATION_EMAIL_EAGER=False, RESEND_WEBHOOK_SECRET=WEBHOOK_SECRET)
class ProviderEventsTest(TestCase):
    URL = "/api/notifications/email/events"

    def setUp(self):
        self.client = Client()
        cd = person("director@edify.test", "CountryDirector")
        pl = person("lead@edify.test", "Program Lead")
        notification = follow_up(cd, pl)
        self.delivery = deliveries(notification).get()
        NotificationDelivery.objects.filter(id=self.delivery.id).update(
            status="accepted", provider_message_id="re-99"
        )

    def post(self, event_type, headers=None, body=None):
        body = (
            body
            or json.dumps({"type": event_type, "data": {"email_id": "re-99"}}).encode()
        )
        return self.client.post(
            self.URL,
            data=body,
            content_type="application/json",
            **(headers if headers is not None else signed(body)),
        )

    def test_a_signed_delivered_event_marks_it_delivered(self):
        response = self.post("email.delivered")

        self.assertEqual(response.status_code, 200)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "delivered")
        self.assertIsNotNone(self.delivery.delivered_at)

    def test_a_bounce_is_recorded_as_a_bounce(self):
        self.post("email.bounced")

        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "bounced")

    def test_a_late_event_never_moves_a_bounce_back_to_delivered(self):
        self.post("email.bounced")
        self.post("email.delivered")

        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "bounced")

    def test_an_unsigned_or_forged_event_is_refused(self):
        body = json.dumps(
            {"type": "email.delivered", "data": {"email_id": "re-99"}}
        ).encode()
        forged = signed(body, secret="whsec_" + base64.b64encode(b"x" * 32).decode())

        self.assertEqual(self.post("email.delivered", headers={}).status_code, 401)
        self.assertEqual(
            self.post("email.delivered", headers=forged, body=body).status_code, 401
        )
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "accepted")

    def test_an_old_signed_event_cannot_be_replayed(self):
        body = json.dumps(
            {"type": "email.delivered", "data": {"email_id": "re-99"}}
        ).encode()
        stale = signed(body, at=time.time() - 3600)

        self.assertEqual(
            self.post("email.delivered", headers=stale, body=body).status_code, 401
        )

    @override_settings(RESEND_WEBHOOK_SECRET="")
    def test_events_are_refused_until_a_signing_secret_is_set(self):
        self.assertEqual(self.post("email.delivered").status_code, 503)


@override_settings(NOTIFICATION_EMAIL_EAGER=False)
class SettingsAndPagesTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.cd = person("director@edify.test", "CountryDirector")
        self.pl = person("lead@edify.test", "Program Lead")
        self.admin = person("admin@edify.test", "Admin")

    def test_a_person_turns_their_own_email_off_and_on(self):
        self.client.force_login(self.pl, backend=BACKEND)

        response = self.client.post(
            "/notifications/settings",
            {"email_enabled": "", "muted": ["finance"]},
        )

        self.assertIn(response.status_code, (200, 302))
        preference = NotificationPreference.objects.get(user_id=self.pl.id)
        self.assertFalse(preference.email_enabled)
        self.assertEqual(preference.email_muted_categories, ["finance"])

        self.client.post("/notifications/settings", {"email_enabled": "on"})
        preference.refresh_from_db()
        self.assertTrue(preference.email_enabled)
        self.assertEqual(preference.email_muted_categories, [])

    def test_settings_cannot_name_somebody_else(self):
        self.client.force_login(self.pl, backend=BACKEND)

        self.client.post(
            "/notifications/settings",
            {"email_enabled": "", "user_id": self.cd.id},
        )

        self.assertFalse(
            NotificationPreference.objects.filter(user_id=self.cd.id).exists()
        )

    def test_the_settings_need_a_signed_in_person(self):
        response = self.client.post("/notifications/settings", {"email_enabled": ""})

        self.assertIn(response.status_code, (302, 401, 403))
        self.assertFalse(NotificationPreference.objects.exists())

    def test_the_bell_says_who_sent_it(self):
        follow_up(self.cd, self.pl)
        self.client.force_login(self.pl, backend=BACKEND)

        page = self.client.get("/notifications/").content.decode()
        drawer = self.client.get("/notifications/drawer").content.decode()

        self.assertIn("From Director", page)
        self.assertIn("From Director", drawer)

    def test_an_administrator_sees_delivery_health_without_any_secret(self):
        follow_up(self.cd, self.pl)
        self.client.force_login(self.admin, backend=BACKEND)

        with (
            mock.patch.dict(os.environ, RESEND),
            override_settings(RESEND_WEBHOOK_SECRET=WEBHOOK_SECRET),
        ):
            response = self.client.get("/system-health/notifications")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Email", html)
        self.assertIn("Queued", html)
        self.assertNotIn(RESEND["RESEND_API_KEY"], html)
        self.assertNotIn(WEBHOOK_SECRET, html)

    def test_delivery_health_is_for_administrators_only(self):
        self.client.force_login(self.pl, backend=BACKEND)

        response = self.client.get("/system-health/notifications")

        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn("Delivery health", response.content.decode())

    def test_an_administrator_can_send_themselves_a_test_notification(self):
        self.client.force_login(self.admin, backend=BACKEND)

        response = self.client.post("/system-health/notifications/test")

        self.assertIn(response.status_code, (200, 302))
        notification = Notification.objects.get(recipient_id=self.admin.id)
        self.assertEqual(notification.sender_id, self.admin.id)
        self.assertEqual(deliveries(notification).count(), 1)

    def test_nobody_else_can_send_the_test(self):
        self.client.force_login(self.pl, backend=BACKEND)

        self.client.post("/system-health/notifications/test")

        self.assertFalse(Notification.objects.filter(recipient_id=self.pl.id).exists())
