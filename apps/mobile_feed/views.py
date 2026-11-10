"""Screen feeds: Home and navigation.

Each view resolves the reader exactly as the web request would (the account's
own record, with any acting capacity attached), applies the page's own
permission check, calls the service the page is rendered from, and returns
its fields. Nothing is computed here.
"""

from __future__ import annotations

import re

from django.template.loader import render_to_string
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import Forbidden
from apps.core.permissions import can_open_url

HOME_PAGE = "home"
#: The icons Home's own headings and rows use (partials/home/icon.html).
PAGE_GLYPHS = ("bolt", "grid", "calendar", "clock", "chevron", "arrow")


def reader(request: Request):
    """The account behind the token, as the pages see it.

    The page services read the `User` record, not the API principal, and a
    person working in an acting appointment is presented in that capacity
    (apps.acting.services.attach), as ActingCapacityMiddleware does for a
    browser session.
    """
    from apps.acting import services as acting_services

    principal = request.user
    user = getattr(principal, "_user", principal)
    # The role this request is made in, already checked against the account's
    # roles by the authentication class. In memory only; nothing is saved.
    user.active_role = principal.active_role
    acting_services.attach(user)
    return user


def require_page(user, page: str) -> None:
    from apps.core.permissions import RolePermissionService

    if not RolePermissionService.can_view_page(user, page):
        raise Forbidden("Your active role does not have permission to view this page.")


def home_icon(name: str) -> str:
    """Home's own icon set, as the SVG the page draws."""
    return render_to_string("partials/home/icon.html", {"name": name}).strip()


def figure(item: dict) -> dict:
    return {
        "key": str(item.get("key") or ""),
        "label": str(item.get("label") or ""),
        "value": "" if item.get("loading") else str(item.get("value")),
        "iconSvg": home_icon(item.get("icon") or ""),
        "tone": str(item.get("tone") or "plain"),
        "url": str(item.get("url") or ""),
        "loading": bool(item.get("loading")),
        "description": str(item.get("definition") or item.get("helper") or ""),
    }


def priority_row(row: dict) -> dict:
    return {
        "key": str(row.get("key") or ""),
        "title": str(row.get("title") or ""),
        "context": str(row.get("context") or ""),
        "dueLabel": str(row.get("due_label") or ""),
        "dueTone": str(row.get("due_tone") or "plain"),
        "statusLabel": str(row.get("status_label") or ""),
        "statusTone": str(row.get("status_tone") or "plain"),
        "markTone": str(row.get("mark_tone") or ""),
        "actionLabel": str(row.get("action_label") or "Open"),
        "url": str(row.get("url") or ""),
        "iconSvg": home_icon(row.get("icon") or ""),
        "count": int(row.get("count") or 0),
    }


def nav_item(item: dict) -> dict:
    return {
        "label": str(item.get("label") or ""),
        "url": str(item.get("url") or ""),
        "iconSvg": str(item.get("icon") or ""),
        "pageKey": str(item.get("page_key") or ""),
    }


class HomeFeedView(APIView):
    def get(self, request: Request) -> Response:
        from apps.command_center.home_service import build_home
        from apps.partners.member_scope import MEMBER_HOME_URL, is_team_member

        user = reader(request)
        require_page(user, HOME_PAGE)
        # A partner's team member starts on their own schools, as on the web.
        if is_team_member(user):
            return Response({"redirectUrl": MEMBER_HOME_URL})

        home = build_home(user, "/home")
        today = home["today"]
        return Response(
            {
                "glyphs": {name: home_icon(name) for name in PAGE_GLYPHS},
                "greeting": home["greeting"],
                "firstName": home["first_name"],
                "roleTitle": home["role_title"],
                "today": today.isoformat(),
                "todayLabel": f"{today:%a, %b} {today.day}",
                "fy": str(home["fy"]),
                "figures": [figure(f) for f in home["figures"]],
                "hasPlan": bool(home["has_plan"]),
                "upcoming": [
                    {
                        "id": str(a["id"]),
                        "month": a["month"],
                        "day": int(a["day"]),
                        "isToday": bool(a["is_today"]),
                        "title": str(a["title"] or ""),
                        "where": str(a["where"] or ""),
                        "time": str(a["time"] or ""),
                        "typeLabel": str(a["type_label"] or ""),
                        "statusLabel": str(a["status_label"] or ""),
                        "url": a["url"],
                    }
                    for a in home["upcoming"]
                ],
                "shortcuts": [
                    {
                        "label": str(s.get("label") or ""),
                        "url": str(s.get("url") or ""),
                        "iconSvg": str(s.get("icon") or ""),
                    }
                    for s in home["shortcuts"]
                ],
            }
        )


class HomeQueueFeedView(APIView):
    def get(self, request: Request) -> Response:
        from apps.command_center.home_service import build_home_queue
        from apps.partners.member_scope import is_team_member

        user = reader(request)
        require_page(user, HOME_PAGE)
        if is_team_member(user):
            return Response({})

        queue = build_home_queue(user)
        body = {
            "priorityRows": [priority_row(r) for r in queue["priority_rows"]],
            "hasPlan": bool(queue["has_plan"]),
            "queueFigures": [figure(f) for f in queue["queue_figures"]],
            "todoFiguresLater": bool(queue["todo_figures_later"]),
        }
        if queue["priority_total"] is not None:
            body["priorityTotal"] = int(queue["priority_total"])
        return Response(body)


