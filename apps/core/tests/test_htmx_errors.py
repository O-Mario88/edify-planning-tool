"""A failed action tells the user what happened, and nothing else.

Thirty-one views used to answer a failure by interpolating the exception
straight into an HTML fragment. Both halves of that were wrong: the text was
not escaped, and exception messages routinely quote the value that caused them,
so a school name carrying markup became script in the response; and the bare
`except Exception` meant an IntegrityError quoting a constraint or a database
error carrying part of the query went to whoever tripped it.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.htmx_errors import (
    UNEXPECTED_MESSAGE,
    error_fragment,
    error_message,
    is_user_facing,
    notice_fragment,
)


class UserFacingClassificationTest(TestCase):
    def test_domain_exceptions_carry_a_message_for_the_user(self):
        for exc in (
            BadRequest("Pick a date first."),
            Forbidden("Not your activity."),
            NotFoundError("No such school."),
            DjangoValidationError("Score must be between 0 and 10."),
        ):
            with self.subTest(exc=type(exc).__name__):
                self.assertTrue(is_user_facing(exc))

    def test_everything_else_is_a_bug_not_a_message(self):
        for exc in (
            ValueError("invalid literal for int() with base 10: 'x'"),
            AttributeError("'NoneType' object has no attribute 'school_id'"),
            KeyError("cost_setting"),
            ZeroDivisionError("division by zero"),
        ):
            with self.subTest(exc=type(exc).__name__):
                self.assertFalse(is_user_facing(exc))


class ErrorMessageTest(TestCase):
    def test_a_domain_message_is_shown_as_written(self):
        self.assertEqual(
            error_message(BadRequest("Pick a date first.")), "Pick a date first."
        )

    def test_an_unexpected_exception_says_nothing_about_itself(self):
        detail = 'relation "activity" violates constraint uniq_sf_id'
        message = error_message(ValueError(detail))
        self.assertEqual(message, UNEXPECTED_MESSAGE)
        self.assertNotIn("constraint", message)
        self.assertNotIn("activity", message)

    def test_the_action_says_what_was_being_attempted(self):
        self.assertEqual(
            error_message(BadRequest("No slots left."), action="Could not schedule"),
            "Could not schedule: No slots left.",
        )


class ErrorFragmentTest(TestCase):
    def test_markup_in_a_domain_message_is_escaped(self):
        """The live shape: a message quoting a value the user supplied."""
        body = error_fragment(
            BadRequest('School "<script>alert(1)</script>" not found.')
        ).content.decode()
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_an_unexpected_exception_is_logged_with_its_traceback(self):
        with self.assertLogs("apps.core.htmx_errors", level=logging.ERROR) as logs:
            body = error_fragment(
                ValueError("secret internal detail"), action="Save the plan"
            ).content.decode()
        self.assertIn("Save the plan", "\n".join(logs.output))
        self.assertIn("secret internal detail", "\n".join(logs.output))
        self.assertNotIn("secret internal detail", body)

    def test_a_domain_failure_is_not_logged_as_an_error(self):
        """A user picking a bad date is not an incident, and a log full of
        them is a log nobody reads."""
        with self.assertNoLogs("apps.core.htmx_errors", level=logging.ERROR):
            error_fragment(BadRequest("Pick a date first."))

    def test_the_status_defaults_to_bad_request_and_is_overridable(self):
        self.assertEqual(error_fragment(BadRequest("x")).status_code, 400)
        self.assertEqual(error_fragment(Forbidden("x"), status=403).status_code, 403)

    def test_the_fragment_announces_itself_to_a_screen_reader(self):
        body = error_fragment(BadRequest("Pick a date first.")).content.decode()
        self.assertIn('role="alert"', body)


class NoticeFragmentTest(TestCase):
    def test_a_composed_message_is_escaped_too(self):
        body = notice_fragment("Missing score for <b>Leadership</b>").content.decode()
        self.assertNotIn("<b>", body)
        self.assertIn("&lt;b&gt;", body)
