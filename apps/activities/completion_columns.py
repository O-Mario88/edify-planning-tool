"""The two completion columns, and what "complete" means, on every planned
activities table (owner, 2026-09-26).

Completing an activity has two halves: the Salesforce ID, and the uploaded
form — the visit form for a school visit, the attendance register for a
group training or a cluster meeting. Every planned activities table on My
Plan, the oversight pages and the Programme Lead's week shows both, in the
same words:

* Salesforce ID — the stored ID as entered (SVE- for a visit, TS- for a
  training or meeting; apps.activities.salesforce validates the prefix at
  entry), green; or "Not in SF".
* Evidence — "Visit Form" or "Attendance" once that form is uploaded, green;
  the kinds uploaded when it is other evidence (amber: there, but not the
  form), so a file that is there is never reported missing; or "No Evidence
  Uploaded". Evidence counts the way completion counts it: any record not
  quarantined.

An activity is complete only when its status says the officer finished it
(the evidence and Salesforce ID handed on — `submitted_to_pl`,
`awaiting_ia_verification` — or verified) AND both columns are green (owner,
2026-09-26: "the action and status are only complete if the Salesforce
column has the Salesforce ID and the Evidence column has the upload, and are
both green"). A status that says done over a missing half reads what is
missing instead ("Missing Salesforce ID", "Missing evidence", or "Not
Complete" when neither is in) and never offers the complete action.

And one order: work that is not complete first, by planned date oldest
first (undated last among it); complete work at the bottom, in the same
order.

A read: it owns no table and writes nothing. Two queries answer a page of
rows, however many there are.

UPLOAD-OFF (owner, 2026-10-13: "remove the upload and use strictly visit ID
and training IDs to complete the activities"; 2026-10-14: "Only staff dont
need to upload. partners HAVE to upload because that is how we verify their
work"). The form is the second half of completing for a PARTNER's work only.
Staff work is complete with its Salesforce ID: its `evidence_ok` is always
True, its `evidence_label` blank, no file is read for it, and the staff
tables no longer draw the Evidence column (components/completion_cells.html
draws it only where a table asks, which the partner tables do). The switch
is apps.evidence.form_document.takes_upload.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
)

#: The status says the officer finished: evidence uploaded and Salesforce ID
#: entered, whether the work now waits on the Programme Lead, on Impact
#: Assessment, or is verified. Complete also needs both halves present.
OFFICER_COMPLETED_STATUSES = frozenset(
    ("submitted_to_pl", "awaiting_ia_verification", *COMPLETED_WORK_STATUSES)
)

#: Done before its planned day (owner, 2026-10-14: "the activities finished
#: early should be taken off the calendar and on My Plan tables, planning
#: oversight marked complete so we can be able to track"). The calendar leaves
#: every completed activity off (OFFICER_COMPLETED_STATUSES).
FINISHED_EARLY = "Completed Early"

NOT_IN_SF = "Not in SF"
NO_EVIDENCE = "No Evidence Uploaded"
MISSING_SF = "Missing Salesforce ID"
MISSING_EVIDENCE = "Missing evidence"
#: Neither half in (owner, 2026-09-26: reads "Not Complete").
MISSING_BOTH = "Not Complete"

_ATTENDANCE_TYPES = frozenset((*TRAINING_TYPES, *CLUSTER_MEETING_TYPES))

EMPTY = {
    "salesforce_id": "",
    "evidence_label": "",
    "salesforce_ok": False,
    "evidence_ok": False,
    "early_on": None,
}


def is_officer_completed(status) -> bool:
    return (status or "") in OFFICER_COMPLETED_STATUSES


def delivered_day(actual_delivery_date, execution_started_at) -> date | None:
    """The day the work was done: the delivery date the officer recorded, or
    else the day they pressed Complete — the day Country Execution reads too
    (apps.planning.country_execution.dataset)."""
    if actual_delivery_date:
        return actual_delivery_date
    if execution_started_at is None:
        return None
    from django.utils import timezone

    if timezone.is_aware(execution_started_at):
        return timezone.localtime(execution_started_at).date()
    return execution_started_at.date()


def early_day(
    planned_date, scheduled_date, actual_delivery_date, execution_started_at
) -> date | None:
    """The day the work was done when that is before its planned day, else
    None. Whether it is finished is the status's question (finished_early)."""
    from django.utils import timezone

    planned = planned_date or (
        timezone.localtime(scheduled_date).date() if scheduled_date else None
    )
    done = delivered_day(actual_delivery_date, execution_started_at)
    return done if planned and done and done < planned else None