class HomeTodoFiguresFeedView(APIView):
    def get(self, request: Request) -> Response:
        from apps.command_center.home_service import build_home_todo_figures
        from apps.partners.member_scope import is_team_member

        user = reader(request)
        require_page(user, HOME_PAGE)
        if is_team_member(user):
            return Response({})

        figures = build_home_todo_figures(user)
        return Response(
            {
                "queueFigures": [figure(f) for f in figures["queue_figures"]],
                "priorityTotal": int(figures["priority_total"] or 0),
            }
        )


class NavigationFeedView(APIView):
    def get(self, request: Request) -> Response:
        from apps.core.navigation import (
            build_mobile_nav_for_user,
            build_sidebar_for_user,
        )

        user = reader(request)
        sections = build_sidebar_for_user(user, "/home")
        bottom = build_mobile_nav_for_user(user, "/home", sections)
        return Response(
            {
                "bottom": [nav_item(i) for i in bottom],
                "sections": [
                    {
                        "label": str(s.get("label") or s.get("title") or ""),
                        "items": [nav_item(i) for i in s.get("items", [])],
                    }
                    for s in sections
                ],
            }
        )


#: The directory's tabs, in the page's order and wording (partials/schools/tabs.html).
DIRECTORY_TABS = (
    ("all", "All Schools", "all_count"),
    ("unclustered", "Unclustered", "unclustered_count"),
    ("clustered", "Clustered", "clustered_count"),
    ("not_assigned", "Not Assigned to Project", "not_assigned_count"),
    ("assigned", "Assigned to Project", "assigned_count"),
)

#: The page's own query parameters, passed through unchanged.
DIRECTORY_PARAMS = (
    "q",
    "fy",
    "district",
    "sub_county",
    "school_type",
    "cluster_status",
    "project_status",
    "gap",
    "tab",
    "page",
)


def option(value, label) -> dict:
    return {"value": str(value), "label": str(label)}


def directory_actions(row: dict, context: dict) -> list[dict]:
    """The row's Actions menu, in the order and wording of
    partials/schools/directory_row.html."""
    available = row.get("available_actions") or []
    reasons = row.get("disabled_reasons") or {}
    actions = []
    if context.get("selected_gap") == "unheld" and context.get("can_take_schools"):
        actions.append({"key": "take", "label": "Take This School", "enabled": True})
        actions.append(
            {"key": "complete", "label": "Open And Complete", "enabled": True}
        )
    if context.get("can_plan_from_directory"):
        actions.append({"key": "schedule", "label": "Schedule", "enabled": True})
    if "add_to_cluster" in available:
        actions.append(
            {"key": "add_to_cluster", "label": "Add to Cluster", "enabled": True}
        )
    elif "change_cluster" in available:
        actions.append(
            {"key": "change_cluster", "label": "Change Cluster", "enabled": True}
        )
    elif reasons.get("add_to_cluster"):
        actions.append(
            {
                "key": "add_to_cluster",
                "label": "Add to Cluster",
                "enabled": False,
                "reason": str(reasons["add_to_cluster"]),
            }
        )
    if "reassign_owner" in available:
        actions.append(
            {"key": "reassign_owner", "label": "Reassign Owner", "enabled": True}
        )
    if "assign_to_project" in available:
        actions.append(
            {"key": "assign_to_project", "label": "Add to Project", "enabled": True}
        )
    elif reasons.get("assign_to_project"):
        actions.append(
            {
                "key": "assign_to_project",
                "label": "Add to Project",
                "enabled": False,
                "reason": str(reasons["assign_to_project"]),
            }
        )
    return actions


