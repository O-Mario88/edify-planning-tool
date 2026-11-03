"""Stage an uploaded file: read it, match every line to its activity, and
classify it — before anything is completed.

A line names its activity by ``planned_activity_id`` alone (owner,
2026-11-03), and its school by ``school_id``:

* both must be in Edify, inside the uploader's country — an ID Edify does not
  hold makes the line invalid and is listed on the error report;
* a visit's, or an in-school training's, school_id must be its own school;
* a cluster or group training takes one line per participating school, each
  linked to the training when it completes.

Whatever cannot be matched with certainty is sent for review, with the
reason, and is not completed. The drawers that complete one activity at a
time are untouched: this is a second door into the same workflow.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from django.db import transaction

from apps.core.exceptions import BadRequest

from .columns import field_positions, headings, missing_columns
from .lines import Line, Verdict, merge_lines, read_lines, scheduled_day
from .models import BatchStatus, BulkCompletionBatch, BulkCompletionRow, RowStatus
from .rules import (
    KIND_TYPES,
    activities_in_reach,
    is_called_off,
    is_done,
    is_open,
    is_partner,
    schools_in_reach,
)

#: Lines in one file. A country's month of visits fits many times over; a
#: larger file is split so each upload previews and completes quickly.
MAX_ROWS = 5000


@dataclass
class _Lookups:
    """Everything the lines refer to, read once for the whole file."""

    by_id: dict = field(default_factory=dict)
    by_salesforce: dict = field(default_factory=dict)
    in_reach: set = field(default_factory=set)
    schools: dict = field(default_factory=dict)
    schools_outside: dict = field(default_factory=dict)

    def activity(self, pk):
        return self.by_id.get(pk)


def _lookups(principal, lines: list[Line]) -> _Lookups:
    from apps.activities.models import ActivitySalesforceReference

    reach = activities_in_reach(principal).select_related("school", "cluster")
    ids = {line.activity_id for line in lines if line.activity_id}
    salesforce = {line.salesforce_id for line in lines if line.salesforce_id}
    codes = {line.school_code for line in lines if line.school_code}

    found = _Lookups()
    found.by_id = reach.in_bulk(list(ids)) if ids else {}
    if salesforce:
        for ref in ActivitySalesforceReference.objects.filter(
            normalized_value__in=salesforce
        ).select_related("activity__school", "activity__cluster"):
            found.by_salesforce[ref.normalized_value] = ref.activity
        holders = [a.pk for a in found.by_salesforce.values()]
        found.in_reach = set(reach.filter(pk__in=holders).values_list("pk", flat=True))
    found.schools, found.schools_outside = schools_in_reach(principal, codes)
    return found


def describe(activity) -> str:
    where = activity.school.name if activity.school_id else ""
    if not where and activity.cluster_id:
        where = activity.cluster.name
    day = scheduled_day(activity)
    when = f" on {day:%d %b %Y}" if day else ""
    return f"{activity.get_activity_type_display()} at {where or 'no school'}{when}"


def _missing(line: Line, found: _Lookups) -> str:
    """Why the line's IDs are not ones Edify holds in the uploader's country,
    or "". Each ID it does not hold is noted for the error report. An empty
    cell is the line's own problem (lines._parse), not a missing ID."""
    problems = []
    if line.activity_id and line.activity_id not in found.by_id:
        line.missing_ids["planned_activity_id"] = line.activity_id
        problems.append(
            f"planned_activity_id {line.activity_id} is not a planned activity "
            "in your country."
        )
    if line.school_code and line.school_code not in found.schools:
        line.missing_ids["school_id"] = line.school_code
        where = (
            "is outside your country"
            if line.school_code in found.schools_outside
            else "is not in the School Directory"
        )
        problems.append(f"school_id {line.school_code} {where}.")
    return " ".join(problems)


def _resolve(line: Line, found: _Lookups):
    """(activity, problem) for one line."""
    missing = _missing(line, found)
    if missing:
        return None, (RowStatus.INVALID, missing)
    named = found.by_id[line.activity_id]
    holder = found.by_salesforce.get(line.salesforce_id)
    if holder is not None and is_called_off(holder):
        holder = None  # a cancelled activity gives its ID up when it is reused
    if holder is not None and holder.pk != named.pk:
        if holder.pk not in found.in_reach:
            return None, (
                RowStatus.REVIEW,
                "This Salesforce ID already belongs to an activity outside your "
                "country.",
            )
        return None, (
            RowStatus.REVIEW,
            f"This Salesforce ID already belongs to another activity "
            f"({describe(holder)}).",
        )
    return named, None


def _standing(activity, kind: str):
    """(status, message) when the activity is not one this line can complete."""
    from apps.core.fy import get_operational_fy

    if activity.activity_type not in KIND_TYPES[kind]:
        other = "Trainings" if kind == "visit" else "School Visits"
        return (
            RowStatus.INVALID,
            f"This activity is a {activity.get_activity_type_display()}; complete "
            f"it with the {other} upload.",
        )
    if is_done(activity):
        saved = activity.salesforce_activity_id or ""
        note = f" with Salesforce ID {saved}" if saved else ""
        return RowStatus.ALREADY_COMPLETED, f"Already completed{note}."
    if is_called_off(activity):
        return (
            RowStatus.INVALID,
            f"This activity is {activity.get_status_display().lower()}.",
        )
    if not is_open(activity):
        if is_partner(activity):
            return (
                RowStatus.REVIEW,
                "Partner work is completed once the partner has uploaded its "
                "form; it has not been handed in yet.",
            )
        return RowStatus.REVIEW, "This activity is not scheduled yet."
    if activity.fy > get_operational_fy():
        return (
            RowStatus.REVIEW,
            f"This activity is in FY {activity.fy}, which has not started.",
        )
    return None


