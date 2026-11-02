"""One uploaded line: its parsed cells, its verdict, and the rules for lines
that name the same activity twice."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from apps.schools.upload_mapping import normalize_header

from .models import BulkCompletionRow, BulkKind, RowStatus


def scheduled_day(activity) -> date | None:
    if activity.planned_date:
        return activity.planned_date
    if activity.scheduled_date:
        from apps.core.clock import local_day

        return local_day(activity.scheduled_date)
    return None


@dataclass
class Line:
    row_number: int
    raw: dict
    activity_id: str = ""
    school_code: str = ""
    activity_type: str = ""
    scheduled_on: date | None = None
    salesforce_id: str = ""  # normalized
    completed_on: date | None = None
    teachers: int | None = None
    leaders: int | None = None
    participants: list[str] = field(default_factory=list)
    #: (status, message) when the line itself is unusable.
    problem: tuple[str, str] | None = None

    def refuse(self, message: str) -> None:
        if self.problem is None:
            self.problem = (RowStatus.INVALID, message)


def _type_index() -> dict[str, str]:
    from apps.core.enums import ActivityType

    index: dict[str, str] = {}
    for value, label in ActivityType.choices:
        index[normalize_header(value)] = value
        index[normalize_header(label)] = value
    return index


def _date(text: str):
    from apps.schools.upload_service import _parse_date

    return _parse_date(text) if text else None


def _count(line: Line, text: str, heading: str) -> int | None:
    if not text:
        return None
    try:
        value = int(float(text))
    except ValueError:
        line.refuse(f"{heading} must be a whole number.")
        return None
    if value < 0:
        line.refuse(f"{heading} cannot be negative.")
        return None
    return value


def _parse(line: Line, values: dict, salesforce_kind: str, types: dict) -> None:
    from apps.activities.salesforce import (
        accepted_forms,
        is_valid_new_entry,
        normalize_salesforce_id,
    )

    line.activity_id = values.get("activity_id", "")
    line.school_code = values.get("school_code", "")
    typed = values.get("activity_type", "")
    if typed:
        line.activity_type = types.get(normalize_header(typed), "")
        if not line.activity_type:
            line.refuse(f"Unknown type '{typed}'.")
    try:
        line.scheduled_on = _date(values.get("scheduled_on", ""))
    except ValueError:
        line.refuse("Scheduled Date is not a date (use YYYY-MM-DD).")
    raw_id = values.get("salesforce_id", "")
    line.salesforce_id = normalize_salesforce_id(raw_id)
    if line.salesforce_id and not is_valid_new_entry(
        line.salesforce_id, salesforce_kind
    ):
        line.refuse(f"Enter the Salesforce ID as {accepted_forms(salesforce_kind)}.")
    done = values.get("completed_on", "")
    if not done:
        line.refuse("Completion Date is missing.")
    else:
        try:
            line.completed_on = _date(done)
        except ValueError:
            line.refuse("Completion Date is not a date (use YYYY-MM-DD).")
        if line.completed_on and line.completed_on > timezone.localdate():
            line.refuse(
                "Completion Date is in the future: give the day the work was done."
            )
    line.teachers = _count(line, values.get("teachers", ""), "Teachers Attended")
    line.leaders = _count(line, values.get("leaders", ""), "School Leaders Attended")
    codes = re.split(r"[,;\s]+", values.get("participants", ""))
    line.participants = list(dict.fromkeys(code for code in codes if code))


def read_lines(kind, headers, index, cells, salesforce_kind) -> list[Line]:
    """Every line that carries anything; blank lines are dropped."""
    types = _type_index()
    lines: list[Line] = []
    for row_number, row in cells:
        if not any((cell or "").strip() for cell in row):
            continue
        raw = {
            heading: row[position] if position < len(row) else ""
            for position, heading in enumerate(headers)
            if heading
        }
        values = {
            name: (row[position] if position < len(row) else "").strip()
            for name, position in index.items()
        }
        line = Line(row_number=row_number, raw=raw)
        _parse(line, values, salesforce_kind, types)
        lines.append(line)
    return lines


@dataclass
class Verdict:
    line: Line
    status: str = RowStatus.REVIEW
    message: str = ""
    activity_id: str = ""
    school_code: str = ""
    salesforce_id: str = ""
    teachers: int | None = None
    leaders: int | None = None
    participants: list[str] = field(default_factory=list)

    @classmethod
    def unmatched(cls, line: Line, status: str, message: str) -> "Verdict":
        return cls(
            line=line,
            status=status,
            message=message,
            school_code=line.school_code,
            salesforce_id=line.salesforce_id,
        )

    @classmethod
    def matched(cls, line: Line, activity) -> "Verdict":
        return cls(
            line=line,
            activity_id=activity.pk,
            school_code=(
                activity.school.school_id if activity.school_id else line.school_code
            ),
            salesforce_id=line.salesforce_id,
            teachers=line.teachers,
            leaders=line.leaders,
            participants=list(line.participants),
        )

    def mark(self, status: str, message: str) -> "Verdict":
        self.status, self.message = status, message
        return self

    def as_row(self, batch) -> BulkCompletionRow:
        return BulkCompletionRow(
            batch=batch,
            row_number=self.line.row_number,
            status=self.status,
            message=self.message,
            activity_id=self.activity_id or "",
            school_code=self.school_code or "",
            salesforce_id=self.salesforce_id or "",
            completed_on=self.line.completed_on,
            teachers_attended=self.teachers,
            leaders_attended=self.leaders,
            participating_school_codes=self.participants,
            raw=self.line.raw,
        )


_COUNTED = (RowStatus.READY, RowStatus.ALREADY_COMPLETED)


def _same_salesforce_twice(verdicts: list[Verdict]) -> None:
    """One Salesforce ID given to two different activities in one file."""
    first: dict[str, Verdict] = {}
    for verdict in verdicts:
        if verdict.status != RowStatus.READY or not verdict.salesforce_id:
            continue
        earlier = first.setdefault(verdict.salesforce_id, verdict)
        if earlier is not verdict and earlier.activity_id != verdict.activity_id:
            verdict.mark(
                RowStatus.REVIEW,
                f"Row {earlier.line.row_number} gives this Salesforce ID to "
                "another activity.",
            )


def _second_mention(verdict: Verdict, earlier: Verdict, kind: str) -> None:
    """A later line naming an activity an earlier line already named."""
    row = earlier.line.row_number
    if earlier.status == RowStatus.ALREADY_COMPLETED:
        verdict.mark(RowStatus.DUPLICATE, f"Same activity as row {row}.")
        return
    if (
        verdict.salesforce_id
        and earlier.salesforce_id
        and verdict.salesforce_id != earlier.salesforce_id
    ):
        verdict.mark(
            RowStatus.REVIEW,
            f"Row {row} gives this activity Salesforce ID {earlier.salesforce_id}; "
            f"this line gives {verdict.salesforce_id}.",
        )
        return
    new_schools = [s for s in verdict.participants if s not in earlier.participants]
    if kind == BulkKind.TRAINING and new_schools:
        # One line per attending school: joined into the first line's register.
        earlier.participants.extend(new_schools)
        earlier.teachers = (earlier.teachers or 0) + (verdict.teachers or 0)
        earlier.leaders = (earlier.leaders or 0) + (verdict.leaders or 0)
        verdict.mark(RowStatus.MERGED, f"Joined to row {row}'s training.")
        return
    if verdict.participants:
        verdict.mark(
            RowStatus.DUPLICATE,
            f"The schools on this line are already listed for row {row}'s training.",
        )
        return
    verdict.mark(RowStatus.DUPLICATE, f"Same activity as row {row}.")


def _training_register(verdict: Verdict, activity, schools: dict) -> str:
    """Why a staff training's attendance cannot complete it, or ""."""
    if verdict.teachers is None and verdict.leaders is None:
        verdict.teachers = activity.teachers_attended
        verdict.leaders = activity.leaders_attended
    if (verdict.teachers or 0) + (verdict.leaders or 0) <= 0:
        return "Give the number of teachers or school leaders who attended."
    unknown = [code for code in verdict.participants if code not in schools]
    if unknown:
        return "Participating School IDs not found in your country: " + ", ".join(
            unknown
        )
    if activity.cluster_id:
        if not verdict.participants and not activity.attended_school_ids:
            return (
                "List the School IDs that attended this cluster or group "
                "training in Participating School IDs."
            )
        return ""
    if activity.school_id and verdict.participants:
        others = set(verdict.participants) - {activity.school.school_id}
        if others:
            return (
                "An in-school training is at one school; complete the other "
                "schools' trainings on their own lines."
            )
    return ""