def directory_school(row: dict, context: dict) -> dict:
    if row.get("cluster_training_planned"):
        training_state = "positive"
    elif row.get("cluster_training_required"):
        training_state = "attention"
    else:
        training_state = ""
    cluster_name = row.get("cluster_name")
    body = {
        "id": str(row["id"]),
        "schoolId": str(row["school_id"]),
        "name": str(row["school_name"]),
        "district": str(row.get("district") or "—"),
        "districtId": str(row.get("district_id") or ""),
        "shippingAddress": str(row.get("shipping_address") or "—"),
        "schoolType": str(row.get("school_type") or ""),
        "clusterId": str(row.get("cluster_id") or ""),
        "clusterName": str(cluster_name)
        if cluster_name and cluster_name != "—"
        else "Not assigned",
        "enrolment": int(row.get("enrolment") or 0),
        "phone": str(row.get("phone") or "—"),
        "contact": str(row.get("school_contact") or "—"),
        "staffName": str(row.get("staff_name") or "—"),
        "ssaTone": str(row.get("ssa_average_tone") or ""),
        "visitStatusLabel": str(row.get("visit_plan_status_label") or ""),
        "visitStatusTone": str(row.get("visit_plan_status_tone") or ""),
        "nextVisitDate": row["next_visit_date"].isoformat()
        if row.get("next_visit_date")
        else "",
        "clusterTrainingLabel": str(row.get("cluster_training_status_label") or ""),
        "clusterTrainingReason": str(row.get("cluster_training_reason") or ""),
        "clusterTrainingState": training_state,
        "visitCount": int(row.get("visit_count") or 0),
        "trainingCount": int(row.get("training_count") or 0),
        "projectIds": [p for p in str(row.get("project_ids") or "").split() if p],
        "actions": []
        if context.get("directory_read_only")
        else directory_actions(row, context),
        "ssaGroups": [
            {
                "key": str(group.get("key") or ""),
                "title": str(group.get("title") or ""),
                "tone": str(group.get("tone") or ""),
                "items": [
                    {
                        "label": str(item.get("label") or ""),
                        "score": float(item.get("score") or 0),
                        "band": str(item.get("band") or ""),
                        "bandTone": str(item.get("band_tone") or ""),
                    }
                    for item in group.get("items", [])
                ],
            }
            for group in row.get("ssa_groups") or []
        ],
    }
    if row.get("ssa_average") is not None:
        body["ssaAverage"] = float(row["ssa_average"])
    return body


def bulk_project(project) -> dict:
    """One project of the bulk dialog, labelled as its option on the web."""
    label = project.name
    if getattr(project, "coordinator_name", ""):
        label += f" · {project.coordinator_name}"
    allocation = getattr(project, "allocation", None)
    block = str(getattr(project, "capacity_block", "") or "")
    if allocation:
        label += f" · {allocation.remaining} of {allocation.maximum} left"
    elif block:
        label += " · no allocation"
    body = {"value": project.id, "label": label, "block": block}
    remaining = getattr(project, "capacity_remaining", None)
    if remaining is not None:
        body["remaining"] = int(remaining)
    return body


class SchoolDirectoryFeedView(APIView):
    def get(self, request: Request) -> Response:
        from django.http import HttpResponse
        from django.test import RequestFactory

        from apps.frontend.views.school_views import school_directory_context

        user = reader(request)
        require_page(user, "school_directory")

        # The page's own view-model, from the page's own query parameters
        # only: never an export, never a partial.
        params = {
            key: request.query_params[key]
            for key in DIRECTORY_PARAMS
            if request.query_params.get(key)
        }
        page_request = RequestFactory().get("/schools", params)
        page_request.user = user
        context = school_directory_context(page_request)
        if isinstance(
            context, HttpResponse
        ):  # pragma: no cover - export is never asked for
            raise Forbidden("Exports are not available here.")

        page = context["page_obj"]
        gaps = [
            option(g["key"], f"{g['label']} ({g['count']:,})")
            for g in context["gap_options"]
        ]
        if context.get("can_take_schools"):
            gaps.append(
                option("unheld", f"Nobody Holds It ({context['unheld_count']:,})")
            )
        return Response(
            {
                "tabs": [
                    {"key": key, "label": label, "count": int(context[count])}
                    for key, label, count in DIRECTORY_TABS
                ],
                "activeTab": context["active_tab"],
                "filters": {
                    "fy": str(context["selected_fy"]),
                    "fyOptions": [
                        option(fy, f"FY {fy}") for fy in context["fy_options"]
                    ],
                    "district": context["selected_district"],
                    "districts": [option(d.id, d.name) for d in context["districts"]],
                    "subCounty": context["selected_sub_county"],
                    "subCounties": [
                        option(s.id, s.name) for s in context["sub_counties"]
                    ],
                    "schoolType": context["selected_type"],
                    "schoolTypes": [
                        option(v, label) for v, label in context["school_types"]
                    ],
                    "clusterStatus": context["selected_cluster_status"],
                    "clusterStatuses": [
                        option("clustered", "Clustered"),
                        option("unclustered", "Unclustered"),
                    ],
                    "projectStatus": context["selected_project_status"],
                    "projectStatuses": [
                        option("assigned", "Assigned"),
                        option("unassigned", "Not Assigned"),
                    ],
                    "gap": context["selected_gap"],
                    "gaps": gaps,
                },
                "schools": [
                    directory_school(row, context) for row in context["view_models"]
                ],
                "page": {
                    "page": page.number,
                    "pageSize": int(context["per_page"]),
                    "total": str(page.paginator.count),
                    "totalPages": page.paginator.num_pages,
                },
                "canAddSchool": bool(context.get("can_add_school")),
                "readOnly": bool(context.get("directory_read_only")),
                "emptyState": context.get("directory_empty_state") or "",
                "bulkClusters": [
                    option(c.id, c.name) for c in context.get("clusters") or []
                ],
                "bulkProjects": [
                    bulk_project(p) for p in context.get("projects") or []
                ],
                "mayTransferSchool": bool(context.get("may_transfer_school")),
                # The row links a school's name to its profile only for a
                # reader the profile lets in (directory_row.html).
                "mayOpenProfile": can_open_url(user, "/schools/0"),
            }
        )


