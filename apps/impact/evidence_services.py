"""School evidence the SSA does not capture (IA review, owner, 2026-09-13).

The role description asks Impact Assessment to track change in student
outcomes, discipleship engagement and learning, not only the eight SSA
self-scores. The owner chose three measures IA captures (not classroom lesson
observations):

  Student learning results  class-level results — OneTest, national
                            examinations, the school's own assessments — with
                            no pupil names or records;
  Discipleship engagement   observable practice (devotions, active groups,
                            learners in groups, staff in devotions, a spiritual
                            lead, timetabled Bible lessons), read beside the
                            reviewed Most Significant Change stories
                            (apps.targets.mscs_review);
  EdTech rollout            what a school received, and later checks of whether
                            the units work, and whether teachers and learners
                            use them.

The rules every record follows:

  - Recorded by one person, confirmed by another. A record lands PENDING;
    a second Impact Assessment officer in the school's country confirms or
    returns it; where the recorder is the country's only IA officer, the
    Country Director confirms instead (apps.impact.review). Nobody confirms
    their own record. Only confirmed records count anywhere.
  - Country-bound. Every read and write goes through the reader's analytics
    scope (apps.core.scoping.scoped_school_queryset): IA and the Country
    Director see their country, Admin the deployment; summary-only readers see
    no school records.
  - Who records. Impact Assessment records on /ia/school-evidence/. The person
    who completed a OneTest diagnostic visit records that visit's class results
    from the visit itself (apps/frontend/views/ia_school_evidence_views.py), so
    results are linked to the delivery they came from.
  - Missing is not zero. A class result below MIN_LEARNERS learners, or a year
    with no confirmed result, is shown as withheld or not measured, never as a
    change of 0.

Reads are bulk: the registers, the summaries and the Outcomes figures take a
fixed number of queries whatever the number of records.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.metrics import percentage
from apps.core.rbac import EdifyRole

from .models import (
    DiscipleshipIndicatorRecord,
    EdTechAssetType,
    EdTechCheck,
    EdTechDeployment,
    EdTechFunding,
    EvidenceVerification,
    LearningAssessmentResult,
    LearningAssessmentType,
)

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value

LEARNING = "learning"
DISCIPLESHIP = "discipleship"
EDTECH = "edtech"
CHECK = "check"

MODELS = {
    LEARNING: LearningAssessmentResult,
    DISCIPLESHIP: DiscipleshipIndicatorRecord,
    EDTECH: EdTechDeployment,
    CHECK: EdTechCheck,
}
KIND_LABELS = {
    LEARNING: "Learning result",
    DISCIPLESHIP: "Discipleship record",
    EDTECH: "EdTech deployment",
    CHECK: "EdTech check",
}
#: The register tab each kind is listed on (an EdTech check sits with EdTech).
KIND_TAB = {
    LEARNING: LEARNING,
    DISCIPLESHIP: DISCIPLESHIP,
    EDTECH: EDTECH,
    CHECK: EDTECH,
}

PENDING = EvidenceVerification.PENDING.value
CONFIRMED = EvidenceVerification.CONFIRMED.value
RETURNED = EvidenceVerification.RETURNED.value
STATUS_LABELS = dict(EvidenceVerification.choices)
STATUS_TONES = {PENDING: "warning", CONFIRMED: "success", RETURNED: "danger"}

#: A class result from fewer learners than this is recorded and shown, but
#: never compared year on year: one absent child moves the mean too far.
MIN_LEARNERS = 10

#: Change in learning results has no approved threshold yet, so it follows the
#: one fallback of apps.ssa.change_rules: movement is movement, and says so.
LEARNING_RULE_LABEL = "Any change (no approved threshold)"

EVENT_RETURNED = "ia.school_evidence.returned"

#: Activity statuses that mean a OneTest visit took place.
DELIVERED_STATUSES = (
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
)

LEARNING_CSV_COLUMNS = (
    "school_id",
    "assessment_type",
    "assessed_on",
    "grade_level",
    "subject",
    "learners_tested",
    "mean_score",
    "max_score",
    "learners_proficient",
    "evidence_reference",
    "notes",
)
#: A file larger than this is refused before it is parsed.
MAX_CSV_ROWS = 2000


# ── Scope and authority ─────────────────────────────────────────────────────


def _uid(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def evidence_schools(principal):
    """The schools whose evidence `principal` may read: their analytics
    scope, and nothing for a summary-only reader."""
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.schools.models import School

    scope = resolve_user_scope(principal)
    if scope.can_view_summary_only:
        return School.objects.none()
    schools = scoped_school_queryset(scope)
    return schools if schools is not None else School.objects.none()


def visible(principal, kind: str):
    """Every non-deleted record of `kind` in the reader's scope."""
    model = MODELS[kind]
    return model.objects.filter(school__in=evidence_schools(principal))


def may_record(principal) -> bool:
    """Impact Assessment records school evidence on its page. The Country
    Director confirms where the country has one officer, never records."""
    return _role(principal) == IA


def _assert_may_record(principal) -> None:
    if not may_record(principal):
        raise Forbidden(
            "Only Impact Assessment records school evidence here. Field staff "
            "record OneTest results from the visit they completed."
        )


def school_country(school) -> str:
    region = getattr(school, "region", None)
    return (getattr(region, "country", "") or "").strip()


def is_onetest(activity) -> bool:
    """A OneTest diagnostic visit: the catalogue's OneTest costing profile,
    as recorded on the activity or read from its catalogue item."""
    if (getattr(activity, "costing_profile_snapshot", "") or "") == "ONETEST":
        return True
    item = getattr(activity, "catalogue_item", None)
    return (getattr(item, "costing_profile", "") or "") == "ONETEST"


