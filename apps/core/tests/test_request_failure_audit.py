"""A 500 must leave behind enough to diagnose it after the container is gone.

App Platform keeps no logs for a superseded deployment. During the live audit
on 2026-08-04 a page was returning 500 for the current month; the container log
had the traceback, but the deployment that produced it had already been
replaced, so the only way to read it was to reproduce the fault against the
live app. That worked because the bug was still reproducible. A one-off — a
race, a bad row since corrected, an error a user hit on Tuesday — would have
left nothing.

`AllExceptionsMiddleware` already wrote a `request_failed` audit row, and that
row does survive deploys. It already carried the correlation id too —
`audit.services.log` fills it from the request context, so a user quoting the
code from an error banner could always be matched. One thing was missing:
**where the exception came from.** The row named the exception type and the
path, which does not distinguish one bug from another.

What is deliberately *not* stored is the formatted traceback, or the exception
message. Audit rows are read and exported by administrators; a traceback
carries locals and arguments, and a message routinely carries data — an
IntegrityError names the conflicting key and its value.
`test_error_observability` asserts that boundary with `RuntimeError("secret")`
and exact payload equality, and it is what caught a `message` field added
during this work.

`file:line:function` locates the fault exactly and carries none of that.
"""

from __future__ import annotations

from django.http import HttpRequest
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.core.middleware import AllExceptionsMiddleware, _exception_origin


def _boom():
    raise AttributeError("'FundRequest' object has no attribute 'GET'")


class RequestFailureAuditTest(TestCase):
    def _trigger(self, path="/accounts/monthly-request/"):
        request = HttpRequest()
        request.method = "GET"
        request.path = path
        middleware = AllExceptionsMiddleware(lambda r: None)
        try:
            _boom()
        except AttributeError as exc:
            return middleware.process_exception(request, exc)

    def test_the_failure_is_recorded_at_all(self):
        self._trigger()
        self.assertTrue(AuditLog.objects.filter(action="request_failed").exists())

    def test_the_exception_message_never_reaches_the_audit_row(self):
        """The one field that routinely carries data.

        An IntegrityError names the conflicting key and its value; a
        ValidationError quotes the input. Audit rows are read and exported by
        administrators, so the message stays in the container log and out of
        here. test_error_observability guards the same boundary with
        RuntimeError("secret") — this is the same rule stated from the other
        side, because I added a `message` field during this work and that test
        is what caught it.
        """
        self._trigger()
        row = AuditLog.objects.filter(action="request_failed").latest("id")
        self.assertNotIn("message", row.payload)
        self.assertNotIn("FundRequest", str(row.payload))

    def test_it_records_where_the_exception_came_from(self):
        self._trigger()
        row = AuditLog.objects.filter(action="request_failed").latest("id")
        origin = row.payload.get("origin")
        self.assertTrue(origin, "an exception type alone cannot be acted on")
        self.assertTrue(
            any("test_request_failure_audit.py" in f and ":_boom" in f for f in origin),
            f"origin should name the raising frame, got {origin}",
        )

    def test_it_does_not_store_a_formatted_traceback(self):
        # Locals and argument values must not reach an exportable audit table.
        self._trigger()
        row = AuditLog.objects.filter(action="request_failed").latest("id")
        blob = str(row.payload)
        self.assertNotIn("Traceback (most recent call last)", blob)


class ExceptionOriginTest(TestCase):
    def test_library_frames_are_dropped(self):
        """A Django or psycopg frame is identical for every error of its kind
        and would push out the frames that identify this one."""
        try:
            _boom()
        except AttributeError as exc:
            frames = _exception_origin(exc)
        self.assertTrue(frames)
        self.assertFalse([f for f in frames if "site-packages" in f])

    def test_it_keeps_the_innermost_frames(self):
        def outer():
            _boom()

        try:
            outer()
        except AttributeError as exc:
            frames = _exception_origin(exc)
        # Innermost last: the raising frame is where the fault is.
        self.assertIn(":_boom", frames[-1])
        self.assertLessEqual(len(frames), 3)
