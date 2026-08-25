"""Hold the journey manifest to reality, so its coverage count cannot drift.

The release assessment's "1 of 22" was a sentence. A sentence cannot notice
when a test it names is renamed, deleted, or never existed, and it cannot stop
someone claiming a journey is walked when only its steps are tested
separately. These tests can.

`COVERED_COUNT` below is deliberately a hard-coded number rather than a
derived one. Deriving it would make this suite agree with the manifest no
matter what the manifest said; pinning it means adding or losing journey
coverage forces a deliberate edit here, and the assessment that quotes the
number gets updated in the same commit or the suite goes red.
"""

from __future__ import annotations

import importlib

from django.test import SimpleTestCase

from apps.core.tests.release_journeys import (
    JOURNEYS,
    blocked_journeys,
    covered_journeys,
    uncovered_journeys,
)

#: Journeys walked end to end by a single test. Raise this ONLY when a new
#: journey test genuinely walks the whole journey, and update
#: docs/release-readiness-2026-08-25.md in the same commit.
COVERED_COUNT = 2

#: Journeys that cannot be covered because the capability was never built.
BLOCKED_COUNT = 2


class ManifestMatchesTheMandateTest(SimpleTestCase):
    def test_all_twenty_two_journeys_are_listed(self):
        self.assertEqual(len(JOURNEYS), 22)
        self.assertEqual(
            [j.number for j in JOURNEYS],
            list(range(1, 23)),
            "journeys must be numbered 1..22 exactly as the mandate numbers them",
        )

    def test_every_journey_names_its_steps(self):
        for journey in JOURNEYS:
            with self.subTest(journey=journey.number):
                self.assertTrue(journey.title.strip(), "journey needs a title")
                self.assertGreaterEqual(
                    len(journey.steps),
                    2,
                    "a journey with fewer than two steps is not a journey",
                )
                for step in journey.steps:
                    self.assertTrue(step.strip(), "empty step")


class CoveragePointersResolveTest(SimpleTestCase):
    """A pointer at a test that does not exist is worse than no pointer."""

    def test_every_covered_by_target_exists(self):
        for journey in JOURNEYS:
            for target in journey.covered_by:
                with self.subTest(journey=journey.number, target=target):
                    self.assertIn(
                        ":",
                        target,
                        "expected 'module.path:ClassName.test_method'",
                    )
                    module_path, qualname = target.split(":", 1)
                    class_name, _, method_name = qualname.partition(".")
                    self.assertTrue(
                        method_name.startswith("test_"),
                        f"{target} does not name a test method",
                    )
                    try:
                        module = importlib.import_module(module_path)
                    except ImportError as exc:  # pragma: no cover - failure path
                        self.fail(
                            f"journey {journey.number} names {module_path}: {exc}"
                        )
                    test_class = getattr(module, class_name, None)
                    self.assertIsNotNone(
                        test_class,
                        f"journey {journey.number} names {class_name}, which "
                        f"{module_path} does not define",
                    )
                    self.assertTrue(
                        callable(getattr(test_class, method_name, None)),
                        f"journey {journey.number} names {method_name}, which "
                        f"{class_name} does not define",
                    )


class CoverageCountIsPinnedTest(SimpleTestCase):
    def test_the_covered_count_is_what_this_suite_declares(self):
        covered = covered_journeys()
        self.assertEqual(
            len(covered),
            COVERED_COUNT,
            "journey coverage changed. If a journey test was added, raise "
            "COVERED_COUNT and update the count in "
            "docs/release-readiness-2026-08-25.md in the same commit. If "
            "coverage was lost, that is the regression.\n"
            f"covered now: {[j.number for j in covered]}",
        )

    def test_the_blocked_count_is_what_this_suite_declares(self):
        blocked = blocked_journeys()
        self.assertEqual(
            len(blocked),
            BLOCKED_COUNT,
            "the set of journeys blocked on unbuilt capability changed.\n"
            f"blocked now: {[j.number for j in blocked]}",
        )

    def test_every_blocked_journey_says_what_blocks_it(self):
        for journey in blocked_journeys():
            with self.subTest(journey=journey.number):
                self.assertGreater(
                    len(journey.blocked_by),
                    40,
                    "a blocked journey needs a reason someone can act on, not "
                    "a label",
                )

    def test_uncovered_journeys_claim_nothing(self):
        """An uncovered journey must not carry a half-pointer."""
        for journey in uncovered_journeys():
            with self.subTest(journey=journey.number):
                self.assertEqual(journey.covered_by, ())
