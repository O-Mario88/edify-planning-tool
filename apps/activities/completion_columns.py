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
}


def is_officer_completed(status) -> bool:
    return (status or "") in OFFICER_COMPLETED_STATUSES


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


def completion_records(activity_ids) -> tuple[dict[str, str], dict[str, set]]:
    """Each activity's stored Salesforce ID, and the kinds of evidence
    uploaded for it (not quarantined): two queries for any number of ids."""
    ids = [i for i in dict.fromkeys(activity_ids or ()) if i]
    if not ids:
        return {}, {}
    from apps.activities.models import Activity
    from apps.evidence.models import EvidenceRecord

    salesforce = {
        activity_id: (value or "").strip()
        for activity_id, value in Activity.objects.filter(id__in=ids).values_list(
            "id", "salesforce_activity_id"
        )
    }
    evidence: dict[str, set] = defaultdict(set)
    for activity_id, kind in EvidenceRecord.objects.filter(
        activity_id__in=ids, quarantined=False
    ).values_list("activity_id", "kind"):
        evidence[activity_id].add(kind)
    return salesforce, evidence


def completion_columns(pairs) -> dict[str, dict]:
    """{activity id: {"salesforce_id", "evidence_label", "salesforce_ok",
    "evidence_ok"}} for (activity id, activity type) pairs. Ids that are None
    (a handover not yet scheduled) are skipped: they read EMPTY."""
    pairs = [(i, t) for i, t in pairs if i]
    salesforce, evidence = completion_records([i for i, _ in pairs])
    out = {}
    for activity_id, activity_type in pairs:
        kinds = evidence.get(activity_id, set())
        sf = salesforce.get(activity_id, "")
        out[activity_id] = {
            "salesforce_id": sf,
            "evidence_label": evidence_label(activity_type, kinds),
            "salesforce_ok": bool(sf),
            "evidence_ok": expected_evidence(activity_type)[0] in kinds,
        }
    return out


def completion_fields(status, columns: dict) -> dict:
    """The columns plus the verdict for one row: `is_complete`,
    `completion_gap`, and `shows_complete` — whether the Actions column may
    offer its complete state: a verified status, both columns green."""
    complete = is_complete(status, columns)
    return {
        **columns,
        "is_complete": complete,
        "completion_gap": completion_gap(status, columns),
        "shows_complete": complete and (status or "") in COMPLETED_WORK_STATUSES,
    }


def annotate(
    items,
    *,
    id_attr: str = "activity_id",
    type_attr: str = "activity_type",
    status_attr: str = "activity_status",
):
    """Set the columns, `is_complete` and `completion_gap` on service-layer
    items (the oversight dataclasses), two queries for the lot."""
    items = list(items)
    columns = completion_columns(
        (getattr(item, id_attr, None), getattr(item, type_attr, "")) for item in items
    )
    for item in items:
        values = completion_fields(
            getattr(item, status_attr, ""),
            columns.get(getattr(item, id_attr, None) or "", EMPTY),
        )
        for name, value in values.items():
            setattr(item, name, value)
    return items


def sort_completed_last(items, *, date_attr: str = "planned_date") -> None:
    """Sort annotated items in place: work that is not complete first by
    planned date, complete work at the bottom (completed_last_key)."""
    items.sort(
        key=lambda item: completed_last_key(
            getattr(item, "is_complete", False), getattr(item, date_attr, None)
        )
    )