# ── School row actions ─────────────────────────────────────────────────────
# The web drawers' own flows (apps.frontend.views.school_views), run with a
# responder that returns the outcome's template and context instead of HTML.

CLUSTER_DRAWER = "partials/schools/add_to_cluster_drawer.html"
PROJECT_DRAWER = "partials/schools/assign_to_project_drawer.html"
DRAWER_ERROR = "partials/schools/drawer_error.html"
TOAST = "partials/schools/toast_success.html"

#: Expected support types, as listed in the Add to Project drawer.
SUPPORT_TYPES = (
    "Staff-led support",
    "Partner-led support",
    "Coaching",
    "Training",
    "Assessment",
    "Monitoring",
)


def run_flow(flow, user, school_id: str, data: dict | None = None) -> dict:
    """Run a drawer flow as the web would for an HTMX request, and return the
    outcome it chose to draw: {"template", "context"}."""
    from django.http import Http404
    from django.test import RequestFactory

    factory = RequestFactory()
    path = f"/schools/{school_id}"
    if data is None:
        page_request = factory.get(path, HTTP_HX_REQUEST="true")
    else:
        page_request = factory.post(path, data, HTTP_HX_REQUEST="true")
    page_request.user = user
    try:
        return flow(
            page_request,
            school_id,
            lambda template, context: {"template": template, "context": context},
        )
    except Http404:
        return {"template": DRAWER_ERROR, "context": {"error": "School not found."}}


def action_result(outcome: dict) -> dict:
    template, context = outcome["template"], outcome["context"]
    if template == TOAST:
        return {"saved": True, "message": str(context.get("message") or "")}
    if template == DRAWER_ERROR:
        return {"refused": str(context.get("error") or "")}
    return {"error": str(context.get("validation_error") or "This could not be saved.")}


def cluster_choice(cluster) -> dict:
    """One owner cluster, labelled exactly as the drawer's option."""
    label = f"{cluster.name} · {cluster.district.name}"
    if cluster.is_current:
        label += " (current)"
    elif cluster.is_cross_district:
        label += " · Cross-District Cluster"
        if cluster.serves_school:
            label += " (approved neighbouring district)"
    count = getattr(cluster, "schools_count", 0) or 0
    label += f" · {count} school{'' if count == 1 else 's'}"
    return {"value": cluster.id, "label": label, "disabled": bool(cluster.is_current)}


def cluster_form(context: dict) -> dict:
    school = context["school"]
    owner = context.get("responsible_staff")
    owner_name = owner.user.name if owner and owner.user_id else ""
    clusters = context.get("owner_clusters") or []
    if clusters:
        notice = (
            ""
            if context.get("has_selectable_cluster")
            else "This school's owner has no active cluster to add it to."
        )
    elif context.get("ineligibility_reason"):
        notice = str(context["ineligibility_reason"])
    else:
        notice = (
            f"{owner_name or 'This school' + chr(39) + 's owner'} has no active cluster "
            "yet — create one to add the school."
        )
    current = context.get("current_cluster")
    is_change = bool(context.get("is_change"))
    district = school.district.name if school.district_id else "the school's district"
    sub_county = school.sub_county.name if school.sub_county_id else "the district"
    place = school.sub_county.name if school.sub_county_id else district
    return {
        "title": f"Change cluster for {school.name}"
        if is_change
        else f"Add {school.name} to cluster",
        "isChange": is_change,
        "currentClusterName": current.name if current else "",
        "clusters": [cluster_choice(c) for c in clusters],
        "preselectedClusterId": str(context.get("preselected_cluster_id") or ""),
        "crossDistrictClusterIds": [c.id for c in clusters if c.is_cross_district],
        "hasSelectableCluster": bool(context.get("has_selectable_cluster")),
        "ownerNote": f"Clusters of {owner_name} (the school's owner)."
        if owner_name
        else "",
        "clusterNotice": notice,
        "newClusterPlaceholder": f"e.g. {place} Cluster",
        "newClusterNote": f"A new cluster is created in {district}, covering {sub_county}.",
        "reasonPlaceholder": "Why this school moves to another cluster"
        if is_change
        else "Why this school joins a cluster across the district border",
        "confirmLabel": f"Move this school out of {current.name if current else 'its current cluster'}."
        if is_change
        else "",
        "submitLabel": "Change cluster" if is_change else "Add to cluster",
        "error": str(context.get("validation_error") or ""),
    }


def project_form(context: dict) -> dict:
    school = context["school"]
    projects = []
    for project in context.get("projects") or []:
        label = f"{project.name} ({project.code or 'No Code'})"
        if getattr(project, "coordinator_name", ""):
            label += f" · {project.coordinator_name}"
        block = str(getattr(project, "capacity_block", "") or "")
        projects.append(
            {
                "value": project.id,
                "label": label,
                "disabled": bool(block),
                "reason": block,
            }
        )
    return {
        "title": f"Assign {school.name} to project",
        "projects": projects,
        "supportTypes": [{"value": t, "label": t} for t in SUPPORT_TYPES],
        "coordinators": [
            {"value": c.id, "label": c.user.name if c.user_id else c.id}
            for c in context.get("coordinators") or []
        ],
        "focusAreas": [
            {"value": code, "label": label}
            for code, label in context.get("interventions") or []
        ],
        "emptyNotice": ""
        if projects
        else "No active projects available. Create a project before assigning schools.",
        "error": str(context.get("validation_error") or ""),
    }


