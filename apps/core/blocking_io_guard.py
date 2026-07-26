"""Refuse to make a network call while holding a database transaction open.

The shape this exists to prevent: a request opens a transaction, takes row
locks on something contended — a fund request, a budget line, an activity —
and then, still inside that transaction, calls out to an email or SMS provider.
The locks are now held for as long as the provider takes to answer, which is
not a number this application controls. A provider having a slow afternoon
becomes lock contention, then connection-pool exhaustion, then an outage in a
system that has nothing wrong with it.

It is easy to write by accident and nearly invisible in review, because the
send is usually several call frames below the `transaction.atomic` that opened
the block. A lexical scan for `mailer.send` inside an `atomic` body finds none
of the interesting cases. So the check lives at the bottom of the call stack,
where the I/O actually happens, and asks the connection whether a transaction
is open — which is true however deep the caller is.

Two behaviours, on purpose:

  In tests it raises. A regression should fail the build, and a test suite is
  exactly where the call graph gets exercised widely enough to find one.

  In production it logs and proceeds. The send is already committed to at this
  point; refusing it would turn a latency problem into a lost notification, and
  a person waiting for a sign-in code does not care about lock hygiene. The log
  line is what brings it back for repair.

The fix, when this fires, is almost always `transaction.on_commit(...)`: let
the transaction finish, then send. That is also more correct — a message about
work that then rolled back is worse than a late one.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger("edify.blocking_io")


class BlockingIOInTransaction(RuntimeError):
    """Raised in tests when network I/O is attempted inside a transaction."""


def _tests_are_running() -> bool:
    return bool(getattr(settings, "IS_TESTING", False))


# Telling the application's transaction from the test harness's.
#
# This needs no baseline capture, which is just as well: there is no seam to
# capture one from. Django's `TestCase` enters its per-test atomic inside
# `TestCase.run()`, which is *below* every pytest hook and fixture, so anything
# that reads the depth earlier records zero and then reports every send inside
# a `TestCase` as a violation. Two attempts at that failed the same way.
#
# The two harnesses are distinguishable by shape instead:
#
#   TestCase             holds a transaction, so a send sees savepoint depth 1
#                        before the application has opened anything. An atomic
#                        the application opens nests above it: depth 2.
#
#   TransactionTestCase  holds none. `in_atomic_block` is False until the
#                        application opens one, and then it is the outermost —
#                        depth 0.
#
#   A request            looks like TransactionTestCase: the first atomic is
#                        the outermost, depth 0.
#
# So depth 0 with a transaction open always means the application opened it,
# and depth 1 means the harness alone only while tests are running.
#
# The gap: `transaction.atomic(savepoint=False)` under `TestCase` does not
# raise the depth, so a send inside one is missed there. It is still caught
# under `TransactionTestCase` and in production, which is where the check
# matters most.
HARNESS_ONLY_DEPTH = 1


def in_application_transaction() -> bool:
    """Is a transaction the application opened currently in force?

    The one question both halves of this module turn on: the guard asks it to
    decide whether a send is a violation, and `send_after_commit` asks it to
    decide whether a send needs deferring.
    """
    if not connection.in_atomic_block:
        return False
    depth = len(getattr(connection, "savepoint_ids", []) or [])
    return not (_tests_are_running() and depth == HARNESS_ONLY_DEPTH)


def send_after_commit(send) -> None:
    """Run a send once the surrounding transaction has committed.

    Two reasons, and the second is the better one:

    The locks stop being held across the provider round-trip, which is what the
    guard above is complaining about.

    And an email is no longer sent for work that then rolled back. An
    invitation to an account that was never created is worse than a late
    invitation — the recipient gets a link that cannot work and no explanation.

    Deferred only when the application actually has a transaction open. With
    none, the send happens now, which keeps every existing caller behaving
    exactly as it did — including under `TestCase`, whose transaction never
    commits, so anything handed to `on_commit` there would simply never run and
    the tests asserting an email was sent would quietly stop asserting it.
    """
    if in_application_transaction():
        transaction.on_commit(send)
    else:
        send()


def refuse_inside_transaction(what: str) -> None:
    """Call at the point of network I/O, naming what is about to be sent."""
    if not in_application_transaction():
        return

    message = (
        f"{what} was attempted inside an open database transaction. The locks "
        "this request holds stay held for as long as the provider takes to "
        "answer. Move the send into transaction.on_commit()."
    )
    if _tests_are_running():
        raise BlockingIOInTransaction(message)
    logger.warning(message)


__all__ = [
    "refuse_inside_transaction",
    "send_after_commit",
    "in_application_transaction",
    "BlockingIOInTransaction",
]
