"""GOV-01 — the BT school-assessment registers have readers and no writers.

Two registers share this shape. `SchoolComplianceAssessment` (with its
`ComplianceRequirement` catalogue) records a school's government requirements —
registration, tax, NSSF. `FinancialPracticeAssessment` records whether a school
adopted the financial practices a Business Transformation visit recommended.
Both are fully designed. The catalogue carries the responsible authority, the school
types a requirement applies to, and `renewal_months`; each per-school
assessment carries a registration number and date, an **indexed**
`expiry_date`, an evidence reference and a follow-up action. Three Business
Transformation surfaces read them — the per-school compliance rows, the
portfolio metrics (`compliant`, `actionRequired`, `awaiting_verification`,
`nearest_expiry`) and the school detail drawer.

Nothing creates or updates either. Not a service, a view, the admin, a
management command, an importer or a template — and not through a related
manager or a bare constructor either, both of which this test checks because a
naive scan misses them. So every school's government-requirements compliance
and financial-practice adoption render empty and zero for ever, no certificate
can be recorded as expiring, and the practice-adoption step of Journey 15 has
nothing to record.

That is the same shape as two defects this platform has already had: D5, where
`CorePlan.assessment_completed` was unreachable by any route, and the
documents app's `expiry_date`, which "drove the nightly expiry job and the
health check, and no form ever posted it — so nothing could ever expire".

CLOSED. This test carried `expectedFailure` rather than `skipTest` for one
reason: a skipped test does not run and reports nothing, while an expected
failure runs, records its failure, and — the moment somebody builds the write
path — reports an UNEXPECTED SUCCESS, which fails the build and forces the
marker off. That is exactly what happened. The registers now have
`record_compliance_assessment` / `verify_compliance_assessment` and
`record_financial_practice_assessment` / `verify_financial_practice_assessment`
in apps/business_transformation/services.py, and the marker is gone.

The test stays, without the marker, as a standing guard: it fails again if a
future refactor leaves either register with readers and no writers.
"""

from __future__ import annotations

import ast
import pathlib

from django.test import SimpleTestCase

APP = pathlib.Path(__file__).resolve().parent
REPO = APP.parent.parent
MODELS = ("SchoolComplianceAssessment", "FinancialPracticeAssessment")

#: The reverse accessors a write could hide behind. A related-manager create
#: (`case.compliance_assessments.create(...)`) never mentions the model name,
#: so scanning for the class alone reports a false positive.
RELATED_NAMES = (
    "compliance_assessments",
    "school_assessments",
    "financial_practice_assessments",
)

#: Where a write would legitimately live. The model file itself is excluded —
#: defining the model is not writing to it.
SEARCH_ROOTS = (REPO / "apps",)
SKIP_PARTS = {"migrations", "__pycache__", ".venv", "node_modules"}


PERSISTING = {"create", "get_or_create", "update_or_create", "bulk_create", "save"}


def _writes_to_model(path: pathlib.Path, model: str) -> bool:
    """True if this module persists `model` by any of the three routes.

    A scan that only looks for `Model.objects.create(...)` misses two real
    ones, and missing them would turn this guard into a false alarm:

    1. a related-manager write — `case.compliance_assessments.create(...)`,
       which never mentions the class at all;
    2. a bare constructor — `Model(...)` handed to `bulk_create`, which is a
       Call on a Name rather than an attribute access. That is how
       LoanRepaymentInstallment is genuinely written, and an earlier version
       of this scan reported it as unwritten.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our code
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # (2) bare constructor
        if isinstance(node.func, ast.Name) and node.func.id == model:
            return True
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in PERSISTING:
            continue
        source = ast.unparse(node.func)
        # (1) related manager, or the ordinary manager path
        if model in source or any(rel in source for rel in RELATED_NAMES):
            return True
    return False


class ComplianceRegisterHasAWritePathTest(SimpleTestCase):
    """A designed capability that nothing can populate is not a capability."""

    def _writers(self, model: str) -> list[str]:
        found = []
        for root in SEARCH_ROOTS:
            for path in root.rglob("*.py"):
                if SKIP_PARTS & set(path.parts):
                    continue
                if path.name.startswith("test_") or path.name == "tests.py":
                    continue
                if path.name == "models.py":
                    continue
                if _writes_to_model(path, model):
                    found.append(str(path.relative_to(REPO)))
        return sorted(found)

    def test_the_bt_school_assessment_registers_can_be_written(self):
        unwritten = [m for m in MODELS if not self._writers(m)]
        self.assertEqual(
            unwritten,
            [],
            "GOV-01 is still open: nothing in apps/ creates or updates "
            f"{', '.join(unwritten)} — by manager, related manager or bare "
            "constructor. The models, their catalogues and three reading "
            "surfaces all exist, so government-requirements compliance and "
            "financial-practice adoption render empty and zero permanently, "
            "and no expiry can be recorded or reminded on. This test turns "
            "green by itself once a write path is built.",
        )

    def test_the_scan_can_still_see_a_model_that_IS_written(self):
        """Guard against the guard going blind.

        If `_writes_to_model` stopped detecting writes, the assertion above
        would pass its expected failure for entirely the wrong reason.
        `LoanRepaymentInstallment` is written by a bare constructor fed to
        bulk_create — the exact form an earlier version of this scan missed —
        so it is the right control.
        """
        self.assertTrue(
            self._writers("LoanRepaymentInstallment"),
            "the write scan can no longer see a model that IS written, so "
            "its report of an unwritten one proves nothing",
        )

    def test_the_readers_this_would_feed_still_exist(self):
        """Guard the guard.

        If the reading surfaces were deleted, the test above would become
        meaningless — a register nobody reads needs no writer. This keeps the
        finding honest by failing loudly if the premise changes.
        """
        services = (APP / "services.py").read_text(encoding="utf-8")
        for model in MODELS:
            self.assertIn(
                model,
                services,
                f"{model} is no longer read anywhere in "
                "business_transformation services. If the capability was "
                "withdrawn deliberately, delete this test and its siblings "
                "with it; if not, the reading surfaces have been lost.",
            )
        self.assertIn(
            "nearest_expiry",
            services,
            "the portfolio metric that would surface an expiring government "
            "requirement is gone, so GOV-01's impact statement is stale",
        )
