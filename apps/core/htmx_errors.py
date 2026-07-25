"""One way to render a failed action back into an htmx swap.

Views used to build these by hand:

    except Exception as e:
        return HttpResponse(f'<div class="...">Error: {str(e)}</div>', status=400)

which is wrong twice over. The exception text goes into the page unescaped, and
exception messages routinely quote the value that caused them — so a school
name or an id with markup in it becomes script in the response. And `Exception`
catches everything, so an IntegrityError quoting a constraint, an AttributeError
naming an internal attribute, or a database error carrying a fragment of the
query all get shown to whoever triggered them.

The distinction that matters is whether the message was written for a user.
`EdifyAPIException` and Django's `ValidationError` are raised deliberately by
domain code with a sentence someone is meant to read; everything else is a bug,
and the honest response is a generic line to the user and a full traceback in
the log where it can be acted on.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.utils.html import format_html

from apps.core.exceptions import EdifyAPIException

logger = logging.getLogger(__name__)

# Shown when the exception was not one the domain raised on purpose. It says
# what failed and that it was recorded, and nothing about how.
UNEXPECTED_MESSAGE = "Something went wrong. The error has been logged."

FRAGMENT = (
    '<div class="p-3 rounded-surface bg-rose-50 text-rose-700 '
    'text-[12px] font-bold" role="alert">{}</div>'
)


def is_user_facing(exc: BaseException) -> bool:
    """True when the exception's message was written to be read by a user."""
    return isinstance(exc, (EdifyAPIException, DjangoValidationError))


def error_message(exc: BaseException, *, action: str | None = None) -> str:
    """The sentence to show for `exc`, without any markup.

    `action` prefixes it with what was being attempted, which is most of the
    value of these messages — "Could not schedule the selection" tells the user
    what to try again, where the exception text alone often does not.
    """
    if is_user_facing(exc):
        detail = getattr(exc, "message", None) or str(exc)
    else:
        detail = UNEXPECTED_MESSAGE
    return f"{action}: {detail}" if action else detail


def error_fragment(
    exc: BaseException,
    *,
    action: str | None = None,
    status: int = 400,
) -> HttpResponse:
    """An escaped inline error block for an htmx swap.

    Unexpected exceptions are logged with their traceback before the generic
    message goes out, so nothing is lost by not showing it.
    """
    if not is_user_facing(exc):
        # exc_info=exc rather than logger.exception(): the latter reads
        # sys.exc_info(), which is only populated inside an active handler.
        # Callers are inside one today, but a helper that silently logs
        # "NoneType: None" when they are not is worse than no log at all.
        logger.error("Unhandled error during %s", action or "an action", exc_info=exc)
    return HttpResponse(
        format_html(FRAGMENT, error_message(exc, action=action)), status=status
    )


def notice_fragment(message: str, *, status: int = 400) -> HttpResponse:
    """The same block for a message the view composed itself.

    Views also refuse actions for reasons that are not exceptions — a stale
    status, a missing field. Those went out as hand-built f-strings too, and
    while the values in them come from server-side enums today, the next one
    to be written that way will not necessarily.
    """
    return HttpResponse(format_html(FRAGMENT, message), status=status)
