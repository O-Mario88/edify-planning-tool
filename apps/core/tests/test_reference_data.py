"""The convention only holds if something enforces it.

Reference data seeded by a migration disappears when a `TransactionTestCase`
truncates the database, and the test that then fails is somewhere else
entirely, hundreds of files away, with nothing in the failure pointing back.
Each app that got bitten fixed itself; nothing stopped the next one being
written the same way.

So these are the four things that have to stay true, and each of them is a way
the convention has already failed or could quietly fail next:

  COMPLETENESS  An app that seeds reference data in a migration must register
                an ensure function, or be listed below as a one-off. This is
                the gate — a new feature cannot forget, because forgetting
                fails the build rather than a stranger's test next quarter.

  IDEMPOTENCY   The ensure functions run on every migrate and every flush. One
                that creates rows a second time turns a restore into
                duplication, and duplicated reference data is worse than
                missing reference data — the code resolves by key and picks
                one arbitrarily.

  RESTORATION   Registration that does not actually restore anything is
                paperwork. Proved by flushing for real and counting rows.

  NO SERIALIZED Django's own remedy for this problem, `serialized_rollback`,
  ROLLBACK      collides with ours: it re-inserts serialized content types that
                the post_migrate restore has already recreated, and the unique
                constraint refuses. Tried during the audit — it turned two
                failures into six errors. Nobody should have to find that out
                twice.
"""

from __future__ import annotations

import ast
import pathlib

from django.apps import apps as django_apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.core import reference_data

ROOT = pathlib.Path(settings.BASE_DIR)
APPS = ROOT / "apps"

# Migrations that create rows describing a TRANSITION rather than a required
# state. Re-running these after a flush would be wrong: they exist to carry an
# old database forward, and a fresh one was never in the state they repair.
#
# Adding to this list is a deliberate edit somebody has to justify in review,
# which is the entire point of it being a list rather than a heuristic.
ONE_OFF_DATA_MIGRATIONS = {
    "documents": (
        "0002 installs the two first-login agreements (safeguarding policy, "
        "Apostles' Creed). It declares itself a one-off: the migration returns "
        "early under IS_TESTING because the suite builds its own policy "
        "fixtures and asserts exact acknowledgement counts, so re-running it "
        "on every flush would be wrong — the criterion this list exists for. "
        "If these documents ever need guaranteeing on a database the initial "
        "migrate did not touch, they should graduate to a registered ensure "
        "function instead of staying here."
    ),
    "accounts": (
        "0020 grants the Admin role every canonical permission and 0021 adds "
        "the super-admin's field hat plus the StaffProfile that field work "
        "keys off. Both are one-offs about one named account and the role "
        "matrix that already exists: they touch the row for SUPER_ADMIN_EMAIL "
        "and nothing else, so on a test database — where that account is never "
        "created — they match nothing and write nothing. Restoring them on "
        "every flush would mean re-asserting a specific person's roles in the "
        "middle of tests that set their own, which is the opposite of what "
        "reference data means."
    ),
    "clusters": "0003 repairs canonical cluster membership on existing rows.",
    "core_schools": "0003 backfills the 9th package slot onto existing packages.",
    "messaging": "0005 backfills participants for pre-multi-participant threads.",
    "system_health": (
        "0002 stamps the database with the environment of the process that "
        "migrated it. Restoring that on flush would re-stamp a test database "
        "as whatever the runner is, which is a decision about the boot gate "
        "rather than about reference data."
    ),
}

_ROW_CREATING = ("objects.create(", "objects.bulk_create(", "objects.get_or_create(")


def _apps_seeding_in_migrations() -> set[str]:
    """Apps whose migrations create rows, by reading the migrations."""
    found = set()
    for path in APPS.rglob("migrations/*.py"):
        if path.name == "__init__.py":
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        if "RunPython" not in source:
            continue
        if not any(marker in source for marker in _ROW_CREATING):
            continue
        found.add(path.parts[path.parts.index("migrations") - 1])
    return found