def may_record_for_activity(principal, activity) -> bool:
    """Whoever may complete a delivered OneTest visit records its results."""
    from apps.core.permissions import RolePermissionService
    from apps.core.scoping import country_bound, resolve_user_scope

    if activity is None:
        return False
    scope = resolve_user_scope(principal)
    if country_bound(scope) and not (
        activity.school_id
        and evidence_schools(principal).filter(id=activity.school_id).exists()
    ):
        # A country role reads every activity; it records only its country's.
        return False
    return bool(
        activity is not None
        and activity.deleted_at is None
        and activity.school_id
        and is_onetest(activity)
        and activity.status in DELIVERED_STATUSES
        and RolePermissionService.can_view_record(principal, activity)
        and RolePermissionService.can_upload_evidence(principal, activity)
    )


def reviewer_basis(principal, record) -> str | None:
    from apps.impact.review import reviewer_basis as basis

    return basis(
        principal, author_id=record.recorded_by_user_id, country=record.country
    )


def _audit(action: str, record, principal, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=type(record).__name__,
        subject_id=str(record.id),
        actor_id=_uid(principal) or None,
        actor_role=_role(principal) or None,
        reason=(payload or {}).get("reason"),
        payload={
            "school_id": record.school_id,
            "country": record.country,
            "status": record.verification_status,
            **(payload or {}),
        },
    )


# ── Parsing ─────────────────────────────────────────────────────────────────


def _text(data, key, *, required=False, label="", max_length=None) -> str:
    value = str(data.get(key) or "").strip()
    if required and not value:
        raise BadRequest(f"{label or key.replace('_', ' ').capitalize()} is required.")
    if max_length and len(value) > max_length:
        raise BadRequest(
            f"{label or key.replace('_', ' ').capitalize()} is longer than "
            f"{max_length} characters."
        )
    return value


def _date(data, key, *, label, required=True, not_future=True):
    raw = str(data.get(key) or "").strip()
    if not raw:
        if required:
            raise BadRequest(f"{label} is required.")
        return None
    try:
        value = date.fromisoformat(raw[:10])
    except ValueError:
        raise BadRequest(f"{label} must be a date (YYYY-MM-DD).") from None
    if not_future and value > timezone.localdate():
        raise BadRequest(f"{label} cannot be in the future.")
    return value


