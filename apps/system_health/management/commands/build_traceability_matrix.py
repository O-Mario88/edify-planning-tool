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
"""

import argparse
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment

from apps.system_health.traceability import (
    build_traceability_matrix,
    matrix_as_json,
    matrix_as_markdown,
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

    def handle(self, *args, **options):
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
