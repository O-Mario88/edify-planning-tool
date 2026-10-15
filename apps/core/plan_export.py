"""One layout for every export of planned work.

Owner, 2026-10-12: "for school visit export, i want the following column:
School ID, School Name, District, District type, Activity, Planned Date,
Executor, Purpose of Visit, Focus Intervention, Cost, Budget status,
Verification, Salesforce ID, Evidence, Status. For Training and Cluster
Meeting, I want the following columns: Cluster Name, District, District type,
Planned Date, Executor, Training, SSA Intervention, Participants, Cost,
Budget status, Verification, Salesforce ID, Evidence, Status."

Those are My Plan's own tables with a District Type beside the District, so
an export reads like the page it was taken from. The Evidence column the
owner named left the staff sheets on 2026-10-13 with the staff upload ("remove
the upload and use strictly visit ID and training IDs ... removing upload
evidence column from the tables as well"); it is commented out below, marked
UPLOAD-OFF. Partner Schedules keeps it: a partner's work is verified from its
uploaded form (owner, 2026-10-14). Owner, 2026-10-12, later:
"put visits on its sheet, group training on its sheet, cluster meetings on
its sheet, partner schedules on its sheet and the budget for those selected
activities in the last sheet and the budget should be fetched direct from
those planned activities." So a workbook holds, in this order: School
Visits, Group Trainings, Cluster Meetings, Partner Schedules (work handed to
a partner, whatever its kind), Other Activities (a district meeting, a field
event, a conference) and, last, Budget — the Budget page's Activity cost
plan laid out from the cost lines of exactly the activities on the sheets
before it (`budget_sheet`).

Each exporter hands over plain rows (`row(...)`); nothing here queries the
plan, so My Plan, Team and Country Planning Oversight and Cluster Oversight
cannot lay the same work out three ways.
"""

from __future__ import annotations

from collections.abc import Iterable

VISIT = "visit"
TRAINING = "training"
MEETING = "meeting"
PARTNER = "partner"
OTHER = "other"

MONEY = "#,##0"
DATE = "d mmm yyyy"

VISIT_SHEET = "School Visits"
TRAINING_SHEET = "Group Trainings"
MEETING_SHEET = "Cluster Meetings"
PARTNER_SHEET = "Partner Schedules"
OTHER_SHEET = "Other Activities"
BUDGET_SHEET = "Budget"

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
    # UPLOAD-OFF (owner, 2026-10-13): "Evidence",
    "Status",
)
#: The owner's Training / Cluster Meeting columns; both sheets share them.
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
    # UPLOAD-OFF (owner, 2026-10-13): "Evidence",
    "Status",
)
TRAINING_HEADERS = SESSION_HEADERS
MEETING_HEADERS = SESSION_HEADERS
#: Work a partner delivers: who the partner is, where, and the same tail.
PARTNER_HEADERS = (
    "Partner",
    "Activity",
    "School ID",
    "School Name",
    "Cluster Name",
    "District",
    "District Type",
    "Planned Date",
    "Training",
    "SSA Intervention",
    "Participants",
    "Cost (UGX)",
    "Budget Status",
    "Verification",
    "Salesforce ID",
    # A partner's work is verified from its uploaded form (owner, 2026-10-14),
    # so this sheet alone keeps the column.
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
    # UPLOAD-OFF (owner, 2026-10-13): "Evidence",
    "Status",
)
ALL_HEADERS = (
    VISIT_HEADERS,
    TRAINING_HEADERS,
    MEETING_HEADERS,
    PARTNER_HEADERS,
    OTHER_HEADERS,
)

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


def _day(value):
    """A planned date as a date, whether a row carries one or its ISO text."""
    import datetime as _dt

    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def row(kind: str, **fields) -> dict:
    """One exported activity. ``kind`` is VISIT, TRAINING, MEETING, PARTNER or
    OTHER; the fields are the cells: school_id, school_name, cluster_name,
    venue, district, district_type, activity, planned_date, executor, partner,
    purpose, intervention, training, participants, cost, budget_status,
    verification, salesforce_id, evidence, status — and ``activity_id``, which
    the Budget sheet reads the activity's cost lines by."""
    return {"kind": kind, **fields}


