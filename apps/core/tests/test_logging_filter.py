"""A logged value cannot forge a second log line.

Records here carry outside data — a school id, an activity reference, an
exception message quoting whatever tripped it. A newline in any of those splits
one event into two, and the second can be spelled to look like a genuine entry:
a fabricated "user X granted admin" sitting in the same file, in the same
format, as the real ones. Nothing downstream can tell them apart afterwards.

The control is a logging filter rather than sanitisation at each of the several
hundred call sites, because a call site that is added next month will not
remember. These tests pin the filter, and pin that it is actually installed —
a filter configured but not attached to the handler is no control at all.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.logging_filters import SingleLineFilter, escape_control_characters

FORGED = "SCH-1\nWARNING probe: user forged-admin granted Admin"


class EscapeTest(SimpleTestCase):
    def test_a_line_break_cannot_end_the_line(self):
        self.assertNotIn("\n", escape_control_characters(FORGED))
        self.assertIn("\\n", escape_control_characters(FORGED))

    def test_a_carriage_return_cannot_either(self):
        self.assertNotIn("\r", escape_control_characters("a\rb"))

    def test_an_escape_sequence_cannot_drive_the_terminal(self):
        """A log read in a terminal is still a program reading input."""
        self.assertNotIn("\x1b", escape_control_characters("a\x1b[2Jb"))

    def test_ordinary_text_is_untouched(self):
        for text in ("SCH-1 onboarded", "Ada O'Brien", "score 7.5/10", ""):
            with self.subTest(text=text):
                self.assertEqual(escape_control_characters(text), text)


class FilterTest(SimpleTestCase):
    def _record(self, msg, args=None):
        return logging.LogRecord(
            name="probe",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=None,
        )

    def test_the_message_is_flattened(self):
        record = self._record(FORGED)
        SingleLineFilter().filter(record)
        self.assertNotIn("\n", record.getMessage())

    def test_positional_arguments_are_flattened(self):
        """The usual shape: the message is a literal, the injection is in an
        argument."""
        record = self._record("school %s onboarded", (FORGED,))
        SingleLineFilter().filter(record)
        self.assertNotIn("\n", record.getMessage())
        self.assertIn("forged-admin", record.getMessage())

    def test_mapping_arguments_are_flattened(self):
        # A 1-tuple holding the mapping, which is how a logger passes one:
        # LogRecord unwraps that itself, and handing it a bare dict raises.
        record = self._record("school %(id)s onboarded", ({"id": FORGED},))
        SingleLineFilter().filter(record)
        self.assertNotIn("\n", record.getMessage())

    def test_non_string_arguments_survive_unchanged(self):
        record = self._record("count %d of %d", (3, 10))
        SingleLineFilter().filter(record)
        self.assertEqual(record.getMessage(), "count 3 of 10")

    def test_the_filter_always_passes_the_record_through(self):
        """It sanitises; it is not an excuse to drop events."""
        self.assertTrue(SingleLineFilter().filter(self._record(FORGED)))


class InstalledTest(SimpleTestCase):
    """A filter nobody attached is not a control."""

    def test_the_console_handler_carries_the_filter(self):
        self.assertIn("single_line", settings.LOGGING["handlers"]["console"]["filters"])

    def test_the_root_logger_uses_that_handler(self):
        self.assertIn("console", settings.LOGGING["root"]["handlers"])

    def test_djangos_own_request_logger_uses_it_too(self):
        """django.request logs the path, which is entirely attacker-chosen."""
        self.assertIn("console", settings.LOGGING["loggers"]["django"]["handlers"])
