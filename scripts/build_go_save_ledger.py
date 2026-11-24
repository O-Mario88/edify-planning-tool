"""Build the Go migration's save ledger (docs/migration/190-save-ledger.*).

One row for every save the web application offers: each distinct destination
of a state-changing control in docs/platform-interaction-inventory.json, with
the Django view behind it, its size, the roles that can reach it
(docs/platform-permission-matrix.json) and where Go stands on it.

Go's status is kept by hand in GO_STATUS below and changes only with
evidence: "proved" means the save was compared with Django and replayed with
Django stopped (the doc named beside it); "unproved" means Go has code for
the path that has not been compared; everything else still saves through
Django.

Run from the repository root:  python3 scripts/build_go_save_ledger.py
"""

from __future__ import annotations

import ast
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "docs/migration/190-save-ledger.json"
OUT_MD = ROOT / "docs/migration/190-save-ledger.md"

#: Field staff: the roles that do the daily school work.
FIELD_ROLES = {"CCEO", "PartnerFieldOfficer", "ProjectCoordinator"}
LEADER_ROLES = {
    "Program Lead",
    "CountryDirector",
    "RegionalVicePresident",
    "RegionalProgramLead",
}
MONEY_AREAS = (
    "/fund-requests",
    "/finance",
    "/accounts",
    "/disbursements",
    "/cost-settings",
    "/country-budget",
    "/budget",
    "/fund-approvals",
)
HR_AREAS = (
    "/hr",
    "/performance-conversation",
    "/recruitment",
    "/compliance-register",
    "/health-safety",
    "/offboarding",
    "/pulse-surveys",
    "/recognition",
    "/recovery-plans",
    "/employee-relations",
    "/candidate-pipeline",
    "/team",
    "/compensation-benefits",
)
PARTNER_AREAS = (
    "/partner",
    "/partners",
    "/partner-oversight",
    "/loans",
    "/loan-applications",
)

PROVED = "proved"
UNPROVED = "unproved"
DJANGO = "django"
#: A save the web no longer offers, decided on purpose: its effect happens
#: elsewhere in Go, and the reason is in doc 189.
RETIRED = "retired"
#: A save Go's own service makes by design, ported earlier under the existing
#: rules (sign-in, accounts, acting, the notification centre): the web calls
#: Go for it, never Django. The doc beside it is where it was ported.
GO_OWNED = "go-owned"

