"""Transactional-test guard for migration-owned reference data.

``TransactionTestCase`` flushes the database after each test. Django then
emits ``post_migrate``; the receiver in ``apps.core.apps`` is the only code
allowed to restore reference data.

This base class deliberately does not repair anything. It verifies the
result after Django's teardown so a disconnected receiver, an inhibited
signal, or a failing ensure function makes the responsible test fail at the
point where it damaged the shared test database.
"""

from __future__ import annotations

from django.test import TransactionTestCase


class ReferenceDataTransactionTestCase(TransactionTestCase):
    """Verify, but never perform, post-flush reference-data restoration."""

    def _post_teardown(self):
        super()._post_teardown()

        from apps.core import reference_data

        outcome = reference_data.verify_all()
        failed = sorted(app for app, ok in outcome.items() if not ok)
        self.assertEqual(
            failed,
            [],
            "post_migrate did not restore required reference data for: "
            + ", ".join(failed),
        )


__all__ = ["ReferenceDataTransactionTestCase"]
