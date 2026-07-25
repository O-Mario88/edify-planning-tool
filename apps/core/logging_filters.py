"""Keep one logged event on one line.

Log records here carry values that came from outside: a school id, an activity
reference, an exception message quoting whatever tripped it. A newline in any
of those splits one event into two, and the second one can be spelled to look
like a genuine entry — a forged "user X granted admin" sitting in the same file
as the real ones. Nothing downstream can tell them apart afterwards.

Rather than remembering to sanitise at each of the several hundred logging
calls, the record is cleaned once on its way out. Applied as a filter so it
runs regardless of which handler or formatter is configured.
"""

from __future__ import annotations

import logging

# Anything that would end the line, plus the escape that drives a terminal.
_TRANSLATION = {
    ord("\n"): "\\n",
    ord("\r"): "\\r",
    ord("\x1b"): "\\x1b",
    ord("\x00"): "\\x00",
}


def escape_control_characters(value: str) -> str:
    return value.translate(_TRANSLATION)


class SingleLineFilter(logging.Filter):
    """Escape line breaks in the message and its arguments.

    The traceback attached by exc_info is deliberately left alone — it is
    multi-line by nature, it is produced by the interpreter rather than by
    request data, and flattening it would make it unreadable for no gain.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = escape_control_characters(record.msg)
        if isinstance(record.args, dict):
            record.args = {
                key: escape_control_characters(value)
                if isinstance(value, str)
                else value
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                escape_control_characters(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True