#: Go's status for a destination, with its evidence. Only what is proved
#: against Django and with Django stopped is "proved".
GO_STATUS: dict[str, tuple[str, str]] = {
    "/planning/schedule-action": (
        PROVED,
        "Schedule Visit, the training pair, Group Training (docs 27, 33, 38, 189)",
    ),
    "/my-plan/<str:activity_id>/cancel": (PROVED, "cancel (doc 30)"),
    "/my-plan/<str:activity_id>/edit": (PROVED, "edit (doc 31)"),
    "/my-plan/<str:activity_id>/complete": (PROVED, "complete a staff visit (doc 182)"),
    "/activity-selection/reschedule": (PROVED, "group reschedule (doc 36)"),
    "/activity-selection/cancel": (PROVED, "group cancel (doc 36)"),
    "/core-schools/schedule-visit/action": (PROVED, "Core visit form (doc 189)"),
    "/core-schools/schedule-training/action": (PROVED, "Core training form (doc 189)"),
    "/core-schools/assign-partner/action": (PROVED, "Core partner hand-over (doc 189)"),
    "/today/snooze": (PROVED, "To-Do snooze (doc 50)"),
    "/today/unsnooze": (PROVED, "To-Do unsnooze (doc 63)"),
    "/planning/visit-requests/<str:activity_id>/<str:decision>": (
        PROVED,
        "owner's visit decision (doc 189)",
    ),
    "/activities/<str:activity_id>/start/action": (PROVED, "Start activity (doc 189)"),
    "/schools/<str:school_id>/take": (PROVED, "Take a school nobody holds (doc 189)"),
    "/fund-requests/weekly/<str:request_id>/confirm": (
        PROVED,
        "owner sends their week (doc 189)",
    ),
    "/fund-requests/weekly/<str:request_id>/self-funded": (
        PROVED,
        "owner self-funds their week (doc 189)",
    ),
    "/fund-requests/weekly/<str:request_id>/not-requested": (
        PROVED,
        "owner's No Advance (doc 189)",
    ),
    "/fund-requests/weekly/<str:request_id>/confirm-receipt": (
        PROVED,
        "owner's Fund Received (doc 189)",
    ),
    "/fund-requests/receipt-confirm": (PROVED, "requester's monthly receipt (doc 189)"),
    "/extra-work/<str:assignment_id>/<str:action>": (
        PROVED,
        "Extra Assigned Work's start, submit, return, verify, cancel (doc 189)",
    ),
    "/extra-work/assign": (
        UNPROVED,
        "Go saves it; Django's own save always fails, so there is nothing to compare (doc 189)",
    ),
    "/schools/<str:school_id>/assign-to-project": (PROVED, "Add to Project (doc 189)"),
    "/planning/assign-partner-action": (
        PROVED,
        "Planning drawer's Assign to Partner, outside a Core package (doc 189)",
    ),
    "/logout": (GO_OWNED, "SignOut (doc 08)"),
    "/change-password": (GO_OWNED, "SetNewPassword (docs 08, 09)"),
    "/auth/switch-role": (GO_OWNED, "SwitchRole (doc 09)"),
    "/acting-leadership/appoint": (GO_OWNED, "Appoint (doc 11)"),
    "/acting-leadership/<str:assignment_id>/cancel": (
        GO_OWNED,
        "CancelAppointment (doc 11)",
    ),
    "/acting-leadership/<str:assignment_id>/reschedule": (
        GO_OWNED,
        "ChangeMonth (doc 11)",
    ),
    "/notifications/<str:notif_id>/read": (GO_OWNED, "notification centre (doc 189)"),
    "/notifications/mark-all-read": (GO_OWNED, "notification centre (doc 189)"),
    "/notifications/settings": (GO_OWNED, "notification preferences (doc 189)"),
    "/fund-requests/generate-request": (
        RETIRED,
        "the week is refiled with every priced day (doc 189)",
    ),
    "/my-plan/<str:activity_id>/confirm-reimbursement-receipt": (
        PROVED,
        "officer's reimbursement receipt (doc 189)",
    ),
    "/my-plan/<str:activity_id>/accountability": (
        PROVED,
        "officer's accountability with a receipt (doc 189)",
    ),
    "/activities/<str:activity_id>/salesforce-id/action": (
        PROVED,
        "Salesforce ID hand-in (doc 189)",
    ),
    # Go has code naming these paths, never compared with Django.
    "/admin-panel/staff-setup-queue": (UNPROVED, "Go names the path"),
    "/support": (UNPROVED, "internal/support"),
    "/cluster-oversight/scoring": (UNPROVED, "Go names the path"),
    "/debriefs/submit": (PROVED, "Daily Debrief submit, inline page form (doc 189)"),
    "/messages/new/": (UNPROVED, "Go names the path"),
    "/notifications": (UNPROVED, "notificationcenter"),
    "/planning/fiscal-years": (UNPROVED, "Go names the path"),
    "/quality-checks": (UNPROVED, "Go names the path"),
    "/schools/upload": (UNPROVED, "Go names the path"),
    "/ssa/manual/": (UNPROVED, "Go names the path"),
    "/ssa/verification/": (UNPROVED, "Go names the path"),
    "/my-targets/mscs": (UNPROVED, "Go names the path"),
    "/partner-oversight/withdraw/bulk": (UNPROVED, "Go names the path"),
    "/my-professional-development/request": (
        UNPROVED,
        "form opens in Go; save not compared",
    ),
    "/projects/capacity/set": (UNPROVED, "form opens in Go; save not compared"),
    "/projects/capacity/withdraw": (UNPROVED, "form opens in Go; save not compared"),
    "/projects/planning/bulk-partner": (UNPROVED, "Go names the path"),
    "/training-ceilings/set": (UNPROVED, "Go names the path"),
    "/training-ceilings/country/set": (UNPROVED, "Go names the path"),
    "/settings/activity-catalogue/new": (UNPROVED, "Go names the path"),
    "/cost-settings/add": (UNPROVED, "form opens in Go; save not compared"),
}


def view_lines(callback: str) -> int | None:
    """The number of lines in the Django view a route calls, or None."""
    module, _, name = callback.rpartition(".")
    path = ROOT / (module.replace(".", "/") + ".py")
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == name
        ):
            return node.end_lineno - node.lineno + 1
    return None


def size_of(lines: int | None) -> str:
    if lines is None:
        return "unknown"
    if lines <= 40:
        return "small"
    if lines <= 120:
        return "medium"
    return "large"


def area_of(route: str) -> str:
    return "/" + route.strip("/").split("/")[0]


def phase_of(route: str, roles: set[str]) -> str:
    """The plan's step (go-migration-forecast-2026-11-24) the save belongs to."""
    area = area_of(route)
    if area in MONEY_AREAS:
        return "8 finance and money"
    if area in HR_AREAS:
        return "7 HR, compliance and coaching"
    if area in PARTNER_AREAS:
        return "6 partners and loans"
    if roles & FIELD_ROLES:
        return "3 field staff"
    if roles & LEADER_ROLES or "ImpactAssessment" in roles:
        return "5 supervisors and leadership"
    return "9 admin and the rest"


