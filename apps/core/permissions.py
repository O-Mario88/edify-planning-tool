"""
DRF permission classes — the RequirePermissions gate.

A faithful port of the NestJS PermissionsGuard: views set `required_permissions`
(a list of permission keys). A request passes only if the authenticated user's
activeRole grants at least one of them. The role→permission mapping comes from
the seeded RolePermission table (source of truth: apps.core.rbac.ROLE_PERMISSIONS).
"""
from __future__ import annotations

from typing import Iterable
from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages

from rest_framework.permissions import BasePermission

from apps.accounts.jwt import AuthPrincipal
from apps.core.rbac import permissions_for_role, EdifyRole


def _user_permissions(principal: AuthPrincipal | object) -> set[str]:
    """Resolve the active-role permissions for a principal. Falls back to the
    canonical matrix so the gate works even before RolePermission is seeded."""
    active_role = getattr(principal, "active_role", None)
    if active_role:
        return set(permissions_for_role(active_role))
    if isinstance(principal, AuthPrincipal):
        return set(permissions_for_role(principal.active_role))
    # Anonymous / unauthenticated
    return set()


class IsAuthenticated(BasePermission):
    """JWT required (mirrors NestJS JwtAuthGuard)."""

    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, "is_authenticated", False))


class RequirePermissions(BasePermission):
    """Permission gate (mirrors PermissionsGuard). The view declares
    `required_permissions = [...]` (any-of semantics, matching the legacy guard).
    Reads/likes may be relaxed per-view via `required_permissions_read`."""

    def has_permission(self, request, view):
        if not bool(request.user and getattr(request.user, "is_authenticated", False)):
            return False
        required: Iterable[str] | None = getattr(view, "required_permissions", None)
        if not required:
            return True  # no permission gate on this view
        perms = _user_permissions(request.user)
        return any(p in perms for p in required)


class AllowAny(BasePermission):
    """Public endpoint (login, health, invite-validate)."""

    def has_permission(self, request, view):
        return True


# Common role gating helpers used by services for object-level checks.
def has_permission(principal: AuthPrincipal, permission: str) -> bool:
    return permission in _user_permissions(principal)


def is_admin(principal: AuthPrincipal) -> bool:
    return principal.active_role == EdifyRole.ADMIN.value


