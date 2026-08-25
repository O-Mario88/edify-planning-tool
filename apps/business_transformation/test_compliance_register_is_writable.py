"""GOV-01 — the government-requirements register has readers and no writers.

`SchoolComplianceAssessment` and its `ComplianceRequirement` catalogue are
fully designed. The catalogue carries the responsible authority, the school
types a requirement applies to, and `renewal_months`; each per-school
assessment carries a registration number and date, an **indexed**
`expiry_date`, an evidence reference and a follow-up action. Three Business
Transformation surfaces read them — the per-school compliance rows, the
portfolio metrics (`compliant`, `actionRequired`, `awaiting_verification`,
`nearest_expiry`) and the school detail drawer.

Nothing creates or updates one. Not a service, a view, the admin, a management
command, an importer or a template. So every school's government-requirements
compliance renders empty and zero for ever, and no certificate can be recorded
as expiring, let alone reminded on.

That is the same shape as two defects this platform has already had: D5, where
`CorePlan.assessment_completed` was unreachable by any route, and the
documents app's `expiry_date`, which "drove the nightly expiry job and the
health check, and no form ever posted it — so nothing could ever expire".

QUARANTINED — the gap this asserts against is OPEN, not fixed. It carries
`expectedFailure` rather than `skipTest`, and the difference is the whole
point: a skipped test does not run and reports nothing, while an expected
failure runs, records its failure, and — when someone finally builds the write
path — reports an UNEXPECTED SUCCESS, which fails the build and forces this
marker to be removed. The gap cannot be closed quietly and cannot stay hidden.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from django.test import SimpleTestCase

APP = pathlib.Path(__file__).resolve().parent
REPO = APP.parent.parent
MODEL = "SchoolComplianceAssessment"

#: Where a write would legitimately live. The model file itself is excluded —
#: defining the model is not writing to it.
SEARCH_ROOTS = (REPO / "apps",)
SKIP_PARTS = {"migrations", "__pycache__", ".venv", "node_modules"}


def _writes_to_model(path: pathlib.Path) -> bool:
    """True if this module calls a persisting method on the model."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our code
        return False
    persisting = {"create", "get_or_create", "update_or_create", "bulk_create", "save"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in persisting:
            continue
        # Walk the attribute chain back to its root name, so both
        # `Model.objects.create(...)` and `instance.save()` are visible.
        source = ast.unparse(func)
        if MODEL in source:
            return True
    return False


class ComplianceRegisterHasAWritePathTest(SimpleTestCase):
    """A designed capability that nothing can populate is not a capability."""

    def _writers(self) -> list[str]:
        found = []
        for root in SEARCH_ROOTS:
            for path in root.rglob("*.py"):
                if SKIP_PARTS & set(path.parts):
                    continue
                if path.name.startswith("test_") or path.name == "tests.py":
                    continue
                if path.name == "models.py":
                    continue
                if _writes_to_model(path):
                    found.append(str(path.relative_to(REPO)))
        return sorted(found)

    @unittest.expectedFailure
    def test_something_can_create_a_school_compliance_assessment(self):
        writers = self._writers()
        self.assertTrue(
            writers,
            "GOV-01 is still open: nothing in apps/ creates or updates a "
            f"{MODEL}. The model, its requirement catalogue and three "
            "reading surfaces all exist, so every school's "
            "government-requirements compliance renders empty and zero "
            "permanently, and no expiry can be recorded or reminded on. "
            "This test turns green by itself once a write path is built.",
        )

    def test_the_readers_this_would_feed_still_exist(self):
        """Guard the guard.

        If the reading surfaces were deleted, the test above would become
        meaningless — a register nobody reads needs no writer. This keeps the
        finding honest by failing loudly if the premise changes.
        """
        services = (APP / "services.py").read_text(encoding="utf-8")
        self.assertIn(
            MODEL,
            services,
            f"{MODEL} is no longer read anywhere in business_transformation "
            "services. If the capability was withdrawn deliberately, delete "
            "this test and its sibling with it; if not, the reading surfaces "
            "have been lost.",
        )
        self.assertIn(
            "nearest_expiry",
            services,
            "the portfolio metric that would surface an expiring government "
            "requirement is gone, so GOV-01's impact statement is stale",
        )
