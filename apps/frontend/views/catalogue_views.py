from functools import wraps

from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.activity_catalogue.authoring import ACTIVITY_KINDS
from apps.budget.costing_service import COSTING_PROFILE_CHOICES, COSTING_PROFILE_LABELS
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
    CatalogueActivityType,
    CatalogueStatus,
    DeliveryMethod,
)
from apps.activity_catalogue.services import list_catalogue, transition_item
from apps.core.enums import SsaIntervention
from apps.core.permissions import has_permission
from apps.core.rbac import Permission


def _catalogue_permission(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect("/login")
            if not has_permission(request.user, permission):
                return HttpResponseForbidden("Activity Catalogue access denied.")
            return view(request, *args, **kwargs)

        # The production-readiness route scanner recognises guarded page views
        # by this attribute (the same contract require_page_permission uses).
        wrapped.has_permission_guard = True
        return wrapped

    return decorator


@_catalogue_permission(Permission.ACTIVITY_CATALOGUE_VIEW.value)
def activity_catalogue_page(request):
    can_manage = has_permission(
        request.user, Permission.ACTIVITY_CATALOGUE_MANAGE.value
    )
    items = list_catalogue(
        intervention=request.GET.get("intervention") or None,
        activity_type=request.GET.get("activity_type") or None,
        delivery_method=request.GET.get("delivery_method") or None,
        project_id=request.GET.get("project_id") or None,
        status=request.GET.get("status") or None,
        include_inactive=can_manage,
    ).prefetch_related("versions")
    from apps.projects.scoping import scoped_projects

    return render(
        request,
        "pages/settings/activity_catalogue.html",
        {
            "items": items,
            "can_manage": can_manage,
            "statuses": CatalogueStatus.choices,
            "activity_types": CatalogueActivityType.choices,
            "delivery_methods": DeliveryMethod.choices,
            "interventions": SsaIntervention.choices,
            "projects": scoped_projects(request.user).order_by("name"),
            "review_queue": (
                ActivityCatalogueReviewQueue.objects.filter(
                    status="needs_review"
                ).order_by("created_at")[:100]
                if can_manage
                else []
            ),
            "all_catalogue_items": (
                ActivityCatalogueItem.objects.order_by("display_name")
                if can_manage
                else []
            ),
            "filters": request.GET,
            "activity_kinds": ACTIVITY_KINDS,
            "costing_profiles": [
                (
                    profile,
                    COSTING_PROFILE_LABELS.get(
                        profile, profile.replace("_", " ").capitalize()
                    ),
                )
                for profile in COSTING_PROFILE_CHOICES
            ],
            "new_open": bool(request.GET.get("new")),
        },
    )


@require_http_methods(["GET", "POST"])
@_catalogue_permission(Permission.ACTIVITY_CATALOGUE_MANAGE.value)
def activity_catalogue_create_action(request):
    """The New activity form (owner, 2026-09-06): a school or a non-school
    activity, typed, delivered and costed like a governed one.

    GET serves the drawer the New activity button opens (owner, 2026-09-07);
    POST creates the item. It was an anchor that jumped to a `<details>` and
    unfolded the form above the catalogue."""
    from django.contrib import messages

    from apps.activity_catalogue.authoring import create_catalogue_item
    from apps.core.exceptions import BadRequest

    if request.method == "GET":
        from apps.activity_catalogue.models import (
            CatalogueActivityType,
            DeliveryMethod,
        )
        from apps.budget.costing_service import (
            COSTING_PROFILE_CHOICES,
            COSTING_PROFILE_LABELS,
        )
        from apps.ssa.models import SsaIntervention

        return render(
            request,
            "partials/catalogue/new_activity_drawer.html",
            {
                "activity_kinds": ACTIVITY_KINDS,
                "activity_types": CatalogueActivityType.choices,
                "delivery_methods": DeliveryMethod.choices,
                "interventions": SsaIntervention.choices,
                "costing_profiles": [
                    (
                        profile,
                        COSTING_PROFILE_LABELS.get(
                            profile, profile.replace("_", " ").capitalize()
                        ),
                    )
                    for profile in COSTING_PROFILE_CHOICES
                ],
            },
        )

    try:
        item = create_catalogue_item(
            {
                "name": request.POST.get("name"),
                "kind": request.POST.get("kind"),
                "activityType": request.POST.get("activity_type"),
                "deliveryMethod": request.POST.get("delivery_method"),
                "costingProfile": request.POST.get("costing_profile"),
                "intervention": request.POST.get("intervention"),
                "targetAudience": request.POST.get("target_audience"),
                "participantCounts": bool(request.POST.get("participant_counts")),
                "multiDay": bool(request.POST.get("multi_day")),
                "description": request.POST.get("description"),
                "reason": request.POST.get("reason"),
            },
            actor_id=getattr(request.user, "user_id", None) or str(request.user.id),
        )
    except BadRequest as exc:
        messages.error(request, str(exc.detail))
        return redirect("/settings/activity-catalogue/?new=1")
    messages.success(request, f"{item.display_name} added to the Activity Catalogue.")
    return redirect(f"/settings/activity-catalogue/?status=active#item-{item.id}")


@require_http_methods(["POST"])
@_catalogue_permission(Permission.ACTIVITY_CATALOGUE_MANAGE.value)
def activity_catalogue_lifecycle_action(request, item_id):
    item = get_object_or_404(ActivityCatalogueItem, id=item_id)
    transition_item(
        item,
        status=request.POST.get("status", ""),
        actor_id=getattr(request.user, "user_id", None) or str(request.user.id),
        reason=request.POST.get("reason", ""),
    )
    return redirect("/settings/activity-catalogue/")


@require_http_methods(["POST"])
@_catalogue_permission(Permission.ACTIVITY_CATALOGUE_MANAGE.value)
@transaction.atomic
def activity_catalogue_review_resolve_action(request, review_id):
    from apps.core.exceptions import BadRequest

    review = get_object_or_404(
        ActivityCatalogueReviewQueue.objects.select_for_update(),
        id=review_id,
        status="needs_review",
    )
    item = get_object_or_404(
        ActivityCatalogueItem,
        stable_code=(request.POST.get("stable_code") or "").strip(),
    )
    note = (request.POST.get("resolution_note") or "").strip()
    if not note:
        raise BadRequest("A resolution note is required.")
    if review.source_model == "activities.Activity":
        from apps.activities.models import Activity
        from apps.activity_catalogue.services import apply_catalogue_snapshot

        activity = get_object_or_404(Activity, id=review.source_record_id)
        apply_catalogue_snapshot(
            activity,
            item=item,
            requested_intervention=activity.focus_intervention,
            source_activity=activity.follow_up_of_activity,
            recommendation_reason="Authorized historical Catalogue review.",
            override_reason=note,
        )
    elif review.source_model == "partners.PartnerAssignment":
        from apps.partners.models import PartnerAssignment

        if not item.partner_delivery_allowed:
            raise BadRequest("The selected Catalogue item disallows Partner delivery.")
        assignment = get_object_or_404(PartnerAssignment, id=review.source_record_id)
        assignment.catalogue_item = item
        assignment.assignment_mode = "specific_activity"
        assignment.catalogue_snapshot = item.snapshot()
        assignment.expected_activity_type = item.workflow_kind
        assignment.save(
            update_fields=[
                "catalogue_item",
                "assignment_mode",
                "catalogue_snapshot",
                "expected_activity_type",
                "updated_at",
            ]
        )
    else:
        raise BadRequest("This review type requires a dedicated correction workflow.")
    actor_id = getattr(request.user, "user_id", None) or str(request.user.id)
    from apps.activity_catalogue.services import resolve_review

    resolve_review(review, item=item, actor_id=actor_id, note=note)
    return redirect("/settings/activity-catalogue/")