class AddToClusterFeedView(APIView):
    def get(self, request: Request, school_id: str) -> Response:
        from apps.frontend.views.school_views import add_to_cluster_flow

        user = reader(request)
        require_page(user, "school_directory")
        outcome = run_flow(add_to_cluster_flow, user, school_id)
        if outcome["template"] == DRAWER_ERROR:
            return Response(
                {"form": {"refused": str(outcome["context"].get("error") or "")}}
            )
        return Response({"form": cluster_form(outcome["context"])})

    def post(self, request: Request, school_id: str) -> Response:
        from apps.frontend.views.school_views import add_to_cluster_flow

        user = reader(request)
        require_page(user, "school_directory")
        body = request.data
        data = {
            "cluster_action_type": str(body.get("actionType") or "existing"),
            "existing_cluster_id": str(body.get("clusterId") or ""),
            "new_cluster_name": str(body.get("newClusterName") or ""),
            "reason": str(body.get("reason") or ""),
        }
        if body.get("confirmChange") is True:
            data["confirm_change"] = "yes"
        outcome = run_flow(add_to_cluster_flow, user, school_id, data)
        return Response({"result": action_result(outcome)})


class AddToProjectFeedView(APIView):
    def get(self, request: Request, school_id: str) -> Response:
        from apps.frontend.views.school_views import assign_to_project_flow

        user = reader(request)
        require_page(user, "school_directory")
        outcome = run_flow(assign_to_project_flow, user, school_id)
        if outcome["template"] == DRAWER_ERROR:
            return Response(
                {"form": {"refused": str(outcome["context"].get("error") or "")}}
            )
        return Response({"form": project_form(outcome["context"])})

    def post(self, request: Request, school_id: str) -> Response:
        from apps.frontend.views.school_views import assign_to_project_flow

        user = reader(request)
        require_page(user, "school_directory")
        body = request.data
        data = {
            "project_id": str(body.get("projectId") or ""),
            "project_type": str(body.get("projectType") or ""),
            "participation_type": str(body.get("participationType") or ""),
            "start_date": str(body.get("startDate") or ""),
            "support_area": str(body.get("supportArea") or ""),
            "coordinator_id": str(body.get("coordinatorId") or ""),
            "notes": str(body.get("notes") or ""),
        }
        outcome = run_flow(assign_to_project_flow, user, school_id, data)
        return Response({"result": action_result(outcome)})


# ── The directory's bulk bar ───────────────────────────────────────────────
# The web's bulk saves report through Django's messages and redirect. They
# run here unchanged; the messages they queue are the outcome.


class CollectedMessages:
    """A message store that keeps what a view adds, for reading back."""

    def __init__(self):
        self.items = []

    def add(self, level, message, extra_tags=""):
        self.items.append((level, str(message)))

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def run_bulk(view, user, data: dict) -> dict:
    from django.contrib import messages
    from django.test import RequestFactory

    page_request = RequestFactory().post("/schools", data)
    page_request.user = user
    collected = CollectedMessages()
    page_request._messages = collected
    view(page_request)

    errors = [text for level, text in collected if level >= messages.ERROR]
    warnings = [text for level, text in collected if level == messages.WARNING]
    successes = [text for level, text in collected if level == messages.SUCCESS]
    if errors:
        return {"error": " ".join(errors), "warnings": warnings}
    if successes:
        return {"saved": True, "message": " ".join(successes), "warnings": warnings}
    return {"error": " ".join(warnings) or "Nothing was changed.", "warnings": []}


def ticked(body) -> list[str]:
    ids = body.get("schoolIds") or []
    return [str(i) for i in ids if str(i).strip()] if isinstance(ids, list) else []


class BulkAssignClusterFeedView(APIView):
    def post(self, request: Request) -> Response:
        from apps.frontend.views.school_views import bulk_assign_cluster_view

        user = reader(request)
        require_page(user, "school_directory")
        data = {
            "school_ids": ",".join(ticked(request.data)),
            "cluster_id": str(request.data.get("clusterId") or ""),
        }
        return Response({"result": run_bulk(bulk_assign_cluster_view, user, data)})


class BulkAssignProjectFeedView(APIView):
    def post(self, request: Request) -> Response:
        from apps.frontend.views.school_views import bulk_assign_project_view

        user = reader(request)
        require_page(user, "school_directory")
        data = {
            "school_ids": ",".join(ticked(request.data)),
            "project_id": str(request.data.get("projectId") or ""),
        }
        return Response({"result": run_bulk(bulk_assign_project_view, user, data)})


#: The profile page's own query parameters.
PROFILE_PARAMS = ("tab", "fy", "period")