#: A row's state, drawn as the whole row's ink (owner, 2026-10-14: "All
#: completed activities, visit, trainings, cluster meetings should be in green
#: the entire row. and overdue in red, not yet due in normal black color on
#: light mode and white on blue and dark mode"). The template writes
#: data-done / data-overdue on the <tr>; components/row-state.css colours it.
ROW_DONE = "done"
ROW_OVERDUE = "overdue"

#: Work that is off the plan or sent back is neither late nor done.
_NEVER_OVERDUE = frozenset(
    (
        "returned",
        "returned_by_pl",
        "returned_by_ia",
        "cancelled",
        "rejected",
        "deferred",
        "not_planned",
        "awaiting_owner_approval",
    )
)


def row_state(status, planned_day, today: date | None = None) -> str:
    """ROW_DONE for completed work (the calendar leaves it off), ROW_OVERDUE
    for work whose planned day has passed and that is not done, "" for the
    rest — work still ahead, today's included."""
    if is_officer_completed(status):
        return ROW_DONE
    if (status or "") in _NEVER_OVERDUE or planned_day is None:
        return ""
    if today is None:
        from django.utils import timezone

        today = timezone.localdate()
    return ROW_OVERDUE if planned_day < today else ""


def is_complete(status, columns: dict) -> bool:
    """Done by status, with the Salesforce ID and the form both in."""
    return bool(
        is_officer_completed(status)
        and columns.get("salesforce_ok")
        and columns.get("evidence_ok")
    )


def completion_gap(status, columns: dict) -> str:
    """What a status that says done is still missing, or "" — the Status
    column reads this in place of any complete label."""
    if not is_officer_completed(status):
        return ""
    sf, evidence = columns.get("salesforce_ok"), columns.get("evidence_ok")
    if sf and evidence:
        return ""
    if not sf and not evidence:
        return MISSING_BOTH
    return MISSING_SF if not sf else MISSING_EVIDENCE


def completed_last_key(complete: bool, planned_date: date | None) -> tuple:
    """Work that is not complete first, oldest planned date first, undated
    last among it; complete work after, in the same order. Stable: rows that
    tie keep the order they arrived in."""
    return (bool(complete), planned_date is None, planned_date or date.max)


def expected_evidence(activity_type) -> tuple[str, str]:
    """(kind, label) of the form an activity is completed with."""
    if (activity_type or "") in _ATTENDANCE_TYPES:
        return "attendance_form", "Attendance"
    return "visit_form", "Visit Form"


def evidence_label(activity_type, kinds: Iterable[str]) -> str:
    """The Evidence column's words, blank when nothing is uploaded (the
    templates then say NO_EVIDENCE)."""
    kinds = set(kinds or ())
    if not kinds:
        return ""
    expected, label = expected_evidence(activity_type)
    if expected in kinds:
        return label
    from apps.core.enums import EvidenceKind

    names = []
    for kind in sorted(kinds):
        try:
            names.append(EvidenceKind(kind).label)
        except ValueError:
            names.append(str(kind).replace("_", " ").capitalize())
    return ", ".join(names)


