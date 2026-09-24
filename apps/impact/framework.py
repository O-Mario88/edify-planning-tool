"""Impact Assessment's measurement framework (IA review, owner, 2026-09-13).

The role description's first responsibility: define the boundaries and the
measures of success, moving attention from counting daily activities to
measuring long-term change in partner schools, and map how programme steps
contribute to Edify's mission. Four registers make that concrete:

  Outcome areas      what transformation Edify measures (spiritual formation,
                     educational quality, sustainability), each read through
                     SSA domains as school-level proxies;
  Indicators         each measure of success, versioned append-only, with its
                     population, denominator, baseline rule, frequency and
                     limitations;
  Measurement rules  which SSA domain each activity is meant to move and how
                     that is judged (apps.activity_catalogue.intervention_mapping);
  Loan purposes      what each lending purpose is measured by.

Nothing here is hard-coded as approved. The three outcome areas are PROPOSED
as drafts for IA to review. Every definition follows one lifecycle — draft,
submitted, reviewed — and the reviewer is never the author: a second IA
officer in the author's country, or the Country Director's acknowledgement
where the country has one officer (apps.impact.review). Approving a new
version supersedes the old one, which stays readable: results measured under
it keep the definition they were measured by. Every transition is audited
inside its transaction and notifies the person it hands to.

Reads are bulk. The register builders take a fixed number of queries whatever
the size of the catalogue (pinned by apps/impact/test_framework.py).
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.interventions import INTERVENTION_ABBREVIATIONS
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission

from .models import (
    DefinitionStatus,
    IndicatorDefinition,
    IndicatorLevel,
    IndicatorSource,
    OutcomeArea,
    OutcomeAreaDomain,
)

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value

INTERVENTION_LABELS = dict(SsaIntervention.choices)

EVENT_REVIEW_REQUESTED = "ia.framework.review_requested"
EVENT_REVIEW_DECIDED = "ia.framework.review_decided"

#: The outcome areas IA is asked to review (owner, 2026-09-13). Proposed as
#: drafts, never inserted as approved: the grouping is a methodological
#: judgement IA owns, and a second officer confirms it.
PROPOSED_OUTCOME_AREAS = (
    {
        "code": "spiritual-formation",
        "name": "Spiritual formation",
        "definition": (
            "Students and staff grow in Christ-like character and are regularly "
            "exposed to the Word of God in the life of the school. Read at school "
            "level through the SSA Christ-like Behaviour and Exposure to the Word "
            "of God domains, beside discipleship indicators and reviewed Most "
            "Significant Change stories."
        ),
        "interventions": ("christlike_behaviour", "exposure_to_word_of_god"),
    },
    {
        "code": "educational-quality",
        "name": "Educational quality",
        "definition": (
            "Learners are taught well, in an environment that supports learning, "
            "by a school that is well led. Read at school level through the SSA "
            "Learning Environment, Teaching Environment and Leadership domains, "
            "beside student learning results and EdTech use."
        ),
        "interventions": (
            "learning_environment",
            "teaching_environment",
            "leadership",
        ),
    },
    {
        "code": "sustainability",
        "name": "Sustainability",
        "definition": (
            "The school can keep serving its community: it is financially "
            "healthy, meets government requirements and holds or grows its "
            "enrolment. Read at school level through the SSA Financial Health, "
            "Government Requirements and Enrolment domains, beside lending "
            "impact evidence."
        ),
        "interventions": ("financial_health", "government_requirement", "enrolment"),
    },
)

PENDING = (DefinitionStatus.DRAFT, DefinitionStatus.RETURNED)

STATUS_TONES = {
    DefinitionStatus.DRAFT: "neutral",
    DefinitionStatus.IN_REVIEW: "warning",
    DefinitionStatus.RETURNED: "danger",
    DefinitionStatus.APPROVED: "success",
    DefinitionStatus.SUPERSEDED: "neutral",
    DefinitionStatus.RETIRED: "neutral",
}


# ── Authority ───────────────────────────────────────────────────────────────


def may_author(principal) -> bool:
    """Only Impact Assessment writes framework definitions; the Country
    Director may acknowledge one, never write it."""
    return getattr(principal, "active_role", "") == IA and has_permission(
        principal, Permission.SSA_ACTIVITY_MAPPING_MANAGE.value
    )


def _assert_may_author(principal) -> None:
    if not may_author(principal):
        raise Forbidden(
            "Only Impact Assessment defines the measurement framework. The "
            "Country Director acknowledges a definition where the country has "
            "no second IA officer, but does not write one."
        )


def _actor(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def principal_country(principal) -> str:
    profile = getattr(principal, "staff_profile", None)
    return (getattr(profile, "country", "") or "").strip()


def _author_country(record) -> str:
    country = (getattr(record, "country", "") or "").strip()
    if country:
        return country
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=record.author_id)
        .values_list("country", flat=True)
        .first()
        or ""
    ).strip()


def _audit(action: str, record, principal, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=type(record).__name__,
        subject_id=str(record.id),
        actor_id=_actor(principal) or None,
        actor_role=getattr(principal, "active_role", None),
        reason=(payload or {}).get("reason"),
        payload={
            "version": getattr(record, "version", None),
            "status": getattr(record, "status", None),
            **(payload or {}),
        },
    )


class ReviewerResolver:
    """reviewer_basis for many records at one query per country."""

    def __init__(self, principal):
        self.principal = principal
        self.user_id = _actor(principal)
        self.role = getattr(principal, "active_role", "")
        self.country = principal_country(principal)
        self._officers: dict[str, list[str]] = {}

    def _others(self, country: str, author_id: str) -> list[str]:
        from apps.impact.review import ia_officer_ids

        if country not in self._officers:
            self._officers[country] = [str(i) for i in ia_officer_ids(country)]
        return [i for i in self._officers[country] if i != str(author_id)]

    def basis(self, *, author_id: str, country: str) -> str | None:
        from apps.impact.review import CD_FALLBACK, PEER_IA

        if not self.user_id or self.user_id == str(author_id or ""):
            return None
        country = (country or "").strip()
        if country and self.country != country:
            return None
        if self.role == IA:
            return PEER_IA
        if self.role == CD:
            return CD_FALLBACK if not self._others(country, author_id) else None
        return None


# ── Outcome areas ───────────────────────────────────────────────────────────


def propose_default_areas(principal) -> list[OutcomeArea]:
    """Draft the three proposed outcome areas that do not exist yet."""
    _assert_may_author(principal)
    created = []
    with transaction.atomic():
        existing = set(OutcomeArea.objects.values_list("code", flat=True))
        for proposal in PROPOSED_OUTCOME_AREAS:
            if proposal["code"] in existing:
                continue
            area = OutcomeArea.objects.create(
                code=proposal["code"],
                name=proposal["name"],
                definition=proposal["definition"],
                status=DefinitionStatus.DRAFT,
                version=1,
                author_id=_actor(principal),
                author_role=IA,
                change_reason="Proposed grouping of SSA domains (IA review, 2026-09-13).",
            )
            OutcomeAreaDomain.objects.bulk_create(
                OutcomeAreaDomain(
                    area=area,
                    intervention=code,
                    note="School-level SSA proxy",
                )
                for code in proposal["interventions"]
            )
            _audit(
                "ia.framework.area_drafted",
                area,
                principal,
                {"code": area.code, "domains": list(proposal["interventions"])},
            )
            created.append(area)
    return created


def _clean_interventions(values) -> list[str]:
    chosen = [v for v in (values or []) if v in SsaIntervention.values]
    return list(dict.fromkeys(chosen))


def save_outcome_area(principal, data: dict, *, area: OutcomeArea | None = None):
    """Create an area, edit a draft or returned one, or start a new version of
    an approved one."""
    _assert_may_author(principal)
    name = (data.get("name") or "").strip()
    definition = (data.get("definition") or "").strip()
    interventions = _clean_interventions(data.get("interventions"))
    if not name or not definition:
        raise BadRequest("An outcome area needs a name and a definition.")
    if not interventions:
        raise BadRequest(
            "Name at least one SSA domain the area is read through, or say in "
            "the definition why no SSA proxy exists."
        )
    actor = _actor(principal)
    with transaction.atomic():
        if area is None:
            code = _slug(data.get("code") or name)
            if OutcomeArea.objects.filter(code=code).exists():
                raise BadRequest("An outcome area with that code already exists.")
            record = OutcomeArea.objects.create(
                code=code,
                name=name,
                definition=definition,
                version=1,
                author_id=actor,
                author_role=IA,
                change_reason=(data.get("change_reason") or "").strip(),
            )
            action = "ia.framework.area_drafted"
        else:
            area = OutcomeArea.objects.select_for_update().get(pk=area.pk)
            if area.status in PENDING:
                if area.author_id != actor:
                    raise Forbidden(
                        "Another officer wrote this draft; they finish it, or you "
                        "review it once they submit it."
                    )
                record = area
                record.name, record.definition = name, definition
                if data.get("change_reason"):
                    record.change_reason = data["change_reason"].strip()
                record.save()
                record.domains.all().delete()
                action = "ia.framework.area_updated"
            elif area.status == DefinitionStatus.IN_REVIEW:
                raise BadRequest("This area is with a reviewer.")
            else:
                if OutcomeArea.objects.filter(
                    code=area.code,
                    status__in=(*PENDING, DefinitionStatus.IN_REVIEW),
                ).exists():
                    raise BadRequest(
                        "A new version of this area is already being drafted or reviewed."
                    )
                last = OutcomeArea.objects.filter(code=area.code).aggregate(
                    v=Max("version")
                )["v"]
                record = OutcomeArea.objects.create(
                    code=area.code,
                    name=name,
                    definition=definition,
                    version=(last or 0) + 1,
                    author_id=actor,
                    author_role=IA,
                    change_reason=(data.get("change_reason") or "").strip(),
                )
                action = "ia.framework.area_version_drafted"
        OutcomeAreaDomain.objects.bulk_create(
            OutcomeAreaDomain(
                area=record, intervention=code, note="School-level SSA proxy"
            )
            for code in interventions
        )
        _audit(
            action, record, principal, {"code": record.code, "domains": interventions}
        )
    return record


# ── Indicators ──────────────────────────────────────────────────────────────

INDICATOR_TEXT_FIELDS = (
    "population",
    "denominator",
    "baseline_rule",
    "frequency",
    "disaggregation",
    "limitations",
    "data_owner_role",
)


def save_indicator(
    principal, data: dict, *, indicator: IndicatorDefinition | None = None
):
    """Create an indicator, edit a draft or returned version, or start a new
    version of an approved one (versions are append-only)."""
    _assert_may_author(principal)
    fields = {
        "name": (data.get("name") or "").strip(),
        "level": data.get("level") or "",
        "unit": (data.get("unit") or "").strip(),
        "source": data.get("source") or "",
        "calculation": (data.get("calculation") or "").strip(),
    }
    missing = [
        label
        for key, label in (
            ("name", "name"),
            ("unit", "unit"),
            ("calculation", "calculation"),
        )
        if not fields[key]
    ]
    if missing:
        raise BadRequest("An indicator needs its " + ", ".join(missing) + ".")
    if fields["level"] not in IndicatorLevel.values:
        raise BadRequest("Choose whether the indicator is an output or an outcome.")
    if fields["source"] not in IndicatorSource.values:
        raise BadRequest("Choose the evidence source the indicator is calculated from.")
    if (
        fields["level"] == IndicatorLevel.OUTCOME
        and fields["source"] == IndicatorSource.ACTIVITY
    ):
        # The role description's first line: activity counts are outputs.
        raise BadRequest(
            "An outcome indicator cannot be calculated from activity records "
            "alone — counting delivered work is an output."
        )
    for name in INDICATOR_TEXT_FIELDS:
        fields[name] = (data.get(name) or "").strip()
    area_id = (data.get("outcome_area") or "").strip()
    fields["outcome_area"] = (
        OutcomeArea.objects.filter(id=area_id).first() if area_id else None
    )
    if area_id and fields["outcome_area"] is None:
        raise BadRequest("That outcome area does not exist.")
    fields["effective_from"] = data.get("effective_from") or None
    actor = _actor(principal)
    country = principal_country(principal)
    with transaction.atomic():
        if indicator is None:
            key = _slug(data.get("key") or fields["name"])
            if IndicatorDefinition.objects.filter(key=key).exists():
                raise BadRequest("An indicator with that key already exists.")
            record = IndicatorDefinition.objects.create(
                key=key,
                version=1,
                author_id=actor,
                author_role=IA,
                country=country,
                change_reason=(data.get("change_reason") or "").strip(),
                **fields,
            )
            action = "ia.framework.indicator_drafted"
            before = None
        else:
            indicator = IndicatorDefinition.objects.select_for_update().get(
                pk=indicator.pk
            )
            before = indicator_snapshot(indicator)
            if indicator.status in PENDING:
                if indicator.author_id != actor:
                    raise Forbidden(
                        "Another officer wrote this draft; they finish it, or you "
                        "review it once they submit it."
                    )
                record = indicator
                for name, value in fields.items():
                    setattr(record, name, value)
                if data.get("change_reason"):
                    record.change_reason = data["change_reason"].strip()
                record.save()
                action = "ia.framework.indicator_updated"
            elif indicator.status == DefinitionStatus.IN_REVIEW:
                raise BadRequest("This indicator is with a reviewer.")
            else:
                if IndicatorDefinition.objects.filter(
                    key=indicator.key,
                    status__in=(*PENDING, DefinitionStatus.IN_REVIEW),
                ).exists():
                    raise BadRequest(
                        "A new version of this indicator is already being drafted "
                        "or reviewed."
                    )
                last = IndicatorDefinition.objects.filter(key=indicator.key).aggregate(
                    v=Max("version")
                )["v"]
                record = IndicatorDefinition.objects.create(
                    key=indicator.key,
                    version=(last or 0) + 1,
                    author_id=actor,
                    author_role=IA,
                    country=indicator.country or country,
                    change_reason=(data.get("change_reason") or "").strip(),
                    **fields,
                )
                action = "ia.framework.indicator_version_drafted"
        _audit(
            action,
            record,
            principal,
            {"key": record.key, "before": before, "after": indicator_snapshot(record)},
        )
    return record


def indicator_snapshot(record) -> dict:
    return {
        "name": record.name,
        "level": record.level,
        "unit": record.unit,
        "source": record.source,
        "calculation": record.calculation,
        "outcome_area": record.outcome_area_id,
        **{name: getattr(record, name) for name in INDICATOR_TEXT_FIELDS},
    }


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if not out:
        raise BadRequest("Give it a name or a key made of letters and numbers.")
    return out[:80]


# ── Loan purposes ───────────────────────────────────────────────────────────

LOAN_PURPOSE_KEY_PREFIX = "loan-purpose-"


def loan_purpose_key(purpose) -> str:
    return _slug(f"{LOAN_PURPOSE_KEY_PREFIX}{purpose.code}")


def _lines(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value or "").splitlines()
    return [str(item).strip(" -•\t") for item in items if str(item).strip(" -•\t")]


def save_loan_purpose_measurement(principal, purpose, data: dict):
    """Draft how an existing loan purpose is measured.

    New purposes keep their own route (MFI request → BT review → IA defines →
    CD approves, apps.business_transformation.lending_impact). An EXISTING
    purpose has no route at all: it is already an approved product, and what
    is missing is IA's judgement of what it is measured by. That judgement is
    drafted here as an indicator (source "lending", key loan-purpose-<code>)
    and reviewed like every other IA definition; approving it writes the
    measurement profile onto the purpose.

    The indicator's fields carry the profile: `calculation` holds the impact
    indicators (one per line), `baseline_rule` the verification method,
    `disaggregation` the required evidence (one per line) and `frequency` the
    follow-up in days.
    """
    _assert_may_author(principal)
    country = principal_country(principal)
    applicable = [c for c in (purpose.applicable_countries or []) if c]
    if applicable and country and country not in applicable:
        raise Forbidden("That loan purpose is not offered in your country.")
    indicators = _lines(data.get("impact_indicators"))
    evidence = _lines(data.get("required_evidence"))
    method = (data.get("verification_method") or "").strip()
    try:
        days = int(data.get("follow_up_days") or purpose.follow_up_days or 0)
    except (TypeError, ValueError) as exc:
        raise BadRequest("The follow-up is a number of days.") from exc
    if not indicators or not evidence or not method:
        raise BadRequest(
            "Impact indicators, required evidence and the verification method are "
            "all required."
        )
    if days <= 0:
        raise BadRequest("The follow-up must be at least one day after disbursement.")
    key = loan_purpose_key(purpose)
    payload = {
        "name": f"{purpose.label} — lending measurement",
        "level": IndicatorLevel.OUTCOME,
        "unit": purpose.unit_of_measure or "count",
        "source": IndicatorSource.LENDING,
        "calculation": "\n".join(indicators),
        "baseline_rule": method,
        "disaggregation": "\n".join(evidence),
        "frequency": f"{days} days",
        "population": "Schools financed for this purpose",
        "limitations": (data.get("limitations") or "").strip(),
        "data_owner_role": IA,
        "change_reason": (data.get("change_reason") or "").strip(),
    }
    latest = IndicatorDefinition.objects.filter(key=key).order_by("-version").first()
    if latest is None:
        return save_indicator(principal, {**payload, "key": key})
    return save_indicator(principal, payload, indicator=latest)


def _apply_loan_purpose(record, principal) -> None:
    from apps.business_transformation.models import LoanPurpose

    code = record.key[len(LOAN_PURPOSE_KEY_PREFIX) :]
    purpose = None
    for candidate in LoanPurpose.objects.select_for_update():
        if loan_purpose_key(candidate) == record.key or candidate.code.lower() == code:
            purpose = candidate
            break
    if purpose is None:
        return
    before = {
        "impact_indicators": purpose.impact_indicators,
        "required_evidence": purpose.required_evidence,
        "verification_method": purpose.verification_method,
        "follow_up_days": purpose.follow_up_days,
    }
    purpose.impact_indicators = _lines(record.calculation)
    purpose.required_evidence = _lines(record.disaggregation)
    purpose.verification_method = record.baseline_rule
    digits = re.match(r"\d+", record.frequency or "")
    if digits:
        purpose.follow_up_days = int(digits.group(0))
    purpose.measurement_profile_complete = True
    purpose.version = (purpose.version or 1) + 1
    purpose.save()
    _audit(
        "bt.loan.purpose_measurement_defined",
        purpose,
        principal,
        {"indicator": record.id, "before": before},
    )


# ── Review lifecycle (outcome areas and indicators) ─────────────────────────


def _model_for(kind: str):
    return {"area": OutcomeArea, "indicator": IndicatorDefinition}.get(kind)


def get_record(kind: str, record_id: str):
    model = _model_for(kind)
    if model is None:
        raise NotFoundError("That framework record does not exist.")
    record = model.objects.filter(id=record_id).first()
    if record is None:
        raise NotFoundError("That framework record does not exist.")
    return record


def submit(principal, record, change_reason: str = ""):
    """Hand a draft to a second reviewer."""
    _assert_may_author(principal)
    model = type(record)
    with transaction.atomic():
        row = model.objects.select_for_update().get(pk=record.pk)
        if row.status not in PENDING:
            raise BadRequest("Only a draft or a returned definition can be submitted.")
        if row.author_id != _actor(principal):
            raise Forbidden("The officer who wrote this definition submits it.")
        reason = (change_reason or row.change_reason or "").strip()
        if not reason:
            raise BadRequest(
                "Say what this definition establishes or changes, and why."
            )
        row.change_reason = reason
        row.status = DefinitionStatus.IN_REVIEW
        row.submitted_at = timezone.now()
        row.save(
            update_fields=["change_reason", "status", "submitted_at", "updated_at"]
        )
        _audit(
            f"ia.framework.{_kind(row)}_submitted", row, principal, {"reason": reason}
        )
    _notify_reviewers(row)
    return row


def review(principal, record, *, decision: str, note: str = ""):
    """Approve or return a submitted definition. The reviewer is never the
    author (apps.impact.review)."""
    from apps.impact.review import assert_can_review

    note = (note or "").strip()
    if decision not in ("approve", "return"):
        raise BadRequest("Approve the definition or return it with a note.")
    model = type(record)
    with transaction.atomic():
        row = model.objects.select_for_update().get(pk=record.pk)
        if row.status != DefinitionStatus.IN_REVIEW:
            raise BadRequest("Only a submitted definition can be reviewed.")
        basis = assert_can_review(
            principal, author_id=row.author_id, country=_author_country(row)
        )
        row.reviewed_by_id = _actor(principal)
        row.reviewed_at = timezone.now()
        row.review_basis = basis
        row.review_note = note
        kind = _kind(row)
        if decision == "return":
            if not note:
                raise BadRequest("Say what has to change before it can be approved.")
            row.status = DefinitionStatus.RETURNED
            row.save()
            _audit(f"ia.framework.{kind}_returned", row, principal, {"reason": note})
        else:
            identity = {"code": row.code} if kind == "area" else {"key": row.key}
            for prior in (
                model.objects.select_for_update()
                .filter(status=DefinitionStatus.APPROVED, **identity)
                .exclude(pk=row.pk)
            ):
                prior.status = DefinitionStatus.SUPERSEDED
                prior.save(update_fields=["status", "updated_at"])
                _audit(
                    f"ia.framework.{kind}_superseded",
                    prior,
                    principal,
                    {"superseded_by": row.id},
                )
            row.status = DefinitionStatus.APPROVED
            if kind == "indicator" and not row.effective_from:
                row.effective_from = timezone.localdate()
            row.save()
            _audit(f"ia.framework.{kind}_approved", row, principal, {"basis": basis})
            if kind == "indicator" and row.key.startswith(LOAN_PURPOSE_KEY_PREFIX):
                _apply_loan_purpose(row, principal)
    _notify_author(row, decision)
    return row


def _kind(record) -> str:
    return "area" if isinstance(record, OutcomeArea) else "indicator"


def _title(record) -> str:
    return f"{record.name} (v{record.version})"


def _notify_reviewers(record) -> None:
    try:
        from apps.activity_catalogue.intervention_mapping import reviewer_ids
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_REQUESTED,
            category="ia",
            priority="high",
            title="Framework definition to review",
            body=f"{_title(record)}: {record.change_reason}"[:500],
            context_type=type(record).__name__,
            context_id=record.id,
            recipients=reviewer_ids(_author_country(record), record.author_id),
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the submission
        pass


def _notify_author(record, decision: str) -> None:
    try:
        from apps.notifications.services import (
            WorkflowNotificationService,
            resolve_condition,
        )

        resolve_condition(EVENT_REVIEW_REQUESTED, type(record).__name__, record.id)
        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_DECIDED,
            category="ia",
            priority="normal" if decision == "approve" else "high",
            title=(
                "Framework definition approved"
                if decision == "approve"
                else "Framework definition returned"
            ),
            body=(
                _title(record)
                + (f": {record.review_note}" if record.review_note else "")
            )[:500],
            context_type=type(record).__name__,
            context_id=record.id,
            recipients=[record.author_id],
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the decision
        pass


# ── Registers (bulk reads) ──────────────────────────────────────────────────


def school_outcome_items():
    """Active catalogue items with a school outcome: school-facing, cluster or
    training delivery. Cluster and central trainings are where most
    Christian-transformation and education work happens, so they belong in
    the rules register as much as a school visit does."""
    from apps.activity_catalogue.models import ActivityCatalogueItem

    return ActivityCatalogueItem.objects.filter(status="active").filter(
        Q(requires_school=True)
        | Q(cluster_delivery_allowed=True)
        | Q(is_training_course=True)
    )


def _names(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = {str(i) for i in user_ids if i}
    if not ids:
        return {}
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def _window(row) -> str:
    parts = [
        row.follow_up_min_days,
        row.follow_up_expected_days,
        row.follow_up_max_days,
    ]
    if all(p is None for p in parts):
        return "No window"
    lo, mid, hi = (("—" if p is None else str(p)) for p in parts)
    return f"{lo} / {mid} / {hi} days"


def _intervention_text(row) -> str:
    from apps.activity_catalogue.models import MappingMode

    if row.not_ssa_measured_reason:
        return "Not measured by a score"
    if row.intervention:
        return INTERVENTION_LABELS.get(row.intervention, row.intervention)
    if row.mapping_mode == MappingMode.ANY_SSA_INTERVENTION:
        return "Planner selects"
    if row.mapping_mode == MappingMode.INHERIT_FROM_SOURCE_ACTIVITY:
        return "Inherited from the source activity"
    if row.mapping_mode == MappingMode.SSA_COMPLETION_PREREQUISITE:
        return "SSA completion (prerequisite)"
    return "—"


def rule_state(row) -> tuple[str, str]:
    """The register's plain-text status and tone for a mapping row."""
    from apps.activity_catalogue.intervention_mapping import (
        REFERENCE_DEFAULT_LABEL,
        is_reference_default,
    )
    from apps.activity_catalogue.models import MappingStatus

    if row is None:
        return "Mapping required", "danger"
    if is_reference_default(row):
        return REFERENCE_DEFAULT_LABEL, "warning"
    return {
        MappingStatus.PUBLISHED: ("Published", "success"),
        MappingStatus.IN_REVIEW: ("In review", "warning"),
        MappingStatus.DRAFT: (
            "Returned" if row.review_note else "Draft",
            "danger" if row.review_note else "neutral",
        ),
        MappingStatus.SUPERSEDED: ("Superseded", "neutral"),
        MappingStatus.RETIRED: ("Retired", "neutral"),
    }.get(row.status, (row.get_status_display(), "neutral"))


