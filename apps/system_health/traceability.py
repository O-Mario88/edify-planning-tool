"""Trace each mandated requirement to the code that actually runs for it.

Section 11 of the release mandate asks for a requirements traceability matrix:
every approved requirement mapped to its role, page, API, service, model,
permission, notification, metric, test and evidence. Two prior audits deferred
it, and the reason is not hard to see -- written by hand it is a spreadsheet of
assertions, and a spreadsheet of assertions is the same evidence problem this
audit has been closing everywhere else. Nobody can check it, and it rots the
first time a service is renamed.

So this module does not ask anyone to assert anything. It takes the twenty-two
mandated journeys from ``apps.core.tests.release_journeys`` -- the one
requirement set this platform has in machine-readable form -- and for each one
that has a covering test, it RUNS that test with the platform instrumented, and
records what was genuinely touched:

* the HTTP routes requested (``request_started``),
* the first-party source files executed (a ``sys.settrace`` call hook),
* the models written (``post_save`` / ``post_delete`` on every sender),
* the permissions and page gates checked (locals read at the guard call),
* the notifications raised (``Notification.source_event_type``),
* the audit actions written (``AuditLog.action``),
* the metrics the run computes and the metrics it moves.

Roles come from the RBAC tables: the roles that hold the permissions the run
checked. Nothing in a row is a claim about what the code ought to do -- every
cell is a record of what happened when the requirement was exercised.

That has a consequence worth stating plainly, because it is the honest limit of
this artefact: a journey whose test drives services directly rather than over
HTTP will have an empty route column. That is not a gap in the platform; it is
this matrix reporting the shape of its own evidence rather than inventing
coverage it did not observe. The same goes for a blocked journey, which gets a
row with a reason and no trace at all.

What a zero means, exactly, because a zero is the cell most easily misread:

* An empty **routes** cell means the run made no HTTP request. Verified: the
  route control in ``test_traceability_matrix`` proves the tracer records one
  when it happens.
* An empty **permissions** cell means no call to ``has_permission`` or
  ``RolePermissionService.can_view_page`` and no view carrying
  ``required_permissions``. It does **not** mean the run was unauthorised.
  Services also refuse by comparing roles inline and raising ``Forbidden``,
  and those refusals carry no permission key for the tracer to record. Read
  the cell as "no permission key was consulted", never as "anyone could do
  this".
* An empty **metrics computed** cell means the metric registry's named
  computing function did not run. Attribution is function-level on purpose:
  the first version matched on the module file, and credited a journey with
  twelve analytics metrics because some unrelated function in the same file
  had run.

Building the matrix requires a test database and takes several minutes, so it
is a management command (``build_traceability_matrix``) that writes
``docs/platform-traceability-matrix.json`` and ``.md``. The committed artefact
is then held to the manifest by ``test_traceability_matrix``, which also runs
the tracer against known-answer fixtures so that "the matrix is empty" can never
pass as "the platform touched nothing".
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = str(REPO_ROOT / "apps") + os.sep

#: Guard functions whose call frames name the thing being checked. Read at the
#: ``call`` event, where the arguments are already bound. Anything not listed
#: here is invisible to the permission column -- deliberately, because guessing
#: at a permission from a variable name is how a matrix starts inventing rows.
_PERMISSION_GUARDS = {
    # apps/core/permissions.py::has_permission (module-level service helper)
    "has_permission": ("permission", "view"),
    # apps/core/permissions.py::RolePermissionService.can_view_page
    "can_view_page": ("page",),
}

#: Object-level authorisation helpers. These do not name a permission string --
#: they answer "may this principal write this row" -- so they are recorded by
#: name rather than folded into the permission column.
_OBJECT_GUARDS = {
    "assert_may_write_school",
    "assert_may_plan_school",
}


def _is_first_party(filename: str) -> bool:
    return filename.startswith(APPS_ROOT)


def _relative(filename: str) -> str:
    return os.path.relpath(filename, REPO_ROOT)


def _is_evidence_source(rel: str) -> bool:
    """Source that counts as implementation, not as the harness testing it."""
    parts = rel.split(os.sep)
    name = parts[-1]
    if "migrations" in parts or "tests" in parts:
        return False
    if name.startswith("test_") or name in {"tests.py", "conftest.py"}:
        return False
    # This module and its command instrument the run; they are not the subject.
    return rel not in {
        os.path.join("apps", "system_health", "traceability.py"),
        os.path.join(
            "apps",
            "system_health",
            "management",
            "commands",
            "build_traceability_matrix.py",
        ),
    }


#: A path segment that is an opaque record identifier rather than a route word:
#: a CUID (this platform's own id format), a UUID, or a bare integer.
_OPAQUE_SEGMENT = re.compile(
    r"^(?:c[a-z0-9]{19,}"
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\d+)$"
)


def normalise_route(path: str) -> str:
    """``/schools/cmt9sle.../edit-drawer`` -> ``/schools/{id}/edit-drawer``.

    Fixture identifiers are freshly generated on every run, so recording the
    raw path would make the committed artefact differ from itself on every
    rebuild. A matrix that churns without the platform changing teaches its
    readers to ignore its diffs, which is how a real change goes unnoticed.
    """
    return "/".join(
        "{id}" if _OPAQUE_SEGMENT.match(segment) else segment
        for segment in path.split("/")
    )


@dataclass
class Recording:
    """Everything one instrumented run touched."""

    routes: set[str] = field(default_factory=set)
    services: set[str] = field(default_factory=set)
    #: ``apps/x/y.py::name`` for every first-party function that ran. The
    #: metric registry names one computing function per metric, so
    #: file-level granularity would credit a whole module's metrics to a
    #: run that touched one of them.
    functions: set[str] = field(default_factory=set)
    models_written: set[str] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)
    pages: set[str] = field(default_factory=set)
    object_guards: set[str] = field(default_factory=set)
    notifications: set[str] = field(default_factory=set)
    audit_actions: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (self.routes or self.services or self.models_written)


class Instrumentation:
    """Record what the platform touches, for the duration of a ``with`` block.

    The trace hook returns ``None`` for every frame, so no line events are
    requested and the cost stays proportional to call count rather than to
    executed lines. Frames outside ``apps/`` are rejected on the first
    comparison, which is most of them.
    """

    def __init__(self) -> None:
        self.recording = Recording()
        self._previous_trace = None
        self._receivers: list = []

    # ── the trace hook ───────────────────────────────────────────────────
    def _trace(self, frame, event, arg):
        if event != "call":
            return None
        code = frame.f_code
        filename = code.co_filename
        if not _is_first_party(filename):
            return None
        rel = _relative(filename)
        if not _is_evidence_source(rel):
            return None
        self.recording.services.add(rel)

        name = code.co_name
        self.recording.functions.add(f"{rel}::{name}")
        if name in _PERMISSION_GUARDS:
            self._record_guard(frame, name)
        elif name in _OBJECT_GUARDS:
            self.recording.object_guards.add(f"{rel}::{name}")
        return None

    def _record_guard(self, frame, name: str) -> None:
        wanted = _PERMISSION_GUARDS[name]
        local = frame.f_locals
        for key in wanted:
            value = local.get(key)
            if value is None:
                continue
            if key == "permission" and isinstance(value, str):
                self.recording.permissions.add(value)
            elif key == "page" and isinstance(value, str):
                self.recording.pages.add(value)
            elif key == "view":
                required = getattr(value, "required_permissions", None) or ()
                for permission in required:
                    if isinstance(permission, str):
                        self.recording.permissions.add(permission)

    # ── signal receivers ─────────────────────────────────────────────────
    def _on_request(self, sender, environ=None, **kwargs):
        if not environ:
            return
        method = environ.get("REQUEST_METHOD", "?")
        path = normalise_route(environ.get("PATH_INFO", "?"))
        self.recording.routes.add(f"{method} {path}")

    def _on_save(self, sender, instance=None, created=None, **kwargs):
        self._note_write(sender, instance)

    def _on_delete(self, sender, instance=None, **kwargs):
        self._note_write(sender, instance)

    def _note_write(self, sender, instance) -> None:
        meta = getattr(sender, "_meta", None)
        if meta is None:
            return
        label = meta.label
        self.recording.models_written.add(label)
        if label == "notifications.Notification":
            kind = getattr(instance, "source_event_type", None) or getattr(
                instance, "category", None
            )
            if kind:
                self.recording.notifications.add(str(kind))
        elif label == "audit.AuditLog":
            action = getattr(instance, "action", None)
            if action:
                self.recording.audit_actions.add(str(action))

    # ── lifecycle ────────────────────────────────────────────────────────
    def __enter__(self) -> "Instrumentation":
        from django.core.signals import request_started
        from django.db.models.signals import post_delete, post_save

        request_started.connect(self._on_request, weak=False)
        post_save.connect(self._on_save, weak=False)
        post_delete.connect(self._on_delete, weak=False)
        self._receivers = [
            (request_started, self._on_request),
            (post_save, self._on_save),
            (post_delete, self._on_delete),
        ]
        self._previous_trace = sys.gettrace()
        threading.settrace(self._trace)
        sys.settrace(self._trace)
        return self

    def __exit__(self, *exc) -> None:
        sys.settrace(self._previous_trace)
        threading.settrace(None)
        for signal, receiver in self._receivers:
            signal.disconnect(receiver)
        self._receivers = []
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Turning recordings into requirement rows
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RequirementRow:
    """One requirement, traced to what exercising it actually touched."""

    requirement: str
    title: str
    steps: tuple[str, ...]
    test: str
    #: Empty for a traced requirement; the reason, for one that cannot be run.
    untraced_because: str = ""
    roles: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    models_written: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()
    object_guards: tuple[str, ...] = ()
    notifications: tuple[str, ...] = ()
    audit_actions: tuple[str, ...] = ()
    metrics_computed: tuple[str, ...] = ()
    metrics_affected: tuple[str, ...] = ()

    @property
    def traced(self) -> bool:
        return not self.untraced_because

    def as_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "title": self.title,
            "steps": list(self.steps),
            "test": self.test,
            "untracedBecause": self.untraced_because,
            "roles": list(self.roles),
            "routes": list(self.routes),
            "services": list(self.services),
            "modelsWritten": list(self.models_written),
            "permissions": list(self.permissions),
            "pages": list(self.pages),
            "objectGuards": list(self.object_guards),
            "notifications": list(self.notifications),
            "auditActions": list(self.audit_actions),
            "metricsComputed": list(self.metrics_computed),
            "metricsAffected": list(self.metrics_affected),
        }


def roles_holding(permissions) -> tuple[str, ...]:
    """Which roles hold any of these permissions, per the RBAC tables.

    Any-of, matching ``RequirePermissions``: a role that holds one of the
    permissions a run checked is a role that can reach part of the requirement.
    The permission matrix already proved that reading all-of invents findings
    nobody can act on.
    """
    from apps.core.rbac import EdifyRole, permissions_for_role

    wanted = set(permissions)
    if not wanted:
        return ()
    holders = []
    for role in EdifyRole:
        if wanted & set(permissions_for_role(role)):
            holders.append(role.value)
    return tuple(sorted(holders))


def split_service_path(dotted: str) -> tuple[str, str] | None:
    """``apps.x.services.fn`` -> ``("apps/x/services.py", "fn")``.

    Returns ``None`` when no prefix of the dotted path is an importable file,
    which is how a stale ``service`` field shows up rather than being silently
    dropped. ``registry.check()`` already fails the build on that, so this is
    the belt to its braces.
    """
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        head, tail = parts[:cut], parts[cut:]
        # At most ``function`` or ``Class.method`` may remain. Without this the
        # walk keeps shortening until it reaches ``apps/__init__.py``, which
        # exists, and every unresolvable path resolves to the package root --
        # a metric pointing at a deleted module would then look traceable. The
        # control test for this exists because the first version did exactly
        # that.
        if len(tail) > 2:
            continue
        candidate = REPO_ROOT.joinpath(*head).with_suffix(".py")
        if not candidate.exists():
            candidate = REPO_ROOT.joinpath(*head, "__init__.py")
            if not candidate.exists():
                continue
        return _relative(str(candidate)), tail[-1]
    return None


def _metrics_for(recording: Recording) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Metrics this run computed, and metrics whose sources it wrote."""
    from apps.core.metrics.registry import all_metrics

    written = {label.lower() for label in recording.models_written}
    computed, affected = set(), set()
    for spec in all_metrics():
        located = split_service_path(spec.service)
        if located and f"{located[0]}::{located[1]}" in recording.functions:
            computed.add(spec.key)
        for source in spec.source_models:
            if source.lower() in written:
                affected.add(spec.key)
                break
    return tuple(sorted(computed)), tuple(sorted(affected))