def main() -> None:
    controls = json.loads(
        (ROOT / "docs/platform-interaction-inventory.json").read_text()
    )["controls"]
    routes = {
        r["route"]: r
        for r in json.loads((ROOT / "docs/platform-page-inventory.json").read_text())[
            "routes"
        ]
    }
    matrix = json.loads((ROOT / "docs/platform-permission-matrix.json").read_text())
    roles_of = {g["route"]: set(g.get("roles") or []) for g in matrix["guarded"]}
    everyone = set(matrix["roles"])
    unguarded = {u["route"] for u in matrix["unguarded"]}

    saves = [c for c in controls if c.get("state_changing")]
    by_route: dict[str, list[dict]] = collections.defaultdict(list)
    for control in saves:
        by_route[control.get("destination_route") or ""].append(control)

    rows = []
    for route, found in sorted(by_route.items()):
        if not route:
            continue
        known = routes.get(route) or routes.get(route.rstrip("/")) or {}
        callback = known.get("callback", "")
        lines = view_lines(callback) if callback else None
        roles = (
            roles_of.get(route)
            or roles_of.get(route.rstrip("/"))
            or (everyone if route in unguarded else set())
        )
        status, evidence = GO_STATUS.get(route, (DJANGO, ""))
        names = sorted(
            {c.get("accessible_name", "") for c in found if c.get("accessible_name")}
        )[:3]
        rows.append(
            {
                "route": route,
                "controls": len(found),
                "labels": names,
                "view": callback,
                "view_lines": lines,
                "size": size_of(lines),
                "roles": sorted(roles),
                "field_staff": bool(roles & FIELD_ROLES),
                "phase": phase_of(route, roles),
                "go": status,
                "evidence": evidence,
                "templates": sorted({c.get("template", "") for c in found})[:3],
            }
        )

    blank = collections.Counter(c.get("template", "") for c in by_route.get("", []))
    summary = {
        "saves": len(rows),
        "controls": len(saves),
        "controls_without_a_destination": sum(blank.values()),
        "go": dict(collections.Counter(r["go"] for r in rows)),
        "size": dict(collections.Counter(r["size"] for r in rows)),
        "phase": dict(sorted(collections.Counter(r["phase"] for r in rows).items())),
        "field_staff_left": sum(
            1
            for r in rows
            if r["field_staff"] and r["go"] not in (PROVED, RETIRED, GO_OWNED)
        ),
    }
    OUT_JSON.write_text(
        json.dumps(
            {
                "summary": summary,
                "saves": rows,
                "templates_with_unresolved_destinations": dict(blank.most_common()),
            },
            indent=1,
        )
        + "\n"
    )
    write_markdown(summary, rows, blank)
    print(json.dumps(summary, indent=1))


def write_markdown(summary: dict, rows: list[dict], blank: collections.Counter) -> None:
    lines = [
        "# 190 · Save ledger",
        "",
        "Every save the web application offers, by the Django route it posts to, and where Go stands on it.",
        "Built by `scripts/build_go_save_ledger.py` from the checked-in inventories; Go's status is kept by",
        "hand in that script and changes only with evidence. *Proved* means compared with Django and replayed",
        "with Django stopped.",
        "",
        f"- Saves: {summary['saves']} destinations from {summary['controls']} save controls.",
        f"- Go: {summary['go'].get(PROVED, 0)} proved, {summary['go'].get(UNPROVED, 0)} with unproved Go code, "
        f"{summary['go'].get(DJANGO, 0)} still Django's, {summary['go'].get(RETIRED, 0)} retired on purpose, "
        f"{summary['go'].get(GO_OWNED, 0)} made by Go's own services.",
        f"- Field staff can reach {summary['field_staff_left']} saves that are not yet proved in Go.",
        f"- {summary['controls_without_a_destination']} controls post to a destination the inventory cannot read "
        "(set by a variable or script); they are listed by template at the end and must be classified by hand.",
        "",
        "| Step | Saves |",
        "|---|---|",
        *[f"| {phase} | {count} |" for phase, count in summary["phase"].items()],
        "",
    ]
    for phase in sorted({r["phase"] for r in rows}):
        lines += [
            f"## Step {phase}",
            "",
            "| Route | Go | Size | Roles | Labels |",
            "|---|---|---|---|---|",
        ]
        for r in sorted(
            (r for r in rows if r["phase"] == phase),
            key=lambda r: (r["go"] != PROVED, r["route"]),
        ):
            roles = (
                ", ".join(r["roles"])
                if len(r["roles"]) < 6
                else f"{len(r['roles'])} roles"
            )
            lines.append(
                f"| `{r['route']}` | {r['go']} | {r['size']} | {roles} | {'; '.join(r['labels'])} |"
            )
        lines.append("")
    lines += [
        "## Controls whose destination the inventory cannot read",
        "",
        "| Template | Controls |",
        "|---|---|",
    ]
    lines += [f"| `{template}` | {count} |" for template, count in blank.most_common()]
    OUT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
