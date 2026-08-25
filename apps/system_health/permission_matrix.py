"""The exhaustive role x surface authorization matrix (mandate §45.5).

The audit recorded this deliverable as not built and deferred twice. What
existed was a route/permission scanner covering roughly half the resolver, plus
targeted denial suites — which found a live privilege escalation (SEC-01), and
that is evidence the coverage was worth completing rather than evidence it was
enough.

TWO RULES THIS MODULE FOLLOWS, BOTH LEARNED FROM DEFECTS IN THIS CODEBASE

**It asks the real gates rather than modelling them.** Every cell is answered
by calling `RolePermissionService.can_view_page` or `has_permission` — the same
functions the request path calls — with a stand-in principal carrying only an
active role, which is all either of them reads. A matrix that reimplemented the
rule would be a second definition of the authority, and a second definition
that drifts is precisely SEC-01: the school edit drawer gated its WRITE on the
READ helper, and a matrix built from a copy of the rule would have agreed with
it.

**It counts what it cannot answer.** A routed surface that declares no page
permission and no required permission is reported as unguarded, by kind, rather
than omitted. Most are legitimately open (login, health, static-ish routes) or
guarded inside the view body, and this module cannot tell which — so it says
how many there are and which they are, and leaves the judgement visible. A
coverage figure that quietly dropped what it could not classify would be the
"536 of 1,028" problem restated as a percentage.
"""

from __future__ import annotations

import inspect
import json

from django.urls import get_resolver

from apps.core.navigation import PAGE_PERMISSIONS, ROLE_EXCLUSIVE_PAGES
from apps.core.permissions import RolePermissionService, has_permission
from apps.core.rbac import EdifyRole

from .page_inventory import _iter_patterns


class _RolePrincipal:
    """What `can_view_page` and `has_permission` actually read: a role.

    Deliberately not a User. Building the matrix must not depend on the
    database, so it cannot drift with whatever accounts happen to exist, and it
    can run as a SimpleTestCase in CI.
    """

    is_authenticated = True

    def __init__(self, role: str):
        self.active_role = role


ROLES = tuple(role.value for role in EdifyRole)


def _declared_authority(callback) -> tuple[str, list[str]]:
    """(page permission key, required permission values) for one view."""
    page_key = getattr(callback, "page_permission", "") or ""
    required = getattr(callback, "required_permissions", None)
    if required is None:
        required = getattr(
            getattr(callback, "view_class", None), "required_permissions", None
        )
    if isinstance(required, str):
        values = [required]
    elif isinstance(required, (list, tuple, set, frozenset)):
        values = list(required)
    else:
        # Class-based views sometimes expose a descriptor here; the runtime
        # permission class resolves it on an instance and this cannot.
        values = []
    return page_key, sorted(str(getattr(v, "value", v)) for v in values)


def _roles_for(page_key: str, required: list[str]) -> list[str]:
    """Which roles pass this surface's declared gates.

    `required_permissions` is ANY-of, not all-of — `RequirePermissions` says so
    in its own docstring ("any-of semantics, matching the legacy guard") and
    implements it as `any(p in perms for p in required)`. The first version of
    this module used all-of and promptly reported five API routes as reachable
    by nobody, which was a finding it had invented. `test_permission_matrix`
    pins the semantics against the real class so the mirror cannot drift from
    the original.
    """
    allowed = []
    for role in ROLES:
        principal = _RolePrincipal(role)
        if page_key and not RolePermissionService.can_view_page(principal, page_key):
            continue
        if required and not any(has_permission(principal, p) for p in required):
            continue
        allowed.append(role)
    return allowed


