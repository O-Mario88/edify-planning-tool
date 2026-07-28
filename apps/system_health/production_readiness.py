"""Scanners for the deployment gates that require a hard zero.

The platform already inventories pages, KPIs and cards. What it has never
measured are the gates the deployment mandate states as "required count: 0" —
mock data in the production runtime, business analytics computed in JavaScript,
controls with no endpoint behind them, routes with no permission guard, and
workflow state written outside a canonical service.

Each scanner returns findings, not opinions: a file, a line and the text that
triggered it, so every number in a readiness report can be walked back to the
source. A scanner that cannot point at a line has not measured anything.

Deliberately static analysis. A runtime crawl proves what happened on the paths
it happened to walk; a source scan proves what is *in* the tree, which is the
question a deployment gate is asking.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings

APPS = Path(settings.BASE_DIR) / "apps"
TEMPLATES = Path(settings.BASE_DIR) / "templates"
STATIC_JS = Path(settings.BASE_DIR) / "static" / "js"


@dataclass(frozen=True)
class Finding:
    gate: str
    path: str
    line: int
    evidence: str
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _python_files():
    for path in APPS.rglob("*.py"):
        parts = set(path.parts)
        if "migrations" in parts or "__pycache__" in parts:
            continue
        # Test infrastructure may legitimately hold fixtures and fakes.
        if path.name.startswith("test_") or path.name in ("tests.py", "conftest.py"):
            continue
        if "tests" in parts:
            continue
        yield path


def _template_files():
    yield from TEMPLATES.rglob("*.html")


# ── Gate 1: mock or demo data in the production runtime (§7) ─────────────────

_MOCK_PATTERNS = (
    (re.compile(r"\bMOCK_[A-Z_]+\b"), "a module-level MOCK_ constant"),
    (re.compile(r"\bFAKE_[A-Z_]+\b"), "a module-level FAKE_ constant"),
    (re.compile(r"\bDUMMY_[A-Z_]+\b"), "a module-level DUMMY_ constant"),
    (re.compile(r"\bSAMPLE_DATA\b"), "a SAMPLE_DATA constant"),
    (re.compile(r"placeholder_(?:rows|data|metrics)"), "placeholder data"),
    (re.compile(r"lorem ipsum", re.I), "lorem ipsum copy"),
    (re.compile(r"#\s*TODO:?\s*(?:fake|mock|stub|hardcode)", re.I), "an admitted stub"),
)

#: Seed and demo tooling is legitimate — it is how a fresh environment is made
#: usable. What must not exist is a *runtime* path that serves invented data.
_SEED_MARKERS = ("seed", "demo", "fixtures", "factories", "management/commands")


def scan_mock_runtime_data() -> list[Finding]:
    findings: list[Finding] = []
    this_file = Path(__file__).name
    for path in _python_files():
        relative = str(path.relative_to(settings.BASE_DIR))
        if any(marker in relative for marker in _SEED_MARKERS):
            continue
        # This module *contains* the patterns, so it matches all of them. A
        # scanner counting itself reports two defects that do not exist.
        if path.name == this_file:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern, detail in _MOCK_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        Finding(
                            "mock_runtime_data",
                            relative,
                            number,
                            line.strip()[:160],
                            detail,
                        )
                    )
    return findings


# ── Gate 2: business analytics computed in JavaScript (§13, §40) ─────────────

#: Arithmetic on a business quantity, in a template's inline script or a JS
#: file. Visual maths -- chart coordinates, widths, percentages of a pixel box
#: -- is legitimate and is excluded by name below.
_JS_BUSINESS_MATH = re.compile(
    r"\b(total|sum|amount|budget|cost|ugx|achievement|variance|balance|"
    r"disbursed|outstanding)\w*\s*[+\-*/]?=\s*[^=]",
    re.I,
)
_JS_VISUAL_NAMES = re.compile(
    r"\b(x|y|cx|cy|width|height|left|right|top|bottom|step|offset|px|"
    r"coordinate|point|stroke|radius|scale|zoom|opacity)\b",
    re.I,
)
_JS_REDUCE = re.compile(r"\.reduce\s*\(")
#: An assignment whose right-hand side is a literal, or a plain read of a
#: server-supplied field with a fallback. No arithmetic is being performed.
_JS_ASSIGNMENT_ONLY = re.compile(
    r"=\s*(?:\d+(?:\.\d+)?|null|undefined|\[\]|\{\}|"
    r"[\w.]+\s*\|\|\s*[\d\[\{'\"]|[\w.$]+)\s*[;,)]?\s*$"
)


def scan_javascript_business_maths() -> list[Finding]:
    findings: list[Finding] = []
    sources = list(_template_files()) + list(STATIC_JS.glob("*.js"))
    for path in sources:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = str(path.relative_to(settings.BASE_DIR))
        in_script = path.suffix == ".js"
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if path.suffix == ".html":
                if "<script" in lowered:
                    in_script = True
                if "</script" in lowered:
                    in_script = False
                    continue
                if not in_script:
                    continue
            if _JS_VISUAL_NAMES.search(line):
                continue  # chart geometry, not business arithmetic
            if _JS_ASSIGNMENT_ONLY.search(line):
                # `x = 0` and `x = data.total || 0` read or initialise a value
                # the server already decided. The gate is about arithmetic the
                # client performs, not about a variable that holds a result.
                continue
            if _JS_BUSINESS_MATH.search(line) or (
                _JS_REDUCE.search(line) and re.search(r"total|amount|sum", lowered)
            ):
                findings.append(
                    Finding(
                        "javascript_business_maths",
                        relative,
                        number,
                        line.strip()[:160],
                        "a business quantity computed client-side",
                    )
                )
    return findings


# ── Gate 3: controls with nothing behind them (§11) ──────────────────────────

_DEAD_HREF = re.compile(r"""href\s*=\s*["'](#|javascript:void\(0\)?;?)["']""")
_HANDLER = re.compile(
    r"(hx-get|hx-post|hx-put|hx-delete|@click|x-on:click|onclick|type=[\"']submit)"
)


def scan_dead_controls() -> list[Finding]:
    """An anchor that names no destination and carries no handler.

    `href="#"` on an element that also has an Alpine or htmx handler is a
    normal idiom -- the handler is the behaviour and the href is a focus
    affordance. Only a control with neither is dead.
    """
    findings: list[Finding] = []
    for path in _template_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = str(path.relative_to(settings.BASE_DIR))
        for number, line in enumerate(text.splitlines(), start=1):
            if _DEAD_HREF.search(line) and not _HANDLER.search(line):
                findings.append(
                    Finding(
                        "dead_control",
                        relative,
                        number,
                        line.strip()[:160],
                        "an anchor with no destination and no handler",
                    )
                )
    return findings


# ── Gate 4: routed views with no permission guard (§9, §11) ─────────────────

_EXEMPT_VIEW_NAMES = {
    # Public by design.
    "login_view",
    "logout_view",
    "forgot_password_view",
    "reset_password_view",
    "set_password_view",
    "health_view",
    "readiness_view",
    "liveness_view",
    "csrf_failure",
    "handler404",
    "handler500",
    "manifest_view",
    "manifest",
    "service_worker_view",
    "service_worker",
    "offline_view",
    "splash_view",
    # Mid-authentication surfaces: the user is part-way through signing in, so
    # there is no active role yet to check a page permission against.
    "mfa_verify_view",
    "mfa_resend_view",
    "mfa_settings_view",
    "switch_role_view",
    "force_change_password_view",
    # Policy-agreement surfaces are exempt from the policy gate by design (a
    # person must be able to read and answer the policy blocking them) and
    # enforce their own ownership checks per acknowledgement.
    "agreement_center_view",
    "restricted_view",
    "submit_acknowledgement_view",
    "attest_offline_view",
    "engagement_heartbeat_view",
    # The document viewer resolves audience per request through
    # `_readable_or_404`, which is narrower than any page permission: it 404s
    # on an audience miss because the existence of a confidential policy is
    # itself information.
    "document_viewer_view",
    "document_preview_view",
    "document_download_view",
    "document_print_view",
}


def scan_unguarded_page_routes() -> list[Finding]:
    """Server-rendered pages reachable without a declared permission.

    Only page views are in scope: DRF endpoints declare their gate through
    `permission_classes`, which this scanner does not read, and reporting them
    would bury the pages in noise.
    """
    from django.urls import get_resolver

    findings: list[Finding] = []
    seen: set[str] = set()

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern, prefix + str(pattern.pattern))
                continue
            view = getattr(pattern, "callback", None)
            if view is None:
                continue
            name = getattr(view, "__name__", "")
            module = getattr(view, "__module__", "")
            if not module.startswith("apps."):
                continue
            if "frontend.views" not in module and "documents.views" not in module:
                continue  # page views only
            if name in _EXEMPT_VIEW_NAMES or name in seen:
                continue
            seen.add(name)
            if getattr(view, "has_permission_guard", False):
                continue
            if getattr(view, "page_permission", None):
                continue
            findings.append(
                Finding(
                    "unguarded_page_route",
                    module.replace(".", "/") + ".py",
                    0,
                    f"{prefix}{pattern.pattern}",
                    f"{name} has no require_page_permission",
                )
            )

    walk(get_resolver())
    return findings


