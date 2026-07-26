"""Backwards-compatible shim over apps.core.reference_data.

This module used to hold its own copy of the migration-seeded rows — the five
official target areas and the cost catalogue — and three existing
`TransactionTestCase` classes call `reseed_migration_data()` from an overridden
`_post_teardown()` to put them back after the flush.

Two problems with that, both fixed by delegating:

The rows were **duplicated, not imported**. The target areas existed in the
migration, in `apps/targets/reference.py`, and again here — with a comment
explaining that migration modules are not meant to be imported as app code.
That is true, and the answer is to import the app's own ensure function rather
than keep a third copy that nothing stops from drifting. A weight edited in two
of the three places would have produced a different Overall Progress depending
on whether the database had been flushed.

And it was **opt-in**. A `TransactionTestCase` whose author did not know to
override `_post_teardown` left the database empty, which is the failure this
whole area keeps producing. The registry's `post_migrate` receiver is not
opt-in: Django emits that signal after the teardown flush too, so the rows come
back whether or not anyone knew to ask.

Kept as a shim because three test classes already call it and there is nothing
to gain from editing them. New code should not call it — there is no longer
anything here to call.
"""

from __future__ import annotations


def reseed_migration_data() -> None:
    """Restore every registered app's reference data. Idempotent.

    Superseded by the `post_migrate` receiver in `apps.core.apps`, which runs
    on its own after each flush. Calling it again costs a few queries and
    changes nothing.
    """
    from apps.core import reference_data

    reference_data.restore_all()