def build_permission_matrix() -> dict:
    """Every routed surface, every role, answered by the real gate."""
    guarded: list[dict] = []
    unguarded: list[dict] = []

    for pattern, route in _iter_patterns(get_resolver().url_patterns):
        callback = pattern.callback
        original = inspect.unwrap(callback)
        module = getattr(callback, "__module__", "")
        page_key, required = _declared_authority(callback)
        row = {
            "route": route,
            "route_name": pattern.name or "",
            "view": f"{module}.{getattr(original, '__name__', type(original).__name__)}",
            "page_permission": page_key,
            "required_permissions": required,
        }
        if not page_key and not required:
            unguarded.append(row)
            continue
        row["roles"] = _roles_for(page_key, required)
        row["role_exclusive"] = bool(page_key and page_key in ROLE_EXCLUSIVE_PAGES)
        guarded.append(row)

    guarded.sort(key=lambda r: (r["route"], r["route_name"]))
    unguarded.sort(key=lambda r: (r["route"], r["route_name"]))

    by_role = {role: 0 for role in ROLES}
    for row in guarded:
        for role in row["roles"]:
            by_role[role] += 1

    # A guarded surface no role can reach is either a retired page or a
    # mis-declared permission key, and either way nobody can use it.
    unreachable = [row["route"] for row in guarded if not row["roles"]]

    return {
        "roles": list(ROLES),
        "summary": {
            "routes_total": len(guarded) + len(unguarded),
            "routes_guarded": len(guarded),
            "routes_unguarded": len(unguarded),
            "page_keys_declared": len(
                {row["page_permission"] for row in guarded if row["page_permission"]}
            ),
            "page_keys_in_navigation": len(PAGE_PERMISSIONS),
            "surfaces_no_role_can_reach": len(unreachable),
        },
        "routes_reachable_by_role": by_role,
        "unreachable_guarded_routes": unreachable,
        "guarded": guarded,
        "unguarded": unguarded,
    }


def matrix_as_json(matrix: dict) -> str:
    return json.dumps(matrix, indent=1, sort_keys=True) + "\n"


def matrix_as_markdown(matrix: dict) -> str:
    """The reader's view: one row per surface, one column per role."""
    roles = matrix["roles"]
    summary = matrix["summary"]
    lines = [
        "# Role × Surface Authorization Matrix",
        "",
        "Generated by `manage.py build_permission_matrix` from the URL resolver and",
        "the same gate functions the request path calls. Do not edit by hand — a",
        "hand-maintained copy of an authority is how SEC-01 happened.",
        "",
        f"- Routed surfaces: **{summary['routes_total']}**",
        f"- Declaring an authority: **{summary['routes_guarded']}**",
        f"- Declaring none: **{summary['routes_unguarded']}** "
        "(open by design, or guarded inside the view body — this module cannot "
        "tell which, so it lists them rather than scoring them)",
        f"- Guarded surfaces no role can reach: **{summary['surfaces_no_role_can_reach']}**",
        "",
        "## Surfaces reachable per role",
        "",
        "| Role | Guarded surfaces reachable |",
        "| --- | --- |",
    ]
    for role, count in matrix["routes_reachable_by_role"].items():
        lines.append(f"| {role} | {count} |")

    lines += [
        "",
        "## Every guarded surface",
        "",
        "`Y` means the role passes the gate this surface declares. Row order is by route.",
        "",
        "| Route | Page key | " + " | ".join(roles) + " |",
        "| --- | --- | " + " | ".join("---" for _ in roles) + " |",
    ]
    for row in matrix["guarded"]:
        allowed = set(row["roles"])
        key = row["page_permission"] or ", ".join(row["required_permissions"]) or "—"
        cells = " | ".join("Y" if role in allowed else "" for role in roles)
        lines.append(f"| `{row['route']}` | {key} | {cells} |")

    if matrix["unreachable_guarded_routes"]:
        lines += [
            "",
            "## Guarded surfaces no role can reach",
            "",
            "Either a retired page or a mis-declared permission key. Both are worth",
            "looking at: nobody can use these.",
            "",
        ]
        lines += [f"- `{route}`" for route in matrix["unreachable_guarded_routes"]]

    lines += [
        "",
        "## Surfaces declaring no authority",
        "",
        "Listed, not scored. Login, health and asset routes belong here; a product",
        "surface does not.",
        "",
        "| Route | View |",
        "| --- | --- |",
    ]
    for row in matrix["unguarded"]:
        lines.append(f"| `{row['route']}` | `{row['view']}` |")
    return "\n".join(lines) + "\n"
