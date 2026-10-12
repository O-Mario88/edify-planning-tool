"""One layout for every export of planned work.

Owner, 2026-10-12: "for school visit export, i want the following column:
School ID, School Name, District, District type, Activity, Planned Date,
Executor, Purpose of Visit, Focus Intervention, Cost, Budget status,
Verification, Salesforce ID, Evidence, Status. For Training and Cluster
Meeting, I want the following columns: Cluster Name, District, District type,
Planned Date, Executor, Training, SSA Intervention, Participants, Cost,
Budget status, Verification, Salesforce ID, Evidence, Status."

Those are My Plan's own tables with a District Type beside the District, so
an export reads like the page it was taken from. A workbook holds one sheet
for each: the school visits, the trainings and cluster meetings, and the
other activities (a district meeting, a field event, a conference), which
keep the same order of columns around the place they happen at.

Each exporter hands over plain rows (`row(...)`); nothing here queries the
plan, so My Plan, Team and Country Planning Oversight and Cluster Oversight
cannot lay the same work out three ways.
"""

from __future__ import annotations

from collections.abc import Iterable

VISIT = "visit"
SESSION = "session"
OTHER = "other"

MONEY = "#,##0"
DATE = "d mmm yyyy"

VISIT_SHEET = "School Visits"
SESSION_SHEET = "Trainings & Cluster Meetings"
OTHER_SHEET = "Other Activities"

VISIT_HEADERS = (
    "School ID",
    "School Name",
    "District",
    "District Type",
    "Activity",
    "Planned Date",
    "Executor",
    "Purpose of Visit",
    "Focus Intervention",
    "Cost (UGX)",
    "Budget Status",
    "Verification",
    "Salesforce ID",
    "Evidence",
    "Status",
)
SESSION_HEADERS = (
    "Cluster Name",
    "District",
    "District Type",
    "Planned Date",
    "Executor",
    "Training",
    "SSA Intervention",
    "Participants",
    "Cost (UGX)",
    "Budget Status",
    "Verification",
    "Salesforce ID",
    "Evidence",
    "Status",
)
OTHER_HEADERS = (
    "Activity",
    "Venue",
    "District",
    "District Type",
    "Planned Date",
    "Executor",
    "Purpose",
    "Participants",
    "Cost (UGX)",
    "Budget Status",
    "Verification",
    "Salesforce ID",
    "Evidence",
    "Status",
)
ALL_HEADERS = (VISIT_HEADERS, SESSION_HEADERS, OTHER_HEADERS)

_BLANKS = ("—", "-", "Unknown", "None")


def _text(value) -> str:
    text = str(value or "").strip()
    return "" if text in _BLANKS else text


def _number(value):
    """A figure a reader can add up; blank when there is none."""
    if value in (None, "", "—"):
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return _text(value)


def row(kind: str, **fields) -> dict:
    """One exported activity. ``kind`` is VISIT, SESSION or OTHER; the fields
    are the cells: school_id, school_name, cluster_name, venue, district,
    district_type, activity, planned_date, executor, purpose, intervention,
    training, participants, cost, budget_status, verification, salesforce_id,
    evidence, status."""
    return {"kind": kind, **fields}


def _tail(r: dict) -> list:
    return [
        _number(r.get("cost")),
        _text(r.get("budget_status")),
        _text(r.get("verification")),
        _text(r.get("salesforce_id")),
        _text(r.get("evidence")),
        _text(r.get("status")),
    ]


def _place(r: dict) -> list:
    return [_text(r.get("district")), _text(r.get("district_type"))]


def _visit(r: dict) -> list:
    return [
        _text(r.get("school_id")),
        _text(r.get("school_name")),
        *_place(r),
        _text(r.get("activity")),
        r.get("planned_date") or "",
        _text(r.get("executor")),
        _text(r.get("purpose")),
        _text(r.get("intervention")),
        *_tail(r),
    ]


def _session(r: dict) -> list:
    return [
        _text(r.get("cluster_name")),
        *_place(r),
        r.get("planned_date") or "",
        _text(r.get("executor")),
        _text(r.get("training")),
        _text(r.get("intervention")),
        _number(r.get("participants")),
        *_tail(r),
    ]


def _other(r: dict) -> list:
    return [
        _text(r.get("activity")),
        _text(r.get("venue")),
        *_place(r),
        r.get("planned_date") or "",
        _text(r.get("executor")),
        _text(r.get("purpose")),
        _number(r.get("participants")),
        *_tail(r),
    ]


