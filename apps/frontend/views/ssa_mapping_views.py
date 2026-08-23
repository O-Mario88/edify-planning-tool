"""Impact Assessment's SSA mapping queue, inside the Priorities workspace.

Not a separate system: this is the section of Priorities where IA says what
each school-facing activity is meant to move, and how that will later be
judged. The queue is derived from state — an activity leaves it the moment it
has a mapping — so there is no list anyone has to maintain.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render

from apps.activity_catalogue import intervention_mapping as im
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ExpectedDirection,
    MappingRelationship,
    MappingStatus,
    MeasurementRole,
)
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import Permission

from apps.core.htmx_errors import error_fragment


def _may_manage(user) -> bool:
    return has_permission(user, Permission.SSA_ACTIVITY_MAPPING_MANAGE.value)


@require_page_permission("priorities_master")
def ssa_mapping_page(request):
    """School-facing activities, and what each is measured against."""
    items = list(
        ActivityCatalogueItem.objects.filter(status="active", requires_school=True)
        .order_by("activity_type", "display_name")
        .prefetch_related("intervention_mappings")
    )
    labels = dict(SsaIntervention.choices)

    unmapped, mapped = [], []
    for item in items:
        resolved = im.mapping_for(item)
        primary = resolved["primary"]
        row = {
            "item": item,
            "primary": primary,
            "primary_label": labels.get(getattr(primary, "intervention", None), ""),
            "secondary_labels": [
                labels.get(m.intervention, "") for m in resolved["secondary"]
            ],
            "not_ssa_measured": resolved["not_ssa_measured"],
            "published": bool(primary and primary.status == MappingStatus.PUBLISHED),
        }
        (unmapped if resolved["needs_mapping"] else mapped).append(row)

    return render(
        request,
        "pages/hr/ssa_mapping.html",
        {
            "unmapped": unmapped,
            "mapped": mapped,
            "unmapped_count": len(unmapped),
            "mapped_count": len(mapped),
            "can_manage": _may_manage(request.user),
        },
    )


@require_page_permission("priorities_master")
def ssa_mapping_drawer(request, item_id):
    """The focused drawer for one activity's mapping."""
    if not _may_manage(request.user):
        return error_fragment(
            Forbidden(
                "Only Impact Assessment sets which SSA intervention an "
                "activity is measured against."
            ),
            action="SSA Mapping",
            status=403,
        )
    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    if item is None:
        return error_fragment(
            BadRequest("That activity is not in the catalogue."),
            action="SSA Mapping",
            status=400,
        )

    resolved = im.mapping_for(item)
    return render(
        request,
        "partials/hr/ssa_mapping_drawer.html",
        {
            "item": item,
            "current": resolved["primary"],
            "secondary": resolved["secondary"],
            "interventions": SsaIntervention.choices,
            "bands": im.SCORE_BANDS,
            "relationships": MappingRelationship.choices,
            "measurement_roles": MeasurementRole.choices,
            "directions": ExpectedDirection.choices,
            "drawer_size": "md",
        },
    )


@require_page_permission("priorities_master")
def ssa_mapping_action(request, item_id):
    """Save, publish, or record that an activity is not SSA-measured."""
    if request.method != "POST":
        return HttpResponse(status=405)

    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    if item is None:
        return error_fragment(
            BadRequest("That activity is not in the catalogue."),
            action="SSA Mapping",
            status=400,
        )

    try:
        if request.POST.get("not_ssa_measured"):
            im.classify_not_ssa_measured(
                request.user, item, request.POST.get("not_ssa_measured_reason", "")
            )
        else:
            mapping = im.link_intervention(
                request.user,
                item,
                {
                    "intervention": request.POST.get("intervention"),
                    "relationship": request.POST.get("relationship"),
                    "measurement_role": request.POST.get("measurement_role"),
                    "expected_direction": request.POST.get("expected_direction"),
                    "eligible_bands": request.POST.getlist("eligible_bands"),
                    "eligibility_note": request.POST.get("eligibility_note"),
                    "follow_up_min_days": request.POST.get("follow_up_min_days"),
                    "follow_up_expected_days": request.POST.get(
                        "follow_up_expected_days"
                    ),
                    "follow_up_max_days": request.POST.get("follow_up_max_days"),
                    "min_meaningful_change": (
                        request.POST.get("min_meaningful_change") or None
                    ),
                },
            )
            if request.POST.get("publish"):
                im.publish(request.user, mapping)
    except (BadRequest, Forbidden) as exc:
        return error_fragment(exc, action="SSA Mapping", status=400)

    response = HttpResponse(status=204)
    response["HX-Redirect"] = "/priorities/ssa-mapping"
    return response
