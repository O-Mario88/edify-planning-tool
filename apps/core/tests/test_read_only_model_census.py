"""Every model that is read somewhere and written nowhere, named on purpose.

GOV-01 was one instance of a defect this platform keeps producing: a designed
capability that has readers and no writers. The register exists, the page that
reads it exists, the metric that counts it exists — and no code path can ever
put a row in it. Earlier passes of this audit found the same shape in
`CorePlan.assessment_completed` (D5), in document `expiry_date`, and in the two
business-transformation assessment registers (GOV-01). FIN-05 found it again
on the Accountant's Returned queue, where the empty state read "All corrections
resolved" beneath a live returned balance.

GOV-01's own two registers were on this list when it was written and are no
longer: `record_compliance_assessment` and
`record_financial_practice_assessment` now exist, so the census removed them
itself — its second test fails on a stale entry, which is what forced the
list to be corrected rather than left flattering.

Three of the entries below were already known and already handled before this
census existed, each in a different way and each with a comment explaining it:
`MonthlyFundRequest` (apps/frontend/views/budget_views.py — the reader was
rewritten onto the live FundRequest), `ReimbursementClaim`
(apps/core/navigation.py — de-linked so it is not a permanent-empty-state
trap), and `EmployeeComplianceRecord` / `PayrollReadinessRecord`
(apps/accounts/hr_dashboard_service.py — "a percentage over an empty table is
not 0%"). The scan rediscovered all of them from scratch, which is the best
evidence available that it detects the class rather than the instance.

WHAT THIS TEST IS FOR

Not to assert that nothing is unwritten — several entries below are correct,
deliberate, and should stay. It is to stop the list changing silently. A new
read-only model has to be added here with a reason, and a model that gains a
writer has to be removed. Either way somebody looks.

WHAT COUNTS AS A WRITE

Django creates rows more ways than a `.create(` grep sees, and an earlier
version of this scan was wrong in the dangerous direction — it reported
`LoanRepaymentInstallment` as unwritten when `lending_ledger.py` builds one
with a bare constructor. All three Python spellings are detected: the bare
constructor, the manager call, and the related-manager call.

Three further paths are not Python spellings at all, and each one cleared a
suspect that the first pass had wrongly listed:

  * a ModelSerializer or ModelForm — `.save()` writes `Meta.model`
  * the admin site — a registered ModelAdmin creates rows through the UI

Those are checked too, and checked at second order: a form class must actually
be referenced by something outside its own module before it counts. That
distinction is not academic. `AnalyticsReportScheduleForm` exists, is a proper
ModelForm over `AnalyticsReportSchedule`, and has no caller anywhere — so the
model stays unwritten, and the scheduled delivery job that reads it runs
forever over an empty table. A form nobody instantiates writes exactly as much
as no form at all.

`.save()` on a variable is deliberately NOT treated as a write. It updates a
row that must already exist, so it cannot be what first creates one — which is
the claim this census makes. That is why `AdvanceRequest` shows a single
writing file (advance_service.py, where it is created) despite being saved all
over the codebase, and checking that surprise by hand is what established the
rule.
"""

from __future__ import annotations

import ast
import collections
import pathlib

from django.conf import settings
from django.test import SimpleTestCase

ROOT = pathlib.Path(settings.BASE_DIR)
SKIP_PARTS = {"migrations", "__pycache__", ".venv", "node_modules", "staticfiles"}
PERSIST = {"create", "get_or_create", "update_or_create", "bulk_create", "save"}
NON_MODEL_BASES = {
    "TextChoices",
    "IntegerChoices",
    "Choices",
    "Enum",
    "StrEnum",
    "Exception",
    "object",
    "Protocol",
    "NamedTuple",
    "TypedDict",
}