def _int(data, key, *, label, required=False, minimum=0, maximum=None):
    raw = str(data.get(key) if data.get(key) is not None else "").strip()
    if raw == "":
        if required:
            raise BadRequest(f"{label} is required.")
        return None
    try:
        value = int(raw)
    except ValueError:
        raise BadRequest(f"{label} must be a whole number.") from None
    if value < minimum:
        raise BadRequest(f"{label} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise BadRequest(f"{label} must be at most {maximum}.")
    return value


def _decimal(data, key, *, label, minimum=Decimal("0"), maximum=None, places=2):
    raw = str(data.get(key) if data.get(key) is not None else "").strip()
    if raw == "":
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise BadRequest(f"{label} must be a number.") from None
    if not value.is_finite():
        raise BadRequest(f"{label} must be a number.")
    if value < minimum:
        raise BadRequest(f"{label} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise BadRequest(f"{label} must be at most {maximum}.")
    return value.quantize(Decimal(1).scaleb(-places))


def _tristate(data, key):
    raw = str(data.get(key) or "").strip().lower()
    if raw in ("yes", "true", "1"):
        return True
    if raw in ("no", "false", "0"):
        return False
    return None


def _choice(data, key, choices, *, label):
    value = str(data.get(key) or "").strip()
    if value not in {c for c, _ in choices}:
        raise BadRequest(f"Choose a {label.lower()}.")
    return value


def find_school(principal, code: str):
    """A school in the reader's scope by its directory id (or record id)."""
    code = (code or "").strip()
    if not code:
        raise BadRequest("School ID is required.")
    school = (
        evidence_schools(principal)
        .select_related("region")
        .filter(Q(school_id=code) | Q(id=code))
        .first()
    )
    if school is None:
        raise BadRequest(f"No school with ID {code} is in your country.")
    return school


def _learning_fields(data) -> dict:
    learners = _int(
        data, "learners_tested", label="Learners tested", required=True, minimum=1
    )
    mean = _decimal(data, "mean_score", label="Mean score")
    maximum = _decimal(
        data, "max_score", label="Maximum score", minimum=Decimal("0.01")
    )
    proficient = _int(data, "learners_proficient", label="Learners proficient")
    if mean is None and proficient is None:
        raise BadRequest(
            "Record a mean score or the number of learners proficient — a result "
            "needs at least one of them."
        )
    if mean is not None and maximum is not None and mean > maximum:
        raise BadRequest("The mean score cannot be above the maximum score.")
    if proficient is not None and proficient > learners:
        raise BadRequest("Learners proficient cannot exceed learners tested.")
    return {
        "assessment_type": _choice(
            data,
            "assessment_type",
            LearningAssessmentType.choices,
            label="Assessment type",
        ),
        "assessed_on": _date(data, "assessed_on", label="Assessment date"),
        "grade_level": _text(
            data, "grade_level", required=True, label="Class or grade", max_length=32
        ),
        "subject": _text(
            data, "subject", required=True, label="Subject", max_length=64
        ),
        "learners_tested": learners,
        "mean_score": mean,
        "max_score": maximum,
        "learners_proficient": proficient,
    }


def _discipleship_fields(data) -> dict:
    fields = {
        "observed_on": _date(data, "observed_on", label="Observed on"),
        "devotions_per_week": _int(
            data, "devotions_per_week", label="Devotions per week", maximum=35
        ),
        "discipleship_groups_active": _int(
            data, "discipleship_groups_active", label="Active discipleship groups"
        ),
        "learners_in_groups": _int(
            data, "learners_in_groups", label="Learners in discipleship groups"
        ),
        "learners_enrolled": _int(data, "learners_enrolled", label="Learners enrolled"),
        "staff_in_devotions_pct": _int(
            data,
            "staff_in_devotions_pct",
            label="Staff in devotions (%)",
            maximum=100,
        ),
        "spiritual_lead_in_post": _tristate(data, "spiritual_lead_in_post"),
        "bible_lessons_timetabled": _tristate(data, "bible_lessons_timetabled"),
    }
    indicators = [v for k, v in fields.items() if k != "observed_on"]
    if all(v is None for v in indicators):
        raise BadRequest("Record at least one discipleship indicator.")
    if (
        fields["learners_in_groups"] is not None
        and fields["learners_enrolled"] is not None
        and fields["learners_in_groups"] > fields["learners_enrolled"]
    ):
        raise BadRequest("Learners in groups cannot exceed learners enrolled.")
    return fields


def _deployment_fields(data) -> dict:
    from apps.projects.models import Project

    project = None
    project_id = str(data.get("project") or "").strip()
    if project_id:
        project = Project.objects.filter(id=project_id).first()
        if project is None:
            raise BadRequest("Choose a project from the list.")
    fields = {
        "asset_type": _choice(
            data, "asset_type", EdTechAssetType.choices, label="Technology"
        ),
        "quantity": _int(data, "quantity", label="Quantity", required=True, minimum=1),
        "deployed_on": _date(data, "deployed_on", label="Deployed on"),
        "funding": _choice(data, "funding", EdTechFunding.choices, label="Funding"),
        "project": project,
        "teachers_trained": _int(data, "teachers_trained", label="Teachers trained"),
        "learners_with_access": _int(
            data, "learners_with_access", label="Learners with access"
        ),
    }
    if fields["funding"] == EdTechFunding.PROJECT and project is None:
        raise BadRequest("Name the special project that funded this technology.")
    return fields


def _check_fields(data, deployment) -> dict:
    fields = {
        "checked_on": _date(data, "checked_on", label="Checked on"),
        "units_functional": _int(
            data, "units_functional", label="Units working", required=True
        ),
        "teachers_using": _int(data, "teachers_using", label="Teachers using"),
        "learners_using": _int(data, "learners_using", label="Learners using"),
        "weekly_use_hours": _decimal(
            data,
            "weekly_use_hours",
            label="Hours of use per week",
            maximum=Decimal("168"),
            places=1,
        ),
        "issues": _text(data, "issues", max_length=4000),
    }
    if fields["units_functional"] > deployment.quantity:
        raise BadRequest(
            f"Units working cannot exceed the {deployment.quantity} deployed."
        )
    if fields["checked_on"] < deployment.deployed_on:
        raise BadRequest("A check cannot be dated before the deployment.")
    return fields


_FIELD_PARSERS = {
    LEARNING: _learning_fields,
    DISCIPLESHIP: _discipleship_fields,
    EDTECH: _deployment_fields,
}


def _duplicate_learning(school, fields, *, exclude_id=None) -> bool:
    rows = LearningAssessmentResult.objects.filter(
        school=school,
        assessment_type=fields["assessment_type"],
        assessed_on=fields["assessed_on"],
        grade_level__iexact=fields["grade_level"],
        subject__iexact=fields["subject"],
    )
    if exclude_id:
        rows = rows.exclude(id=exclude_id)
    return rows.exists()


def _dated(kind: str, fields: dict):
    return fields.get(
        {
            LEARNING: "assessed_on",
            DISCIPLESHIP: "observed_on",
            EDTECH: "deployed_on",
            CHECK: "checked_on",
        }[kind]
    )


# ── Writes ──────────────────────────────────────────────────────────────────


def record(principal, kind: str, data, *, source_activity=None):
    """Record one piece of school evidence, pending verification.

    Impact Assessment records for any school in its country. With
    `source_activity` (a delivered OneTest visit) the person who may complete
    that visit records its learning results, for that visit's school only.
    """
    if kind not in _FIELD_PARSERS:
        raise BadRequest("Unknown evidence type.")
    if source_activity is not None:
        if kind != LEARNING or not may_record_for_activity(principal, source_activity):
            raise Forbidden(
                "Learning results are recorded from a delivered OneTest visit by "
                "someone who may complete it."
            )
        from apps.schools.models import School

        school = School.objects.select_related("region").get(
            id=source_activity.school_id
        )
    else:
        _assert_may_record(principal)
        school = find_school(principal, data.get("school_id"))
    fields = _FIELD_PARSERS[kind](data)
    if kind == LEARNING and _duplicate_learning(school, fields):
        raise BadRequest(
            "This school already has a result for that assessment, date, class "
            "and subject. Correct the existing record instead."
        )
    model = MODELS[kind]
    with transaction.atomic():
        row = model.objects.create(
            school=school,
            country=school_country(school),
            fy=get_operational_fy(_dated(kind, fields)),
            source_activity=source_activity,
            evidence_reference=_text(data, "evidence_reference", max_length=512),
            notes=_text(data, "notes", max_length=4000),
            recorded_by_user_id=_uid(principal),
            verification_status=PENDING,
            **fields,
        )
        _audit(
            f"ia.school_evidence.{kind}_recorded",
            row,
            principal,
            {"source_activity_id": getattr(source_activity, "id", None)},
        )
    return row


def record_check(principal, deployment_id: str, data):
    """A later check of a confirmed deployment: do the units work, and do
    teachers and learners use them."""
    _assert_may_record(principal)
    deployment = (
        visible(principal, EDTECH)
        .select_related("school__region")
        .filter(id=deployment_id)
        .first()
    )
    if deployment is None:
        raise NotFoundError("That deployment is not in your country.")
    if deployment.verification_status != CONFIRMED:
        raise BadRequest(
            "Check a deployment once it is confirmed; until then its quantity "
            "and date may still change."
        )
    fields = _check_fields(data, deployment)
    with transaction.atomic():
        row = EdTechCheck.objects.create(
            deployment=deployment,
            school_id=deployment.school_id,
            country=deployment.country,
            fy=get_operational_fy(fields["checked_on"]),
            evidence_reference=_text(data, "evidence_reference", max_length=512),
            notes=_text(data, "notes", max_length=4000),
            recorded_by_user_id=_uid(principal),
            verification_status=PENDING,
            **fields,
        )
        _audit("ia.school_evidence.check_recorded", row, principal)
    return row


def _own_open_record(principal, kind: str, record_id: str):
    row = (
        MODELS[kind]
        .objects.select_for_update()
        .filter(id=record_id, recorded_by_user_id=_uid(principal))
        .first()
    )
    if row is None:
        raise NotFoundError("That record is not one you recorded.")
    if row.verification_status == CONFIRMED:
        raise BadRequest("A confirmed record can no longer be changed.")
    return row


def correct(principal, kind: str, record_id: str, data):
    """The recorder corrects a pending or returned record; it goes back to
    pending for a verifier."""
    with transaction.atomic():
        row = _own_open_record(principal, kind, record_id)
        if kind == CHECK:
            fields = _check_fields(data, row.deployment)
        else:
            fields = _FIELD_PARSERS[kind](data)
        if kind == LEARNING and _duplicate_learning(
            row.school, fields, exclude_id=row.id
        ):
            raise BadRequest(
                "This school already has a result for that assessment, date, class "
                "and subject."
            )
        for key, value in fields.items():
            setattr(row, key, value)
        row.fy = get_operational_fy(_dated(kind, fields))
        row.evidence_reference = _text(data, "evidence_reference", max_length=512)
        row.notes = _text(data, "notes", max_length=4000)
        was_returned = row.verification_status == RETURNED
        row.verification_status = PENDING
        row.return_reason = ""
        row.verified_by_user_id = None
        row.verified_at = None
        row.save()
        _audit(
            f"ia.school_evidence.{kind}_corrected",
            row,
            principal,
            {"was_returned": was_returned},
        )
    _resolve_returned_notice(row)
    return row


def withdraw(principal, kind: str, record_id: str):
    """The recorder withdraws a record nobody has confirmed (a soft delete:
    the row and its audit trail stay)."""
    with transaction.atomic():
        row = _own_open_record(principal, kind, record_id)
        row.soft_delete()
        _audit(f"ia.school_evidence.{kind}_withdrawn", row, principal)
    _resolve_returned_notice(row)
    return row


def decide(principal, kind: str, record_id: str, *, decision: str, reason: str = ""):
    """Confirm or return a pending record. The verifier is never the recorder:
    a second IA officer in the school's country, or the Country Director where
    the recorder is that country's only officer."""
    from apps.impact.review import assert_can_review

    if decision not in ("confirm", "return"):
        raise BadRequest("Choose confirm or return.")
    reason = (reason or "").strip()
    if decision == "return" and not reason:
        raise BadRequest("Say what the recorder needs to correct.")
    with transaction.atomic():
        row = (
            visible(principal, kind)
            .select_for_update(of=("self",))
            .filter(id=record_id)
            .first()
        )
        if row is None:
            raise NotFoundError("That record is not in your country.")
        if row.verification_status != PENDING:
            raise BadRequest(
                f"This record is already {STATUS_LABELS[row.verification_status].lower()}."
            )
        basis = assert_can_review(
            principal, author_id=row.recorded_by_user_id, country=row.country
        )
        row.verified_by_user_id = _uid(principal)
        row.verified_at = timezone.now()
        if decision == "confirm":
            row.verification_status = CONFIRMED
            row.return_reason = ""
        else:
            row.verification_status = RETURNED
            row.return_reason = reason[:4000]
        row.save(
            update_fields=[
                "verification_status",
                "verified_by_user_id",
                "verified_at",
                "return_reason",
                "updated_at",
            ]
        )
        _audit(
            f"ia.school_evidence.{kind}_{'confirmed' if decision == 'confirm' else 'returned'}",
            row,
            principal,
            {"review_basis": basis, "reason": reason or None},
        )
    if decision == "return":
        _notify_returned(row, kind)
    else:
        _resolve_returned_notice(row)
    return row


def _notice_context(row) -> tuple[str, str]:
    """Where the recorder corrects it: a OneTest visit's results on the visit,
    everything else on the School Evidence page."""
    if getattr(row, "source_activity_id", None):
        return "OneTestActivity", str(row.source_activity_id)
    return type(row).__name__, str(row.id)


def _notify_returned(row, kind: str) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        context_type, context_id = _notice_context(row)
        WorkflowNotificationService.trigger(
            event_type=EVENT_RETURNED,
            category="ia",
            priority="high",
            title=f"{KIND_LABELS[kind]} returned for correction",
            body=f"{row.school.name}: {row.return_reason}"[:500],
            context_type=context_type,
            context_id=context_id,
            recipients=[row.recorded_by_user_id],
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the decision
        pass


def _resolve_returned_notice(row) -> None:
    try:
        from apps.notifications.services import resolve_condition

        context_type, context_id = _notice_context(row)
        resolve_condition(EVENT_RETURNED, context_type, context_id)
    except Exception:  # noqa: BLE001 - housekeeping only
        pass


def upload_learning_csv(principal, uploaded) -> dict:
    """Record every row of a learning results CSV, or none of them.

    Columns: LEARNING_CSV_COLUMNS. Each row is validated exactly as the drawer
    validates one result, against schools in the uploader's country; a file
    with any invalid row records nothing and lists the rows to fix.
    """
    _assert_may_record(principal)
    if uploaded is None:
        raise BadRequest("Choose a CSV file to upload.")
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BadRequest("The file must be a UTF-8 CSV.") from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [
        c
        for c in (
            "school_id",
            "assessment_type",
            "assessed_on",
            "grade_level",
            "subject",
            "learners_tested",
        )
        if c not in headers
    ]
    if missing:
        raise BadRequest(f"The file is missing the column(s): {', '.join(missing)}.")
    rows = [
        {str(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        for row in reader
    ]
    if not rows:
        raise BadRequest("The file has no result rows.")
    if len(rows) > MAX_CSV_ROWS:
        raise BadRequest(f"Upload at most {MAX_CSV_ROWS} rows at a time.")

    codes = {row.get("school_id", "") for row in rows if row.get("school_id")}
    schools = {
        s.school_id: s
        for s in evidence_schools(principal)
        .select_related("region")
        .filter(school_id__in=codes)
    }
    type_labels = {
        label.lower(): value for value, label in LearningAssessmentType.choices
    }
    errors: list[str] = []
    parsed: list[tuple] = []
    seen: set[tuple] = set()
    for number, row in enumerate(rows, start=2):
        row = dict(row)
        row["assessment_type"] = type_labels.get(
            row.get("assessment_type", "").lower(), row.get("assessment_type", "")
        )
        school = schools.get(row.get("school_id", ""))
        try:
            if school is None:
                raise BadRequest(
                    f"No school with ID {row.get('school_id') or '(blank)'} is in your country."
                )
            fields = _learning_fields(row)
            key = (
                school.id,
                fields["assessment_type"],
                fields["assessed_on"],
                fields["grade_level"].lower(),
                fields["subject"].lower(),
            )
            if key in seen:
                raise BadRequest("The same result appears twice in this file.")
            seen.add(key)
            parsed.append((number, school, fields, row))
        except BadRequest as exc:
            errors.append(f"Row {number}: {getattr(exc, 'detail', exc)}")

    if parsed and not errors:
        existing = set(
            LearningAssessmentResult.objects.filter(
                school_id__in={school.id for _n, school, _f, _r in parsed}
            ).values_list(
                "school_id", "assessment_type", "assessed_on", "grade_level", "subject"
            )
        )
        existing = {(s, t, d, g.lower(), subj.lower()) for s, t, d, g, subj in existing}
        for number, school, fields, _row in parsed:
            key = (
                school.id,
                fields["assessment_type"],
                fields["assessed_on"],
                fields["grade_level"].lower(),
                fields["subject"].lower(),
            )
            if key in existing:
                errors.append(
                    f"Row {number}: {school.name} already has this result recorded."
                )
    if errors:
        return {"created": 0, "errors": errors}

    uploader = _uid(principal)
    with transaction.atomic():
        created = LearningAssessmentResult.objects.bulk_create(
            [
                LearningAssessmentResult(
                    school=school,
                    country=school_country(school),
                    fy=get_operational_fy(fields["assessed_on"]),
                    evidence_reference=row.get("evidence_reference", "")[:512],
                    notes=row.get("notes", "")[:4000],
                    recorded_by_user_id=uploader,
                    verification_status=PENDING,
                    **fields,
                )
                for _number, school, fields, row in parsed
            ]
        )
        from apps.audit.services import log as audit_log

        audit_log(
            action="ia.school_evidence.learning_csv_uploaded",
            subject_kind="LearningAssessmentResult",
            subject_id=None,
            actor_id=uploader,
            actor_role=_role(principal),
            payload={
                "rows": len(created),
                "file_name": getattr(uploaded, "name", ""),
                "school_ids": sorted(
                    {school.school_id for _n, school, _f, _r in parsed}
                ),
            },
        )
    return {"created": len(created), "errors": []}


# ── Summaries (bulk) ────────────────────────────────────────────────────────


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _score_pct(row) -> float | None:
    mean, maximum = row.get("mean_score"), row.get("max_score")
    if mean is None or not maximum:
        return None
    return float(mean) / float(maximum) * 100


def learning_comparisons(rows, fy: str) -> list[dict]:
    """Year-on-year comparisons of the same school, assessment, class and
    subject: FY-1 against FY, from confirmed rows only.

    Each side pools that year's confirmed results (weighted by learners). A
    side with fewer than MIN_LEARNERS learners is withheld — shown, never
    compared. The change is in percentage points of the maximum score, or of
    learners proficient where no maximum score was recorded.
    """
    prev_fy = str(int(fy) - 1)
    pools: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if row["verification_status"] != CONFIRMED or row["fy"] not in (fy, prev_fy):
            continue
        key = (
            row["school_id"],
            row["assessment_type"],
            _norm(row["grade_level"]),
            _norm(row["subject"]),
        )
        side = pools[key].setdefault(
            row["fy"],
            {
                "learners": 0,
                "score_weight": 0.0,
                "score_learners": 0,
                "proficient": 0,
                "proficient_learners": 0,
                "grade": row["grade_level"],
                "subject": row["subject"],
            },
        )
        side["learners"] += row["learners_tested"]
        pct = _score_pct(row)
        if pct is not None:
            side["score_weight"] += pct * row["learners_tested"]
            side["score_learners"] += row["learners_tested"]
        if row["learners_proficient"] is not None:
            side["proficient"] += row["learners_proficient"]
            side["proficient_learners"] += row["learners_tested"]

    out = []
    for (school_id, assessment_type, _g, _s), sides in pools.items():
        before, after = sides.get(prev_fy), sides.get(fy)
        label_side = after or before

        def measure(side):
            if side is None:
                return None, None
            score = (
                round(side["score_weight"] / side["score_learners"], 1)
                if side["score_learners"]
                else None
            )
            proficient = (
                round(100 * side["proficient"] / side["proficient_learners"], 1)
                if side["proficient_learners"]
                else None
            )
            return score, proficient

        score_before, prof_before = measure(before)
        score_after, prof_after = measure(after)
        entry = {
            "school_id": school_id,
            "assessment_type": assessment_type,
            "grade_level": label_side["grade"],
            "subject": label_side["subject"],
            "learners_before": before["learners"] if before else None,
            "learners_after": after["learners"] if after else None,
            "score_before": score_before,
            "score_after": score_after,
            "proficient_before": prof_before,
            "proficient_after": prof_after,
            "measure": "",
            "change": None,
            "classification": "",
            "state": "",
        }
        if before is None or after is None:
            entry["state"] = "one_year"
        elif before["learners"] < MIN_LEARNERS or after["learners"] < MIN_LEARNERS:
            entry["state"] = "withheld"
        elif score_before is not None and score_after is not None:
            entry.update(
                measure="score",
                change=round(score_after - score_before, 1),
                state="compared",
            )
        elif prof_before is not None and prof_after is not None:
            entry.update(
                measure="proficient",
                change=round(prof_after - prof_before, 1),
                state="compared",
            )
        else:
            entry["state"] = "not_comparable"
        if entry["state"] == "compared":
            entry["classification"] = (
                "improved"
                if entry["change"] > 0
                else "declined"
                if entry["change"] < 0
                else "no_change"
            )
        out.append(entry)
    return out


def _learning_rows(schools, fy: str):
    prev_fy = str(int(fy) - 1)
    return list(
        LearningAssessmentResult.objects.filter(school__in=schools)
        .filter(Q(verification_status=PENDING) | Q(fy__in=(fy, prev_fy)))
        .values(
            "id",
            "school_id",
            "fy",
            "assessment_type",
            "grade_level",
            "subject",
            "learners_tested",
            "mean_score",
            "max_score",
            "learners_proficient",
            "verification_status",
        )
    )


def _latest_check_annotations():
    checks = EdTechCheck.objects.filter(
        deployment_id=OuterRef("pk"), verification_status=CONFIRMED
    ).order_by("-checked_on", "-created_at")
    return {
        "_check_on": Subquery(checks.values("checked_on")[:1]),
        "_units_functional": Subquery(checks.values("units_functional")[:1]),
        "_teachers_using": Subquery(checks.values("teachers_using")[:1]),
        "_learners_using": Subquery(checks.values("learners_using")[:1]),
        "_weekly_hours": Subquery(checks.values("weekly_use_hours")[:1]),
        "_pending_checks": Count(
            "checks",
            filter=Q(
                checks__verification_status=PENDING, checks__deleted_at__isnull=True
            ),
            distinct=True,
        ),
    }


def outcome_evidence(principal, fy: str) -> dict:
    """The Outcomes view's evidence beyond the SSA, for FY `fy`: four queries.

    Student learning (year-on-year class comparisons), discipleship practice
    beside reviewed change stories, and EdTech rollout from the latest
    confirmed check of each deployment. Only confirmed records count; pending
    records are counted as awaiting verification.
    """
    from apps.analytics.evidence_strength import grade

    schools = evidence_schools(principal)
    learning = _learning_rows(schools, fy)
    comparisons = learning_comparisons(learning, fy)
    compared = [c for c in comparisons if c["state"] == "compared"]
    compared_schools = {c["school_id"] for c in compared}
    learning_out = {
        "comparisons": len(compared),
        "schools": len(compared_schools),
        "improved": sum(1 for c in compared if c["classification"] == "improved"),
        "declined": sum(1 for c in compared if c["classification"] == "declined"),
        "withheld": sum(1 for c in comparisons if c["state"] == "withheld"),
        "confirmed_this_year": sum(
            1
            for r in learning
            if r["verification_status"] == CONFIRMED and r["fy"] == fy
        ),
        "pending": sum(1 for r in learning if r["verification_status"] == PENDING),
        "grade": grade(len(compared_schools), confirmed_share=1.0),
        "rule_label": LEARNING_RULE_LABEL,
        "min_learners": MIN_LEARNERS,
    }
    learning_out["improved_pct"] = percentage(learning_out["improved"], len(compared))
    learning_out["declined_pct"] = percentage(learning_out["declined"], len(compared))

    discipleship = list(
        DiscipleshipIndicatorRecord.objects.filter(school__in=schools)
        .filter(
            Q(verification_status=PENDING) | Q(fy=fy, verification_status=CONFIRMED)
        )
        .order_by("school_id", "-observed_on", "-created_at")
        .values(
            "school_id",
            "verification_status",
            "discipleship_groups_active",
            "learners_in_groups",
            "learners_enrolled",
            "spiritual_lead_in_post",
            "devotions_per_week",
        )
    )
    latest: dict[str, dict] = {}
    for row in discipleship:
        if row["verification_status"] == CONFIRMED:
            latest.setdefault(row["school_id"], row)
    with_groups = sum(
        1 for r in latest.values() if (r["discipleship_groups_active"] or 0) > 0
    )
    with_lead = sum(1 for r in latest.values() if r["spiritual_lead_in_post"] is True)
    in_groups = [
        (r["learners_in_groups"], r["learners_enrolled"])
        for r in latest.values()
        if r["learners_in_groups"] is not None and r["learners_enrolled"]
    ]
    stories = _story_counts(principal, fy)
    discipleship_out = {
        "schools": len(latest),
        "with_groups": with_groups,
        "with_groups_pct": percentage(with_groups, len(latest)),
        "with_lead": with_lead,
        "with_lead_pct": percentage(with_lead, len(latest)),
        "learners_in_groups_pct": percentage(
            sum(a for a, _b in in_groups), sum(b for _a, b in in_groups)
        ),
        "pending": sum(1 for r in discipleship if r["verification_status"] == PENDING),
        "stories_approved": stories["approved"],
        "stories_waiting": stories["waiting"],
        "grade": grade(len(latest), confirmed_share=1.0),
    }

    deployments = list(
        EdTechDeployment.objects.filter(school__in=schools)
        .annotate(**_latest_check_annotations())
        .values(
            "id",
            "school_id",
            "quantity",
            "verification_status",
            "learners_with_access",
            "_check_on",
            "_units_functional",
            "_teachers_using",
            "_learners_using",
            "_pending_checks",
        )
    )
    confirmed = [d for d in deployments if d["verification_status"] == CONFIRMED]
    checked = [d for d in confirmed if d["_check_on"] is not None]
    units_checked = sum(d["quantity"] for d in checked)
    edtech_out = {
        "deployments": len(confirmed),
        "schools": len({d["school_id"] for d in confirmed}),
        "units": sum(d["quantity"] for d in confirmed),
        "checked": len(checked),
        "units_functional": sum(d["_units_functional"] or 0 for d in checked),
        "units_checked": units_checked,
        "functional_pct": percentage(
            sum(d["_units_functional"] or 0 for d in checked), units_checked
        ),
        "teachers_using": sum(d["_teachers_using"] or 0 for d in checked),
        "learners_using": sum(d["_learners_using"] or 0 for d in checked),
        "learners_with_access": sum(
            d["learners_with_access"] or 0
            for d in checked
            if d["learners_with_access"] is not None
        ),
        "pending": sum(1 for d in deployments if d["verification_status"] == PENDING)
        + sum(d["_pending_checks"] for d in deployments),
        "grade": grade(len({d["school_id"] for d in checked}), confirmed_share=1.0),
    }
    return {
        "fy": fy,
        "learning": learning_out,
        "discipleship": discipleship_out,
        "edtech": edtech_out,
    }


def _story_counts(principal, fy: str) -> dict:
    """Most Significant Change stories evidencing spiritual formation: approved
    in FY `fy`, and waiting for review — one query."""
    from apps.targets import mscs_review

    counts = mscs_review.visible_stories(principal).aggregate(
        approved=Count(
            "id",
            filter=Q(status="approved")
            & mscs_review.spiritual_story_q()
            & mscs_review.fy_q(fy),
        ),
        waiting=Count("id", filter=Q(status="submitted")),
    )
    return {"approved": counts["approved"] or 0, "waiting": counts["waiting"] or 0}


# ── Registers ───────────────────────────────────────────────────────────────


def _names(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = {str(i) for i in user_ids if i}
    if not ids:
        return {}
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def register(principal, kind: str, *, status: str = "", fy: str = "", extra=None):
    """The records of one kind in the reader's scope, newest first, with who
    recorded them and what the reader may do with each (bulk)."""
    rows = visible(principal, kind).select_related("school")
    if kind == CHECK:
        rows = rows.select_related("deployment")
    if status in STATUS_LABELS:
        rows = rows.filter(verification_status=status)
    if fy:
        rows = rows.filter(fy=fy)
    for key, value in (extra or {}).items():
        if value:
            rows = rows.filter(**{key: value})
    order = {
        LEARNING: "-assessed_on",
        DISCIPLESHIP: "-observed_on",
        EDTECH: "-deployed_on",
        CHECK: "-checked_on",
    }[kind]
    return rows.order_by(order, "-created_at")


def decorate(principal, records) -> list[dict]:
    """Who recorded and verified each record, and whether the reader may
    verify, correct or withdraw it. One user query and one IA officer query
    per country, whatever the number of rows."""
    from apps.impact.framework import ReviewerResolver

    resolver = ReviewerResolver(principal)
    me = _uid(principal)
    names = _names(
        [r.recorded_by_user_id for r in records]
        + [r.verified_by_user_id for r in records]
    )
    out = []
    for row in records:
        pending = row.verification_status == PENDING
        out.append(
            {
                "record": row,
                "recorded_by": names.get(str(row.recorded_by_user_id), "Staff member"),
                "verified_by": names.get(str(row.verified_by_user_id or ""), ""),
                "status_label": STATUS_LABELS.get(row.verification_status, ""),
                "status_tone": STATUS_TONES.get(row.verification_status, ""),
                "can_verify": pending
                and bool(
                    resolver.basis(
                        author_id=row.recorded_by_user_id, country=row.country
                    )
                ),
                "is_mine": str(row.recorded_by_user_id) == me,
                "can_correct": str(row.recorded_by_user_id) == me
                and row.verification_status != CONFIRMED,
            }
        )
    return out


def counts(principal) -> dict:
    """The School Evidence page's tiles: four aggregate queries."""
    schools = evidence_schools(principal)
    out = {}
    for kind, model in MODELS.items():
        out[kind] = model.objects.filter(school__in=schools).aggregate(
            pending=Count("id", filter=Q(verification_status=PENDING)),
            confirmed=Count("id", filter=Q(verification_status=CONFIRMED)),
            returned=Count("id", filter=Q(verification_status=RETURNED)),
            schools=Count(
                "school_id", filter=Q(verification_status=CONFIRMED), distinct=True
            ),
        )
    return out


def learning_summary(principal, fy: str, *, subject: str = "") -> list[dict]:
    """The Learning tab's school-level comparisons, with school names."""
    schools = evidence_schools(principal)
    rows = _learning_rows(schools, fy)
    if subject:
        rows = [r for r in rows if _norm(r["subject"]) == _norm(subject)]
    comparisons = learning_comparisons(rows, fy)
    names = dict(
        schools.filter(id__in={c["school_id"] for c in comparisons}).values_list(
            "id", "name"
        )
    )
    order = {"compared": 0, "withheld": 1, "not_comparable": 2, "one_year": 3}
    for c in comparisons:
        c["school"] = names.get(c["school_id"], "School")
    comparisons.sort(key=lambda c: (order[c["state"]], c["school"], c["subject"]))
    return comparisons


def discipleship_summary(principal, fy: str) -> list[dict]:
    """Each school's latest confirmed discipleship record in FY `fy` beside its
    latest in FY-1, and its approved change stories this year (three queries)."""
    from apps.targets import mscs_review

    schools = evidence_schools(principal)
    prev_fy = str(int(fy) - 1)
    rows = (
        DiscipleshipIndicatorRecord.objects.filter(
            school__in=schools, verification_status=CONFIRMED, fy__in=(fy, prev_fy)
        )
        .select_related("school")
        .order_by("school_id", "-observed_on", "-created_at")
    )
    latest: dict[tuple, DiscipleshipIndicatorRecord] = {}
    for row in rows:
        latest.setdefault((row.school_id, row.fy), row)
    story_counts = dict(
        mscs_review.visible_stories(principal)
        .filter(status="approved", school__isnull=False)
        .filter(mscs_review.spiritual_story_q() & mscs_review.fy_q(fy))
        .values("school_id")
        .annotate(n=Count("id"))
        .values_list("school_id", "n")
    )
    out = []
    for (school_id, row_fy), row in latest.items():
        if row_fy != fy:
            continue
        before = latest.get((school_id, prev_fy))

        def share(r):
            if r is None or r.learners_in_groups is None or not r.learners_enrolled:
                return None
            return round(100 * r.learners_in_groups / r.learners_enrolled)

        now_share, before_share = share(row), share(before)
        out.append(
            {
                "record": row,
                "school_id": row.school_id,
                "school": row.school.name,
                "share_in_groups": now_share,
                "share_before": before_share,
                "share_change": (
                    now_share - before_share
                    if now_share is not None and before_share is not None
                    else None
                ),
                "stories": story_counts.get(school_id, 0),
            }
        )
    out.sort(key=lambda r: r["school"])
    return out


def edtech_summary(principal, *, asset_type: str = "") -> list[dict]:
    """Each confirmed deployment with its latest confirmed check (one query)."""
    rows = (
        EdTechDeployment.objects.filter(
            school__in=evidence_schools(principal), verification_status=CONFIRMED
        )
        .select_related("school")
        .annotate(**_latest_check_annotations())
        .order_by("school__name", "-deployed_on")
    )
    if asset_type:
        rows = rows.filter(asset_type=asset_type)
    out = []
    for d in rows:
        checked = d._check_on is not None
        out.append(
            {
                "deployment": d,
                "school_id": d.school_id,
                "school": d.school.name,
                "checked_on": d._check_on,
                "functional_pct": percentage(d._units_functional or 0, d.quantity)
                if checked
                else None,
                "units_functional": d._units_functional if checked else None,
                "teachers_using": d._teachers_using if checked else None,
                "learners_using": d._learners_using if checked else None,
                "weekly_hours": d._weekly_hours if checked else None,
                "pending_checks": d._pending_checks,
            }
        )
    return out


def waiting_for(principal) -> dict:
    """For To-Dos: pending records the reader may verify, and records returned
    to the reader. Four value queries and one IA officer query per country."""
    from apps.impact.framework import ReviewerResolver

    me = _uid(principal)
    role = _role(principal)
    resolver = ReviewerResolver(principal)
    to_verify: dict[str, list] = {}
    returned: dict[str, list] = {}
    reviewer = role in (IA, CD)
    schools = evidence_schools(principal) if reviewer else None
    for kind, model in MODELS.items():
        condition = Q(verification_status=RETURNED, recorded_by_user_id=me)
        if reviewer:
            condition |= Q(verification_status=PENDING, school__in=schools) & ~Q(
                recorded_by_user_id=me
            )
        for row in model.objects.filter(condition).values(
            "id",
            "recorded_by_user_id",
            "country",
            "verification_status",
            "created_at",
            "updated_at",
            "source_activity_id",
        ):
            if row["verification_status"] == RETURNED:
                returned.setdefault(kind, []).append(row)
            elif resolver.basis(
                author_id=row["recorded_by_user_id"], country=row["country"]
            ):
                to_verify.setdefault(kind, []).append(row)
    return {"to_verify": to_verify, "returned": returned}


def onetest_visits_without_results(principal, *, limit: int = 10) -> list:
    """Delivered OneTest visits this person is responsible for that have no
    learning results recorded yet (this financial year; one query)."""
    from apps.activities.models import Activity
    from apps.core.scoping import owner_ids

    mine = owner_ids(principal)
    if not mine:
        return []
    results = LearningAssessmentResult.objects.filter(source_activity_id=OuterRef("pk"))
    return list(
        Activity.objects.filter(
            Q(responsible_staff_id__in=mine) | Q(monitored_by_staff_id__in=mine),
            Q(costing_profile_snapshot="ONETEST")
            | Q(catalogue_item__costing_profile="ONETEST"),
            deleted_at__isnull=True,
            school__isnull=False,
            status__in=DELIVERED_STATUSES,
            fy=get_operational_fy(),
        )
        .exclude(Exists(results))
        .select_related("school")
        .order_by("actual_delivery_date", "planned_date", "id")[:limit]
    )


__all__ = [
    "CHECK",
    "DISCIPLESHIP",
    "EDTECH",
    "LEARNING",
    "LEARNING_CSV_COLUMNS",
    "MIN_LEARNERS",
    "correct",
    "counts",
    "decide",
    "decorate",
    "discipleship_summary",
    "edtech_summary",
    "evidence_schools",
    "find_school",
    "is_onetest",
    "learning_comparisons",
    "learning_summary",
    "may_record",
    "may_record_for_activity",
    "onetest_visits_without_results",
    "outcome_evidence",
    "record",
    "record_check",
    "register",
    "upload_learning_csv",
    "visible",
    "waiting_for",
    "withdraw",
]