class CompletenessTest(SimpleTestCase):
    """The gate. Everything else here is only worth having because of this."""

    def test_every_app_that_seeds_rows_is_accounted_for(self):
        seeding = _apps_seeding_in_migrations()
        registered = set(reference_data.registered_apps())
        unaccounted = sorted(seeding - registered - set(ONE_OFF_DATA_MIGRATIONS))
        self.assertEqual(
            unaccounted,
            [],
            "These apps create rows in a migration and have neither registered "
            "an ensure function nor been listed as a one-off:\n  "
            + "\n  ".join(unaccounted)
            + "\n\nRows a migration created do not come back when a "
            "TransactionTestCase truncates the database. If the platform needs "
            "them, add an idempotent ensure_*() and register it in "
            "AppConfig.ready(); see apps/core/reference_data.py. If it is a "
            "one-off backfill, add it to ONE_OFF_DATA_MIGRATIONS with a reason.",
        )

    def test_the_scan_finds_something(self):
        """A gate over an empty set passes and guards nothing."""
        self.assertGreaterEqual(len(_apps_seeding_in_migrations()), 5)

    def test_nothing_is_both_registered_and_exempt(self):
        """The two lists mean opposite things; an app in both is a mistake
        whichever way it was meant."""
        both = sorted(
            set(reference_data.registered_apps()) & set(ONE_OFF_DATA_MIGRATIONS)
        )
        self.assertEqual(both, [])

    def test_every_exemption_carries_a_reason(self):
        for app, reason in ONE_OFF_DATA_MIGRATIONS.items():
            with self.subTest(app=app):
                self.assertGreater(len(reason), 30, f"{app}'s exemption says nothing")

    def test_every_exempt_app_still_exists(self):
        """A stale exemption silently narrows the gate."""
        installed = {config.label for config in django_apps.get_app_configs()}
        stale = sorted(set(ONE_OFF_DATA_MIGRATIONS) - installed)
        self.assertEqual(stale, [], f"exemptions for apps that are gone: {stale}")


class TheGateCanActuallyFailTest(SimpleTestCase):
    """The completeness gate is the whole feature, so it needs proving that it
    can go red. A gate that cannot fail is a comment."""

    def test_an_unregistered_seeding_app_would_be_caught(self):
        seeding = _apps_seeding_in_migrations() | {"a_new_app_someone_just_wrote"}
        registered = set(reference_data.registered_apps())
        unaccounted = sorted(seeding - registered - set(ONE_OFF_DATA_MIGRATIONS))
        self.assertEqual(unaccounted, ["a_new_app_someone_just_wrote"])

    def test_the_scan_recognises_how_the_migrations_are_actually_written(self):
        """The markers are substrings, so a migration that created rows some
        other way — a raw INSERT, or a model alias — would slip past and the
        gate would pass vacuously. This pins the scan against the apps known
        to seed, so a change in style shows up here rather than as a silent
        hole."""
        found = _apps_seeding_in_migrations()
        for app in ("targets", "budget", "help_center", "clusters"):
            with self.subTest(app=app):
                self.assertIn(app, found)


class RegistrationTest(SimpleTestCase):
    def test_the_apps_that_had_their_own_wiring_are_all_registered(self):
        """These four each fixed themselves after being bitten, two of them in
        `AppConfig.ready()` and one in a `signals.py`. They now go through one
        registry, and this is what stops one quietly dropping out."""
        for app in ("geography", "budget", "targets", "help_center"):
            with self.subTest(app=app):
                self.assertIn(app, reference_data.registered_apps())

    def test_no_app_wires_post_migrate_for_reference_data_itself(self):
        """One convention, not two. A second receiver would work — and would
        be invisible to every check in this file."""
        # Matched as code, not as prose — several of these files explain the
        # post_migrate arrangement in a docstring, and a substring search
        # cannot tell an explanation from a second receiver.
        offenders = []
        for path in list(APPS.glob("*/apps.py")) + list(APPS.glob("*/signals.py")):
            if path.parts[-2] == "core":
                continue
            source = path.read_text(errors="ignore")
            if "post_migrate.connect(" in source or "receiver(post_migrate" in source:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            "These wire post_migrate directly instead of registering with "
            f"apps.core.reference_data: {offenders}",
        )


