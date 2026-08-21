#!/usr/bin/env python3
"""One-time codemod for the audited pre-registry KPI payload surface.

The command replaces metric-shaped dict literals with calls to the canonical
precomputed renderer and writes frozen MetricSpec declarations. It deliberately
does not touch bare label/value option rows or analytical breakdown rows.
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
REGISTRY = ROOT / "apps/core/metrics/registry.py"
GENERATED = ROOT / "apps/core/metrics/reconciled_registry.py"
TILE_MARKERS = {"variant", "icon", "helper", "hint", "trend", "tone"}


DOMAIN_NAMES = {
    "accounts/hr_dashboard_service.py": "Workforce dashboard",
    "analytics/analytics_dashboard_service.py": "Platform analytics",
    "analytics/cd_analytics_service.py": "Country analytics",
    "analytics/cd_dashboard_service.py": "Country dashboard",
    "analytics/pl_analytics_service.py": "Team analytics",
    "analytics/pl_dashboard_service.py": "Program Lead dashboard",
    "analytics/rvp_dashboard_service.py": "Regional dashboard",
    "clusters/services.py": "Cluster dashboard",
    "command_center/dashboard_service.py": "Role command centre",
    "debriefs/dashboard_service.py": "Debrief dashboard",
    "frontend/views/budget_views.py": "Fund request workspace",
    "frontend/views/core_schools_views.py": "Core schools workspace",
    "frontend/views/dashboard_views.py": "Role dashboard",
    "frontend/views/extended_views.py": "Operations workspace",
    "frontend/views/hr_views.py": "HR workspace",
    "frontend/views/ia_views.py": "IA workspace",
    "frontend/views/leave_views.py": "Leave workspace",
    "frontend/views/school_views.py": "School workspace",
    "frontend/views/staff_views.py": "Staff workspace",
    "fund_requests/disbursement_dashboard_service.py": "Disbursement workspace",
    "fund_requests/pl_approval_service.py": "Fund approval workspace",
    "monthly_work_plan/country_budget_service.py": "Country budget workspace",
    "planning/planning_service.py": "Annual planning workspace",
    "professional_development/hr_dashboard_service.py": "HR learning dashboard",
    "professional_development/services.py": "Learning workspace",
    "projects/dashboard_service.py": "Projects dashboard",
    "projects/impact_service.py": "Project impact analytics",
    "projects/my_plan_service.py": "Special-project personal plan",
    "projects/planning_service.py": "Special-project planning",
    "targets/team_targets.py": "Team targets workspace",
}


MODEL_HINTS = {
    "accounts": ("accounts.User", "accounts.EmployeeProfile"),
    "analytics": ("activities.Activity", "targets.Target"),
    "clusters": ("clusters.Cluster", "schools.School"),
    "command_center": ("activities.Activity", "fund_requests.FundRequest"),
    "debriefs": ("debriefs.DailyDebrief",),
    "frontend": ("activities.Activity",),
    "fund_requests": ("fund_requests.FundRequest",),
    "monthly_work_plan": ("activities.Activity", "budget.BudgetLine"),
    "planning": ("activities.Activity", "schools.School"),
    "professional_development": ("professional_development.Course",),
    "projects": ("projects.Project", "activities.Activity"),
    "targets": ("targets.Target", "activities.Activity"),
}


def literal(node: ast.AST | None):
    if isinstance(node, ast.Constant):
        return node.value
    return None


def dict_items(node: ast.Dict) -> dict[str, ast.expr]:
    return {
        key.value: value
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def is_tile(node: ast.Dict) -> bool:
    keys = set(dict_items(node))
    if "label" not in keys or "value" not in keys:
        return False
    if keys <= {"label", "value"} or {"band", "bar_pct", "score"} <= keys:
        return False
    if {"primary", "status"} <= keys:
        return False
    return bool(keys & TILE_MARKERS)


def slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.casefold())).strip("_")


def source_text(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ast.unparse(node)


def enclosing_functions(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    found = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(current)
    return found


def bind_call(call: ast.Call, function: ast.FunctionDef) -> dict[str, ast.expr]:
    names = [argument.arg for argument in function.args.args]
    bound = dict(zip(names, call.args))
    bound.update(
        keyword.arg and (keyword.arg, keyword.value) for keyword in call.keywords
    )
    return bound


def inferred_unit(label: str, expression: str) -> str:
    if "%" in expression or any(
        word in label.casefold()
        for word in (
            "achievement",
            "completion",
            "compliance",
            "progress",
            "readiness",
            "utilization",
            "utilisation",
            "adoption",
            "rate",
        )
    ):
        return "percent"
    if any(token in expression.casefold() for token in ("ugx", "currency", "_fmt")):
        return "money_ugx"
    if any(word in label.casefold() for word in ("score", "average", "delta")):
        return "score"
    if "/" in expression and expression.lstrip().startswith("f"):
        return "status"
    if any(word in label.casefold() for word in ("status", "weakest", "health")):
        return "status"
    return "count"


def inferred_category(label: str) -> str:
    text = label.casefold()
    if any(word in text for word in ("pending", "awaiting", "due", "required")):
        return "pending_action"
    if any(word in text for word in ("risk", "overdue", "clash", "without", "missing")):
        return "risk"
    if any(word in text for word in ("budget", "fund", "amount", "allocation")):
        return "finance"
    if any(word in text for word in ("compliance", "verified", "evidence")):
        return "compliance"
    if any(word in text for word in ("completion", "progress", "achievement", "util")):
        return "progress"
    if any(word in text for word in ("impact", "improved", "trained", "reached")):
        return "outcome"
    if any(word in text for word in ("ready", "readiness", "on track")):
        return "readiness"
    return "scale"


def inferred_period(label: str) -> str:
    text = label.casefold()
    if "week" in text or "7d" in text:
        return "week"
    if "month" in text:
        return "month"
    if "quarter" in text:
        return "quarter"
    if "fy" in text or "annual" in text:
        return "financial_year"
    if "today" in text:
        return "point_in_time"
    return "point_in_time"


def inferred_date_basis(label: str) -> str:
    text = label.casefold()
    if "ssa" in text:
        return "ssa_assessment_date"
    if any(word in text for word in ("scheduled", "planned")):
        return "activity_planned_date"
    if any(word in text for word in ("completed", "visited", "trained")):
        return "activity_execution_date"
    if any(word in text for word in ("approval", "submitted", "review")):
        return "submission_date"
    if any(word in text for word in ("disbursed", "paid")):
        return "disbursement_date"
    return "not_time_bound"


def finance_stage(label: str) -> str:
    text = label.casefold()
    if "request" in text:
        return "requested"
    if any(word in text for word in ("disburs", "paid")):
        return "disbursed"
    if any(word in text for word in ("account", "clear")):
        return "accounted"
    if any(word in text for word in ("remaining", "variance")):
        return "variance"
    if any(word in text for word in ("approved", "allocation")):
        return "approved"
    return "planned"


def question_for(label: str, category: str) -> str:
    prompts = {
        "pending_action": "What requires action now",
        "risk": "Which exception needs attention",
        "finance": "What financial decision does the current position support",
        "compliance": "Where is required evidence or compliance incomplete",
        "progress": "Is delivery progressing against its declared basis",
        "outcome": "What verified outcome has been achieved",
        "readiness": "Is the scope ready for the next workflow step",
        "scale": "What is the size of the current in-scope workload",
    }
    return f"{prompts[category]} for {label}?"


def route_from(items: dict[str, ast.expr], bound: dict[str, ast.expr] | None = None):
    values = bound or items
    for name in ("link", "href", "drilldown_url"):
        value = literal(values.get(name))
        if isinstance(value, str) and value:
            return value
    return None


def registry_row(
    *,
    key: str,
    label: str,
    source_label: str,
    source_id: str,
    service: str,
    expression: str,
    module_relative: str,
    route: str | None,
    line: int,
) -> dict:
    unit = inferred_unit(label, expression)
    category = inferred_category(label)
    domain = DOMAIN_NAMES[module_relative]
    row = {
        "key": key,
        "label": label,
        "source_label": source_label,
        "source": source_id,
        "definition": (
            f"The {source_label} value produced by {service}; the preserved "
            f"server display expression is `{expression}`."
        ),
        "question": question_for(source_label, category),
        "category": category,
        "unit": unit,
        "service": service,
        "source_models": MODEL_HINTS[module_relative.split("/", 1)[0]],
        "numerator": expression,
        "date_basis": inferred_date_basis(source_label),
        "period": inferred_period(source_label),
        "scope": f"The role- and filter-scoped records in the {domain}",
        "owner_page": slug(domain),
        "filter_behaviour": "partial",
        "drilldown": route,
        "no_drilldown_reason": (
            None
            if route
            else "The existing service exposes no underlying-record route; retain only as contextual information."
        ),
        "notes": f"Reconciled from {module_relative}:{line}; no browser arithmetic added.",
    }
    if unit == "percent":
        row["denominator"] = (
            f"The in-scope denominator used by the server formula in {service}"
        )
    if unit == "money_ugx":
        row["finance_stage"] = finance_stage(source_label)
    return row


def existing_registry_identity() -> tuple[set[str], set[str]]:
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"))
    keys, labels = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "MetricSpec"):
            continue
        values = {keyword.arg: literal(keyword.value) for keyword in node.keywords}
        if values.get("key"):
            keys.add(values["key"])
        if values.get("label"):
            labels.add(values["label"].casefold())
    return keys, labels


def insert_import(source: str, dynamic: bool) -> str:
    names = ["render_precomputed_metric_item"]
    if dynamic:
        names.append("render_precomputed_metric_for_source")
    missing = [
        name
        for name in names
        if not re.search(
            rf"^from apps\.core\.metrics import .*\b{re.escape(name)}\b",
            source,
            re.MULTILINE,
        )
    ]
    if not missing:
        return source
    statement = f"from apps.core.metrics import {', '.join(missing)}\n"
    future = re.search(r"^from __future__ import .+\n", source, re.MULTILINE)
    offset = future.end() if future else 0
    if not future:
        tree = ast.parse(source)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            lines = source.splitlines(keepends=True)
            offset = sum(len(line) for line in lines[: tree.body[0].end_lineno])
    return source[:offset] + "\n" + statement + source[offset:]


def generate() -> tuple[list[dict], dict[Path, str]]:
    rows_by_identity: dict[tuple[str, str], dict] = {}
    replacements_by_path: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
    dynamic_by_path: dict[Path, bool] = defaultdict(bool)
    used_keys, existing_labels = existing_registry_identity()

    for path in sorted(APPS.rglob("*.py")):
        relative_path = path.relative_to(APPS).as_posix()
        if relative_path not in DOMAIN_NAMES:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        line_offsets = [0]
        for match in re.finditer("\n", source):
            line_offsets.append(match.end())

        def offsets(node: ast.AST) -> tuple[int, int]:
            return (
                line_offsets[node.lineno - 1] + node.col_offset,
                line_offsets[node.end_lineno - 1] + node.end_col_offset,
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict) or not is_tile(node):
                continue
            items = dict_items(node)
            if literal(items["label"]) is None and set(items) <= {
                "label",
                "value",
                "pct",
                "tone",
            }:
                continue
            functions = enclosing_functions(node, parents)
            owner = functions[-1] if functions else None
            nearest = functions[0] if functions else None
            service_module = (
                path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
            )
            service = f"{service_module}.{owner.name if owner else '<module>'}"
            source_label = literal(items["label"])

            if isinstance(source_label, str):
                source_id = f"{service}:{nearest.name if nearest else 'payload'}"
                identity = (source_id, source_label)
                base = slug(f"{relative_path.removesuffix('.py')} {source_label}")
                key = base
                suffix = 2
                while key in used_keys:
                    key = f"{base}_{suffix}"
                    suffix += 1
                if identity in rows_by_identity:
                    key = rows_by_identity[identity]["key"]
                else:
                    used_keys.add(key)
                    expression = source_text(
                        source, items.get("raw_value", items["value"])
                    )
                    rows_by_identity[identity] = registry_row(
                        key=key,
                        label=source_label,
                        source_label=source_label,
                        source_id=source_id,
                        service=service,
                        expression=expression,
                        module_relative=relative_path,
                        route=route_from(items),
                        line=node.lineno,
                    )
                arguments = [repr(key), source_text(source, items["value"])]
                kwargs = []
                for name, value in items.items():
                    if name in {"label", "value", "metric_key"}:
                        continue
                    kwargs.append(f"{name}={source_text(source, value)}")
                call = (
                    "render_precomputed_metric_item("
                    + ", ".join(arguments + kwargs)
                    + ")"
                )
            else:
                if nearest is None:
                    raise RuntimeError(
                        f"Cannot reconcile dynamic label at {relative_path}:{node.lineno}"
                    )
                outer = functions[-1] if len(functions) > 1 else tree
                owner_name = functions[-1].name if len(functions) > 1 else nearest.name
                source_id = (
                    f"{service_module}:{owner_name}.{nearest.name}"
                    if len(functions) > 1
                    else f"{service_module}:{nearest.name}"
                )
                labels_found = 0
                for call_node in ast.walk(outer):
                    if not (
                        isinstance(call_node, ast.Call)
                        and isinstance(call_node.func, ast.Name)
                        and call_node.func.id == nearest.name
                    ):
                        continue
                    bound = bind_call(call_node, nearest)
                    call_label = literal(bound.get("label"))
                    if not isinstance(call_label, str):
                        continue
                    labels_found += 1
                    identity = (source_id, call_label)
                    supplied_key = literal(bound.get("key"))
                    base = (
                        slug(supplied_key)
                        if isinstance(supplied_key, str) and "_" in supplied_key
                        else slug(f"{relative_path.removesuffix('.py')} {call_label}")
                    )
                    key = base
                    suffix = 2
                    while key in used_keys:
                        key = f"{base}_{suffix}"
                        suffix += 1
                    if identity in rows_by_identity:
                        continue
                    used_keys.add(key)
                    expression_node = (
                        bound.get("raw_value")
                        or bound.get("raw")
                        or bound.get("value")
                        or items["value"]
                    )
                    expression = source_text(source, expression_node)
                    rows_by_identity[identity] = registry_row(
                        key=key,
                        label=call_label,
                        source_label=call_label,
                        source_id=source_id,
                        service=service,
                        expression=expression,
                        module_relative=relative_path,
                        route=route_from(items, bound),
                        line=call_node.lineno,
                    )
                if not labels_found:
                    raise RuntimeError(
                        f"No static labels found for {source_id} at line {node.lineno}"
                    )
                dynamic_by_path[path] = True
                arguments = [
                    repr(source_id),
                    source_text(source, items["label"]),
                    source_text(source, items["value"]),
                ]
                kwargs = []
                for name, value in items.items():
                    if name in {"label", "value", "metric_key"}:
                        continue
                    kwargs.append(f"{name}={source_text(source, value)}")
                call = (
                    "render_precomputed_metric_for_source("
                    + ", ".join(arguments + kwargs)
                    + ")"
                )
            replacements_by_path[path].append((*offsets(node), call))

    rows = list(rows_by_identity.values())
    label_counts = Counter(row["label"].casefold() for row in rows)
    scope_counters: Counter[tuple[str, str]] = Counter()
    for row in rows:
        folded = row["label"].casefold()
        if folded in existing_labels or label_counts[folded] > 1:
            domain = row["scope"].removeprefix(
                "The role- and filter-scoped records in the "
            )
            scope_counters[(folded, domain)] += 1
            number = scope_counters[(folded, domain)]
            qualifier = domain if number == 1 else f"{domain} {number}"
            row["label"] = f"{row['label']} — {qualifier}"

    rewritten = {}
    for path, replacements in replacements_by_path.items():
        source = path.read_text(encoding="utf-8")
        for start, end, replacement in sorted(replacements, reverse=True):
            source = source[:start] + replacement + source[end:]
        source = insert_import(source, dynamic_by_path[path])
        rewritten[path] = source
    return rows, rewritten


def write_registry(rows: list[dict]) -> None:
    header, rest = GENERATED.read_text(encoding="utf-8").split(
        "RECONCILED_METRIC_ROWS: tuple[dict, ...] =", 1
    )
    _, footer = rest.split("\n\n\ndef _build", 1)
    body = "(\n" + "".join(f"    {row!r},\n" for row in rows) + ")"
    GENERATED.write_text(
        header
        + "RECONCILED_METRIC_ROWS: tuple[dict, ...] = "
        + body
        + "\n\n\ndef _build"
        + footer,
        encoding="utf-8",
    )


def main() -> None:
    if "RECONCILED_METRIC_ROWS: tuple[dict, ...] = ()" not in GENERATED.read_text(
        encoding="utf-8"
    ):
        raise SystemExit(
            "The reconciled registry is already populated. This is a one-time "
            "codemod; refusing to overwrite stable metric keys."
        )
    rows, rewritten = generate()
    for path, source in rewritten.items():
        path.write_text(source, encoding="utf-8")
    write_registry(rows)
    print(f"Reconciled {len(rows)} metric definitions across {len(rewritten)} modules.")


if __name__ == "__main__":
    main()
