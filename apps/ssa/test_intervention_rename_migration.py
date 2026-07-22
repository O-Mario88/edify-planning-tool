"""The SSA intervention rename must be reversible, not just applicable.

Migration 0004 rewrites stored intervention values to the canonical set. Its
forward path is exercised every time a database is built, so a break there is
loud. Its reverse path is exercised by nothing, and it was wrong: the array
column passed array_replace(col, old, new), which re-applies the forward
rename rather than undoing it, so rolling the migration back left the array
columns fully migrated while the scalar columns went back. A rollback that
half-reverses is worse than one that fails outright, because it looks like it
worked.

These tests call the migration's own forward/reverse functions against real
rows so both directions are covered by something.
"""

from __future__ import annotations

from django.db import connection
from django.test import TransactionTestCase


class InterventionRenameRoundTripTest(TransactionTestCase):
    """A forward-then-reverse cycle must return every column to its start."""

    def _module(self):
        import importlib

        return importlib.import_module(
            "apps.ssa.migrations.0004_rename_ssa_interventions"
        )

    def _run(self, fn):
        with connection.schema_editor() as se:
            fn(None, se)

    def _activity(self, aid, *, scalar=None, array=None):
        """Create a valid Activity via the ORM, then write the legacy values
        in with raw SQL — the model's choices no longer accept them, which is
        the whole reason the migration exists."""
        from datetime import date

        from apps.activities.models import Activity

        Activity.objects.create(
            id=aid,
            activity_type="school_visit",
            delivery_type="staff",
            status="planned",
            fy="2026",
            quarter="Q1",
            planned_date=date(2026, 4, 1),
        )
        sets, params = [], []
        if scalar is not None:
            sets.append("focus_intervention = %s")
            params.append(scalar)
        if array is not None:
            sets.append("secondary_focus_interventions = %s")
            params.append(array)
        with connection.cursor() as c:
            c.execute(
                f"UPDATE activity SET {', '.join(sets)} WHERE id = %s",
                [*params, aid],
            )

    def test_reverse_restores_the_original_array_values(self):
        mod = self._module()
        self._activity("mig-rt-1", array=["teaching_and_learning", "leadership"])

        self._run(mod.forward)
        with connection.cursor() as c:
            c.execute(
                "SELECT secondary_focus_interventions FROM activity WHERE id=%s",
                ["mig-rt-1"],
            )
            after_forward = c.fetchone()[0]
        self.assertEqual(
            after_forward,
            ["teaching_environment", "leadership"],
            "forward did not rename the array element",
        )

        self._run(mod.reverse)
        with connection.cursor() as c:
            c.execute(
                "SELECT secondary_focus_interventions FROM activity WHERE id=%s",
                ["mig-rt-1"],
            )
            after_reverse = c.fetchone()[0]
        self.assertEqual(
            after_reverse,
            ["teaching_and_learning", "leadership"],
            "reverse left the array column migrated — rolling this migration "
            "back would silently keep the new values",
        )

    def test_reverse_restores_the_original_scalar_values(self):
        mod = self._module()
        self._activity("mig-rt-2", scalar="teaching_and_learning")

        self._run(mod.forward)
        with connection.cursor() as c:
            c.execute(
                "SELECT focus_intervention FROM activity WHERE id=%s", ["mig-rt-2"]
            )
            self.assertEqual(c.fetchone()[0], "teaching_environment")

        self._run(mod.reverse)
        with connection.cursor() as c:
            c.execute(
                "SELECT focus_intervention FROM activity WHERE id=%s", ["mig-rt-2"]
            )
            self.assertEqual(
                c.fetchone()[0],
                "teaching_and_learning",
                "reverse did not restore the scalar column",
            )

    def test_forward_is_idempotent(self):
        """Re-running forward must not corrupt already-migrated rows."""
        mod = self._module()
        self._activity(
            "mig-rt-3",
            scalar="teaching_and_learning",
            array=["education_technology"],
        )
        self._run(mod.forward)
        self._run(mod.forward)
        with connection.cursor() as c:
            c.execute(
                "SELECT focus_intervention, secondary_focus_interventions "
                "FROM activity WHERE id=%s",
                ["mig-rt-3"],
            )
            scalar, array = c.fetchone()
        self.assertEqual(scalar, "teaching_environment")
        self.assertEqual(array, ["enrolment"])
