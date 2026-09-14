"""Which SSA intervention an activity is meant to move, and how that is judged.

The mapping is a governed record rather than a label. It answers, for one
catalogue item: which intervention is the point of this work, which others it
also touches, which schools it is for, and how long before a re-assessment
means anything. A project's measurement later reads those rules rather than
guessing them.

Authority sits with Impact Assessment alone. Setting a country target and
deciding what counts as that target having worked are different powers, and
the second must not arrive as a side effect of the first.

Review (owner, 2026-09-13). A measurement rule is never published by the
person who wrote it:

  Save draft → Submit for review (a change reason is required) → Review.

The reviewer is a second Impact Assessment officer in the rule's country; a
country with a single officer has its Country Director acknowledge instead —
an acknowledgement, not authorship, so the Country Director still cannot write
a rule (apps.impact.review). Approving publishes the new version and
supersedes the one it replaces; returning sends the draft back with a note.

Drafts are never live. Planning, SSA recommendations and plan alignment read
the ACTIVE rows, and measurement reads the PUBLISHED ones; a draft or a rule in
review is kept inactive beside the live version, so nothing an officer has not
had reviewed changes what planners may choose or how a school is judged. The
rows the seeder wrote are live but were never reviewed, and the register says
so ("Reference default – not yet reviewed by IA").

Every transition writes an audit row inside the same transaction, and the
version history stays readable: a superseded rule is what some finished
enrolment was measured under.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole, Permission
from apps.core.permissions import has_permission

from .models import (
    MACHINE_AUTHORS,
    NULL_INTERVENTION_MODES,
    ActivityInterventionMapping,
    ExpectedDirection,
    MappingAuthor,
    MappingMode,
    MappingRelationship,
    MappingStatus,
    MeasurementRole,
)

#: The four bands a score rule may name, from apps.core.enums.ssa_score_band.
SCORE_BANDS = ("Critical", "Warning", "Improving", "Strong")

#: The words the register shows beside a seeded row nobody in IA has reviewed.
REFERENCE_DEFAULT_LABEL = "Reference default – not yet reviewed by IA"

#: Modes an Impact Assessment officer may choose for an activity. Inherit,
#: prerequisite and administrative modes belong to catalogue governance; a
#: rule saved on such an item keeps the mode it already has.
IA_SELECTABLE_MODES = (
    MappingMode.FIXED,
    MappingMode.MULTIPLE_ALLOWED,
    MappingMode.ANY_SSA_INTERVENTION,
)

PENDING_STATUSES = (MappingStatus.DRAFT, MappingStatus.IN_REVIEW)

#: Notification events; routed in apps.notifications.services (IA-F block).
EVENT_REVIEW_REQUESTED = "ia.framework.review_requested"
EVENT_REVIEW_DECIDED = "ia.framework.review_decided"


def _assert_may_manage(principal) -> None:
    if not has_permission(principal, Permission.SSA_ACTIVITY_MAPPING_MANAGE.value):
        raise Forbidden(
            "Only Impact Assessment sets which SSA intervention an activity is "
            "measured against."
        )


def _actor(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def _country(principal) -> str:
    profile = getattr(principal, "staff_profile", None)
    return (getattr(profile, "country", "") or "").strip()


def _audit(action: str, mapping, principal, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="ActivityInterventionMapping",
        subject_id=str(mapping.id),
        actor_id=_actor(principal) or None,
        actor_role=getattr(principal, "active_role", None),
        reason=(payload or {}).get("reason"),
        payload={
            "catalogue_item": mapping.catalogue_item_id,
            "version": mapping.version,
            "status": mapping.status,
            **(payload or {}),
        },
    )


def rule_snapshot(mapping) -> dict:
    """The fields that decide measurement, for audit before/after payloads."""

    return {
        "intervention": mapping.intervention,
        "mapping_mode": mapping.mapping_mode,
        "relationship": mapping.relationship,
        "measurement_role": mapping.measurement_role,
        "expected_direction": mapping.expected_direction,
        "eligible_bands": list(mapping.eligible_bands or []),
        "eligibility_note": mapping.eligibility_note,
        "follow_up_min_days": mapping.follow_up_min_days,
        "follow_up_expected_days": mapping.follow_up_expected_days,
        "follow_up_max_days": mapping.follow_up_max_days,
        "min_meaningful_change": (
            str(mapping.min_meaningful_change)
            if mapping.min_meaningful_change is not None
            else None
        ),
        "not_ssa_measured_reason": mapping.not_ssa_measured_reason,
        "country": mapping.country,
    }


def is_reference_default(mapping) -> bool:
    return bool(
        mapping
        and mapping.authored_by in MACHINE_AUTHORS
        and mapping.status != MappingStatus.PUBLISHED
    )


# ── Drafting ────────────────────────────────────────────────────────────────


def _live_base(item, relationship: str, intervention: str | None):
    live = ActivityInterventionMapping.objects.filter(catalogue_item=item, active=True)
    if relationship == MappingRelationship.PRIMARY:
        return live.filter(relationship=MappingRelationship.PRIMARY).first()
    return live.filter(
        relationship=MappingRelationship.SECONDARY, intervention=intervention
    ).first()


def _pending_slot(item, relationship: str, intervention: str | None):
    rows = ActivityInterventionMapping.objects.select_for_update().filter(
        catalogue_item=item,
        active=False,
        status__in=PENDING_STATUSES,
        relationship=relationship,
    )
    if relationship == MappingRelationship.SECONDARY:
        rows = rows.filter(intervention=intervention)
    return rows.order_by("-version").first()


def _threshold(data: dict):
    raw = data.get("min_meaningful_change")
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise BadRequest(
            "The minimum meaningful change is a number of points."
        ) from exc
    if value < 0 or value > 10:
        raise BadRequest("A meaningful change sits between 0 and 10 SSA points.")
    return value


def _mode_for(data: dict, base) -> str:
    requested = (data.get("mapping_mode") or "").strip()
    if requested:
        if requested not in IA_SELECTABLE_MODES:
            raise BadRequest(
                "Choose whether the activity names its intervention or the "
                "planner selects one."
            )
        if base is not None and base.mapping_mode not in (
            *IA_SELECTABLE_MODES,
            MappingMode.ADMINISTRATIVE,
        ):
            # Inherit and prerequisite activities are defined by catalogue
            # governance; the rule keeps the mode rather than converting it.
            return base.mapping_mode
        return requested
    if base is not None and base.mapping_mode != MappingMode.ADMINISTRATIVE:
        # Never convert a planner-selects, inherit or prerequisite activity
        # into a FIXED one as a side effect of editing its window: planning
        # would then refuse every intervention but one.
        return base.mapping_mode
    return MappingMode.FIXED


def save_draft(principal, catalogue_item, data: dict):
    """Record, as a draft, what this activity is for and how it will be judged.

    The draft sits beside the live version and changes nothing until a second
    reviewer approves it. Saving again edits the same draft. The mapping mode
    of the live row is kept unless the officer explicitly chooses another
    selectable mode.
    """
    _assert_may_manage(principal)

    relationship = data.get("relationship") or MappingRelationship.PRIMARY
    if relationship not in MappingRelationship.values:
        raise BadRequest("Choose a primary or secondary relationship.")
    posted_intervention = (data.get("intervention") or "").strip()
    base = _live_base(
        catalogue_item,
        relationship,
        posted_intervention if relationship == MappingRelationship.SECONDARY else None,
    )
    mode = _mode_for(data, base)
    if mode in NULL_INTERVENTION_MODES:
        # The rule applies to whichever intervention the planner chose (or the
        # source activity carries); the row itself names none.
        if relationship == MappingRelationship.SECONDARY:
            raise BadRequest("A secondary intervention has to name the intervention.")
        intervention = None
    else:
        if posted_intervention not in SsaIntervention.values:
            raise BadRequest("Choose one of the eight SSA interventions.")
        intervention = posted_intervention

    direction = data.get("expected_direction") or ExpectedDirection.IMPROVE
    if direction not in ExpectedDirection.values:
        raise BadRequest("Choose what success looks like for this activity.")
    role = data.get("measurement_role") or MeasurementRole.ELIGIBILITY_AND_OUTCOME
    if role not in MeasurementRole.values:
        raise BadRequest("Choose what the score is used for.")

    bands = [b for b in (data.get("eligible_bands") or []) if b in SCORE_BANDS]
    window = _validated_window(data)
    threshold = _threshold(data)
    fields = {
        "intervention": intervention,
        "mapping_mode": mode,
        "relationship": relationship,
        "is_primary": relationship == MappingRelationship.PRIMARY,
        "measurement_role": role,
        "expected_direction": direction,
        "eligible_bands": bands,
        "eligibility_note": (data.get("eligibility_note") or "").strip(),
        "follow_up_min_days": window["min"],
        "follow_up_expected_days": window["expected"],
        "follow_up_max_days": window["max"],
        "min_meaningful_change": threshold,
        "not_ssa_measured_reason": "",
        "change_reason": (data.get("change_reason") or "").strip(),
        "fy": (data.get("fy") or "").strip(),
    }
    return _write_draft(principal, catalogue_item, fields)


def _write_draft(principal, catalogue_item, fields: dict):
    actor = _actor(principal)
    with transaction.atomic():
        pending = _pending_slot(
            catalogue_item, fields["relationship"], fields["intervention"]
        )
        if pending is not None:
            if pending.status == MappingStatus.IN_REVIEW:
                raise BadRequest(
                    "This rule is with a reviewer. It can change again once they "
                    "return it."
                )
            if pending.submitted_by and pending.submitted_by != actor:
                raise Forbidden(
                    "Another Impact Assessment officer started this draft; they "
                    "finish it, or you review it once they submit it."
                )
            before = rule_snapshot(pending)
            for name, value in fields.items():
                if name == "change_reason" and not value:
                    continue
                setattr(pending, name, value)
            pending.submitted_by = actor
            pending.save()
            _audit(
                "ia.mapping.draft_updated",
                pending,
                principal,
                {"before": before, "after": rule_snapshot(pending)},
            )
            return pending

        last = ActivityInterventionMapping.objects.filter(
            catalogue_item=catalogue_item
        ).aggregate(v=Max("version"))["v"]
        mapping = ActivityInterventionMapping.objects.create(
            catalogue_item=catalogue_item,
            status=MappingStatus.DRAFT,
            version=(last or 0) + 1,
            authored_by=MappingAuthor.IMPACT_ASSESSMENT,
            country=_country(principal),
            active=False,
            submitted_by=actor,
            **fields,
        )
        live = _live_base(
            catalogue_item, fields["relationship"], fields["intervention"]
        )
        _audit(
            "ia.mapping.drafted",
            mapping,
            principal,
            {
                "before": rule_snapshot(live) if live else None,
                "after": rule_snapshot(mapping),
            },
        )
        return mapping


def link_intervention(principal, catalogue_item, data: dict):
    """Save a draft rule (the name planning and tests have always called).

    A published mapping is not edited in place — completed activities were
    measured under it, and rewriting it would change what they meant. The
    draft becomes a new version when a reviewer approves it.
    """
    return save_draft(principal, catalogue_item, data)


def classify_not_ssa_measured(principal, catalogue_item, reason: str, change_reason=""):
    """Say plainly that an activity is not judged by a school's scores.

    An internal planning meeting does not improve a school's Leadership score,
    and attaching it to an intervention to satisfy a required field would put
    governance work into school-improvement analytics. The honest answer is
    recorded, with the reason, rather than approximated — and, like any rule,
    reviewed by a second person before it takes effect.
    """
    _assert_may_manage(principal)

    reason = (reason or "").strip()
    if not reason:
        raise BadRequest(
            "Say why this activity is not measured by an SSA score. An "
            "unexplained exemption is indistinguishable from an oversight."
        )
    fields = {
        "intervention": None,
        "mapping_mode": MappingMode.ADMINISTRATIVE,
        "relationship": MappingRelationship.PRIMARY,
        "is_primary": True,
        "measurement_role": MeasurementRole.ELIGIBILITY_AND_OUTCOME,
        "expected_direction": ExpectedDirection.IMPROVE,
        "eligible_bands": [],
        "eligibility_note": "",
        "follow_up_min_days": None,
        "follow_up_expected_days": None,
        "follow_up_max_days": None,
        "min_meaningful_change": None,
        "not_ssa_measured_reason": reason,
        "change_reason": (change_reason or "").strip(),
        "fy": "",
    }
    return _write_draft(principal, catalogue_item, fields)


def _validated_window(data: dict) -> dict:
    """A follow-up window has to be orderable to mean anything."""

    def _days(key):
        raw = data.get(key)
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequest("Follow-up windows are a number of days.") from exc
        if value < 0:
            raise BadRequest("A follow-up window cannot be negative.")
        return value

    window = {
        "min": _days("follow_up_min_days"),
        "expected": _days("follow_up_expected_days"),
        "max": _days("follow_up_max_days"),
    }
    lo, mid, hi = window["min"], window["expected"], window["max"]
    if lo is not None and hi is not None and lo > hi:
        raise BadRequest(
            "The earliest valid follow-up cannot fall after the latest one."
        )
    if mid is not None and (
        (lo is not None and mid < lo) or (hi is not None and mid > hi)
    ):
        raise BadRequest(
            "The expected follow-up has to fall inside the earliest and latest days."
        )
    return window


# ── Review ──────────────────────────────────────────────────────────────────


def _locked(mapping):
    row = (
        ActivityInterventionMapping.objects.select_for_update()
        .filter(id=mapping.id)
        .first()
    )
    if row is None:
        raise NotFoundError("That measurement rule no longer exists.")
    return row


def submit_for_review(principal, mapping, change_reason: str = ""):
    """Hand a draft to a second reviewer. The reason says what changed and why."""
    _assert_may_manage(principal)
    actor = _actor(principal)
    with transaction.atomic():
        row = _locked(mapping)
        if row.status != MappingStatus.DRAFT or row.active:
            raise BadRequest("Only a draft can be submitted for review.")
        if row.submitted_by and row.submitted_by != actor:
            raise Forbidden("The officer who wrote this draft submits it.")
        reason = (change_reason or row.change_reason or "").strip()
        if not reason:
            raise BadRequest(
                "Say what changed and why. A reviewer cannot judge a rule change "
                "whose reason nobody recorded."
            )
        row.change_reason = reason
        row.status = MappingStatus.IN_REVIEW
        row.submitted_by = actor
        row.submitted_at = timezone.now()
        # A resubmission after a return is a fresh review; the earlier note
        # stays in the audit trail.
        row.reviewed_by, row.reviewed_at = "", None
        row.review_basis, row.review_note = "", ""
        row.save(
            update_fields=[
                "change_reason",
                "status",
                "submitted_by",
                "submitted_at",
                "reviewed_by",
                "reviewed_at",
                "review_basis",
                "review_note",
                "updated_at",
            ]
        )
        _audit("ia.mapping.submitted", row, principal, {"reason": reason})
    _notify_reviewers(row)
    return row


def review_basis_for(principal, mapping) -> str | None:
    """How `principal` may review `mapping`, or None (apps.impact.review)."""
    from apps.impact.review import reviewer_basis

    if mapping.status != MappingStatus.IN_REVIEW:
        return None
    return reviewer_basis(
        principal, author_id=mapping.submitted_by, country=mapping.country
    )


def review(principal, mapping, *, decision: str, note: str = ""):
    """Approve (publish) or return a rule in review.

    Approving supersedes the live version it replaces: for a primary, the
    item's live primary; for any rule, a live row with the same intervention
    and mode. The superseded rows stay readable. Returning needs a note, and
    the draft goes back to its author.
    """
    from apps.impact.review import assert_can_review

    note = (note or "").strip()
    if decision not in ("approve", "return"):
        raise BadRequest("Approve the rule or return it with a note.")
    with transaction.atomic():
        row = _locked(mapping)
        if row.status != MappingStatus.IN_REVIEW:
            raise BadRequest("Only a rule submitted for review can be reviewed.")
        basis = assert_can_review(
            principal, author_id=row.submitted_by, country=row.country
        )
        now = timezone.now()
        row.reviewed_by = _actor(principal)
        row.reviewed_at = now
        row.review_basis = basis
        row.review_note = note
        if decision == "return":
            if not note:
                raise BadRequest("Say what has to change before it can be approved.")
            row.status = MappingStatus.DRAFT
            row.save()
            _audit("ia.mapping.returned", row, principal, {"reason": note})
        else:
            if (
                not row.intervention
                and not row.not_ssa_measured_reason
                and (row.mapping_mode not in NULL_INTERVENTION_MODES)
            ):
                raise BadRequest(
                    "A mapping needs an intervention before it can govern anything."
                )
            for prior in _rows_replaced_by(row):
                before = rule_snapshot(prior)
                _supersede(prior, principal)
                _audit(
                    "ia.mapping.superseded",
                    prior,
                    principal,
                    {"superseded_by": row.id, "before": before},
                )
            row.status = MappingStatus.PUBLISHED
            row.active = True
            row.approved_by = row.reviewed_by
            row.approved_at = now
            row.effective_from = timezone.localdate()
            row.effective_to = None
            row.save()
            _audit(
                "ia.mapping.published",
                row,
                principal,
                {"basis": basis, "after": rule_snapshot(row)},
            )
    _notify_author(row, decision)
    return row


def _rows_replaced_by(row):
    live = ActivityInterventionMapping.objects.select_for_update().filter(
        catalogue_item_id=row.catalogue_item_id, active=True
    )
    replaced = {}
    if row.not_ssa_measured_reason:
        # Not measured at all: every live intervention link for the item goes.
        for prior in live:
            replaced[prior.id] = prior
    if row.relationship == MappingRelationship.PRIMARY:
        for prior in live.filter(relationship=MappingRelationship.PRIMARY):
            replaced[prior.id] = prior
    same_slot = live.filter(mapping_mode=row.mapping_mode)
    same_slot = (
        same_slot.filter(intervention=row.intervention)
        if row.intervention
        else same_slot.filter(intervention__isnull=True)
    )
    for prior in same_slot:
        replaced[prior.id] = prior
    return [prior for prior in replaced.values() if prior.id != row.id]


def publish(principal, mapping):
    """Approve a rule in review — the reviewer's publish, never the author's."""
    status = (
        ActivityInterventionMapping.objects.filter(id=mapping.id)
        .values_list("status", flat=True)
        .first()
    )
    if status == MappingStatus.PUBLISHED:
        raise BadRequest("That mapping is already published.")
    if status != MappingStatus.IN_REVIEW:
        raise BadRequest(
            "Submit the rule for review first; a second reviewer publishes it."
        )
    return review(principal, mapping, decision="approve")


def _supersede(mapping, principal) -> None:
    mapping.status = MappingStatus.SUPERSEDED
    mapping.active = False
    mapping.effective_to = timezone.localdate()
    mapping.save(update_fields=["status", "active", "effective_to", "updated_at"])


# ── Notices ─────────────────────────────────────────────────────────────────


def reviewer_ids(country: str, author_id: str) -> list[str]:
    """Who is asked to review: the country's other IA officers, or — where
    there is none — its Country Director (apps.impact.review)."""
    from apps.accounts.models import User
    from apps.impact.review import ia_officer_ids

    peers = [i for i in ia_officer_ids(country) if str(i) != str(author_id)]
    if peers or not country:
        return peers
    return list(
        User.objects.filter(
            roles__contains=[EdifyRole.COUNTRY_DIRECTOR.value],
            is_active=True,
            deleted_at__isnull=True,
            staff_profile__country=country,
        ).values_list("id", flat=True)
    )


def _notify_reviewers(mapping) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_REQUESTED,
            category="ia",
            priority="high",
            title="Measurement rule to review",
            body=(
                f"{mapping.catalogue_item.display_name} (v{mapping.version}): "
                f"{mapping.change_reason}"
            )[:500],
            context_type="ActivityInterventionMapping",
            context_id=mapping.id,
            recipients=reviewer_ids(mapping.country, mapping.submitted_by),
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the submission
        pass


def _notify_author(mapping, decision: str) -> None:
    try:
        from apps.notifications.services import (
            WorkflowNotificationService,
            resolve_condition,
        )

        resolve_condition(
            EVENT_REVIEW_REQUESTED, "ActivityInterventionMapping", mapping.id
        )
        if not mapping.submitted_by:
            return
        title = (
            "Measurement rule published"
            if decision == "approve"
            else "Measurement rule returned"
        )
        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_DECIDED,
            category="ia",
            priority="normal" if decision == "approve" else "high",
            title=title,
            body=(
                f"{mapping.catalogue_item.display_name} (v{mapping.version})"
                + (f": {mapping.review_note}" if mapping.review_note else "")
            )[:500],
            context_type="ActivityInterventionMapping",
            context_id=mapping.id,
            recipients=[mapping.submitted_by],
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the decision
        pass


# ── Reading ─────────────────────────────────────────────────────────────────


def mapping_for(catalogue_item):
    """The rules an activity created now would be measured under."""
    rows = list(
        ActivityInterventionMapping.objects.filter(
            catalogue_item=catalogue_item, active=True
        ).order_by("-is_primary", "priority")
    )
    return _resolve_rows(rows)


def _resolve_rows(rows):
    primary = next(
        (r for r in rows if r.relationship == MappingRelationship.PRIMARY), None
    )
    return {
        "primary": primary,
        "secondary": [
            r for r in rows if r.relationship == MappingRelationship.SECONDARY
        ],
        "not_ssa_measured": bool(primary and primary.not_ssa_measured_reason),
        "needs_mapping": primary is None,
    }


def pending_for(catalogue_item):
    """Drafts and rules in review for the item, newest first."""
    return list(
        ActivityInterventionMapping.objects.filter(
            catalogue_item=catalogue_item,
            active=False,
            status__in=PENDING_STATUSES,
        ).order_by("-version")
    )


def history_for(catalogue_item):
    """Every version of every rule the item has carried, newest first."""
    return list(
        ActivityInterventionMapping.objects.filter(
            catalogue_item=catalogue_item
        ).order_by("-version", "-created_at")
    )