#: model name -> why it has no writer. Every entry has been read by hand; the
#: reason says what a reader of the affected surface actually sees.
KNOWN_READ_ONLY = {
    # ── Already found, already handled. Kept so the handling is not undone. ──
    "MonthlyFundRequest": (
        "Legacy monthly plan. budget_views.py reads the live FundRequest "
        "instead and says why in a comment; this row would show Draft forever."
    ),
    "ReimbursementClaim": (
        "Retired. claim_reimbursement() has no production caller; the live "
        "path is AdvanceRequest, and navigation.py de-links the dead queue."
    ),
    "EmployeeComplianceRecord": (
        "HR compliance register with no entry surface. The dashboard renders "
        "an em dash rather than 0%, so the empty table is not read as failure."
    ),
    "PayrollReadinessRecord": (
        "Payroll readiness register with no entry surface. Descoped from "
        "navigation like the two above, and the HR dashboard KPI renders an "
        "em dash rather than 0% so an empty table is not read as failure."
    ),
    "FinanceReturn": (
        "Legacy. FIN-05 — /accounts/returned/ now reads the advance ledger, "
        "which is where returned-for-correction money has always lived."
    ),
    # ── Correct by design: absence is the safe state, and it is surfaced. ──
    "ExtraWorkScoringPolicy": (
        "Fail-closed by design (§18.8): without an APPROVED policy extra work "
        "stays tracked-but-unscored, and the page says so. No approval "
        "surface exists, so the safe state is the permanent one."
    ),
    "SchoolGeoPoint": (
        "Top of a documented coordinate fallback chain — override, then the "
        "school's own lat/lng, then sub-county, then district centroid. "
        "location.py invents nothing when all four are absent."
    ),
    "StaffTargetProfile": (
        "Legacy annual target store. Targets are set through the performance "
        "agreement, which writes MonthlyPersonalTarget; this is the fallback "
        "that never fires. Absent targets render as 'No Target Set'."
    ),
    "RolePriorityTemplate": (
        "Superseded by the priority cascade. build_annual_review passes "
        "include_role_templates=False on the production path and falls back "
        "to DEFAULT_TEMPLATES in code when it does not."
    ),
    # ── GOV-02: workspaces a user can open that can never hold data. ──
    "CompensationRecord": (
        "Descoped, and said so first. navigation.py carries the page commented "
        "out with 'DESCOPED until a production writer exists' — the sidebar "
        "does not advertise it, the direct URL keeps an honest empty state."
    ),
    "SuccessionCandidate": (
        "Descoped the same way, with the same comment. Succession Planning is "
        "not offered in navigation; its URL still answers, empty and honest."
    ),
    "MaintenanceTemplate": (
        "GOV-02, and the only one of its group still advertised: the "
        "Maintenance Calendar is linked in navigation and is a drilldown "
        "target. 'No maintenance templates are configured yet' reads as "
        "pending rather than absent, and admin_ops_stale_maintenance reports "
        "Maintenance Generation ok permanently over the empty table."
    ),
    "AnalyticsReportSchedule": (
        "Retired, second order. AnalyticsReportScheduleForm is a real "
        "ModelForm with no caller; the drawer a user actually sees sends an "
        "immediate snapshot and says 'No scheduler worker or email provider "
        "is involved'. deliver_due_schedules stays a registered scheduler job "
        "running over an empty table."
    ),
    "Village": (
        "Unreached admin5 leaf. Nothing writes one, the seed stops at Parish, "
        "and no template or script calls /geography/villages."
    ),
    "HRAuditEvent": (
        "Retired second audit table with no hash chain; hr_views.py reads the "
        "canonical audit log and says why."
    ),
}


