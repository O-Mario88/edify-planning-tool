"""Impact Assessment's measurement rules: which SSA domain an activity is meant
to move, and how that is judged later.

The register moved into the Measurement Framework (/ia/framework/, tab
"Measurement rules", IA review 2026-09-13). /priorities/ssa-mapping sends the
framework's readers there and stays a read-only register for the other roles
that hold the ssa_mapping page (RVP, Programme Lead, Project Coordinator).

Every view here is gated on the ssa_mapping page. Drafting is Impact
Assessment's alone (ssaActivityMapping.manage); reviewing belongs to a second
IA officer in the rule's country, or the Country Director where there is no
second officer — an acknowledgement, never authorship
(apps.activity_catalogue.intervention_mapping, apps.impact.review).
"""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.activity_catalogue import intervention_mapping as im
from apps.activity_catalogue.models import (
    NULL_INTERVENTION_MODES,
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    ExpectedDirection,
    MappingMode,
    MappingRelationship,
    MappingStatus,
    MeasurementRole,
)
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.htmx_errors import error_fragment
from apps.core.permissions import (
    RolePermissionService,
    has_permission,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field

RULES_URL = "/ia/framework/?tab=rules"

MODE_CHOICES = (
    (MappingMode.FIXED, "This activity names its SSA domain"),
    (MappingMode.MULTIPLE_ALLOWED, "One of several named domains"),
    (MappingMode.ANY_SSA_INTERVENTION, "The planner selects the domain"),
)


def _may_manage(user) -> bool:
    return has_permission(user, Permission.SSA_ACTIVITY_MAPPING_MANAGE.value)


def _names(ids) -> dict[str, str]:
    from apps.accounts.models import User

    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(User.objects.filter(id__in=wanted).values_list("id", "name"))


@require_page_permission("ssa_mapping")
def ssa_mapping_page(request):
    """The framework's readers work the rules on /ia/framework/; every other
    ssa_mapping reader gets the read-only register."""
    if RolePermissionService.can_view_page(request.user, "ia_framework"):
        return redirect(RULES_URL)
    from apps.impact.framework import rules_register

    register = rules_register(request.user)
    return render(
        request,
        "pages/hr/ssa_mapping.html",
        {
            "rows": register["rows"],
            "row_count": len(register["rows"]),
        },
    )


def _drawer_refusal():
    return error_fragment(
        Forbidden(
            "Only Impact Assessment sets which SSA intervention an activity is "
            "measured against."
        ),
        action="SSA Mapping",
        status=403,
    )


def _version_rows(item) -> list[dict]:
    history = im.history_for(item)
    names = _names(
        [row.submitted_by for row in history] + [row.reviewed_by for row in history]
    )
    rows = []
    for row in history:
        state, tone = _state(row)
        rows.append(
            {
                "row": row,
                "state": state,
                "tone": tone,
                "author": names.get(row.submitted_by, "")
                or row.get_authored_by_display(),
                "reviewer": names.get(row.reviewed_by, ""),
                "basis": {
                    "peer_ia": "second IA officer",
                    "cd_fallback": "Country Director acknowledgement",
                }.get(row.review_basis, ""),
            }
        )
    return rows


def _state(row):
    from apps.impact.framework import rule_state

    return rule_state(row)


@require_page_permission("ssa_mapping")
def ssa_mapping_drawer(request, item_id):
    """The one-column drawer for one activity's rule: every saved field
    prefilled, the draft or rule in review beside the live version, and the
    version history."""
    if not _may_manage(request.user):
        return _drawer_refusal()
    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    if item is None:
        return error_fragment(
            BadRequest("That activity is not in the catalogue."),
            action="SSA Mapping",
            status=400,
        )

    resolved = im.mapping_for(item)
    live = resolved["primary"]
    pending = next(
        (
            row
            for row in im.pending_for(item)
            if row.relationship == MappingRelationship.PRIMARY
        ),
        None,
    )
    # The form shows what the officer is working on: their draft when one
    # exists, otherwise the live rule — never blank selects that would
    # quietly reset a saved rule on the next save.
    current = pending or live
    base_mode = getattr(live, "mapping_mode", "") or ""
    mode_locked = base_mode in NULL_INTERVENTION_MODES and base_mode not in (
        MappingMode.ANY_SSA_INTERVENTION,
    )
    return render(
        request,
        "partials/hr/ssa_mapping_drawer.html",
        {
            "item": item,
            "current": current,
            "live": live,
            "pending": pending,
            "in_review": bool(pending and pending.status == MappingStatus.IN_REVIEW),
            "not_measured": bool(current and current.not_ssa_measured_reason),
            "current_mode": getattr(current, "mapping_mode", "") or MappingMode.FIXED,
            "mode_locked": mode_locked,
            "locked_mode_label": dict(MappingMode.choices).get(base_mode, ""),
            "mode_choices": MODE_CHOICES,
            "secondary": resolved["secondary"],
            "interventions": SsaIntervention.choices,
            "bands": im.SCORE_BANDS,
            "current_bands": list(getattr(current, "eligible_bands", None) or []),
            "relationships": MappingRelationship.choices,
            "measurement_roles": MeasurementRole.choices,
            "directions": ExpectedDirection.choices,
            "history": _version_rows(item),
            "reference_default": im.is_reference_default(live),
            "reference_label": im.REFERENCE_DEFAULT_LABEL,
            "drawer_size": "md",
        },
    )


@require_page_permission("ssa_mapping")
def ssa_mapping_action(request, item_id):
    """Save a draft rule (and, with "submit", hand it to a reviewer), or record
    that an activity is not SSA-measured."""
    if request.method != "POST":
        return HttpResponse(status=405)

    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    if item is None:
        return error_fragment(
            BadRequest("That activity is not in the catalogue."),
            action="SSA Mapping",
            status=400,
        )

    change_reason = request.POST.get("change_reason", "")
    try:
        if request.POST.get("not_ssa_measured"):
            mapping = im.classify_not_ssa_measured(
                request.user,
                item,
                request.POST.get("not_ssa_measured_reason", ""),
                change_reason=change_reason,
            )
        else:
            mapping = im.save_draft(
                request.user,
                item,
                {
                    "intervention": request.POST.get("intervention"),
                    "mapping_mode": request.POST.get("mapping_mode"),
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
                    "change_reason": change_reason,
                },
            )
        if request.POST.get("submit"):
            im.submit_for_review(request.user, mapping, change_reason)
            messages.success(
                request,
                f"{item.display_name}: rule v{mapping.version} submitted for review.",
            )
        else:
            messages.success(
                request,
                f"{item.display_name}: rule v{mapping.version} saved as a draft.",
            )
    except (BadRequest, Forbidden) as exc:
        return error_fragment(exc, action="SSA Mapping", status=400)

    response = HttpResponse(status=204)
    response["HX-Redirect"] = RULES_URL
    return response


def _rule_facts(row) -> list[dict]:
    from apps.impact.framework import _intervention_text, _window

    return [
        {"label": "SSA domain", "value": _intervention_text(row)},
        {"label": "Used for", "value": row.get_measurement_role_display()},
        {"label": "Success looks like", "value": row.get_expected_direction_display()},
        {
            "label": "Schools it is for",
            "value": ", ".join(row.eligible_bands or []) or "Any band",
        },
        {"label": "Eligibility note", "value": row.eligibility_note},
        {
            "label": "Follow-up window (earliest / expected / latest)",
            "value": _window(row),
        },
        {
            "label": "Meaningful change",
            "value": (
                f"±{row.min_meaningful_change:g}"
                if row.min_meaningful_change is not None
                else "Any change (no approved threshold)"
            ),
        },
        {"label": "Scope", "value": row.country or "All countries"},
    ]


@require_page_permission("ssa_mapping")
@require_http_methods(["GET"])
def rule_review_drawer(request, mapping_id):
    """A second reviewer's drawer: the live rule, the proposed version, the
    reason, and the decision."""
    row = (
        ActivityInterventionMapping.objects.filter(id=mapping_id)
        .select_related("catalogue_item")
        .first()
    )
    if row is None:
        raise Http404
    live = im.mapping_for(row.catalogue_item)["primary"]
    names = _names([row.submitted_by])
    facts = [
        {"label": "Activity", "value": row.catalogue_item.display_name},
        {"label": "Proposed version", "value": f"v{row.version}"},
        {"label": "Written by", "value": names.get(row.submitted_by, "—")},
        {"label": "Why", "value": row.change_reason},
        *[
            {"label": f"Proposed · {fact['label']}", "value": fact["value"]}
            for fact in _rule_facts(row)
        ],
    ]
    if row.not_ssa_measured_reason:
        facts.append(
            {"label": "Not measured because", "value": row.not_ssa_measured_reason}
        )
    if live is not None and live.id != row.id:
        facts += [
            {"label": f"Live v{live.version} · {fact['label']}", "value": fact["value"]}
            for fact in _rule_facts(live)
        ]
    basis = im.review_basis_for(request.user, row)
    if not basis:
        return _drawer(
            request,
            title=f"Review rule: {row.catalogue_item.display_name}",
            subtitle="Measurement rules",
            facts=facts,
            empty=(
                "A second Impact Assessment officer in the rule's country reviews it; "
                "the Country Director acknowledges only where there is none. Nobody "
                "reviews a rule they wrote."
                if row.status == MappingStatus.IN_REVIEW
                else "This rule is not waiting for review."
            ),
        )
    return _drawer(
        request,
        title=f"Review rule: {row.catalogue_item.display_name}",
        subtitle=(
            "Acknowledge as Country Director (no second IA officer in the country)"
            if basis == "cd_fallback"
            else "Review as a second Impact Assessment officer"
        ),
        action=f"/priorities/ssa-mapping/rules/{row.id}/review/save",
        submit="Record decision",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                value="approve",
                options=(
                    ("approve", "Approve and publish"),
                    ("return", "Return with a note"),
                ),
            ),
            _field(
                "note",
                "Review note",
                type="textarea",
                rows=3,
                help="Required when returning it.",
            ),
        ],
    )