def _records(
    activity_ids, early: dict | None = None
) -> tuple[dict[str, str], dict[str, set], set[str]]:
    """Each activity's stored Salesforce ID; the kinds of evidence uploaded
    for the activities that are asked for an upload (not quarantined); and
    which activities those are. Two queries at most, one when none is asked.
    ``early``, when given, is filled with the day each activity was done
    where that is before its planned day (early_day)."""
    ids = [i for i in dict.fromkeys(activity_ids or ()) if i]
    if not ids:
        return {}, {}, set()
    from apps.activities.models import Activity
    from apps.evidence.models import EvidenceRecord

    salesforce: dict[str, str] = {}
    asked: set[str] = set()
    for (
        activity_id,
        value,
        delivery_type,
        planned_date,
        scheduled_date,
        actual_delivery_date,
        execution_started_at,
    ) in Activity.objects.filter(id__in=ids).values_list(
        "id",
        "salesforce_activity_id",
        "delivery_type",
        "planned_date",
        "scheduled_date",
        "actual_delivery_date",
        "execution_started_at",
    ):
        salesforce[activity_id] = (value or "").strip()
        if early is not None:
            early[activity_id] = early_day(
                planned_date, scheduled_date, actual_delivery_date, execution_started_at
            )
        # apps.evidence.form_document.takes_upload, read in bulk.
        if (delivery_type or "") == "partner":
            asked.add(activity_id)
    evidence: dict[str, set] = defaultdict(set)
    if asked:
        for activity_id, kind in EvidenceRecord.objects.filter(
            activity_id__in=asked, quarantined=False
        ).values_list("activity_id", "kind"):
            evidence[activity_id].add(kind)
    return salesforce, evidence, asked


def completion_records(activity_ids) -> tuple[dict[str, str], dict[str, set]]:
    """Each activity's stored Salesforce ID, and the kinds of evidence
    uploaded for it where it is asked for an upload (a partner's work)."""
    salesforce, evidence, _asked = _records(activity_ids)
    return salesforce, evidence


def completion_columns(pairs) -> dict[str, dict]:
    """{activity id: {"salesforce_id", "evidence_label", "salesforce_ok",
    "evidence_ok"}} for (activity id, activity type) pairs. Ids that are None
    (a handover not yet scheduled) are skipped: they read EMPTY."""
    pairs = [(i, t) for i, t in pairs if i]
    early: dict[str, date | None] = {}
    salesforce, evidence, asked = _records([i for i, _ in pairs], early)
    out = {}
    for activity_id, activity_type in pairs:
        kinds = evidence.get(activity_id, set())
        sf = salesforce.get(activity_id, "")
        # Staff work is complete with its Salesforce ID alone; a partner's
        # also needs the form it is verified from (UPLOAD-OFF, see above).
        upload_asked = activity_id in asked
        out[activity_id] = {
            "salesforce_id": sf,
            "evidence_label": (
                evidence_label(activity_type, kinds) if upload_asked else ""
            ),
            "salesforce_ok": bool(sf),
            "evidence_ok": (
                expected_evidence(activity_type)[0] in kinds if upload_asked else True
            ),
            "early_on": early.get(activity_id),
        }
    return out


def completion_fields(status, columns: dict) -> dict:
    """The columns plus the verdict for one row: `is_complete`,
    `completion_gap`, `shows_complete` — whether the Actions column may
    offer its complete state: a verified status, both columns green — and
    `finished_early`: complete, on a day before the one planned (the tables
    then read FINISHED_EARLY)."""
    complete = is_complete(status, columns)
    return {
        **columns,
        "is_complete": complete,
        "completion_gap": completion_gap(status, columns),
        "shows_complete": complete and (status or "") in COMPLETED_WORK_STATUSES,
        "finished_early": complete and columns.get("early_on") is not None,
    }


def annotate(
    items,
    *,
    id_attr: str = "activity_id",
    type_attr: str = "activity_type",
    status_attr: str = "activity_status",
):
    """Set the columns, `is_complete`, `completion_gap` and `row_state` on
    service-layer items (the oversight dataclasses), two queries for the lot."""
    items = list(items)
    columns = completion_columns(
        (getattr(item, id_attr, None), getattr(item, type_attr, "")) for item in items
    )
    from django.utils import timezone

    today = timezone.localdate()
    for item in items:
        status = getattr(item, status_attr, "")
        values = completion_fields(
            status, columns.get(getattr(item, id_attr, None) or "", EMPTY)
        )
        for name, value in values.items():
            setattr(item, name, value)
        item.row_state = row_state(status, getattr(item, "planned_date", None), today)
    return items


def sort_completed_last(items, *, date_attr: str = "planned_date") -> None:
    """Sort annotated items in place: work that is not complete first by
    planned date, complete work at the bottom (completed_last_key)."""
    items.sort(
        key=lambda item: completed_last_key(
            getattr(item, "is_complete", False), getattr(item, date_attr, None)
        )
    )