class SchoolProfileFeedView(APIView):
    """A school's profile: the page the web renders for the same person, read
    as its shared components (apps.mobile_feed.page_blocks)."""

    def get(self, request: Request, school_id: str) -> Response:
        from importlib import import_module

        from django.conf import settings
        from django.http import Http404
        from django.test import RequestFactory

        from apps.frontend.views.school_views import school_detail_view
        from apps.mobile_feed import page_blocks

        user = reader(request)
        require_page(user, "school_profile")
        params = {
            key: request.query_params[key]
            for key in PROFILE_PARAMS
            if request.query_params.get(key)
        }
        path = f"/schools/{school_id}"
        page_request = RequestFactory().get(path, params)
        page_request.user = user
        # The page's own session and messages, in memory only: nothing is
        # saved and nothing reaches the reader's browser.
        page_request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        page_request._messages = CollectedMessages()
        try:
            page = school_detail_view(page_request, school_id)
        except Http404:
            return Response({"error": "School not found."}, status=404)
        if page.status_code != 200:
            return Response({"error": "School not found."}, status=page.status_code)
        return Response({**page_blocks.read(page.content.decode()), "webPath": path})


# ── The profile's drawers ──────────────────────────────────────────────────
# A drawer is the web's own: the feed renders it for the reader and reads it
# (apps.mobile_feed.drawer_blocks), and a save posts the drawer's own fields
# to the web view that saves it. Only these drawers are reachable.


def _school_drawers() -> dict:
    from apps.frontend.views import school_views

    return {
        "edit": (
            school_views.school_edit_drawer_view,
            school_views.school_edit_drawer_view,
        ),
        "close": (school_views.school_close_drawer, school_views.school_close_action),
        "ssa-entry": (
            school_views.school_ssa_entry_view,
            school_views.school_ssa_entry_view,
        ),
    }


#: The choice lists a drawer field reloads, by the web path the field names.
def _option_sources() -> dict:
    from apps.frontend.views import school_views

    return {
        "/schools/sub-counties": school_views.school_sub_county_options_view,
        "/schools/parishes": school_views.school_parish_options_view,
    }


def _page_request(user, path: str, data: dict | None = None):
    """A request the web view takes as an HTMX one from ``user``: its own
    session and messages in memory, nothing saved to a browser."""
    from importlib import import_module

    from django.conf import settings
    from django.test import RequestFactory

    factory = RequestFactory()
    if data is None:
        page_request = factory.get(path, HTTP_HX_REQUEST="true")
    else:
        page_request = factory.post(path, data, HTTP_HX_REQUEST="true")
    page_request.user = user
    page_request.session = import_module(settings.SESSION_ENGINE).SessionStore()
    page_request._messages = CollectedMessages()
    return page_request


def _drawer_html(view, user, school_id: str) -> str | None:
    """The drawer as the web renders it for ``user``, or None if not theirs."""
    from django.http import Http404

    try:
        response = view(_page_request(user, f"/schools/{school_id}"), school_id)
    except Http404:
        return None
    if response.status_code != 200:
        return None
    return response.content.decode()


def _saved_outcome(response, collected: CollectedMessages) -> dict:
    """What a drawer's save answered: saved, with the web's message; or not,
    with the drawer again (its errors in it) or the web's reason."""
    from django.contrib import messages as levels

    from apps.mobile_feed import drawer_blocks, page_blocks

    body = response.content.decode()
    said = {
        "ok": [
            text
            for level, text in collected
            if level >= levels.SUCCESS and level < levels.WARNING
        ],
        "bad": [text for level, text in collected if level >= levels.WARNING],
    }
    trigger = response.get("HX-Trigger", "")
    redirect = response.get("HX-Redirect", "")
    shown = page_blocks.parse(body).text()
    saved = response.status_code < 400 and (
        "close-drawer" in trigger
        or bool(response.get("HX-Refresh"))
        or bool(redirect)
        or "pill-success" in body
        or bool(said["ok"])
    )
    if saved:
        return {
            "saved": True,
            "message": " ".join(said["ok"]) or shown or "Saved.",
            "redirect": redirect,
        }
    if "data-edify-drawer" in body:
        return {"saved": False, "drawer": drawer_blocks.read(body)}
    return {
        "saved": False,
        "error": " ".join(said["bad"]) or shown or "This could not be saved.",
    }


class SchoolDrawerFeedView(APIView):
    """One of the profile's drawers: read (GET) or saved (POST)."""

    def _views(self, kind: str):
        return _school_drawers().get(kind)

    def get(self, request: Request, school_id: str, kind: str) -> Response:
        from apps.mobile_feed import drawer_blocks

        user = reader(request)
        require_page(user, "school_profile")
        views = self._views(kind)
        html = _drawer_html(views[0], user, school_id) if views else None
        if html is None:
            return Response({"error": "Not found."}, status=404)
        return Response({"drawer": drawer_blocks.read(html)})

    def post(self, request: Request, school_id: str, kind: str) -> Response:
        from django.http import Http404

        from apps.mobile_feed import drawer_blocks

        user = reader(request)
        require_page(user, "school_profile")
        views = self._views(kind)
        html = _drawer_html(views[0], user, school_id) if views else None
        if html is None:
            return Response({"error": "Not found."}, status=404)
        values = request.data.get("values") if isinstance(request.data, dict) else None
        if not isinstance(values, dict):
            return Response({"error": "Values are required."}, status=400)
        page_request = _page_request(
            user, f"/schools/{school_id}", drawer_blocks.form_data(html, values)
        )
        try:
            response = views[1](page_request, school_id)
        except Http404:
            return Response({"error": "Not found."}, status=404)
        return Response(_saved_outcome(response, page_request._messages))