def merge_lines(verdicts: list[Verdict], kind: str, activity_of, schools: dict):
    """Apply the in-file duplicate rules, then the training register checks."""
    _same_salesforce_twice(verdicts)
    first: dict[str, Verdict] = {}
    for verdict in verdicts:
        if verdict.status not in _COUNTED or not verdict.activity_id:
            continue
        earlier = first.setdefault(verdict.activity_id, verdict)
        if earlier is not verdict:
            _second_mention(verdict, earlier, kind)
    if kind != BulkKind.TRAINING:
        return verdicts
    for verdict in first.values():
        if verdict.status != RowStatus.READY:
            continue
        activity = activity_of(verdict.activity_id)
        if activity is None or activity.delivery_type == "partner":
            continue
        problem = _training_register(verdict, activity, schools)
        if problem:
            verdict.mark(RowStatus.REVIEW, problem)
        elif activity.paired_school_visit_id:
            verdict.message = (
                "Its paired school visit is completed with the school visit upload."
            )
    _follow_primaries(verdicts, first)
    return verdicts


def _follow_primaries(verdicts: list[Verdict], first: dict) -> None:
    """A joined line shares the fate of the line it joined."""
    for verdict in verdicts:
        if verdict.status != RowStatus.MERGED:
            continue
        primary = first.get(verdict.activity_id)
        if primary is not None and primary.status != RowStatus.READY:
            verdict.mark(
                primary.status,
                f"Row {primary.line.row_number}, which this line joins: "
                f"{primary.message}",
            )