class RolePermissionService:
    """Central Role-Based Access Control and Row Scope Service.
    Enforces security clearance, workflow gates, record ownership, and messaging rules.
    """

    @staticmethod
    def can_view_page(user, page: str) -> bool:
        role = getattr(user, "active_role", None)
        if not role:
            return False

        if role == "Admin":
            return True

        # Admin pages
        if page in ["admin_dashboard", "users", "roles_permissions", "page_access_matrix", "audit_log", "workflow_rules", "feature_flags", "security_center", "upload_history", "notifications_mgmt", "region_district_setup"]:
            return False

        # IA Dashboards and queues
        if page in [
            "ia_dashboard", "ia_verification_queue", "ia_verification", "ia_review_workspace",
            "ia_returned", "ia_history", "ia_duplicates", "ia_notifications", "ia_compare",
            "data_quality_center", "intervention_impact_review", "core_assessment_verification",
            "cluster_ssa_review", "analytics_quality", "ia_reports"
        ]:
            return role in ["ImpactAssessment", "Admin"]

        # RVP Strategic oversight pages
        if page in [
            "rvp_dashboard", "regional_performance", "country_performance", "cd_performance",
            "pl_performance", "cceo_performance_rollups", "budget_approval", "monthly_fund_request",
            "donor_metrics", "strategic_reports", "finance_summary", "risk_dashboard"
        ]:
            return role in ["RegionalVicePresident", "Admin"]

        # HR People management pages
        if page in [
            "hr_dashboard", "staff_performance", "workload_health", "returned_work_patterns",
            "performance_risk", "staff_activity_trends", "workload_balance"
        ]:
            return role in ["HumanResources", "Admin"]

        # Accountant Dashboard
        if page == "accountant_dashboard":
            return role in ["Accountant", "Admin"]

        # School Directory vs Profiles
        if page == "school_directory":
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]
            
        if page in ["school_profile", "school_action_drawer"]:
            return role in ["CCEO", "Program Lead", "ImpactAssessment", "ProjectCoordinator"]

        if page == "school_upload":
            return role in ["ImpactAssessment"]

        # Program scheduling pages
        if page in ["planning", "planning_dashboard", "planning_schedule", "planning_schedule_modal", "planning_schedule_action", "planning_assign_partner_modal", "planning_assign_partner_action", "planning_intelligence", "planning_bulk_action", "cost_preview"]:
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]

        if page == "core_schools":
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]

        # Clusters & Cluster Planning
        if page in ["clusters", "cluster_planning", "cluster_detail"]:
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]

        # Personal and partner planning
        if page == "my_plan":
            return role in ["CCEO", "Program Lead", "ProjectCoordinator", "PartnerAdmin", "PartnerFieldOfficer"]

        if page == "partner_scheduling":
            return role in ["PartnerAdmin", "PartnerFieldOfficer"]

        if page == "evidence_upload":
            return role in ["CCEO", "Program Lead", "PartnerAdmin", "PartnerFieldOfficer"]

        # Consolidated finance page
        if page in ["consolidated_fund_allocation", "fund_allocation", "budget_overview", "cost_settings"]:
            return role in ["Accountant", "CountryDirector", "RegionalVicePresident", "Program Lead"]

        # Budgets & Fund Requests
        if page in ["monthly_budget", "fund_requests"]:
            return role in ["CCEO", "Program Lead", "CountryDirector", "RegionalVicePresident", "Accountant"]

        # Disbursement / Accountant views
        if page in ["disbursements", "reimbursements", "accountability", "finance_action_drawer", "weekly_fund_request_confirm", "weekly_fund_request_self_funded", "weekly_fund_request_disburse"]:
            return role in ["Accountant"]

        # Staff records / HR
        if page in ["staff_directory", "staff", "my_team", "debriefs_list", "debrief_detail", "leave_planner", "leave_planner_view"]:
            return role in ["HumanResources", "Program Lead", "CountryDirector", "RegionalVicePresident"]

        if page == "activity_timeline":
            return role in ["ImpactAssessment", "Admin", "CCEO", "Program Lead", "Accountant", "ProjectCoordinator"]

        # SSA pages
        if page in ["ssa_master", "ssa_upload", "ssa_history", "ssa"]:
            return role in ["ImpactAssessment", "CountryDirector", "RegionalVicePresident", "Program Lead", "CCEO"]

        # Partner dashboards
        if page in ["partner_today", "partner_schools", "partner_activities", "partner_evidence"]:
            return role in ["PartnerAdmin", "PartnerFieldOfficer"]

        # Partners directory
        if page in ["partners", "partner_detail"]:
            return role in ["CCEO", "Program Lead", "CountryDirector", "RegionalVicePresident", "ImpactAssessment", "ProjectCoordinator"]

        # Default allowed for personal views (dashboard, my-plan, profile, settings, help, calendar)
        return True

    @staticmethod
    def can_view_record(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin":
            return True

        obj_type = obj.__class__.__name__

        # CountryDirector and RegionalVicePresident cannot view raw field/planning records directly
        if role in ["CountryDirector", "RegionalVicePresident"] and obj_type in ["School", "Cluster", "Activity", "CorePlan", "CoreActivitySlot"]:
            return False

        from apps.core.scoping import resolve_user_scope
        scope = resolve_user_scope(user)

        if obj_type == "School":
            if scope.country_scope:
                return True
            return obj.id in scope.school_ids

        elif obj_type == "Cluster":
            if scope.country_scope:
                return True
            from apps.schools.models import School
            return obj.id in scope.cluster_ids or School.objects.filter(cluster_id=obj.id, id__in=scope.school_ids).exists()

        elif obj_type == "Activity":
            if scope.country_scope:
                return True
            if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
                return obj.assigned_partner_id in scope.partner_ids
            return obj.school_id in scope.school_ids or obj.responsible_staff_id == user.id

        elif obj_type in ["CorePlan", "CoreActivitySlot"]:
            if scope.country_scope:
                return True
            return obj.school_id in scope.school_ids

        elif obj_type == "FundRequest":
            if role in ["Accountant", "CountryDirector", "RegionalVicePresident"]:
                return True
            return obj.requester_id == user.id or obj.requester_id in scope.supervised_staff_ids

        elif obj_type == "PartnerAssignment":
            if scope.country_scope:
                return True
            return obj.partner_id in scope.partner_ids or obj.school_id in scope.school_ids

        elif obj_type == "MessageThread":
            return obj.participants.filter(id=user.id).exists()

        return True

    @staticmethod
    def can_create(user, object_type: str) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin":
            return True
        if role == "CountryDirector" and object_type in ["activity", "cluster"]:
            return False
        if role == "CountryDirector":
            return True

        if object_type == "activity":
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]
        if object_type == "cluster":
            return role in ["Program Lead", "ImpactAssessment"]
        if object_type == "partner":
            return False
        if object_type == "user":
            return role in ["HumanResources"]
        return False

    @staticmethod
    def can_update(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        obj_type = obj.__class__.__name__
        if role == "CountryDirector" and obj_type in ["School", "Cluster", "Activity", "CorePlan", "CoreActivitySlot"]:
            return False
        return RolePermissionService.can_view_record(user, obj)

    @staticmethod
    def can_delete(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        obj_type = obj.__class__.__name__
        if role == "CountryDirector" and obj_type in ["School", "Cluster", "Activity", "CorePlan", "CoreActivitySlot"]:
            return False
        return role in ["Admin"]

    @staticmethod
    def can_schedule_activity(user, school_or_cluster=None) -> bool:
        role = getattr(user, "active_role", None)
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return False
        if school_or_cluster is None:
            return role in ["CCEO", "Program Lead", "Admin", "ProjectCoordinator"]
        
        return RolePermissionService.can_view_record(user, school_or_cluster)

    @staticmethod
    def can_assign_to_partner(user, school_or_cluster=None) -> bool:
        role = getattr(user, "active_role", None)
        # Mirrors can_schedule_activity's allowed set: assigning to a partner
        # is the alternative to scheduling yourself (spec §5), so whoever can
        # schedule for their portfolio can also hand it off to a partner.
        return role in ["CCEO", "Program Lead", "ProjectCoordinator", "Admin"]

    @staticmethod
    def can_assign_to_staff(user, school) -> bool:
        role = getattr(user, "active_role", None)
        if role == "CountryDirector":
            return False
        return role in ["Program Lead", "ProjectCoordinator", "Admin"]

    @staticmethod
    def can_assign_to_project(user, school) -> bool:
        role = getattr(user, "active_role", None)
        if role == "CountryDirector":
            return False
        return role in ["ProjectCoordinator", "Admin"]

    @staticmethod
    def can_add_to_cluster(user, school) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CCEO", "Program Lead", "ImpactAssessment", "CountryDirector", "Admin"]

    @staticmethod
    def can_upload_evidence(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return activity.assigned_partner_id is not None
        return activity.responsible_staff_id == user.id or role in ["Admin", "ImpactAssessment"]

    @staticmethod
    def can_enter_activity_sf_id(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CCEO", "Program Lead", "ImpactAssessment", "Admin"]

    @staticmethod
    def can_review_activity(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin" or role == "CountryDirector":
            return True
        if role == "Program Lead":
            from apps.core.scoping import resolve_user_scope
            scope = resolve_user_scope(user)
            return activity.responsible_staff_id in scope.supervised_staff_ids
        return False

    @staticmethod
    def can_verify_ia(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["ImpactAssessment", "Admin"]

    @staticmethod
    def can_clear_accounts(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["Accountant", "Admin"]

    @staticmethod
    def can_export(user, page_or_dataset: str) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CountryDirector", "RegionalVicePresident", "Program Lead", "Accountant", "ImpactAssessment", "Admin"]

    @staticmethod
    def can_manage_cost_catalogue(user) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CountryDirector", "Admin"]

    @staticmethod
    def can_manage_users(user) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["Admin", "HumanResources"]

    @staticmethod
    def can_message_recipient(user, recipient) -> bool:
        sender_role = getattr(user, "active_role", None)
        recipient_role = getattr(recipient, "active_role", None)
        if not sender_role or not recipient_role:
            return False
        
        if sender_role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return recipient_role in ["CCEO", "Program Lead", "ProjectCoordinator", "Admin"]

        if sender_role in ["RegionalVicePresident", "HumanResources"]:
            return recipient_role != "PartnerAdmin" and recipient_role != "PartnerFieldOfficer"

        return True


def require_page_permission(page_name: str):
    """Enforces page-level gating across routes and views."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path(), login_url="/login")
            if not RolePermissionService.can_view_page(request.user, page_name):
                from apps.audit.services import log as audit_log
                audit_log(
                    action="unauthorized_page_access",
                    subject_kind="Page",
                    subject_id=page_name,
                    actor_id=str(request.user.id),
                    actor_role=getattr(request.user, "active_role", None),
                    success=False,
                    reason=f"Role '{getattr(request.user, 'active_role', None)}' attempted to access page: {page_name}"
                )
                if request.headers.get("HX-Request") == "true":
                    return HttpResponseForbidden(
                        "<div class='p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-xl text-[12.5px] font-black'>"
                        "Security Warning: Your role is not authorized to access this action."
                        "</div>"
                    )
                messages.error(request, f"Access Denied: Your active role does not have permission to view {page_name.replace('_', ' ').title()}.")
                return redirect("/dashboard")
            return view_func(request, *args, **kwargs)
        _wrapped_view.has_permission_guard = True
        _wrapped_view.page_permission = page_name
        return _wrapped_view
    return decorator


def get_scoped_object_or_404(model, user, *args, **kwargs):
    """Fetch an object by kwargs and verify backend-enforced role and scope access."""
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    
    obj = get_object_or_404(model, *args, **kwargs)
    if not RolePermissionService.can_view_record(user, obj):
        raise PermissionDenied("Access Denied: Your active role or assigned portfolio scope does not permit accessing this record.")
    return obj


__all__ = [
    "IsAuthenticated",
    "RequirePermissions",
    "AllowAny",
    "has_permission",
    "is_admin",
    "RolePermissionService",
    "require_page_permission",
    "get_scoped_object_or_404",
]