class DrawerOptionsFeedView(APIView):
    """The choices a drawer field reloads when another field changes."""

    def get(self, request: Request) -> Response:
        from apps.mobile_feed import drawer_blocks

        user = reader(request)
        view = _option_sources().get(request.query_params.get("source", ""))
        if view is None:
            return Response({"error": "Not found."}, status=404)
        params = {
            key: value for key, value in request.query_params.items() if key != "source"
        }
        page_request = _page_request(user, "/schools")
        page_request.GET = page_request.GET.copy()
        page_request.GET.update(params)
        response = view(page_request)
        if response.status_code != 200:
            return Response({"error": "Not found."}, status=response.status_code)
        return Response({"options": drawer_blocks.options(response.content.decode())})


# ── The profile's planning drawers ─────────────────────────────────────────
# Schedule visit and Assign to Partner, read by apps.mobile_feed.
# planning_drawers. Each is the web's own drawer for the reader, opened as
# the profile's buttons open it (?school_id=); a save posts to the web view
# the drawer's form posts to.


def _planning_drawers() -> dict:
    from apps.frontend.views import planning_views
    from apps.mobile_feed import planning_drawers

    return {
        "schedule": (
            "/planning/schedule-modal",
            planning_views.schedule_modal_view,
            planning_views.schedule_action_view,
            planning_drawers.read_schedule,
        ),
        "assign": (
            "/planning/assign-partner-modal",
            planning_views.assign_partner_modal_view,
            planning_views.assign_partner_action_view,
            planning_drawers.read_assign,
        ),
    }


def _planning_html(user, kind: str, school_id: str) -> tuple[int, str]:
    """The planning drawer as the web renders it for ``user``: its status
    and its HTML."""
    from django.http import Http404

    path, view, _save, _read = _planning_drawers()[kind]
    page_request = _page_request(user, path)
    page_request.GET = page_request.GET.copy()
    page_request.GET["school_id"] = school_id
    try:
        response = view(page_request)
    except Http404:
        return 404, ""
    return response.status_code, response.content.decode()


class PlanningDrawerFeedView(APIView):
    """A school's Schedule visit or Assign to Partner drawer: read (GET) or
    saved (POST)."""

    def _open(self, request: Request, school_id: str, kind: str):
        from apps.mobile_feed import page_blocks

        user = reader(request)
        require_page(user, "school_profile")
        if kind not in _planning_drawers():
            return user, None, Response({"error": "Not found."}, status=404)
        status, html = _planning_html(user, kind, school_id)
        if status == 404:
            return user, None, Response({"error": "Not found."}, status=404)
        if status != 200:
            # The web's own refusal, e.g. no permission to schedule.
            reason = page_blocks.parse(html).text() or "This is not available to you."
            return user, None, Response({"error": reason}, status=403)
        return user, html, None

    def get(self, request: Request, school_id: str, kind: str) -> Response:
        from apps.mobile_feed import page_blocks

        _user, html, refused = self._open(request, school_id, kind)
        if refused is not None:
            return refused
        drawer = _planning_drawers()[kind][3](html)
        if drawer is None:
            # The web drew a message instead of a form (a school whose
            # visits are locked): say it, as the web's drawer does.
            return Response({"refusal": page_blocks.parse(html).text()})
        return Response({"drawer": drawer})

    def post(self, request: Request, school_id: str, kind: str) -> Response:
        from apps.mobile_feed import planning_drawers

        user, html, refused = self._open(request, school_id, kind)
        if refused is not None:
            return refused
        values = request.data.get("values") if isinstance(request.data, dict) else None
        if not isinstance(values, dict):
            return Response({"error": "Values are required."}, status=400)
        path, _view, save, _read = _planning_drawers()[kind]
        page_request = _page_request(
            user, path, planning_drawers.form_data(kind, html, values)
        )
        response = save(page_request)
        outcome = _saved_outcome(response, page_request._messages)
        if outcome.get("saved"):
            toast = planning_drawers.toast_message(response.content.decode())
            outcome["message"] = toast or outcome["message"]
        outcome.pop("drawer", None)
        return Response(outcome)