@require_page_permission("ssa_mapping")
@require_POST
def rule_review_action(request, mapping_id):
    row = ActivityInterventionMapping.objects.filter(id=mapping_id).first()
    if row is None:
        raise Http404
    decision = request.POST.get("decision", "")
    try:
        im.review(
            request.user, row, decision=decision, note=request.POST.get("note", "")
        )
    except SERVICE_ERRORS as exc:
        messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect(RULES_URL)
    messages.success(
        request,
        "Rule published." if decision == "approve" else "Rule returned to its author.",
    )
    return redirect(RULES_URL)


@require_page_permission("ssa_mapping")
@require_http_methods(["GET"])
def rule_history_drawer(request, item_id):
    """Every version of an activity's rule, for anyone who reads the register."""
    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    if item is None:
        raise Http404
    facts = []
    for entry in _version_rows(item):
        row = entry["row"]
        dates = ""
        if row.effective_from:
            dates = f" · from {row.effective_from:%-d %b %Y}"
            if row.effective_to:
                dates += f" to {row.effective_to:%-d %b %Y}"
        lines = [
            f"{entry['state']}{dates}",
            " · ".join(
                fact["value"]
                for fact in _rule_facts(row)[:1] + _rule_facts(row)[5:7]
                if fact["value"]
            ),
            f"Written by {entry['author']}" if entry["author"] else "",
            (
                f"Reviewed by {entry['reviewer']} ({entry['basis']})"
                if entry["reviewer"]
                else ""
            ),
            f"Why: {row.change_reason}" if row.change_reason else "",
            f"Review note: {row.review_note}" if row.review_note else "",
        ]
        facts.append(
            {
                "label": f"v{row.version}",
                "value": "\n".join(line for line in lines if line),
            }
        )
    return _drawer(
        request,
        title=f"Rule history: {item.display_name}",
        subtitle="Superseded versions stay readable: enrolments measured under them keep them.",
        facts=facts,
        empty="" if facts else "No rule has been recorded for this activity.",
    )