# ── Gate 5: workflow state written outside a canonical service (§6, §37) ────

#: Fields whose value *is* a workflow position. Writing one from a view is how
#: a platform ends up with two definitions of "closed".
_WORKFLOW_FIELDS = {
    "status",
    "state",
    "workflow_status",
    "verification_status",
    "ia_verification_status",
    "payment_status",
    "evidence_status",
}


def scan_raw_workflow_mutations() -> list[Finding]:
    """Assignments to a workflow field inside a view module.

    Services own transitions; a view that sets `.status` directly has bypassed
    every guard, notification and audit row that transition was supposed to
    carry.
    """
    findings: list[Finding] = []
    for path in _python_files():
        relative = str(path.relative_to(settings.BASE_DIR))
        if "/views" not in relative and not relative.endswith("views.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in _WORKFLOW_FIELDS
                    and isinstance(target.value, ast.Name)
                    and target.value.id not in ("self", "cls")
                ):
                    findings.append(
                        Finding(
                            "raw_workflow_mutation",
                            relative,
                            node.lineno,
                            f"{target.value.id}.{target.attr} = …",
                            "workflow state set outside a canonical service",
                        )
                    )
    return findings


# ── Report ───────────────────────────────────────────────────────────────────

GATES = {
    "mock_runtime_data": scan_mock_runtime_data,
    "javascript_business_maths": scan_javascript_business_maths,
    "dead_control": scan_dead_controls,
    "unguarded_page_route": scan_unguarded_page_routes,
    "raw_workflow_mutation": scan_raw_workflow_mutations,
}


def run_all() -> dict:
    """Every hard-zero gate, measured. Returns findings per gate."""
    results = {}
    for gate, scanner in GATES.items():
        try:
            findings = scanner()
        except Exception as exc:  # noqa: BLE001 — a broken scanner is a finding
            results[gate] = {
                "count": -1,
                "error": str(exc),
                "findings": [],
            }
            continue
        results[gate] = {
            "count": len(findings),
            "findings": [f.as_dict() for f in findings],
        }
    return results
