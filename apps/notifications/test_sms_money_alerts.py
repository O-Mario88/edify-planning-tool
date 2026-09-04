"""SMS money alerts — the off-device copy of every decision that moves money.

The in-app rail only reaches a person who is on the platform. A CCEO in the
field learns that their week was approved, returned or disbursed only when
they next open the app. These tests pin the SMS fan-out in
WorkflowNotificationService: one message per recipient with a phone, sent
after commit, never for people who opted out, never for events outside the
money set, and never able to fail the workflow that triggered it.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.core.sms import SmsService
from apps.notifications.models import Notification
from apps.notifications.services import (
    SMS_MAX_LENGTH,
    SMS_MONEY_EVENTS,
    WorkflowNotificationService,
    compose_money_sms,
)

PHONE = "+256700000001"
TITLE = "Weekly fund request approved"
BODY = (
    "Your weekly fund request (Jul 06 – Jul 12) was approved and sent to the "
    "Accountant for disbursement."
)


def _user(email: str, *, phone: str | None = PHONE, **extra) -> User:
    return User.objects.create_user(
        email=email,
        name="Ana CCEO",
        roles=["CCEO"],
        active_role="CCEO",
        password="x",
        is_active=True,
        phone=phone,
        **extra,
    )


def _trigger(recipients, event_type="weekly_fund_request_approved", **overrides):
    kwargs = dict(
        event_type=event_type,
        category="finance",
        priority="high",
        title=TITLE,
        body=BODY,
        context_type="WeeklyFundRequest",
        context_id="WFR-1",
        recipients=recipients,
    )
    kwargs.update(overrides)
    return WorkflowNotificationService.trigger(**kwargs)


class SmsMoneyAlertsTest(TestCase):
    def test_money_event_set_is_the_agreed_seven(self):
        self.assertEqual(
            SMS_MONEY_EVENTS,
            {
                "weekly_fund_request_approved",
                "weekly_fund_request_returned",
                "weekly_fund_request_disbursed",
                "fund_request_disbursed",
                "accountability_cleared",
                "accountability_pl_approved",
                "accountability_pl_returned",
            },
        )

    def test_sms_is_queued_on_commit_for_an_approved_weekly_request(self):
        cceo = _user("cceo@sms.test")
        with patch.object(SmsService, "send", return_value={"delivered": True}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                created = _trigger([cceo.id])
                # Nothing leaves while the transaction is open: the provider
                # refuses inside one, and a rolled-back approval must not be
                # announced.
                send.assert_not_called()
        self.assertEqual(len(created), 1)
        send.assert_called_once()
        msg = send.call_args.args[0]
        self.assertEqual(msg.to, PHONE)
        self.assertTrue(msg.text.startswith(f"{TITLE}. {BODY}"), msg.text)
        # The resolver deep-links the request itself when it can.
        self.assertTrue(msg.text.endswith(" /fund-requests/weekly/WFR-1"), msg.text)
        self.assertLessEqual(len(msg.text), SMS_MAX_LENGTH)

    def test_every_money_event_fans_out(self):
        cceo = _user("cceo@sms.test")
        for index, event in enumerate(sorted(SMS_MONEY_EVENTS)):
            with patch.object(SmsService, "send", return_value={}) as send:
                with self.captureOnCommitCallbacks(execute=True):
                    _trigger([cceo.id], event_type=event, context_id=f"CTX-{index}")
            self.assertEqual(send.call_count, 1, event)

    def test_no_sms_without_a_phone(self):
        blank = _user("blank@sms.test", phone="")
        none = _user("none@sms.test", phone=None)
        spaces = _user("spaces@sms.test", phone="   ")
        with patch.object(SmsService, "send") as send:
            with self.captureOnCommitCallbacks(execute=True):
                created = _trigger([blank.id, none.id, spaces.id])
        # The in-app notification still lands; only the SMS copy is skipped.
        self.assertEqual(len(created), 3)
        send.assert_not_called()

    def test_no_sms_when_the_person_opted_out(self):
        quiet = _user("quiet@sms.test", sms_money_alerts=False)
        with patch.object(SmsService, "send") as send:
            with self.captureOnCommitCallbacks(execute=True):
                created = _trigger([quiet.id])
        self.assertEqual(len(created), 1)
        self.assertEqual(Notification.objects.filter(recipient_id=quiet.id).count(), 1)
        send.assert_not_called()

    def test_no_sms_for_events_outside_the_money_set(self):
        cceo = _user("cceo@sms.test")
        with patch.object(SmsService, "send") as send:
            with self.captureOnCommitCallbacks(execute=True):
                _trigger(
                    [cceo.id],
                    event_type="leave_approved",
                    context_type="leave",
                    context_id="L-1",
                    title="Leave approved",
                    body="Your leave was approved.",
                )
                _trigger(
                    [cceo.id],
                    event_type="weekly_fund_request_submitted",
                    title="Weekly fund request submitted",
                    body="A request awaits your review.",
                )
        send.assert_not_called()

    def test_only_the_recipients_with_phones_are_messaged(self):
        with_phone = _user("with@sms.test", phone="+256700000002")
        without = _user("without@sms.test", phone="")
        opted_out = _user("out@sms.test", phone="+256700000003", sms_money_alerts=False)
        with patch.object(SmsService, "send", return_value={}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                created = _trigger([with_phone.id, without.id, opted_out.id])
        self.assertEqual(len(created), 3)
        self.assertEqual([c.args[0].to for c in send.call_args_list], ["+256700000002"])

    def test_sms_failure_never_fails_the_workflow(self):
        cceo = _user("cceo@sms.test")
        with patch.object(
            SmsService, "send", side_effect=RuntimeError("provider down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                created = _trigger([cceo.id])
        self.assertEqual(len(created), 1)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=cceo.id, source_event_type="weekly_fund_request_approved"
            ).exists()
        )

    def test_one_broken_number_does_not_block_the_next(self):
        first = _user("first@sms.test", phone="+256700000011")
        second = _user("second@sms.test", phone="+256700000012")

        def _send(msg):
            if msg.to == "+256700000011":
                raise RuntimeError("bad number")
            return {"delivered": True}

        with patch.object(SmsService, "send", side_effect=_send) as send:
            with self.captureOnCommitCallbacks(execute=True):
                _trigger([first.id, second.id])
        self.assertEqual(
            sorted(c.args[0].to for c in send.call_args_list),
            ["+256700000011", "+256700000012"],
        )

    def test_a_refire_of_the_same_condition_is_messaged_again(self):
        """A returned-then-resubmitted request re-fires the same event on
        the same context; the rail dedupes into one row, but the person still
        needs to hear the new decision off-device."""
        cceo = _user("cceo@sms.test")
        with patch.object(SmsService, "send", return_value={}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                _trigger([cceo.id])
                _trigger([cceo.id])
        self.assertEqual(Notification.objects.filter(recipient_id=cceo.id).count(), 1)
        self.assertEqual(send.call_count, 2)


class ComposeMoneySmsTest(TestCase):
    def test_short_message_carries_the_route(self):
        text = compose_money_sms(TITLE, BODY, "/fund-requests/weekly")
        self.assertEqual(text, f"{TITLE}. {BODY} /fund-requests/weekly")
        self.assertLessEqual(len(text), SMS_MAX_LENGTH)

    def test_long_message_is_cut_to_one_segment_and_drops_the_route(self):
        long_body = "Reason: " + ("receipt missing " * 20).strip()
        text = compose_money_sms(
            "Weekly fund request returned", long_body, "/fund-requests/weekly"
        )
        self.assertEqual(len(text), SMS_MAX_LENGTH)
        self.assertNotIn("/fund-requests", text)
        self.assertTrue(text.startswith("Weekly fund request returned. Reason: "))

    def test_route_is_only_added_when_the_whole_message_fits(self):
        route = "/fund-requests/weekly/abc"
        body = "x" * (SMS_MAX_LENGTH - len("T. ") - len(" " + route))
        self.assertTrue(compose_money_sms("T", body, route).endswith(route))
        self.assertFalse(compose_money_sms("T", body + "y", route).endswith(route))

    def test_title_full_stop_is_not_doubled(self):
        self.assertEqual(
            compose_money_sms("Funds disbursed.", "Confirm receipt.", None),
            "Funds disbursed. Confirm receipt.",
        )
