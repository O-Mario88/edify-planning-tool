"""Which SSA intervention an activity is meant to move, and how that is judged.

The mapping is a governed record rather than a label. It answers, for one
catalogue item: which intervention is the point of this work, which others it
also touches, which schools it is for, and how long before a re-assessment
means anything. A project's measurement later reads those rules rather than
guessing them.

Authority sits with Impact Assessment alone. Setting a country target and
deciding what counts as that target having worked are different powers, and
the second must not arrive as a side effect of the first.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import Permission
from apps.core.permissions import has_permission

from .models import (
    ActivityInterventionMapping,
    MappingAuthor,
    MappingMode,
    MappingRelationship,
    MappingStatus,
    MeasurementRole,
    ExpectedDirection,
)

#: The four bands a score rule may name, from apps.core.enums.ssa_score_band.
SCORE_BANDS = ("Critical", "Warning", "Improving", "Strong")


def _assert_may_manage(principal) -> None:
    if not has_permission(principal, Permission.SSA_ACTIVITY_MAPPING_MANAGE.value):
        raise Forbidden(
            "Only Impact Assessment sets which SSA intervention an activity is "
            "measured against."
        )


def link_intervention(principal, catalogue_item, data: dict):
    """Record what this activity is for, and how it will be judged.

    A published mapping is not edited in place — completed activities were
    measured under it, and rewriting it would change what they meant. Changing
    a published rule supersedes it and starts a new version.
    """
    _assert_may_manage(principal)

    intervention = (data.get("intervention") or "").strip()
    relationship = data.get("relationship") or MappingRelationship.PRIMARY

    if intervention not in SsaIntervention.values:
        raise BadRequest("Choose one of the eight SSA interventions.")

    bands = [b for b in (data.get("eligible_bands") or []) if b in SCORE_BANDS]

    window = _validated_window(data)
    threshold = data.get("min_meaningful_change")

    with transaction.atomic():
        live = ActivityInterventionMapping.objects.select_for_update().filter(
            catalogue_item=catalogue_item, active=True
        )
        if relationship == MappingRelationship.PRIMARY:
            # One primary per activity. An activity may genuinely move several
            # interventions, but it has one purpose, and analytics that
            # weighed every link equally could not say which.
            existing_primary = live.filter(
                relationship=MappingRelationship.PRIMARY
            ).exclude(intervention=intervention)
            for prior in existing_primary:
                _supersede(prior, principal)

        current = live.filter(intervention=intervention).first()
        if current is not None and current.status == MappingStatus.PUBLISHED:
            _supersede(current, principal)
            version = current.version + 1
        else:
            version = current.version if current else 1
            if current is not None:
                current.delete()

        return ActivityInterventionMapping.objects.create(
            catalogue_item=catalogue_item,
            intervention=intervention,
            mapping_mode=MappingMode.FIXED,
            relationship=relationship,
            is_primary=relationship == MappingRelationship.PRIMARY,
            measurement_role=(
                data.get("measurement_role") or MeasurementRole.ELIGIBILITY_AND_OUTCOME
            ),
            expected_direction=(
                data.get("expected_direction") or ExpectedDirection.IMPROVE
            ),
            eligible_bands=bands,
            eligibility_note=(data.get("eligibility_note") or "").strip(),
            follow_up_min_days=window["min"],
            follow_up_expected_days=window["expected"],
            follow_up_max_days=window["max"],
            min_meaningful_change=threshold,
            status=MappingStatus.DRAFT,
            version=version,
            authored_by=MappingAuthor.IMPACT_ASSESSMENT,
            country=(data.get("country") or "").strip(),
            fy=(data.get("fy") or "").strip(),
            active=True,
        )


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
    lo, hi = window["min"], window["max"]
    if lo is not None and hi is not None and lo > hi:
        raise BadRequest(
            "The earliest valid follow-up cannot fall after the latest one."
        )
    return window


def _supersede(mapping, principal) -> None:
    mapping.status = MappingStatus.SUPERSEDED
    mapping.active = False
    mapping.effective_to = timezone.now().date()
    mapping.save(
        update_fields=["status", "active", "effective_to", "updated_at"]
    )


def publish(principal, mapping):
    """Make the mapping the rule new activities are measured under."""
    _assert_may_manage(principal)

    if mapping.status == MappingStatus.PUBLISHED:
        raise BadRequest("That mapping is already published.")
    if not mapping.intervention:
        raise BadRequest(
            "A mapping needs an intervention before it can govern anything."
        )
    mapping.status = MappingStatus.PUBLISHED
    mapping.approved_by = str(getattr(principal, "id", "") or "")
    mapping.approved_at = timezone.now()
    mapping.effective_from = timezone.now().date()
    mapping.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "effective_from",
            "updated_at",
        ]
    )
    return mapping


def classify_not_ssa_measured(principal, catalogue_item, reason: str):
    """Say plainly that an activity is not judged by a school's scores.

    An internal planning meeting does not improve a school's Leadership score,
    and attaching it to an intervention to satisfy a required field would put
    governance work into school-improvement analytics. The honest answer is
    recorded, with the reason, rather than approximated.
    """
    _assert_may_manage(principal)

    reason = (reason or "").strip()
    if not reason:
        raise BadRequest(
            "Say why this activity is not measured by an SSA score. An "
            "unexplained exemption is indistinguishable from an oversight."
        )

    with transaction.atomic():
        for prior in ActivityInterventionMapping.objects.select_for_update().filter(
            catalogue_item=catalogue_item, active=True
        ):
            _supersede(prior, principal)

        return ActivityInterventionMapping.objects.create(
            catalogue_item=catalogue_item,
            intervention=None,
            mapping_mode=MappingMode.ADMINISTRATIVE,
            relationship=MappingRelationship.PRIMARY,
            is_primary=True,
            not_ssa_measured_reason=reason,
            status=MappingStatus.PUBLISHED,
            approved_by=str(getattr(principal, "id", "") or ""),
            approved_at=timezone.now(),
            authored_by=MappingAuthor.IMPACT_ASSESSMENT,
            active=True,
        )


def mapping_for(catalogue_item):
    """The rules an activity created now would be measured under."""
    rows = list(
        ActivityInterventionMapping.objects.filter(
            catalogue_item=catalogue_item, active=True
        ).order_by("-is_primary", "priority")
    )
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