class IdempotencyTest(TestCase):
    """Run on every migrate and every flush, so running twice must be free."""

    def _counts(self) -> dict[str, int]:
        return {
            f"{model._meta.app_label}.{model.__name__}": model.objects.count()
            for model in django_apps.get_models()
            if model._meta.app_label in reference_data.registered_apps()
        }

    def test_a_second_run_creates_nothing(self):
        reference_data.restore_all()
        before = self._counts()
        reference_data.restore_all()
        after = self._counts()

        grew = {
            table: (before[table], after[table])
            for table in before
            if after[table] > before[table]
        }
        self.assertEqual(
            grew,
            {},
            "An ensure function created rows on a second run. Reference data "
            f"resolved by key cannot be duplicated: {grew}",
        )

    def test_every_registered_function_reports_success(self):
        outcome = reference_data.restore_all()
        failed = sorted(app for app, ok in outcome.items() if not ok)
        self.assertEqual(failed, [])


class RestorationTest(TransactionTestCase):
    """The one test in this codebase whose job is to flush.

    It is deliberately here rather than spread around: this is the behaviour
    every other test is affected by, so it should be asserted in the place
    somebody looks when it breaks.
    """

    def test_reference_rows_survive_a_truncation(self):
        """`TransactionTestCase` truncates on teardown, and post_migrate puts
        the rows back. Asserted by counting rows rather than by trusting an
        ensure function's return value — a function that under-reports would
        otherwise look exactly like one with nothing to do."""
        from apps.targets.models import TargetArea

        # Whatever the flush did, the rows the platform needs are present.
        reference_data.restore_all()
        self.assertGreater(
            TargetArea.objects.count(),
            0,
            "the official target areas are missing — every personal target and "
            "the weighted Overall Progress resolve through TargetArea.key, and "
            "an empty table produces no targets rather than an error",
        )

    def test_restoration_covers_every_registered_app(self):
        outcome = reference_data.restore_all()
        self.assertEqual(sorted(outcome), sorted(reference_data.registered_apps()))
        self.assertTrue(all(outcome.values()))


class NoSerializedRollbackTest(SimpleTestCase):
    def test_nothing_asks_django_to_restore_serialized_data(self):
        """`serialized_rollback = True` is the documented Django remedy for
        exactly this problem, and it does not work here: it re-inserts the
        serialized content types that the post_migrate restore has already
        recreated, and the unique constraint refuses. It was tried during the
        2026-07-26 audit and turned two failures into six errors."""
        # Parsed rather than grepped: this file and two others discuss
        # serialized_rollback at length in prose, and only a real assignment
        # counts.
        offenders = []
        for path in APPS.rglob("test*.py"):
            try:
                tree = ast.parse(path.read_text(errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "serialized_rollback" not in names:
                    continue
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "serialized_rollback collides with the post_migrate reference-data "
            f"restore — both re-insert content types: {offenders}",
        )


class DocumentedTest(SimpleTestCase):
    def test_the_module_says_what_does_not_belong(self):
        """The registry is only useful if the next person can tell reference
        data from a backfill without asking."""
        source = (ROOT / "apps/core/reference_data.py").read_text()
        self.assertIn("WHAT DOES NOT BELONG HERE", source)

    def test_the_ast_scan_is_a_real_parse_not_a_guess(self):
        """Guards the guard: if the marker strings stopped matching how the
        migrations are written, the completeness gate would pass vacuously."""
        sample = APPS / "targets/migrations"
        creating = [
            path
            for path in sample.glob("*.py")
            if "RunPython" in path.read_text(errors="ignore")
        ]
        self.assertTrue(creating, "no RunPython migration in targets to check")
        for path in creating:
            ast.parse(path.read_text())