def _tail(r: dict, *, evidence: bool = False) -> list:
    """The cells every sheet ends with. `evidence` adds the Evidence cell: a
    partner's work is verified from its uploaded form, staff work asks for
    none (UPLOAD-OFF, owner 2026-10-13 and 2026-10-14)."""
    return [
        _number(r.get("cost")),
        _text(r.get("budget_status")),
        _text(r.get("verification")),
        _text(r.get("salesforce_id")),
        *([_text(r.get("evidence"))] if evidence else []),
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


def _partner(r: dict) -> list:
    return [
        _text(r.get("partner")) or _text(r.get("executor")),
        _text(r.get("activity")),
        _text(r.get("school_id")),
        _text(r.get("school_name")),
        _text(r.get("cluster_name")),
        *_place(r),
        r.get("planned_date") or "",
        _text(r.get("training")),
        _text(r.get("intervention")),
        _number(r.get("participants")),
        *_tail(r, evidence=True),
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
    (TRAINING, TRAINING_SHEET, TRAINING_HEADERS, _session),
    (MEETING, MEETING_SHEET, MEETING_HEADERS, _session),
    (PARTNER, PARTNER_SHEET, PARTNER_HEADERS, _partner),
    (OTHER, OTHER_SHEET, OTHER_HEADERS, _other),
)

SHEET_ORDER = (*(title for _, title, _, _ in _LAYOUTS), BUDGET_SHEET)


def budget_sheet(rows: Iterable[dict]) -> dict:
    # Owner, 2026-10-12, on the first version: "use the actual budget format
    # and use that exactly" — nothing of this sheet is written here; every
    # row, heading, style and the period line is the Budget export's.
    """The Budget page's Activity cost plan for exactly the activities on the
    sheets before it, from their own cost lines (owner, 2026-10-12: "the
    budget should be fetched direct from those planned activities").

    `budget_groups` and `cost_plan_sheet` are the Budget page's own ledger,
    so a figure here is the figure the page prints for the same activity: an
    item a row under a band per activity type, a subtotal each, a Grand total.
    An activity with no cost line (an online group training, an in-school
    training whose visit carries the day) adds nothing, as on the page.
    """
    from apps.accounts.models import User
    from apps.activities.models import ActivityScheduleCostLine
    from apps.budget.services import (
        _EXPORT_ACTIVITY_FIELDS,
        _EXPORT_LINE_FIELDS,
        budget_groups,
        cost_line_rows,
        cost_plan_sheet,
    )

    ids = list(
        dict.fromkeys(r.get("activity_id") for r in rows if r.get("activity_id"))
    )
    lines = []
    for start in range(0, len(ids), 5000):
        lines.extend(
            cost_line_rows(
                ActivityScheduleCostLine.objects.filter(
                    activity_id__in=ids[start : start + 5000],
                    activity__deleted_at__isnull=True,
                ).order_by("planned_date", "activity_id", "id"),
                _EXPORT_LINE_FIELDS,
                _EXPORT_ACTIVITY_FIELDS,
            )
        )
    names = dict(
        User.objects.filter(
            id__in={line.responsible_user for line in lines if line.responsible_user}
        ).values_list("id", "name")
    )
    # The Budget export's own period line ("Period: 1 Oct 2026 – 30 Sep
    # 2027"), over the days the exported activities are planned on, so the
    # sheet is the Budget's Activity cost plan word for word.
    days = sorted(d for d in (_day(r.get("planned_date")) for r in rows) if d)
    period_label = f"Period: {days[0]:%-d %b %Y} – {days[-1]:%-d %b %Y}" if days else ""
    sheet = cost_plan_sheet(budget_groups(lines, names), period_label=period_label)
    sheet["title"] = BUDGET_SHEET
    return sheet


def sheets(rows: Iterable[dict], *, budget: bool = True) -> list[dict]:
    """The workbook: a sheet a kind, each with its own columns, every sheet
    present so a reader sees an empty kind as empty rather than missing, and
    the Budget of those activities last."""
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
    if budget:
        out.append(budget_sheet(rows))
    return out


def csv_rows(rows: Iterable[dict]):
    """The same sheets as one CSV, for a link that still asks for one: each
    sheet's name, its heading row and its rows, a blank line between."""
    for sheet in sheets(rows):
        yield [sheet["title"]]
        if sheet["headers"]:
            yield sheet["headers"]
        yield from sheet["rows"]
        yield []


def tables_from_csv(lines: Iterable[list]) -> dict[str, list[dict]]:
    """`csv_rows` read back: ``{sheet name: [{heading: cell}]}``."""
    titles = {title for _, title, _, _ in _LAYOUTS}
    tables: dict[str, list[dict]] = {}
    title, headers = None, None
    for line in lines:
        if len(line) == 1 and line[0] == BUDGET_SHEET:
            # The ledger has no heading row; it is not a table of activities.
            title, headers = None, None
        elif len(line) == 1 and line[0] in titles:
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


def verification_label(
    activity_status: str, ia_status: str, *, lead_approves: bool = False
) -> str:
    """My Plan's "Verification", in its words (apps.my_plan.services
    .verification_label): "PL Approved" / "PL Pending" on a CCEO's or a lead's
    work (owner, 2026-10-15)."""
    if (
        activity_status in ("ia_verified", "accountant_confirmed", "closed")
        or ia_status == "confirmed"
    ):
        return "PL Approved" if lead_approves else "Verified"
    if (
        activity_status in ("returned_by_pl", "returned_by_ia")
        or ia_status == "returned"
    ):
        return "Returned"
    return "PL Pending" if lead_approves else "IA Pending"


def activity_label(activity_type: str) -> str:
    """The activity type as the plan names it ("School Visit")."""
    from django.utils.encoding import force_str

    from apps.activities.models import Activity

    choices = dict(Activity._meta.get_field("activity_type").flatchoices)
    return force_str(
        choices.get(activity_type) or str(activity_type or "").replace("_", " ").title()
    )