def row_from_recording(
    *, requirement: str, title: str, steps, test: str, recording: Recording
) -> RequirementRow:
    computed, affected = _metrics_for(recording)
    return RequirementRow(
        requirement=requirement,
        title=title,
        steps=tuple(steps),
        test=test,
        roles=roles_holding(recording.permissions),
        routes=tuple(sorted(recording.routes)),
        services=tuple(sorted(recording.services)),
        models_written=tuple(sorted(recording.models_written)),
        permissions=tuple(sorted(recording.permissions)),
        pages=tuple(sorted(recording.pages)),
        object_guards=tuple(sorted(recording.object_guards)),
        notifications=tuple(sorted(recording.notifications)),
        audit_actions=tuple(sorted(recording.audit_actions)),
        metrics_computed=computed,
        metrics_affected=affected,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Running the requirement's own test under instrumentation
# ─────────────────────────────────────────────────────────────────────────────


class TestPointerError(RuntimeError):
    """A requirement names a test that cannot be loaded or that did not pass."""


def load_test(pointer: str):
    """``module.path:ClassName.test_method`` -> a runnable single-test suite."""
    import unittest

    module_path, _, qualname = pointer.partition(":")
    class_name, _, method_name = qualname.partition(".")
    if not (module_path and class_name and method_name):
        raise TestPointerError(f"{pointer!r} is not 'module:Class.test'")
    module = importlib.import_module(module_path)
    test_class = getattr(module, class_name, None)
    if test_class is None:
        raise TestPointerError(f"{module_path} defines no {class_name}")
    if not callable(getattr(test_class, method_name, None)):
        raise TestPointerError(f"{class_name} defines no {method_name}")
    return unittest.TestSuite([test_class(method_name)])


class _AsATestRun:
    """Present this process as a test run for the duration of a trace.

    Three services relax a production-only gate when they detect a test runner
    -- ``"test" in sys.argv or "pytest" in sys.modules`` -- and the platform
    treats that as a deliberate convention, with tests opting back into the
    strict path via ``strict_validation`` and
    ``apps/core/tests/test_production_gate_relaxation.py`` holding the
    convention in place.

    The tracer runs those same tests, so it has to present itself the same way.
    Without this, ``complete()`` takes the strict branch that the suite never
    takes, the journey test fails inside the tracer, and the matrix reports a
    requirement as untraceable because the harness changed the code path under
    it. Tracing a different execution than the one the suite proves would make
    every cell describe something nobody verified.
    """

    def __enter__(self) -> "_AsATestRun":
        self._added = "test" not in sys.argv
        if self._added:
            sys.argv.append("test")
        return self

    def __exit__(self, *exc) -> None:
        if self._added and "test" in sys.argv:
            sys.argv.remove("test")
        return None


def trace_test(pointer: str) -> Recording:
    """Run one test with the platform instrumented and return what it touched.

    A failing test produces no recording at all. Tracing a red test would
    describe the code path up to the failure and present it as evidence the
    requirement is met, which is precisely the kind of green this audit exists
    to refuse.
    """
    import unittest

    suite = load_test(pointer)
    stream = open(os.devnull, "w")
    try:
        runner = unittest.TextTestRunner(stream=stream, verbosity=0)
        with _AsATestRun(), Instrumentation() as instrumentation:
            result = runner.run(suite)
    finally:
        stream.close()
    if not result.wasSuccessful():
        problems = result.failures + result.errors
        detail = problems[0][1].strip().splitlines()[-1] if problems else "unknown"
        raise TestPointerError(f"{pointer} did not pass while tracing: {detail}")
    return instrumentation.recording


def build_traceability_matrix(*, progress=None) -> dict:
    """Trace every mandated journey that has a covering test.

    Requires a prepared test database -- see the ``build_traceability_matrix``
    management command, which sets one up.
    """
    from apps.core.tests.release_journeys import JOURNEYS

    rows: list[RequirementRow] = []
    for journey in JOURNEYS:
        requirement = f"journey-{journey.number:02d}"
        if progress:
            progress(f"{requirement} {journey.title}")
        if not journey.covered_by:
            rows.append(
                RequirementRow(
                    requirement=requirement,
                    title=journey.title,
                    steps=journey.steps,
                    test="",
                    untraced_because=(
                        journey.blocked_by
                        or "no test walks this journey end to end, so there is "
                        "nothing to trace"
                    ),
                )
            )
            continue
        pointer = journey.covered_by[0]
        recording = trace_test(pointer)
        rows.append(
            row_from_recording(
                requirement=requirement,
                title=journey.title,
                steps=journey.steps,
                test=pointer,
                recording=recording,
            )
        )
    return {
        "generatedBy": "python manage.py build_traceability_matrix",
        "requirementSource": "apps.core.tests.release_journeys.JOURNEYS",
        "method": (
            "Each requirement's covering test is executed with the platform "
            "instrumented; every cell records what the run touched, not what "
            "anyone asserts it should touch."
        ),
        "requirements": [row.as_dict() for row in rows],
        "summary": {
            "requirements": len(rows),
            "traced": sum(1 for row in rows if row.traced),
            "untraced": sum(1 for row in rows if not row.traced),
        },
        "untracedRequirementSets": UNTRACED_REQUIREMENT_SETS,
    }


#: Requirement sets this matrix does NOT cover, and why. Saying so here rather
#: than in prose means the coverage claim and its limits ship in the same
#: artefact, and the census test can hold both.
UNTRACED_REQUIREMENT_SETS = [
    {
        "set": "Approved product extensions GAP-01..GAP-16",
        "reason": (
            "The list exists only as prose in "
            "docs/release-readiness-2026-08-25.md, which names three of the "
            "sixteen (GAP-02, GAP-10, GAP-15) and summarises the rest. There "
            "is no machine-readable statement of the other thirteen anywhere "
            "in the repository, so they cannot be traced without first being "
            "written down. That is a product-owner deliverable, not an "
            "engineering one."
        ),
    },
    {
        "set": "Role x page authorisation requirements",
        "reason": (
            "Already traced, by a different artefact and a stronger method: "
            "docs/platform-permission-matrix.json enumerates every guarded "
            "route against every role from the RBAC tables themselves, which "
            "is exhaustive rather than execution-derived. Reproducing it here "
            "would add a second source of truth for the same question."
        ),
    },
    {
        "set": "Metric definitions",
        "reason": (
            "apps/core/metrics/registry.py already carries per-metric "
            "traceability as required fields -- owning service, source "
            "models, owner page, roles, drill-down and refresh events -- and "
            "registry.check() verifies the service paths resolve. This matrix "
            "joins to it rather than restating it."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def matrix_as_json(matrix: dict) -> str:
    return json.dumps(matrix, indent=2, sort_keys=False) + "\n"


def _cell(values, limit: int = 6) -> str:
    values = list(values)
    if not values:
        return "—"
    shown = ", ".join(f"`{v}`" for v in values[:limit])
    if len(values) > limit:
        shown += f" _+{len(values) - limit} more_"
    return shown


def matrix_as_markdown(matrix: dict) -> str:
    summary = matrix["summary"]
    out: list[str] = [
        "# Requirements traceability matrix",
        "",
        "> Generated by `python manage.py build_traceability_matrix`. Do not",
        "> edit by hand — every cell is a record of what ran, and typing into",
        "> it turns evidence back into assertion.",
        "",
        matrix["method"],
        "",
        f"**Requirement source:** `{matrix['requirementSource']}`  ",
        f"**Requirements:** {summary['requirements']}  ",
        f"**Traced by executing their own test:** {summary['traced']}  ",
        f"**Untraced:** {summary['untraced']}",
        "",
        "## Coverage at a glance",
        "",
        "| Req | Title | Test | Routes | Services | Models written | Permissions | Roles | Notifications | Audit | Metrics moved |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in matrix["requirements"]:
        if row["untracedBecause"]:
            out.append(
                f"| `{row['requirement']}` | {row['title']} | **not traced** "
                "| — | — | — | — | — | — | — | — |"
            )
            continue
        out.append(
            "| `{req}` | {title} | ✓ | {routes} | {services} | {models} | "
            "{perms} | {roles} | {notifs} | {audit} | {metrics} |".format(
                req=row["requirement"],
                title=row["title"],
                routes=len(row["routes"]),
                services=len(row["services"]),
                models=len(row["modelsWritten"]),
                perms=len(row["permissions"]),
                roles=len(row["roles"]),
                notifs=len(row["notifications"]),
                audit=len(row["auditActions"]),
                metrics=len(row["metricsAffected"]),
            )
        )

    out += ["", "## Each requirement in full", ""]
    for row in matrix["requirements"]:
        out.append(f"### `{row['requirement']}` · {row['title']}")
        out.append("")
        out.append("Steps: " + " → ".join(row["steps"]))
        out.append("")
        if row["untracedBecause"]:
            out.append(f"**Not traced.** {row['untracedBecause']}")
            out.append("")
            continue
        out.append(f"**Evidence test:** `{row['test']}`")
        out.append("")
        out.append("| Dimension | Traced to |")
        out.append("| --- | --- |")
        out.append(
            f"| Roles that hold the checked permissions | {_cell(row['roles'], 12)} |"
        )
        out.append(f"| Routes / API | {_cell(row['routes'], 8)} |")
        out.append(f"| Permissions checked | {_cell(row['permissions'], 12)} |")
        out.append(f"| Page gates checked | {_cell(row['pages'], 8)} |")
        out.append(f"| Object-level guards | {_cell(row['objectGuards'], 6)} |")
        out.append(f"| Services executed | {_cell(row['services'], 10)} |")
        out.append(f"| Models written | {_cell(row['modelsWritten'], 12)} |")
        out.append(f"| Notifications raised | {_cell(row['notifications'], 8)} |")
        out.append(f"| Audit actions (evidence) | {_cell(row['auditActions'], 8)} |")
        out.append(
            f"| Metrics computed in the run | {_cell(row['metricsComputed'], 8)} |"
        )
        out.append(
            f"| Metrics whose sources it moves | {_cell(row['metricsAffected'], 8)} |"
        )
        out.append("")

    out += ["## Requirement sets this matrix does not cover", ""]
    for entry in matrix["untracedRequirementSets"]:
        out.append(f"- **{entry['set']}** — {entry['reason']}")
    out.append("")
    return "\n".join(out)