RULE_STATUS_FILTERS = (
    ("required", "Mapping required"),
    ("reference", "Reference default"),
    ("draft", "Draft or returned"),
    ("in_review", "In review"),
    ("published", "Published"),
)


def rules_register(principal, *, programme: str = "", status: str = "") -> dict:
    """One row per school-outcome catalogue item: its live rule and, where one
    is being drafted or reviewed, that version too. Four queries."""
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )
    from apps.activity_catalogue.intervention_mapping import (
        PENDING_STATUSES,
        is_reference_default,
    )

    items = list(
        school_outcome_items()
        .order_by("programme_category", "display_name")
        .only("id", "display_name", "programme_category", "activity_type")
    )
    item_ids = [i.id for i in items]
    live, pending = defaultdict(list), defaultdict(list)
    for row in (
        ActivityInterventionMapping.objects.filter(catalogue_item_id__in=item_ids)
        .filter(Q(active=True) | Q(status__in=PENDING_STATUSES))
        .order_by("-is_primary", "priority", "-version")
    ):
        (live if row.active else pending)[row.catalogue_item_id].append(row)
    resolver = ReviewerResolver(principal)
    names = _names(
        [r.reviewed_by for rows in live.values() for r in rows]
        + [r.submitted_by for rows in pending.values() for r in rows]
    )
    programmes = sorted({i.programme_category or "" for i in items})

    rows = []
    for item in items:
        if programme and (item.programme_category or "") != programme:
            continue
        primary = next((r for r in live[item.id] if r.is_primary), None)
        pending_row = pending[item.id][0] if pending[item.id] else None
        shown = primary
        state, tone = rule_state(primary)
        key = (
            "required"
            if primary is None
            else "reference"
            if is_reference_default(primary)
            else "published"
            if primary.status == MappingStatus.PUBLISHED
            else "draft"
        )
        if pending_row is not None:
            pending_state, pending_tone = rule_state(pending_row)
            state = (
                f"{state} · v{pending_row.version} {pending_state.lower()}"
                if primary is not None
                else f"v{pending_row.version} {pending_state.lower()}"
            )
            tone = pending_tone
            key = (
                "in_review"
                if pending_row.status == MappingStatus.IN_REVIEW
                else "draft"
            )
            shown = shown or pending_row
        if status and key != status:
            continue
        can_review = bool(
            pending_row is not None
            and pending_row.status == MappingStatus.IN_REVIEW
            and resolver.basis(
                author_id=pending_row.submitted_by, country=pending_row.country
            )
        )
        rows.append(
            {
                "item": item,
                "programme": item.programme_category or "Not categorised",
                "intervention": _intervention_text(shown) if shown else "—",
                "direction": shown.get_expected_direction_display() if shown else "—",
                "window": _window(shown) if shown else "—",
                "threshold": (
                    f"±{shown.min_meaningful_change:g}"
                    if shown is not None and shown.min_meaningful_change is not None
                    else ("Any change" if shown else "—")
                ),
                "scope": (shown.country or "All countries") if shown else "—",
                "version": f"v{shown.version}" if shown else "—",
                "state": state,
                "tone": tone,
                "reviewed_by": (
                    names.get(primary.reviewed_by, "")
                    if primary is not None and primary.reviewed_by
                    else "—"
                ),
                "pending": pending_row,
                "can_review": can_review,
            }
        )
    return {"rows": rows, "programmes": programmes}