class TrainingCapacityFeedView(APIView):
    """What the Schedule drawer shows under its Training field: the
    officer's training ceiling and what is already scheduled under it."""

    FIELDS = (
        "managed",
        "ceiling",
        "scheduled",
        "remaining",
        "staffName",
        "fy",
        "counted",
    )

    def get(self, request: Request) -> Response:
        import json

        from apps.frontend.views.training_ceiling_views import training_capacity_view

        user = reader(request)
        require_page(user, "school_profile")
        page_request = _page_request(user, "/planning/training-capacity")
        page_request.GET = page_request.GET.copy()
        for key in ("training", "date", "school"):
            page_request.GET[key] = request.query_params.get(key, "")
        response = training_capacity_view(page_request)
        if response.status_code != 200:
            return Response({"managed": False}, status=response.status_code)
        answer = json.loads(response.content)
        return Response({key: answer.get(key) for key in self.FIELDS if key in answer})


# ── Pages read as their components ─────────────────────────────────────────
# Any page the native app draws from its components: the page's own view,
# run for the reader as a browser request would be (nothing saved), read by
# apps.mobile_feed.page_blocks. Only the pages named here are reachable, the
# page's own gate decides who opens it, and only the parts it loads after it
# opens that are named here are read into it.

#: The pages, by URL name (an unnamed route by its view's name).
NATIVE_PAGES = frozenset(
    {
        "dashboard",
        "planning_dashboard",
        "my_plan",
        "cluster_list",
        "calendar",
        "core_schools",
        "programme_schools",
        "todos",
        "my_actions",
        "debriefs_list",
        "cluster_oversight",
        "core_schools_oversight",
        "partner_oversight",
        "project_monitoring",
        "weekly_fund_requests",
        "team_performance",
        "projects_list",
        "escalations",
        "extra_work",
        "budget",
        "work_plan",
        "decision_log",
        "my_targets",
        "my_coaching",
        "loans",
        "priorities_master",
        "my_performance",
        "my_professional_development",
        # An unnamed route is named by its view.
        "personal_time_off_view",
        "closed_schools",
    }
)
#: The parts a page loads after it opens that are page sections (never a
#: drawer that pops open), by URL name.
LATER_PARTS = frozenset(
    {
        "my_plan_readiness",
        "today_panel",
        "staff_activity",
        "planning_monitor",
        "cpo_schools",
    }
)
#: A page's own query keys look like this; these never pass (they answer
#: with a file, not the page).
QUERY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
NOT_PASSED = frozenset({"export", "download", "format", "csv", "xlsx", "pdf"})
MAX_QUERY_VALUE = 128


def _page_get(user, path: str, params: dict):
    """A full-page (not HTMX) request the web view takes from ``user``."""
    from importlib import import_module

    from django.conf import settings
    from django.test import RequestFactory

    page_request = RequestFactory().get(path, params)
    page_request.user = user
    page_request.session = import_module(settings.SESSION_ENGINE).SessionStore()
    page_request._messages = CollectedMessages()
    return page_request


def _page_params(query) -> dict:
    return {
        key: value
        for key, value in query.items()
        if QUERY_KEY.match(key)
        and key not in NOT_PASSED
        and len(value) <= MAX_QUERY_VALUE
    }


def _run_page(user, path: str, params: dict, names: frozenset):
    """The page's response, or None when ``path`` is not one of ``names``
    or ``user`` may not open it."""
    from django.urls import Resolver404, resolve

    from apps.core.permissions import can_open_url

    try:
        match = resolve(path)
    except Resolver404:
        return None
    if (match.url_name or match.func.__name__) not in names or not can_open_url(
        user, path
    ):
        return None
    response = match.func(_page_get(user, path, params), *match.args, **match.kwargs)
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    return response


def read_page(user, path: str, query) -> tuple[int, dict]:
    """The page at ``path`` as blocks for ``user``: (status, body)."""
    from urllib.parse import parse_qsl, urlparse

    from django.http import Http404

    from apps.mobile_feed import page_blocks

    try:
        page = _run_page(user, path, _page_params(query), NATIVE_PAGES)
    except Http404:
        return 404, {"error": "This page is not available."}
    if page is None:
        return 404, {"error": "This page is not available."}
    if page.status_code in (301, 302, 303):
        return 200, {"redirect": page.get("Location", "")}
    if page.status_code != 200:
        return page.status_code, {"error": "This page is not available to you."}

    def later(part_path: str) -> str | None:
        url = urlparse(part_path)
        try:
            part = _run_page(
                user, url.path, _page_params(dict(parse_qsl(url.query))), LATER_PARTS
            )
        except Http404:
            return None
        return (
            part.content.decode()
            if part is not None and part.status_code == 200
            else None
        )

    return 200, {**page_blocks.read(page.content.decode(), later), "webPath": path}


class PageFeedView(APIView):
    """A page the native app draws from its components (``?path=``), with
    the page's own query."""

    def get(self, request: Request) -> Response:
        user = reader(request)
        path = request.query_params.get("path", "")
        query = {
            key: value for key, value in request.query_params.items() if key != "path"
        }
        status, body = read_page(user, path, query)
        return Response(body, status=status)


class MyPlanFeedView(APIView):
    """My Plan, as any page is read (kept for the My Plan service)."""

    def get(self, request: Request) -> Response:
        status, body = read_page(reader(request), "/my-plan", request.query_params)
        return Response(body, status=status)
