"""One place that knows which rows must exist for the platform to work.

Reference data is not user data. Nobody creates an official target area or a
cost catalogue entry in the interface; the code resolves through them by key,
and an empty table does not raise — it silently produces nothing. HR approval
writing no targets at all is what that looks like from the outside.

Seeding it in a data migration is enough for a database that only ever moves
forward. It is not enough for one that gets flushed: `TransactionTestCase`
truncates every table, and migration-seeded rows do not come back. The row is
gone for the rest of that database's life, and the test that fails is somewhere
else entirely, with nothing pointing back.

The fix each app reached for was the same — an idempotent `ensure_*()` wired to
`post_migrate`, which Django emits after a flush as well as after a migrate.
Three apps did it in `AppConfig.ready()`, one in a `signals.py`, and the rest
had never been bitten yet. Two conventions, no list, and no way to tell what
was covered without reading every app.

So this is the list. An app registers its ensure function here; one receiver
runs them all. What that buys is not the wiring — that was never hard — it is
that "which rows are protected?" becomes a question with an answer, and
`apps/core/tests/test_reference_data.py` can hold the whole convention to
account: every registered function must be idempotent, must actually restore
its rows after a real flush, and no app may seed reference data in a migration
without appearing here.

WHAT DOES NOT BELONG HERE
-------------------------
A one-off backfill or repair. `clusters.0003` repairs cluster membership;
`messaging.0005` backfills participants for threads that predate the
multi-participant model. Those describe a transition, not a required state, and
re-running them on every flush would be wrong. They are listed as exemptions in
the test rather than registered here, so the distinction is written down once
and reviewed rather than rediscovered.

ORDER
-----
Registration order, which is `INSTALLED_APPS` order, because that is already
arranged so an app comes after anything it has a foreign key into. Geography
before anything that references a district.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger("edify.reference_data")

# app_label -> (the callable that puts this app's reference rows back, the
# read-only callable that proves the required rows are present).
#
# Whatever it returns is ignored. It was tempting to make it report how many
# rows it created and to have the tests assert on that, but a function that
# under-reports would then be indistinguishable from one that had nothing to
# do — the failure this whole module exists to prevent, moved one level up.
# The tests count rows in the database instead.
_REGISTRY: dict[str, tuple[Callable[[], object], Callable[[], bool]]] = {}


def register(
    app_label: str,
    ensure: Callable[[], object],
    verify: Callable[[], bool],
) -> None:
    """Declare that this app has reference data that must survive a flush.

    Call from `AppConfig.ready()`. `ensure` must be idempotent and must only
    ever create what is missing — never update or delete. `verify` must be
    read-only and return whether the app's required state is complete. A label
    or a weight an administrator edited is their decision, and a restore that
    runs on every deploy must not walk it back.
    """
    registration = (ensure, verify)
    if app_label in _REGISTRY and _REGISTRY[app_label] != registration:
        raise RuntimeError(
            f"Reference data for '{app_label}' is already registered to a "
            "different function. One app, one ensure function — if it needs to "
            "restore several tables, have that function call the others."
        )
    _REGISTRY[app_label] = registration


def registered_apps() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def restore_all() -> dict[str, bool]:
    """Run every registered ensure function. Returns which ones succeeded.

    A failure in one app does not stop the others. The alternative is that one
    app's bad state leaves the whole platform without its reference data, which
    is a far larger blast radius than the original problem — and the log line
    names the app either way.

    This runs on every migrate and every flush, so each ensure function needs
    to stay cheap. `test_reference_data.py` holds them to that.
    """
    outcome: dict[str, bool] = {}
    for app_label, (ensure, _verify) in _REGISTRY.items():
        try:
            ensure()
            outcome[app_label] = True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Reference data for '%s' could not be restored: %s", app_label, exc
            )
            outcome[app_label] = False
    failed = sorted(app for app, ok in outcome.items() if not ok)
    if failed:
        logger.error("Reference data could not be restored for: %s", failed)
    return outcome


def verify_all() -> dict[str, bool]:
    """Read only: report whether every app's required rows are present.

    Restoration belongs to the ``post_migrate`` receiver. Test infrastructure
    calls this after Django's teardown flush so it can expose a broken receiver
    instead of silently repairing the evidence it was meant to inspect.
    """
    outcome: dict[str, bool] = {}
    for app_label, (_ensure, verify) in _REGISTRY.items():
        try:
            outcome[app_label] = bool(verify())
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Reference data for '%s' could not be verified: %s", app_label, exc
            )
            outcome[app_label] = False
    return outcome


__all__ = ["register", "registered_apps", "restore_all", "verify_all"]
