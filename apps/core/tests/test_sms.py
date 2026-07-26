"""The SMS sender carries a live sign-in code, so it answers to two rules.

It must not leak the code into a log stream, where it outlives the message and
is readable by anyone with log access — and it must not report success it did
not get, because "your code is on its way" sent to a number that refused it is
how somebody gets locked out while being told everything is fine.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.core.sms import SmsMessage, SmsService

CODE_BODY = "482915 is your Edify sign-in code."


class ProviderSelectionTest(SimpleTestCase):
    def test_console_is_the_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(SmsService().provider, "console")
            self.assertFalse(SmsService().is_configured)

    def test_half_a_configuration_is_not_a_configuration(self):
        """A provider name with no credentials would otherwise take the live
        branch and fail on every send."""
        for env in (
            {"SMS_PROVIDER": "africastalking"},
            {"SMS_PROVIDER": "africastalking", "SMS_API_KEY": "k"},
            {"SMS_PROVIDER": "africastalking", "SMS_USERNAME": "u"},
        ):
            with self.subTest(env=env):
                with mock.patch.dict("os.environ", env, clear=True):
                    self.assertEqual(SmsService().provider, "console")

    def test_a_full_configuration_is_used(self):
        with mock.patch.dict(
            "os.environ",
            {
                "SMS_PROVIDER": "africastalking",
                "SMS_API_KEY": "k",
                "SMS_USERNAME": "u",
            },
            clear=True,
        ):
            self.assertEqual(SmsService().provider, "africastalking")
            self.assertTrue(SmsService().is_configured)


class ConsoleProviderTest(SimpleTestCase):
    def _send(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            return SmsService().send(SmsMessage(to="+256700000000", text=CODE_BODY))

    @override_settings(SMS_LOG_BODIES=False, IS_PRODUCTION=False)
    def test_the_code_is_not_written_to_the_log_by_default(self):
        with self.assertLogs("edify.sms", level="INFO") as logs:
            self._send()
        self.assertNotIn("482915", "\n".join(logs.output))

    @override_settings(SMS_LOG_BODIES=True, IS_PRODUCTION=True)
    def test_production_withholds_the_body_even_when_asked_to_log_it(self):
        """A deploy that forgets its SMS credentials falls back to this
        provider. The opt-in is a local-development convenience and must not
        become a way to print live codes on a production log stream."""
        with self.assertLogs("edify.sms", level="INFO") as logs:
            self._send()
        self.assertNotIn("482915", "\n".join(logs.output))

    @override_settings(SMS_LOG_BODIES=True, IS_PRODUCTION=False)
    def test_a_developer_who_opts_in_can_read_the_code(self):
        with self.assertLogs("edify.sms", level="INFO") as logs:
            self._send()
        self.assertIn("482915", "\n".join(logs.output))

    def test_it_reports_that_nothing_was_delivered(self):
        result = self._send()
        self.assertFalse(result["delivered"])
        self.assertIn("482915", result["devPreview"])


def _response(body: str, status: int = 200):
    fake = mock.MagicMock()
    fake.status = status
    fake.read.return_value = body.encode()
    fake.__enter__.return_value = fake
    return fake


def _accepted(recipients):
    return json.dumps({"SMSMessageData": {"Recipients": recipients}})


class LiveProviderTest(SimpleTestCase):
    ENV = {
        "SMS_PROVIDER": "africastalking",
        "SMS_API_KEY": "k",
        "SMS_USERNAME": "u",
    }

    def _send(self, response):
        with mock.patch.dict("os.environ", self.ENV, clear=True):
            with mock.patch("urllib.request.urlopen", return_value=response):
                return SmsService().send(SmsMessage(to="+256700000000", text=CODE_BODY))

    def test_a_queued_message_counts_as_delivered(self):
        body = _accepted([{"number": "+256700000000", "statusCode": 101}])
        self.assertTrue(self._send(_response(body))["delivered"])

    def test_a_rejected_number_does_not(self):
        """This is the case a status-code check would get wrong: the provider
        answers 200 and refuses the recipient inside the envelope."""
        body = _accepted([{"number": "+256700000000", "statusCode": 403}])
        self.assertFalse(self._send(_response(body))["delivered"])

    def test_an_empty_recipient_list_does_not(self):
        self.assertFalse(self._send(_response(_accepted([])))["delivered"])

    def test_an_unreadable_response_does_not(self):
        with self.assertLogs("edify.sms", level="ERROR"):
            self.assertFalse(self._send(_response("<html>gateway error"))["delivered"])

    def test_an_error_status_does_not(self):
        with self.assertLogs("edify.sms", level="ERROR"):
            result = self._send(_response("nope", status=500))
        self.assertFalse(result["delivered"])

    def test_a_network_failure_never_reaches_the_caller(self):
        """This runs inside a login request. A provider outage must degrade
        into "we could not send the code", not a stack trace on the sign-in
        page."""
        with mock.patch.dict("os.environ", self.ENV, clear=True):
            with mock.patch("urllib.request.urlopen", side_effect=OSError("no route")):
                with self.assertLogs("edify.sms", level="ERROR"):
                    result = SmsService().send(SmsMessage(to="+256700000000", text="x"))
        self.assertFalse(result["delivered"])

    def test_the_request_is_bounded(self):
        """An unbounded call here holds a web worker for as long as the
        provider keeps the socket open."""
        from apps.core import sms as sms_module

        with mock.patch.dict("os.environ", self.ENV, clear=True):
            with mock.patch(
                "urllib.request.urlopen",
                return_value=_response(_accepted([{"statusCode": 101}])),
            ) as urlopen:
                SmsService().send(SmsMessage(to="+256700000000", text="x"))
        self.assertEqual(
            urlopen.call_args.kwargs.get("timeout"),
            sms_module.REQUEST_TIMEOUT_SECONDS,
        )