def _source_files():
    for path in (ROOT / "apps").rglob("*.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def _is_models_file(path: pathlib.Path) -> bool:
    return path.name == "models.py" or "models" in path.name


def _parse(path: pathlib.Path):
    try:
        text = path.read_text(encoding="utf-8")
        return text, ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None, None


def _collect_models():
    """Concrete Django models, and the related_names pointing at them."""
    models: dict[str, str] = {}
    related: dict[str, set[str]] = collections.defaultdict(set)
    for path in _source_files():
        if not _is_models_file(path):
            continue
        _, tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {ast.unparse(b).split(".")[-1] for b in node.bases}
            if not bases or bases & NON_MODEL_BASES:
                continue
            if _declares_abstract(node):
                continue
            models[node.name] = str(path.relative_to(ROOT))
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                for kw in sub.keywords or []:
                    if kw.arg == "related_name" and isinstance(kw.value, ast.Constant):
                        related[node.name].add(kw.value.value)
    return models, related


def _declares_abstract(node: ast.ClassDef) -> bool:
    for sub in node.body:
        if not (isinstance(sub, ast.ClassDef) and sub.name == "Meta"):
            continue
        for stmt in ast.walk(sub):
            if (
                isinstance(stmt, ast.Assign)
                and any(getattr(t, "id", "") == "abstract" for t in stmt.targets)
                and getattr(stmt.value, "value", False) is True
            ):
                return True
    return False


def _meta_model_classes():
    """`class Foo(...): class Meta: model = X` -> the models actually saved.

    Two conditions, and each one was learned by getting it wrong.

    The class must be referenced from outside its own module — see the module
    docstring on AnalyticsReportScheduleForm, a real ModelForm with no caller.
    Test files and this file do not count as callers: the first version of
    this scan exempted AnalyticsReportSchedule because the docstring above
    names the form class, which is the "everything looks fine" failure mode
    arriving by the back door.

    And the referencing file must call `.save()` somewhere. A serializer used
    only to render a response writes nothing — `VillageSerializer(qs,
    many=True).data` is the whole of geography/views.py's use of it, and
    Village has no writer at all.
    """
    declared: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    texts: dict[str, str] = {}
    for path in _source_files():
        text, tree = _parse(path)
        if tree is None:
            continue
        if path.name.startswith("test_") or path.name == "tests.py":
            continue
        texts[str(path)] = text
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for sub in node.body:
                if not (isinstance(sub, ast.ClassDef) and sub.name == "Meta"):
                    continue
                for stmt in sub.body:
                    if isinstance(stmt, ast.Assign) and any(
                        getattr(t, "id", "") == "model" for t in stmt.targets
                    ):
                        model = ast.unparse(stmt.value).split(".")[-1]
                        declared[model].add((node.name, str(path)))

    used: set[str] = set()
    for model, holders in declared.items():
        for class_name, owner in holders:
            for path, text in texts.items():
                if path != owner and class_name in text and ".save(" in text:
                    used.add(model)
                    break
    return used


def _admin_registered():
    registered: set[str] = set()
    for path in _source_files():
        _, tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for dec in node.decorator_list:
                    text = ast.unparse(dec)
                    if "register(" in text:
                        registered.add(text.split("register(")[1].split(")")[0].strip())
            if isinstance(node, ast.Call):
                text = ast.unparse(node)
                if "site.register" in text or text.startswith("admin.register"):
                    inner = text.split("register(")[1].split(")")[0]
                    registered.update(part.strip() for part in inner.split(","))
    return {name.split(".")[-1] for name in registered if name}


def _writers_and_readers(models, related):
    writers: dict[str, set[str]] = collections.defaultdict(set)
    readers: dict[str, set[str]] = collections.defaultdict(set)
    for path in _source_files():
        if path.name.startswith("test_") or path.name == "tests.py":
            continue
        text, tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(ROOT))
        own_models = _is_models_file(path)
        for model in models:
            if model in text and not own_models:
                readers[model].add(rel)
        if own_models:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # 1. bare constructor: Model(...)
            if isinstance(node.func, ast.Name):
                if node.func.id in models:
                    writers[node.func.id].add(rel)
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in PERSIST:
                continue
            source = ast.unparse(node.func)
            for model in models:
                # 2. manager call: Model.objects.create(...)
                if model in source:
                    writers[model].add(rel)
                # 3. related-manager call: parent.things.create(...)
                elif any(name in source for name in related.get(model, ())):
                    writers[model].add(rel)
    return writers, readers