_LAYOUTS = (
    (VISIT, VISIT_SHEET, VISIT_HEADERS, _visit),
    (SESSION, SESSION_SHEET, SESSION_HEADERS, _session),
    (OTHER, OTHER_SHEET, OTHER_HEADERS, _other),
)


def sheets(rows: Iterable[dict]) -> list[dict]:
    """The workbook: a sheet a kind, each with its own columns, every sheet
    present so a reader sees an empty kind as empty rather than missing."""
    rows = list(rows)
    out = []
    for kind, title, headers, cells in _LAYOUTS:
        body = [cells(r) for r in rows if r.get("kind") == kind]
        out.append(
            {
                "title": title,
                "headers": list(headers),
                "rows": body,
                "number_formats": {
                    headers.index("Planned Date") + 1: DATE,
                    headers.index("Cost (UGX)") + 1: MONEY,
                },
            }
        )
    return out


def csv_rows(rows: Iterable[dict]):
    """The same sheets as one CSV, for a link that still asks for one: each
    sheet's name, its heading row and its rows, a blank line between."""
    for sheet in sheets(rows):
        yield [sheet["title"]]
        yield sheet["headers"]
        yield from sheet["rows"]
        yield []


def tables_from_csv(lines: Iterable[list]) -> dict[str, list[dict]]:
    """`csv_rows` read back: ``{sheet name: [{heading: cell}]}``."""
    titles = {title for _, title, _, _ in _LAYOUTS}
    tables: dict[str, list[dict]] = {}
    title, headers = None, None
    for line in lines:
        if len(line) == 1 and line[0] in titles:
            title, headers = line[0], None
            tables[title] = []
        elif title and headers is None and line:
            headers = line
        elif title and headers and line:
            tables[title].append(dict(zip(headers, line)))
    return tables


# ── What the cells say ───────────────────────────────────────────────────────
#: A weekly request's status as My Plan's "Budget status" badge words it.
_REQUEST_BUDGET_STATUS = {
    "pending_responsible_confirmation": "In Weekly Request",
    "submitted_to_pl": "Awaiting PL Approval",
    "submitted_to_cd": "Awaiting CD Approval",
    "returned_by_pl": "Request Returned",
    "returned_by_cd": "Request Returned",
    "returned_by_accountant": "Request Returned",
    "confirmed_for_advance": "Approved",
    "disbursed": "Disbursed",
}


def budget_status_labels(activity_ids: Iterable) -> dict[str, str]:
    """My Plan's "Budget status" for many activities at once: where the
    activity's budget stands in the weekly request it is in, "Budget
    Created" when it is costed and in none; an id with no cost line is left
    out (the caller says "No Budget", or that the cost is on the visit)."""
    from apps.activities.models import ActivityScheduleCostLine

    ids = [i for i in dict.fromkeys(activity_ids) if i]
    labels: dict[str, str] = {}
    for start in range(0, len(ids), 5000):
        for activity_id, status in (
            ActivityScheduleCostLine.objects.filter(
                activity_id__in=ids[start : start + 5000]
            )
            .order_by("activity_id", "id", "weekly_request_lines__id")
            .values_list(
                "activity_id", "weekly_request_lines__weekly_fund_request__status"
            )
        ):
            if activity_id in labels:
                continue
            labels[activity_id] = (
                "Budget Created"
                if status is None
                else _REQUEST_BUDGET_STATUS.get(status, "Included in Request")
            )
    return labels


def verification_label(activity_status: str, ia_status: str) -> str:
    """My Plan's "Verification" as a supervisor reads it."""
    if (
        activity_status in ("ia_verified", "accountant_confirmed", "closed")
        or ia_status == "confirmed"
    ):
        return "Verified"
    if (
        activity_status in ("returned_by_pl", "returned_by_ia")
        or ia_status == "returned"
    ):
        return "Returned"
    return "IA pending"


def activity_label(activity_type: str) -> str:
    """The activity type as the plan names it ("School Visit")."""
    from django.utils.encoding import force_str

    from apps.activities.models import Activity

    choices = dict(Activity._meta.get_field("activity_type").flatchoices)
    return force_str(
        choices.get(activity_type) or str(activity_type or "").replace("_", " ").title()
    )
