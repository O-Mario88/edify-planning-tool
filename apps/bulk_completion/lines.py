"""One uploaded line: its parsed cells, its verdict, and the rules for lines
that name the same activity twice.

A line is a visit when it carries ``visit_sf_id`` and a training when it
carries ``training_sf_id``; both, or neither, is refused. A training is given
one line per participating school, so lines naming one training are joined:
its schools are linked to it and their counts added up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from .columns import heading_of
from .models import BulkCompletionRow, BulkKind, RowStatus

#: The upload a line of each kind belongs in, as the Upload Center names it.
UPLOAD_NAMES = {BulkKind.VISIT: "School Visits", BulkKind.TRAINING: "Trainings"}


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
    salesforce_id: str = ""  # normalized
    completed_on: date | None = None
    teachers: int | None = None
    leaders: int | None = None
    #: The school this line links to a training (one line a school).
    participants: list[str] = field(default_factory=list)
    #: (status, message) when the line itself is unusable.
    problem: tuple[str, str] | None = None
    #: {column heading: ID} for IDs Edify does not hold, for the error report.
    missing_ids: dict = field(default_factory=dict)

    def refuse(self, message: str) -> None:
        if self.problem is None:
            self.problem = (RowStatus.INVALID, message)


def _date(text: str):
    from apps.schools.upload_service import _parse_date

    return _parse_date(text) if text else None


def _count(line: Line, text: str, heading: str) -> int | None:
    if not text:
        line.refuse(f"{heading} is missing.")
        return None
    try:
        value = float(text)
    except ValueError:
        line.refuse(f"{heading} must be a whole number.")
        return None
    if value != int(value):
        line.refuse(f"{heading} must be a whole number.")
        return None
    if value < 0:
        line.refuse(f"{heading} cannot be negative.")
        return None
    return int(value)


def _salesforce_id(line: Line, values: dict, kind: str) -> None:
    """Which Salesforce ID the line carries, and whether it belongs here."""
    from apps.activities.salesforce import (
        accepted_forms,
        is_valid_new_entry,
        normalize_salesforce_id,
    )

    visit_id = values.get("visit_sf_id", "")
    training_id = values.get("training_sf_id", "")
    if visit_id and training_id:
        line.refuse("Give visit_sf_id or training_sf_id, not both.")
        return
    if not visit_id and not training_id:
        line.refuse("Give visit_sf_id or training_sf_id: both are empty.")
        return
    line_kind = BulkKind.VISIT if visit_id else BulkKind.TRAINING
    if line_kind != kind:
        given = "visit_sf_id" if visit_id else "training_sf_id"
        line.refuse(
            f"This line is a {'visit' if visit_id else 'training'} ({given}). "
            f"Upload it with the {UPLOAD_NAMES[line_kind]} upload."
        )
        return
    line.salesforce_id = normalize_salesforce_id(visit_id or training_id)
    if not is_valid_new_entry(line.salesforce_id, line_kind):
        column = "visit_sf_id" if visit_id else "training_sf_id"
        line.refuse(
            f"{column}: enter the Salesforce ID as {accepted_forms(line_kind)}."
        )


def _completed_on(line: Line, text: str) -> None:
    if not text:
        line.refuse("completed_date is missing.")
        return
    try:
        line.completed_on = _date(text)
    except ValueError:
        line.refuse("completed_date is not a date (use YYYY-MM-DD).")
        return
    if line.completed_on > timezone.localdate():
        line.refuse("completed_date is in the future: give the day the work was done.")


def _parse(line: Line, values: dict, kind: str) -> None:
    line.activity_id = values.get("activity_id", "")
    line.school_code = values.get("school_code", "")
    if not line.activity_id:
        line.refuse("planned_activity_id is missing.")
    if not line.school_code:
        line.refuse("school_id is missing.")
    _salesforce_id(line, values, kind)
    _completed_on(line, values.get("completed_on", ""))
    if kind == BulkKind.TRAINING:
        line.teachers = _count(
            line, values.get("teachers", ""), heading_of(kind, "teachers")
        )
        line.leaders = _count(
            line, values.get("leaders", ""), heading_of(kind, "leaders")
        )
        if line.school_code:
            line.participants = [line.school_code]


def read_lines(kind: str, headers: list, positions: dict, cells) -> list[Line]:
    """Every line that carries anything; blank lines are dropped."""
    from .columns import cell_values

    lines: list[Line] = []
    for row_number, row in cells:
        if not any(str(cell or "").strip() for cell in row):
            continue
        raw = {
            heading: row[position] if position < len(row) else ""
            for position, heading in enumerate(headers)
            if heading
        }
        line = Line(row_number=row_number, raw=raw)
        _parse(line, cell_values(row, positions), kind)
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
            # The ID as uploaded, so the preview shows what to put right.
            activity_id=line.activity_id,
            school_code=line.school_code,
            salesforce_id=line.salesforce_id,
        )

    @classmethod
    def matched(cls, line: Line, activity) -> "Verdict":
        return cls(
            line=line,
            activity_id=activity.pk,
            school_code=line.school_code,
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
            missing_ids=self.line.missing_ids,
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
    if verdict.salesforce_id != earlier.salesforce_id:
        verdict.mark(
            RowStatus.REVIEW,
            f"Row {row} gives this activity Salesforce ID {earlier.salesforce_id}; "
            f"this line gives {verdict.salesforce_id}.",
        )
        return
    new_schools = [s for s in verdict.participants if s not in earlier.participants]
    if kind == BulkKind.TRAINING and new_schools:
        # One line per participating school: joined into the first line.
        earlier.participants.extend(new_schools)
        earlier.teachers = (earlier.teachers or 0) + (verdict.teachers or 0)
        earlier.leaders = (earlier.leaders or 0) + (verdict.leaders or 0)
        verdict.mark(RowStatus.MERGED, f"Joined to row {row}'s training.")
        return
    if verdict.participants:
        verdict.mark(
            RowStatus.DUPLICATE,
            f"This school is already listed for row {row}'s training.",
        )
        return
    verdict.mark(RowStatus.DUPLICATE, f"Same activity as row {row}.")


def _training_register(verdict: Verdict) -> str:
    """Why a staff training's lines cannot complete it, or ""."""
    if (verdict.teachers or 0) + (verdict.leaders or 0) <= 0:
        return (
            "teachers_trained and school_leaders_trained add up to 0: a "
            "training is completed with who attended."
        )
    return ""


def merge_lines(verdicts: list[Verdict], kind: str, activity_of) -> list[Verdict]:
    """Apply the in-file duplicate rules, then the training count check."""
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
        problem = _training_register(verdict)
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