def loan_purposes_register(principal) -> list[dict]:
    """Every active loan purpose with its measurement profile and any version
    of it IA is drafting or reviewing. Three queries."""
    from apps.business_transformation.models import LoanPurpose

    purposes = list(LoanPurpose.objects.filter(active=True).order_by("label"))
    keys = [loan_purpose_key(p) for p in purposes]
    latest: dict[str, IndicatorDefinition] = {}
    for record in IndicatorDefinition.objects.filter(key__in=keys).order_by(
        "key", "-version"
    ):
        latest.setdefault(record.key, record)
    resolver = ReviewerResolver(principal)
    country = principal_country(principal)
    rows = []
    for purpose in purposes:
        record = latest.get(loan_purpose_key(purpose))
        applicable = [c for c in (purpose.applicable_countries or []) if c]
        if purpose.measurement_profile_complete:
            state, tone = "Defined", "success"
        else:
            state, tone = "Measurement not defined", "danger"
        if record is not None and record.status != DefinitionStatus.APPROVED:
            state = f"{state} · v{record.version} {record.get_status_display().lower()}"
            tone = STATUS_TONES.get(record.status, tone)
        rows.append(
            {
                "purpose": purpose,
                "indicators": ", ".join(purpose.impact_indicators or []) or "—",
                "verification": purpose.verification_method or "—",
                "follow_up": f"{purpose.follow_up_days} days",
                "countries": ", ".join(applicable) or "All countries",
                "edtech": "EdTech" if purpose.is_edtech else "",
                "state": state,
                "tone": tone,
                "record": record,
                "in_country": not applicable or not country or country in applicable,
                "can_review": bool(
                    record is not None
                    and record.status == DefinitionStatus.IN_REVIEW
                    and resolver.basis(
                        author_id=record.author_id, country=_author_country(record)
                    )
                ),
            }
        )
    return rows


