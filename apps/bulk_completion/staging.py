"""Stage an uploaded file: read it, match every line to its activity, and
classify it — before anything is completed.

A line is matched in this order, and never by guessing:

1. its Salesforce ID, when an activity already holds that ID;
2. its Edify Activity ID (the prefilled template carries it);
3. its School ID, narrowed by the type and the scheduled date given — and
   only when that leaves exactly one open activity of the upload's kind.
   Two visits to one school are two activities, so a School ID alone never
   makes two lines duplicates of each other.

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

from .columns import expected_headings, field_index, missing_columns
from .lines import Line, Verdict, merge_lines, read_lines, scheduled_day
from .models import BatchStatus, BulkCompletionBatch, BulkCompletionRow, RowStatus
from .rules import (
    KIND_TYPES,
    SALESFORCE_KIND,
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
    open_at_school: dict = field(default_factory=dict)

    def activity(self, pk):
        if pk in self.by_id:
            return self.by_id[pk]
        for holder in self.by_salesforce.values():
            if holder.pk == pk:
                return holder
        for group in self.open_at_school.values():
            for candidate in group:
                if candidate.pk == pk:
                    return candidate
        return None


def _lookups(principal, kind: str, lines: list[Line]) -> _Lookups:
    from apps.activities.models import ActivitySalesforceReference

    reach = activities_in_reach(principal).select_related("school", "cluster")
    ids = {line.activity_id for line in lines if line.activity_id}
    salesforce = {line.salesforce_id for line in lines if line.salesforce_id}
    codes = {line.school_code for line in lines if line.school_code}
    for line in lines:
        codes.update(line.participants)

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
    school_pks = {
        found.schools[line.school_code].pk
        for line in lines
        if not line.activity_id and line.school_code in found.schools
    }
    if school_pks:
        for activity in reach.filter(
            school_id__in=school_pks, activity_type__in=KIND_TYPES[kind]
        ):
            if is_open(activity):
                found.open_at_school.setdefault(activity.school_id, []).append(activity)
    return found


def describe(activity) -> str:
    where = activity.school.name if activity.school_id else ""
    if not where and activity.cluster_id:
        where = activity.cluster.name
    day = scheduled_day(activity)
    when = f" on {day:%d %b %Y}" if day else ""
    return f"{activity.get_activity_type_display()} at {where or 'no school'}{when}"


def _by_school(line: Line, found: _Lookups, kind: str):
    """(activity, problem) from the School ID, the type and the date."""
    school = found.schools.get(line.school_code)
    if school is None:
        if line.school_code in found.schools_outside:
            return None, (RowStatus.INVALID, "School is outside your country.")
        return None, (RowStatus.INVALID, "School ID is not in the School Directory.")
    candidates = list(found.open_at_school.get(school.pk, []))
    if line.activity_type:
        candidates = [a for a in candidates if a.activity_type == line.activity_type]
    if line.scheduled_on:
        candidates = [a for a in candidates if scheduled_day(a) == line.scheduled_on]
    noun = "visit" if kind == "visit" else "training"
    if not candidates:
        return None, (
            RowStatus.REVIEW,
            f"No open {noun} at {school.name} matches this line. Add its Edify "
            "Activity ID from the template.",
        )
    if len(candidates) > 1:
        return None, (
            RowStatus.REVIEW,
            f"{len(candidates)} open {noun}s at {school.name} match this line. "
            "Add the Edify Activity ID or the Scheduled Date so one is chosen.",
        )
    return candidates[0], None


def _resolve(line: Line, found: _Lookups, kind: str):
    """(activity, problem) for one line."""
    holder = found.by_salesforce.get(line.salesforce_id) if line.salesforce_id else None
    if holder is not None and is_called_off(holder):
        holder = None  # a cancelled activity gives its ID up when it is reused
    named = found.by_id.get(line.activity_id) if line.activity_id else None
    if line.activity_id and named is None:
        return None, (
            RowStatus.INVALID,
            "No activity with this Edify Activity ID is in your reach.",
        )
    if holder is not None:
        if holder.pk not in found.in_reach:
            return None, (
                RowStatus.REVIEW,
                "This Salesforce ID already belongs to an activity outside your "
                "country.",
            )
        if named is not None and named.pk != holder.pk:
            return None, (
                RowStatus.REVIEW,
                f"This Salesforce ID already belongs to another activity "
                f"({describe(holder)}).",
            )
        return holder, None
    if named is not None:
        return named, None
    if line.school_code:
        return _by_school(line, found, kind)
    return None, (RowStatus.INVALID, "Give the Edify Activity ID or the School ID.")


def _standing(activity, kind: str):
    """(status, message) when the activity is not one this line can complete."""
    from apps.core.fy import get_operational_fy

    if activity.activity_type not in KIND_TYPES[kind]:
        other = "training" if kind == "visit" else "school visit"
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
    from apps.activities.services import sf_kind_for_activity

    verdict = Verdict.matched(line, activity)
    if line.school_code and activity.school_id:
        if activity.school.school_id != line.school_code:
            return verdict.mark(
                RowStatus.REVIEW,
                f"The School ID does not match this activity's school "
                f"({activity.school.school_id}).",
            )
    standing = _standing(activity, kind)
    if standing:
        return verdict.mark(*standing)
    if is_partner(activity):
        problem = _partner_problem(activity, principal)
        if problem:
            return verdict.mark(RowStatus.REVIEW, problem)
    if sf_kind_for_activity(activity) is not None:
        # An ID already saved on the activity completes it as it stands.
        verdict.salesforce_id = verdict.salesforce_id or (
            activity.salesforce_activity_id or ""
        )
        if not verdict.salesforce_id:
            label = "School Visit ID" if kind == "visit" else "Training ID"
            return verdict.mark(
                RowStatus.REVIEW,
                f"The {label} is missing. Work is completed with its Salesforce ID.",
            )
    return verdict.mark(RowStatus.READY, "")


def classify(lines: list[Line], kind: str, principal) -> list[Verdict]:
    found = _lookups(principal, kind, lines)
    verdicts: list[Verdict] = []
    for line in lines:
        if line.problem:
            verdicts.append(Verdict.unmatched(line, *line.problem))
            continue
        activity, problem = _resolve(line, found, kind)
        if problem:
            verdicts.append(Verdict.unmatched(line, *problem))
            continue
        verdicts.append(_judge(line, activity, kind, principal))
    return merge_lines(verdicts, kind, found.activity, found.schools)


def _file_bytes(file) -> bytes:
    raw = file.read()
    return raw.encode("utf-8") if isinstance(raw, str) else raw


def stage_upload(file, kind: str, principal) -> BulkCompletionBatch:
    """Read, match and classify the file; store it as a staged batch."""
    from apps.schools.upload_service import _read_rows

    name = getattr(file, "name", "") or f"bulk-{kind}.xlsx"
    raw = _file_bytes(file)
    if not raw:
        raise BadRequest("The file is empty.")
    buffer = io.BytesIO(raw)
    buffer.name = name
    try:
        headers, cells = _read_rows(buffer)
    except BadRequest:
        raise
    except Exception as exc:  # a corrupt or mislabelled spreadsheet
        raise BadRequest(
            "The file could not be read. Upload the template as .xlsx or .csv."
        ) from exc
    if not headers:
        raise BadRequest("The file is empty — no heading row was found.")
    index = field_index(kind, headers)
    missing = missing_columns(kind, index)
    if missing:
        raise BadRequest(
            "Missing column(s): "
            + ", ".join(missing)
            + ". Download the template: its headings are "
            + ", ".join(expected_headings(kind))
            + "."
        )
    lines = read_lines(kind, headers, index, cells, SALESFORCE_KIND[kind])
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