_CACHE: dict = {}


def _analysis():
    """One AST pass over apps/, shared by every test in this module."""
    if not _CACHE:
        models, related = _collect_models()
        writers, readers = _writers_and_readers(models, related)
        _CACHE.update(
            models=models,
            related=related,
            writers=writers,
            readers=readers,
            exempt=_meta_model_classes() | _admin_registered(),
        )
    return _CACHE


def _scan() -> dict[str, str]:
    """model -> defining file, for every model read somewhere, written nowhere."""
    analysis = _analysis()
    models = analysis["models"]
    writers, readers = analysis["writers"], analysis["readers"]
    exempt = analysis["exempt"]
    return {
        name: models[name]
        for name in sorted(models)
        if readers[name] and not writers[name] and name not in exempt
    }


class ReadOnlyModelCensusTest(SimpleTestCase):
    """The list of unwritten models is pinned, so it cannot change in silence."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.found = _scan()

    def test_no_model_became_read_only_without_being_recorded(self):
        new = sorted(set(self.found) - set(KNOWN_READ_ONLY))
        self.assertEqual(
            new,
            [],
            "these models are read somewhere and written nowhere, and are not "
            "in KNOWN_READ_ONLY: "
            + ", ".join(f"{name} ({self.found[name]})" for name in new)
            + ". A register with readers and no writers is the GOV-01 defect. "
            "Give it a writer, or add it here with what a reader of the "
            "affected surface actually sees.",
        )

    def test_a_model_that_gained_a_writer_is_removed_from_the_list(self):
        stale = sorted(set(KNOWN_READ_ONLY) - set(self.found))
        self.assertEqual(
            stale,
            [],
            "these are listed as read-only but the scan now finds a writer: "
            + ", ".join(stale)
            + ". If the capability was built, delete the entry; if the scan "
            "changed, check it is not the write form that moved.",
        )

    def test_every_entry_says_what_a_reader_of_the_surface_sees(self):
        for name, reason in KNOWN_READ_ONLY.items():
            with self.subTest(name):
                self.assertGreater(
                    len(reason),
                    60,
                    f"{name} needs a reason, not a label — the point of this "
                    "list is that somebody looked at the surface",
                )


class TheScanItselfWorksTest(SimpleTestCase):
    """A guard whose failure mode is 'everything looks fine' is worthless.

    The first version of this scan saw only the manager call, so it reported
    `LoanRepaymentInstallment` — built with a bare constructor in
    lending_ledger.py — as having no writer at all. These hold each write form
    against a model that really uses it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        analysis = _analysis()
        cls.models, cls.related = analysis["models"], analysis["related"]
        cls.writers, cls.readers = analysis["writers"], analysis["readers"]

    def test_it_found_the_models_at_all(self):
        self.assertGreater(len(self.models), 200)
        self.assertIn("Activity", self.models)

    def test_it_sees_a_bare_constructor(self):
        """LoanRepaymentInstallment(...) — no .objects, no related manager."""
        self.assertTrue(
            self.writers.get("LoanRepaymentInstallment"),
            "the bare-constructor write form is invisible to this scan again",
        )

    def test_it_sees_a_manager_call(self):
        """AdvanceRequest.objects.create — and only one file does it.

        Kept as an exact assertion because the surprise is the point: the
        advance ledger is saved all over the codebase and created in exactly
        one place. A `.save()` on a variable updates a row that already
        exists, so it is not what this census measures.
        """
        self.assertEqual(
            sorted(self.writers.get("AdvanceRequest", ())),
            ["apps/fund_requests/advance_service.py"],
        )

    def test_it_sees_a_related_manager_call(self):
        self.assertTrue(self.writers.get("EvidenceRecord"))

    def test_a_heavily_written_model_is_not_reported_as_read_only(self):
        for name in ("Activity", "School", "User"):
            with self.subTest(name):
                self.assertNotIn(name, _scan())