def definitions_register(principal, kind: str, *, status: str = "") -> list[dict]:
    """Outcome areas or indicators, every version, newest first. Three queries."""
    model = _model_for(kind)
    qs = model.objects.all()
    if kind == "indicator":
        qs = qs.exclude(key__startswith=LOAN_PURPOSE_KEY_PREFIX).select_related(
            "outcome_area"
        )
        qs = qs.order_by("key", "-version")
    else:
        qs = qs.annotate(domain_count=Count("domains")).prefetch_related("domains")
        qs = qs.order_by("code", "-version")
    if status in DefinitionStatus.values:
        qs = qs.filter(status=status)
    records = list(qs)
    authors = {r.author_id for r in records}
    countries = dict(_author_countries(authors))
    names = _names(list(authors) + [r.reviewed_by_id for r in records])
    resolver = ReviewerResolver(principal)
    rows = []
    for record in records:
        country = (getattr(record, "country", "") or "") or countries.get(
            record.author_id, ""
        )
        rows.append(
            {
                "record": record,
                "author": names.get(record.author_id, "—"),
                "reviewer": names.get(record.reviewed_by_id or "", "—"),
                "basis": record.get_review_basis_display()
                if record.review_basis
                else "",
                "state": record.get_status_display(),
                "tone": STATUS_TONES.get(record.status, "neutral"),
                "domains": (
                    ", ".join(
                        INTERVENTION_ABBREVIATIONS.get(d.intervention, d.intervention)
                        for d in record.domains.all()
                    )
                    if kind == "area"
                    else ""
                ),
                "can_edit": may_author(principal)
                and (
                    record.status == DefinitionStatus.APPROVED
                    or (
                        record.status in PENDING
                        and record.author_id == _actor(principal)
                    )
                ),
                "can_submit": may_author(principal)
                and record.status in PENDING
                and record.author_id == _actor(principal),
                "can_review": record.status == DefinitionStatus.IN_REVIEW
                and bool(resolver.basis(author_id=record.author_id, country=country)),
            }
        )
    return rows