def _partner_problem(activity, principal) -> str:
    from apps.activities.services import is_partner_ssa_support_activity
    from apps.core.permissions import RolePermissionService

    if is_partner_ssa_support_activity(activity):
        return (
            "SSA Support is completed from its Complete drawer, which records "
            "the scores with the Salesforce ID."
        )
    if not RolePermissionService.can_confirm_partner_activity(principal, activity):
        return "Impact Assessment or the monitoring staff member confirms partner work."
    return ""


def _judge(line: Line, activity, kind: str, principal) -> Verdict:
    """Where the matched activity stands, and whether this line completes it."""
    verdict = Verdict.matched(line, activity)
    # A visit, or an in-school training, is at one school; a cluster or
    # group training (no school of its own) links the schools its lines name.
    if activity.school_id and activity.school.school_id != line.school_code:
        return verdict.mark(
            RowStatus.REVIEW,
            f"school_id {line.school_code} is not this activity's school "
            f"({activity.school.school_id}).",
        )
    standing = _standing(activity, kind)
    if standing:
        return verdict.mark(*standing)
    if is_partner(activity):
        problem = _partner_problem(activity, principal)
        if problem:
            return verdict.mark(RowStatus.REVIEW, problem)
    return verdict.mark(RowStatus.READY, "")


def classify(lines: list[Line], kind: str, principal) -> list[Verdict]:
    found = _lookups(principal, lines)
    verdicts: list[Verdict] = []
    for line in lines:
        if line.problem:
            _missing(line, found)  # its unknown IDs still reach the report
            verdicts.append(Verdict.unmatched(line, *line.problem))
            continue
        activity, problem = _resolve(line, found)
        if problem:
            verdicts.append(Verdict.unmatched(line, *problem))
            continue
        verdicts.append(_judge(line, activity, kind, principal))
    return merge_lines(verdicts, kind, found.activity)


def _file_bytes(file) -> bytes:
    raw = file.read()
    return raw.encode("utf-8") if isinstance(raw, str) else raw


def _read_file(raw: bytes, name: str):
    from apps.schools.upload_service import _read_rows

    buffer = io.BytesIO(raw)
    buffer.name = name
    try:
        return _read_rows(buffer)
    except BadRequest:
        raise
    except Exception as exc:  # a corrupt or mislabelled spreadsheet
        raise BadRequest(
            "The file could not be read. Upload the template as .xlsx or .csv."
        ) from exc


def stage_upload(file, kind: str, principal) -> BulkCompletionBatch:
    """Read, match and classify the file; store it as a staged batch."""
    name = getattr(file, "name", "") or f"bulk-{kind}.xlsx"
    raw = _file_bytes(file)
    if not raw:
        raise BadRequest("The file is empty.")
    headers, cells = _read_file(raw, name)
    if not headers:
        raise BadRequest("The file is empty — no heading row was found.")
    positions = field_positions(kind, headers)
    missing = missing_columns(kind, positions)
    if missing:
        raise BadRequest(
            "Missing column(s): "
            + ", ".join(missing)
            + ". The file needs these columns (any others are ignored): "
            + ", ".join(headings(kind))
            + "."
        )
    lines = read_lines(kind, headers, positions, cells)
    if not lines:
        raise BadRequest("The file has headings but no lines to complete.")
    if len(lines) > MAX_ROWS:
        raise BadRequest(
            f"The file has {len(lines)} lines; upload at most {MAX_ROWS} at a "
            "time by splitting it into smaller files."
        )
    verdicts = classify(lines, kind, principal)
    with transaction.atomic():
        batch = BulkCompletionBatch.objects.create(
            kind=kind,
            file_name=name[:512],
            file_sha256=hashlib.sha256(raw).hexdigest(),
            uploaded_by=str(getattr(principal, "user_id", "") or principal.id),
            uploaded_by_role=getattr(principal, "active_role", "") or "",
            status=BatchStatus.STAGED,
            total_rows=len(lines),
        )
        BulkCompletionRow.objects.bulk_create(
            [verdict.as_row(batch) for verdict in verdicts], batch_size=500
        )
    _log(batch, "bulk_completion.uploaded")
    return batch


def cancel_batch(batch: BulkCompletionBatch, principal) -> bool:
    """Withdraw a staged upload before it is confirmed: nothing was, or will
    be, completed from it. False when it had already been confirmed."""
    cancelled = BulkCompletionBatch.objects.filter(
        pk=batch.pk, status=BatchStatus.STAGED
    ).update(status=BatchStatus.CANCELLED)
    if cancelled:
        _log(
            batch,
            "bulk_completion.cancelled",
            {"by": str(getattr(principal, "user_id", "") or principal.id)},
        )
    return bool(cancelled)


def _log(batch, action: str, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="BulkCompletionBatch",
        subject_id=batch.id,
        actor_id=batch.uploaded_by,
        actor_role=batch.uploaded_by_role,
        payload={
            "kind": batch.kind,
            "file": batch.file_name,
            "sha256": batch.file_sha256,
            "rows": batch.total_rows,
            **(payload or {}),
        },
    )
