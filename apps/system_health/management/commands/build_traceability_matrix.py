"""Regenerate the requirements traceability matrix (mandate §11, §45.2).

This command sets up a test database and runs each mandated journey's covering
test with the platform instrumented, so it takes several minutes. It is not a
CI step: CI checks the committed artefact against the manifest instead, via
``apps/system_health/test_traceability_matrix.py``.

**Why it re-executes itself.** ``config/settings/base.py`` decides
``IS_TESTING`` -- and with it fiscal-year rollover, platform-failure detection,
interaction telemetry and the blocking-IO guard -- from ``sys.argv`` at settings
import time. Launched as ``manage.py build_traceability_matrix``, the word
"test" is absent, so settings load the *production* configuration and the
post-migrate seeding takes a different branch: the journey tests then run
against a platform that is not the one the suite proves. That is not a
theoretical difference. It was found the direct way, by the policy-lifecycle
journey failing inside the tracer while passing in the suite, because seeding
had published two extra mandatory policies its audience then owed
acknowledgements for.

Since the flag is fixed before any of this module runs, the only honest fix is
to start again with the right argv. The command therefore re-execs itself once,
with ``test`` inserted, and the marker positional below exists to receive it.
Tracing under any other configuration would produce a matrix that describes
code paths nobody verified.

**Why it starts an interpreter for every test.** What a process has already
imported, compiled and remembered decided what the next test was seen to touch,
so the same code rebuilt into a different matrix (see "What a rebuild may not
depend on" in ``apps.system_health.traceability``). This process prepares the
test database once; each test is then traced by ``--one``, in an interpreter
started for it alone, which attaches to that database and writes what it saw
to the file named by ``--into``. ``--keepdb`` only saves the minutes the
migrations take: with or without it the matrix is the same. A kept database is
still the one seeded on the day it was made, though, so do not keep one across
the turn of a fiscal year -- the journeys would be walked today against last
year's cost catalogue.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment

from apps.system_health.traceability import (
    DID_NOT_PASS,
    TEST_DATABASE_ENV,
    TestPointerError,
    build_traceability_matrix,
    matrix_as_json,
    matrix_as_markdown,
    trace_test,
)

JSON_PATH = Path(settings.BASE_DIR) / "docs" / "platform-traceability-matrix.json"
MARKDOWN_PATH = Path(settings.BASE_DIR) / "docs" / "platform-traceability-matrix.md"

#: Set on the re-exec so a settings module that still refuses to report
#: IS_TESTING cannot put the command in a loop.
_REEXEC_ENV = "EDIFY_TRACEABILITY_REEXEC"


class Command(BaseCommand):
    help = (
        "Write docs/platform-traceability-matrix.{json,md} by executing each "
        "mandated journey's own test under instrumentation."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keepdb",
            action="store_true",
            help="Reuse the existing test database instead of recreating it.",
        )
        # Receives the "test" marker the re-exec inserts into argv so that
        # settings load in the same configuration the suite runs in.
        parser.add_argument("marker", nargs="*", help=argparse.SUPPRESS)
        # How this command asks an interpreter to trace one test: the pointer,
        # and the file to write what it touched to.
        parser.add_argument("--one", help=argparse.SUPPRESS)
        parser.add_argument("--into", help=argparse.SUPPRESS)

    def handle(self, *args, **options):
        if options["one"]:
            self._trace_one(options["one"], options["into"])
            return
        if not getattr(settings, "IS_TESTING", False):
            self._reexec_as_test_run(options)
            return

        setup_test_environment()
        runner = DiscoverRunner(
            verbosity=0, interactive=False, keepdb=options["keepdb"]
        )
        old_config = runner.setup_databases()
        try:
            matrix = build_traceability_matrix(
                progress=lambda line: self.stdout.write(f"  tracing {line}")
            )
        finally:
            runner.teardown_databases(old_config)
            teardown_test_environment()

        JSON_PATH.write_text(matrix_as_json(matrix), encoding="utf-8")
        MARKDOWN_PATH.write_text(matrix_as_markdown(matrix), encoding="utf-8")
        for key, value in matrix["summary"].items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {JSON_PATH.name} and {MARKDOWN_PATH.name}")
        )

    def _trace_one(self, pointer: str, into: str | None) -> None:
        """Trace one test in this interpreter, on the database already prepared."""
        database = os.environ.get(TEST_DATABASE_ENV)
        if not (database and into and getattr(settings, "IS_TESTING", False)):
            raise CommandError(
                "--one is how build_traceability_matrix runs each test in an "
                "interpreter of its own; it needs the test database that "
                "command prepared and is not meant to be run by hand."
            )
        into = Path(into)
        setup_test_environment()
        # Attach instead of setting up: the database is the caller's, migrated
        # and seeded once, and the test rolls back what it does to it.
        settings.DATABASES["default"]["NAME"] = database
        connections["default"].settings_dict["NAME"] = database
        try:
            recording = trace_test(pointer)
        except TestPointerError as error:
            into.write_text(json.dumps({"error": str(error)}), encoding="utf-8")
            raise SystemExit(DID_NOT_PASS) from error
        finally:
            teardown_test_environment()
        into.write_text(json.dumps(recording.as_dict()), encoding="utf-8")

    def _reexec_as_test_run(self, options) -> None:
        if os.environ.get(_REEXEC_ENV):
            raise SystemExit(
                "settings.IS_TESTING is still false after re-executing with "
                "'test' in argv. Refusing to trace under a configuration the "
                "suite does not use."
            )
        argv = [
            sys.executable,
            str(Path(settings.BASE_DIR) / "manage.py"),
            "build_traceability_matrix",
            "test",
        ]
        if options["keepdb"]:
            argv.append("--keepdb")
        self.stdout.write(
            "Re-executing so settings load with IS_TESTING true "
            "(see this command's docstring)."
        )
        os.execve(argv[0], argv, {**os.environ, _REEXEC_ENV: "1"})