def _author_countries(author_ids):
    from apps.accounts.models import StaffProfile

    ids = [a for a in author_ids if a]
    if not ids:
        return []
    return StaffProfile.objects.filter(user_id__in=ids).values_list(
        "user_id", "country"
    )


def framework_counts(principal) -> dict:
    """The register tiles, in five aggregate queries."""
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )
    from apps.business_transformation.models import LoanPurpose

    items = school_outcome_items()
    live = ActivityInterventionMapping.objects.filter(active=True)
    unmapped = items.exclude(
        id__in=live.filter(is_primary=True).values("catalogue_item_id")
    ).count()
    published = live.filter(status=MappingStatus.PUBLISHED).exclude(
        not_ssa_measured_reason__gt=""
    )
    rules = published.aggregate(
        total=Count("id"),
        without_window=Count(
            "id",
            filter=Q(
                follow_up_min_days__isnull=True,
                follow_up_expected_days__isnull=True,
                follow_up_max_days__isnull=True,
            ),
        ),
    )
    indicators = (
        IndicatorDefinition.objects.filter(status=DefinitionStatus.APPROVED)
        .exclude(key__startswith=LOAN_PURPOSE_KEY_PREFIX)
        .count()
    )
    purposes_undefined = LoanPurpose.objects.filter(
        active=True, measurement_profile_complete=False
    ).count()
    return {
        "items_unmapped": unmapped,
        "rules_published": rules["total"],
        "rules_without_window": rules["without_window"],
        "indicators_approved": indicators,
        "loan_purposes_undefined": purposes_undefined,
    }


def awaiting_review(principal) -> dict:
    """What `principal` may review now, by kind — for To-Dos and the page.
    Four queries plus one per country with a pending definition."""
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )

    resolver = ReviewerResolver(principal)
    if resolver.role not in (IA, CD):
        return {"rules": [], "areas": [], "indicators": []}
    rules = [
        row
        for row in ActivityInterventionMapping.objects.filter(
            status=MappingStatus.IN_REVIEW, active=False
        ).select_related("catalogue_item")
        if resolver.basis(author_id=row.submitted_by, country=row.country)
    ]
    records = list(
        OutcomeArea.objects.filter(status=DefinitionStatus.IN_REVIEW)
    ) + list(IndicatorDefinition.objects.filter(status=DefinitionStatus.IN_REVIEW))
    countries = dict(_author_countries({r.author_id for r in records}))
    areas, indicators = [], []
    for record in records:
        country = (getattr(record, "country", "") or "") or countries.get(
            record.author_id, ""
        )
        if not resolver.basis(author_id=record.author_id, country=country):
            continue
        (areas if isinstance(record, OutcomeArea) else indicators).append(record)
    return {"rules": rules, "areas": areas, "indicators": indicators}


def returned_to_me(principal) -> dict:
    """Definitions a reviewer sent back to `principal`. Three queries."""
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )

    actor = _actor(principal)
    if not actor or getattr(principal, "active_role", "") != IA:
        return {"rules": [], "definitions": []}
    rules = list(
        ActivityInterventionMapping.objects.filter(
            status=MappingStatus.DRAFT,
            active=False,
            submitted_by=actor,
            reviewed_at__isnull=False,
        ).select_related("catalogue_item")
    )
    definitions = list(
        OutcomeArea.objects.filter(status=DefinitionStatus.RETURNED, author_id=actor)
    ) + list(
        IndicatorDefinition.objects.filter(
            status=DefinitionStatus.RETURNED, author_id=actor
        )
    )
    return {"rules": rules, "definitions": definitions}
