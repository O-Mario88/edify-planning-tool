"""Messaging services — contextual, role-scoped, workflow-linked threads.

Core rules:
  * No context = no message. Every thread anchors to a workflow context.
  * No permission to context = no access to the message thread.
  * Recipients are role-scoped (partner/HR/RVP restrictions) and suggested
    from the context (owner, supervisor, IA, accountant, partner, …).
  * Replies inherit the thread's context and notify all other participants.
"""

from __future__ import annotations

import logging

from django.db.models import F, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import RolePermissionService

from .models import (
    Message,
    MessageDraft,
    MessageParticipant,
    MessageThread,
)

logger = logging.getLogger(__name__)

PARTNER_ROLES = {"PartnerAdmin", "PartnerFieldOfficer"}

# Context types that resolve to an Activity record.
ACTIVITY_CONTEXTS = {
    "activity",
    "planning",
    "execution",
    "verification",
    "evidence",
    "evidence_upload",
    "ssa_verification",
    "ia_return",
    "my_plan",
    "field_debrief",
    "accountability_confirmation",
}

FINANCE_CONTEXTS = {
    "fund_request",
    "budget",
    "budget_line",
    "monthly_request",
    "finance",
    "accountant_disbursement",
}

IA_CONTEXTS = {
    "verification",
    "ssa_verification",
    "ia_return",
    "evidence",
    "evidence_upload",
}

# The compose picker tabs: (key, label). Order mirrors the approved design —
# Schedule leads, then School, Cluster, Partner, Activity, Field Debrief, then
# the finance/planning contexts. Generic types accept a free record id.
CONTEXT_TABS = [
    ("schedule", "Schedule"),
    ("school", "School"),
    ("cluster", "Cluster"),
    ("partner_assignment", "Partner"),
    ("activity", "Activity"),
    ("field_debrief", "Field Debrief"),
    ("fund_request", "Fund Request"),
    ("leave", "Leave"),
    ("project", "Project"),
    ("finance", "Finance"),
    ("system", "System Issue"),
]

CONTEXT_LABELS = {k: v for k, v in CONTEXT_TABS} | {
    "planning": "Planning",
    "execution": "Execution",
    "verification": "Verification",
    "evidence_upload": "Evidence Upload",
    "accountant_disbursement": "Disbursement",
    "accountability_confirmation": "Accountability",
    "budget": "Budget",
    "budget_line": "Budget Line",
    "monthly_request": "Monthly Request",
    "core_school": "Core School",
    "ssa_verification": "SSA Verification",
    "ia_return": "IA Return",
    "schedule": "Schedule",
    "field_debrief": "Field Debrief",
    "leave": "Leave",
    "system": "System Issue",
}

# Role-aware message categories (sender role slug → category options).
ROLE_CATEGORIES = {
    "PARTNER": [
        "Planning assignment",
        "Partner scheduling",
        "Evidence upload",
        "Payment update",
        "Field debrief",
        "School follow-up",
        "Returned correction",
    ],
    "CCEO": [
        "Planning",
        "School follow-up",
        "Cluster activity",
        "Partner assignment",
        "Evidence",
        "Fund request",
        "Daily debrief",
        "SSA collection",
    ],
    "PL": [
        "CCEO supervision",
        "Planning review",
        "Performance follow-up",
        "Critical school",
        "Partner monitoring",
        "Fund request review",
        "Returned activity",
    ],
    "IA": [
        "Evidence verification",
        "SSA verification",
        "Returned activity",
        "Data quality issue",
        "Duplicate risk",
        "Impact validation",
    ],
    "ACCOUNTANT": [
        "Advance disbursement",
        "Partner payment",
        "Reimbursement",
        "Accountability",
        "NetSuite Expense ID",
        "Finance blocked",
        "Returned finance item",
    ],
    "HR": [
        "Leave",
        "Personal Time Off",
        "Debrief",
        "Workload",
        "Staff support",
        "Performance concern",
    ],
    "CD": [
        "Budget approval",
        "Country performance",
        "Risk escalation",
        "Monthly request",
        "Strategic report",
        "Leadership follow-up",
    ],
    "RVP": [
        "Budget approval",
        "Country performance",
        "Risk escalation",
        "Monthly request",
        "Strategic report",
        "Leadership follow-up",
    ],
    "PROJECT_COORDINATOR": [
        "Planning",
        "Project follow-up",
        "Partner assignment",
        "School follow-up",
    ],
    "ADMIN": [
        "Planning",
        "Finance",
        "Verification",
        "Leave",
        "System issue",
        "General follow-up",
    ],
}

HIGH_PRIORITY_CATEGORIES = {
    "Returned correction",
    "Returned activity",
    "Returned finance item",
    "Finance blocked",
    "Critical school",
    "Risk escalation",
    "Data quality issue",
}


def _role_slug(user) -> str:
    from apps.core.navigation import get_user_role_slug

    return get_user_role_slug(user)


def categories_for_role(user) -> list[str]:
    return ROLE_CATEGORIES.get(_role_slug(user), ROLE_CATEGORIES["ADMIN"])


# ── Context resolution & permission ──────────────────────────────────────────


def resolve_context_record(context_type: str | None, context_id: str | None):
    """Return (record, label) for a context, or (None, fallback label)."""
    if not context_type or not context_id:
        return None, ""
    # Compose-picker aliases: Schedule selects schools, Field Debrief selects
    # activities (see search_context_records).
    if context_type == "schedule":
        context_type = "school"
    elif context_type == "field_debrief":
        context_type = "activity"
    try:
        if context_type == "school":
            from apps.schools.models import School

            rec = School.objects.filter(
                Q(id=context_id) | Q(school_id=context_id)
            ).first()
            return rec, (rec.name if rec else f"School {context_id}")
        if context_type in ("cluster",):
            from apps.clusters.models import Cluster

            rec = Cluster.objects.filter(id=context_id).first()
            return rec, (rec.name if rec else f"Cluster {context_id}")
        if context_type in ACTIVITY_CONTEXTS:
            from apps.activities.models import Activity

            rec = Activity.objects.filter(id=context_id).first()
            if rec:
                place = (
                    rec.school.name
                    if rec.school
                    else (rec.cluster.name if rec.cluster else "—")
                )
                return rec, f"{rec.activity_type.replace('_', ' ').title()} — {place}"
            return None, f"Activity {context_id}"
        if context_type in ("fund_request", "accountant_disbursement"):
            from apps.fund_requests.models import WeeklyFundRequest

            rec = WeeklyFundRequest.objects.filter(id=context_id).first()
            if rec:
                return rec, f"Fund Request — week of {rec.week_start_date}"
            return None, f"Fund Request {context_id}"
        if context_type == "leave":
            from apps.accounts.models import Leave

            rec = Leave.objects.filter(id=context_id).first()
            if rec:
                return rec, f"Leave — {rec.staff.user.name} ({rec.start_date})"
            return None, f"Leave {context_id}"
        if context_type == "project":
            from apps.projects.models import Project

            rec = Project.objects.filter(id=context_id).first()
            return rec, (rec.name if rec else f"Project {context_id}")
        if context_type == "partner_assignment":
            from apps.partners.models import PartnerAssignment

            rec = PartnerAssignment.objects.filter(id=context_id).first()
            if rec:
                return rec, f"{rec.partner.name} — {rec.school.name}"
            return None, f"Partner Assignment {context_id}"
    except Exception:
        pass
    return None, f"{CONTEXT_LABELS.get(context_type, context_type)} {context_id}"


def can_access_context(user, context_type: str | None, context_id: str | None) -> bool:
    """Backend gate: a user may only message about records they can access."""
    if not context_type or not context_id:
        return False
    role = _role_slug(user)
    if role == "ADMIN":
        return True

    # Accountants: finance-related messaging only (plus their own leave).
    if role == "ACCOUNTANT" and context_type not in FINANCE_CONTEXTS | {"leave"}:
        return False
    # Partners may only message inside partner-permitted contexts.
    if role == "PARTNER" and context_type in FINANCE_CONTEXTS - {
        "accountant_disbursement"
    }:
        return False

    record, _ = resolve_context_record(context_type, context_id)
    if record is None:
        # Generic / unresolvable contexts fall back to role-level typing.
        if context_type in IA_CONTEXTS:
            return role in {"IA", "CCEO", "PL", "PARTNER", "PROJECT_COORDINATOR"}
        return True

    cls = record.__class__.__name__
    if cls in ("School", "Cluster", "Activity"):
        return RolePermissionService.can_view_record(user, record)
    if cls == "WeeklyFundRequest":
        if role in {"ACCOUNTANT", "CD", "RVP", "IA"}:
            return True
        # Requesters and their chain
        return record.responsible_user == user.id or role in {"PL", "CCEO"}
    if cls == "Leave":
        if role in {"HR", "CD", "RVP", "PL"}:
            return True
        sp = getattr(user, "staff_profile", None)
        return bool(sp and record.staff_id == sp.id)
    if cls == "PartnerAssignment":
        if role == "PARTNER":
            partner = getattr(user, "partner", None)
            return bool(partner and record.partner_id == partner.id)
        return role in {"CCEO", "PL", "IA", "PROJECT_COORDINATOR", "CD"}
    return True


# ── Recipients ───────────────────────────────────────────────────────────────


def _serialize_user(u: User) -> dict:
    meta = ""
    try:
        sp = getattr(u, "staff_profile", None)
        if sp and sp.primary_district_id:
            from apps.geography.models import District

            d = District.objects.filter(id=sp.primary_district_id).first()
            meta = d.name if d else ""
        partner = getattr(u, "partner", None)
        if partner:
            meta = partner.name
    except Exception:
        meta = ""
    return {
        "id": u.id,
        "name": u.name,
        "role": getattr(u, "active_role", None) or (u.roles or ["Staff"])[0],
        "meta": meta,
    }


def recipients(principal) -> list[dict]:
    """Composable recipients for the caller (by role policy)."""
    users = User.objects.filter(deleted_at__isnull=True, status="active").exclude(
        id=principal.user_id if hasattr(principal, "user_id") else principal.id
    )
    allowed = [
        u for u in users if RolePermissionService.can_message_recipient(principal, u)
    ]
    return [_serialize_user(u) for u in allowed[:100]]


def suggested_recipients(
    user, context_type: str | None, context_id: str | None
) -> list[dict]:
    """Context-driven recipient suggestions, filtered by role policy."""
    suggestions: list[User] = []

    def add(u):
        if u is not None and u.id != user.id and u not in suggestions:
            suggestions.append(u)

    def add_by_role(role_name, limit=2):
        for u in User.objects.filter(
            status="active", deleted_at__isnull=True, roles__contains=[role_name]
        )[:limit]:
            add(u)

    def supervisor_of(user_id):
        try:
            from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

            sp = StaffProfile.objects.filter(user_id=user_id).first()
            if not sp:
                return None
            link = StaffSupervisorAssignment.objects.filter(supervisee=sp).first()
            return link.supervisor.user if link else None
        except Exception:
            return None

    def user_for_staff_identity(staff_or_user_id):
        """Resolve canonical StaffProfile ids and legacy User ids alike."""
        if not staff_or_user_id:
            return None
        return User.objects.filter(
            Q(id=staff_or_user_id) | Q(staff_profile__id=staff_or_user_id)
        ).first()

    record, _ = resolve_context_record(context_type, context_id)
    cls = record.__class__.__name__ if record is not None else None

    try:
        if cls == "School":
            if record.account_owner_id:
                owner = (
                    User.objects.filter(
                        staff_profile__id=record.account_owner_id
                    ).first()
                    or User.objects.filter(id=record.account_owner_id).first()
                )
                add(owner)
                if owner:
                    add(supervisor_of(owner.id))
            from apps.partners.models import PartnerAssignment

            pa = PartnerAssignment.objects.filter(school=record).first()
            if pa and pa.partner and pa.partner.user_id:
                add(User.objects.filter(id=pa.partner.user_id).first())
            add_by_role("ImpactAssessment", 1)
        elif cls == "Cluster":
            if record.responsible_staff_id:
                add(user_for_staff_identity(record.responsible_staff_id))
            add_by_role("Program Lead", 1)
            add_by_role("ImpactAssessment", 1)
        elif cls == "Activity":
            if record.responsible_staff_id:
                owner = user_for_staff_identity(record.responsible_staff_id)
                add(owner)
                if owner:
                    add(supervisor_of(owner.id))
            if record.monitored_by_staff_id:
                add(user_for_staff_identity(record.monitored_by_staff_id))
            if record.assigned_partner_id:
                from apps.partners.models import Partner

                p = Partner.objects.filter(id=record.assigned_partner_id).first()
                if p and p.user_id:
                    add(User.objects.filter(id=p.user_id).first())
            if context_type in IA_CONTEXTS or record.status in (
                "awaiting_ia_verification",
                "returned_by_ia",
            ):
                add_by_role("ImpactAssessment", 1)
            if record.status in ("accountant_confirmed", "disbursed"):
                add_by_role("Accountant", 1)
        elif cls == "WeeklyFundRequest":
            add(User.objects.filter(id=record.responsible_user).first())
            add_by_role("Program Lead", 1)
            add_by_role("CountryDirector", 1)
            add_by_role("Accountant", 1)
            add_by_role("RegionalVicePresident", 1)
        elif cls == "Leave":
            staff_user = record.staff.user if record.staff else None
            add(staff_user)
            if staff_user:
                add(supervisor_of(staff_user.id))
            if record.covering_staff:
                add(record.covering_staff.user)
            add_by_role("HumanResources", 1)
        elif cls == "PartnerAssignment":
            if record.partner and record.partner.user_id:
                add(User.objects.filter(id=record.partner.user_id).first())
            if record.assigning_staff_id:
                add(user_for_staff_identity(record.assigning_staff_id))
            add_by_role("Program Lead", 1)
        elif context_type in FINANCE_CONTEXTS:
            add_by_role("Accountant", 1)
            add_by_role("CountryDirector", 1)
        elif context_type in IA_CONTEXTS:
            add_by_role("ImpactAssessment", 2)
    except Exception:
        pass

    # Role policy filter — never suggest someone the sender can't message.
    return [
        _serialize_user(u)
        for u in suggestions
        if RolePermissionService.can_message_recipient(user, u)
    ][:8]


def search_context_records(
    user, context_type: str, q: str = "", status_filter: str = ""
) -> list[dict]:
    """Records for the compose picker, scoped to what the user can access.

    The Schedule tab selects schools (scheduling is school-level); Field Debrief
    selects activities. status_filter narrows schools by readiness/SSA.
    """
    out = []
    q = (q or "").strip()
    status_filter = (status_filter or "").strip().lower()
    # Schedule/Field-Debrief reuse the school/activity pickers.
    if context_type == "schedule":
        context_type = "school"
    elif context_type == "field_debrief":
        context_type = "activity"
    try:
        if context_type == "school":
            from apps.core.scoping import resolve_user_scope, school_queryset

            qs = school_queryset(resolve_user_scope(user))
            if qs is None:
                return []
            if q:
                qs = qs.filter(name__icontains=q)
            if status_filter == "scheduled":
                qs = qs.filter(planning_readiness="scheduled")
            elif status_filter == "pending":
                qs = qs.exclude(planning_readiness="scheduled")
            elif status_filter in ("no_ssa", "no ssa"):
                qs = qs.exclude(current_fy_ssa_status="done")
            for s in qs.select_related("district")[:12]:
                out.append(
                    {
                        "id": s.school_id or s.id,
                        "title": s.name,
                        "meta": s.district.name if s.district else "—",
                        "status": (s.planning_readiness or "").replace("_", " ").title()
                        or "Pending",
                    }
                )
        elif context_type == "cluster":
            from apps.clusters.models import Cluster

            qs = Cluster.objects.filter(deleted_at__isnull=True)
            if q:
                qs = qs.filter(name__icontains=q)
            for c in qs[:12]:
                out.append(
                    {"id": c.id, "title": c.name, "meta": "Cluster", "status": c.status}
                )
        elif context_type == "activity":
            from apps.activities.models import Activity

            qs = Activity.objects.filter(deleted_at__isnull=True).select_related(
                "school", "cluster"
            )
            role = _role_slug(user)
            if role == "CCEO":
                qs = qs.filter(responsible_staff_id=user.id)
            elif role == "PARTNER":
                partner = getattr(user, "partner", None)
                qs = qs.filter(assigned_partner_id=partner.id) if partner else qs.none()
            if q:
                qs = qs.filter(
                    Q(school__name__icontains=q) | Q(activity_type__icontains=q)
                )
            for a in qs.order_by("-created_at")[:12]:
                place = (
                    a.school.name
                    if a.school
                    else (a.cluster.name if a.cluster else "—")
                )
                out.append(
                    {
                        "id": a.id,
                        "title": f"{a.activity_type.replace('_', ' ').title()}",
                        "meta": place,
                        "status": a.status,
                    }
                )
        elif context_type == "fund_request":
            from apps.fund_requests.models import WeeklyFundRequest

            qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")
            role = _role_slug(user)
            if role in {"CCEO", "PL"}:
                qs = qs.filter(responsible_user=user.id)
            for w in qs[:12]:
                out.append(
                    {
                        "id": w.id,
                        "title": f"Week of {w.week_start_date}",
                        "meta": f"UGX {w.total_amount:,}",
                        "status": w.status.replace("_", " "),
                    }
                )
        elif context_type == "leave":
            from apps.accounts.models import Leave

            qs = Leave.objects.select_related("staff__user").order_by("-created_at")
            role = _role_slug(user)
            if role not in {"HR", "CD", "RVP", "PL", "ADMIN"}:
                sp = getattr(user, "staff_profile", None)
                qs = qs.filter(staff=sp) if sp else qs.none()
            for leave in qs[:12]:
                out.append(
                    {
                        "id": leave.id,
                        "title": f"{leave.staff.user.name} — {leave.type}",
                        "meta": f"{leave.start_date} → {leave.end_date}",
                        "status": leave.status,
                    }
                )
        elif context_type == "project":
            from apps.projects.models import Project

            qs = Project.objects.filter(deleted_at__isnull=True)
            if q:
                qs = qs.filter(name__icontains=q)
            for p in qs[:12]:
                out.append(
                    {"id": p.id, "title": p.name, "meta": "Project", "status": ""}
                )
        elif context_type == "partner_assignment":
            from apps.partners.models import PartnerAssignment

            qs = PartnerAssignment.objects.select_related("partner", "school")
            role = _role_slug(user)
            if role == "PARTNER":
                partner = getattr(user, "partner", None)
                qs = qs.filter(partner=partner) if partner else qs.none()
            if q:
                qs = qs.filter(school__name__icontains=q)
            for pa in qs[:12]:
                out.append(
                    {
                        "id": pa.id,
                        "title": f"{pa.partner.name} — {pa.school.name}",
                        "meta": pa.expected_activity_type or "Assignment",
                        "status": pa.status,
                    }
                )
    except Exception:
        pass
    return out


def context_summary(user, context_type, context_id, linked_ids=None) -> dict:
    """Compose right-rail summary: type, title, geography, partner, items."""
    record, label = resolve_context_record(context_type, context_id)
    out = {
        "type_label": CONTEXT_LABELS.get(context_type, context_type or ""),
        "title": label,
        "district": "",
        "cluster": "",
        "partner": "",
        "items": [],
    }
    school = None
    try:
        cls = record.__class__.__name__ if record is not None else None
        if cls == "School":
            school = record
        elif cls == "Activity":
            school = record.school
            if record.cluster:
                out["cluster"] = record.cluster.name
        elif cls == "Cluster":
            out["cluster"] = record.name
            if record.district:
                out["district"] = record.district.name
        elif cls == "PartnerAssignment":
            school = record.school
            out["partner"] = record.partner.name if record.partner else ""
        if school is not None:
            out["district"] = (
                school.district.name if school.district else out["district"]
            )
            if not out["cluster"] and school.cluster_id:
                from apps.clusters.models import Cluster

                c = Cluster.objects.filter(id=school.cluster_id).first()
                out["cluster"] = c.name if c else ""
            if not out["partner"]:
                from apps.partners.models import PartnerAssignment

                pa = (
                    PartnerAssignment.objects.filter(school=school)
                    .select_related("partner")
                    .first()
                )
                out["partner"] = pa.partner.name if pa and pa.partner else ""
    except Exception:
        pass
    for item_id in [context_id, *(linked_ids or [])]:
        if not item_id or any(i["id"] == item_id for i in out["items"]):
            continue
        rec, item_label = resolve_context_record(context_type, item_id)
        status = ""
        try:
            status = (
                getattr(rec, "status", "")
                or getattr(rec, "planning_readiness", "")
                or ""
            ).replace("_", " ")
        except Exception:
            status = ""
        out["items"].append({"id": item_id, "label": item_label, "status": status})
    return out


# ── Thread listing / KPIs ────────────────────────────────────────────────────


def _participant_threads(user):
    return (
        MessageParticipant.objects.filter(user_id=user.id)
        .select_related("thread")
        .prefetch_related(
            Prefetch(
                "thread__messages",
                queryset=Message.objects.order_by("created_at"),
                to_attr="_message_cache",
            ),
            Prefetch(
                "thread__participants",
                queryset=MessageParticipant.objects.order_by("created_at"),
                to_attr="_participant_cache",
            ),
        )
    )


def _thread_messages(thread: MessageThread) -> list[Message]:
    cached = getattr(thread, "_message_cache", None)
    return (
        cached if cached is not None else list(thread.messages.order_by("created_at"))
    )


def _thread_participants(thread: MessageThread) -> list[MessageParticipant]:
    cached = getattr(thread, "_participant_cache", None)
    return cached if cached is not None else list(thread.participants.all())


def _last_message(thread: MessageThread) -> Message | None:
    messages = _thread_messages(thread)
    return messages[-1] if messages else None


def _is_unread(p: MessageParticipant, last: Message | None = None) -> bool:
    t = p.thread
    if not t.last_reply_at:
        return False
    if p.last_read_at is None or p.last_read_at < t.last_reply_at:
        last = last or _last_message(t)
        return bool(last and last.sender_id != p.user_id)
    return False


def unread_thread_count(user) -> int:
    """Return the authoritative unread conversation count in one query."""
    latest_sender = (
        Message.objects.filter(thread_id=OuterRef("thread_id"))
        .order_by("-created_at")
        .values("sender_id")[:1]
    )
    return (
        MessageParticipant.objects.filter(
            user_id=user.id,
            archived_at__isnull=True,
            thread__last_reply_at__isnull=False,
        )
        .filter(
            Q(last_read_at__isnull=True)
            | Q(last_read_at__lt=F("thread__last_reply_at"))
        )
        .annotate(latest_sender_id=Subquery(latest_sender))
        .exclude(latest_sender_id=user.id)
        .count()
    )


def threads_for_user(user, tab: str = "all", search: str = "") -> list[dict]:
    parts = _participant_threads(user)
    if tab == "archived":
        parts = parts.filter(archived_at__isnull=False)
    else:
        parts = parts.filter(archived_at__isnull=True)

    rows = []
    partner_user_ids = None
    for p in parts:
        t = p.thread
        last = _last_message(t)
        unread = _is_unread(p, last)
        if not last:
            continue
        if tab == "unread" and not unread:
            continue
        if tab == "assigned" and p.recipient_type != MessageParticipant.TO:
            continue
        if tab == "sent" and t.created_by != user.id:
            continue
        if tab == "finance" and t.context_type not in FINANCE_CONTEXTS:
            continue
        if tab == "ia_review" and t.context_type not in IA_CONTEXTS:
            continue
        if tab == "partner":
            if partner_user_ids is None:
                partner_user_ids = set(
                    User.objects.filter(
                        Q(roles__contains=["PartnerAdmin"])
                        | Q(roles__contains=["PartnerFieldOfficer"])
                    ).values_list("id", flat=True)
                )
            member_ids = {member.user_id for member in _thread_participants(t)}
            if not member_ids & partner_user_ids:
                continue
        if (
            search
            and search.lower() not in (t.subject or "").lower()
            and search.lower() not in (t.context_label or "").lower()
        ):
            continue
        rows.append(
            {
                "id": t.id,
                "subject": t.subject,
                "snippet": (last.body or "")[:90],
                "sender_id": last.sender_id,
                "context_type": t.context_type,
                "context_badge": CONTEXT_LABELS.get(
                    t.context_type, t.context_type or ""
                ),
                "context_label": t.context_label or "",
                "priority": t.priority,
                "unread": unread,
                "starred": p.starred,
                "is_system": t.is_system_generated,
                "last_at": t.last_reply_at or t.updated_at,
            }
        )
    sender_names = dict(
        User.objects.filter(id__in={row["sender_id"] for row in rows}).values_list(
            "id", "name"
        )
    )
    for row in rows:
        row["sender_name"] = sender_names.get(row.pop("sender_id"), "System")
    rows.sort(key=lambda r: r["last_at"], reverse=True)
    return rows


def message_kpis(user) -> dict:
    parts = list(_participant_threads(user).filter(archived_at__isnull=True))
    unread = sum(1 for p in parts if _is_unread(p, _last_message(p.thread)))
    awaiting = 0
    returned = 0
    finance = 0
    partner = 0
    system = 0
    partner_user_ids = set(
        User.objects.filter(
            Q(roles__contains=["PartnerAdmin"])
            | Q(roles__contains=["PartnerFieldOfficer"])
        ).values_list("id", flat=True)
    )
    for p in parts:
        t = p.thread
        last = _last_message(t)
        if last and last.sender_id == user.id:
            awaiting += 1
        if (t.category or "").lower().startswith(
            "returned"
        ) or t.context_type == "ia_return":
            returned += 1
        if t.context_type in FINANCE_CONTEXTS:
            finance += 1
        if {member.user_id for member in _thread_participants(t)} & partner_user_ids:
            partner += 1
        if t.is_system_generated:
            system += 1
    total = len(parts) or 1
    return {
        "unread": unread,
        "awaiting_reply": awaiting,
        "returned": returned,
        "finance": finance,
        "finance_pct": round(finance * 100 / total),
        "partner": partner,
        "partner_pct": round(partner * 100 / total),
        "system": system,
        "total": len(parts),
    }


# ── Thread detail ────────────────────────────────────────────────────────────


def _require_thread_access(thread_id: str, user) -> MessageThread:
    t = MessageThread.objects.filter(id=thread_id).first()
    if not t:
        raise NotFoundError("Thread not found.")
    role = _role_slug(user)
    is_participant = t.participants.filter(user_id=user.id).exists()
    if not is_participant and role != "ADMIN":
        raise Forbidden("You are not a participant in this conversation thread.")
    # Context gate: participants lose access if they cannot access the record.
    if role != "ADMIN" and t.context_type and t.context_id:
        if not can_access_context(user, t.context_type, t.context_id):
            raise Forbidden(
                "You no longer have access to the record this conversation is about."
            )
    return t


def thread_detail(thread_id: str, user) -> dict:
    t = _require_thread_access(thread_id, user)
    msgs = list(t.messages.order_by("created_at").prefetch_related("attachments"))
    user_ids = {m.sender_id for m in msgs} | set(
        t.participants.values_list("user_id", flat=True)
    )
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)}

    # Advance this user's read cursor.
    MessageParticipant.objects.filter(thread=t, user_id=user.id).update(
        last_read_at=timezone.now()
    )
    Message.objects.filter(thread=t, recipient_id=user.id, status="unread").update(
        status="read"
    )

    participants = [
        {
            **_serialize_user(users[p.user_id]),
            "recipient_type": p.recipient_type,
        }
        for p in t.participants.all()
        if p.user_id in users
    ]
    me = t.participants.filter(user_id=user.id).first()
    return {
        "thread": t,
        "participants": participants,
        "can_reply": any(p["id"] != user.id for p in participants),
        "starred": bool(me and me.starred),
        "messages": [
            {
                "id": m.id,
                "sender": _serialize_user(users[m.sender_id])
                if m.sender_id in users
                else {"id": m.sender_id, "name": "System", "role": "System"},
                "body": m.body,
                "created_at": m.created_at,
                "is_system": m.is_system_generated,
                "attachments": [
                    {
                        "id": a.id,
                        "name": a.file_name,
                        "size": a.file_size,
                        "url": f"/messages/attachments/{a.id}",
                    }
                    for a in m.attachments.all()
                ],
            }
            for m in msgs
        ],
    }


def context_panel(thread: MessageThread, user) -> dict:
    """Workflow context fields, timeline, and quick actions for a thread."""
    record, label = resolve_context_record(thread.context_type, thread.context_id)
    fields = {
        "context_type": CONTEXT_LABELS.get(thread.context_type, thread.context_type),
        "context_label": thread.context_label or label,
    }
    timeline: list[dict] = []
    actions: list[dict] = []
    cls = record.__class__.__name__ if record is not None else None

    if cls == "Activity":
        owner = User.objects.filter(
            Q(id=record.responsible_staff_id)
            | Q(staff_profile__id=record.responsible_staff_id)
        ).first()
        next_map = {
            "planned": "Schedule the visit",
            "scheduled": "Confirm schedule",
            "partner_scheduled": "Confirm partner schedule",
            "in_progress": "Complete the activity",
            "completion_started": "Submit for verification",
            "completed": "Await IA verification",
            "awaiting_ia_verification": "IA verification",
            "returned_by_ia": "Fix and resubmit",
            "ia_verified": "Accountant confirmation",
        }
        fields.update(
            {
                "owner": owner.name if owner else "—",
                "status": record.status.replace("_", " ").title(),
                "next_action": next_map.get(record.status, ""),
                "activity_date": record.planned_date,
                "linked_record": label,
            }
        )
        steps = [
            ("Planned", ["planned"]),
            ("Scheduled", ["scheduled", "partner_scheduled", "assigned_to_partner"]),
            ("In Progress", ["in_progress", "completion_started"]),
            ("Completed", ["completed", "awaiting_ia_verification"]),
            ("Verified & Closed", ["ia_verified", "accountant_confirmed", "closed"]),
        ]
        reached = True
        for label_s, statuses in steps:
            current = record.status in statuses
            timeline.append(
                {"label": label_s, "done": reached and not current, "current": current}
            )
            if current:
                reached = False
        actions.append(
            {"label": "Open Linked Activity", "href": f"/my-plan/{record.id}"}
        )
        if record.cluster_id:
            actions.append(
                {
                    "label": "View Cluster Dashboard",
                    "href": f"/clusters/{record.cluster_id}",
                }
            )
        actions.append({"label": "Review Related Evidence", "href": "/evidence/"})
    elif cls == "School":
        fields.update(
            {
                "owner": record.account_owner_name_raw or "—",
                "status": record.planning_readiness or "—",
                "linked_record": record.name,
            }
        )
        actions.append(
            {"label": "Open School Profile", "href": f"/schools/{record.school_id}"}
        )
    elif cls == "Cluster":
        fields.update({"status": record.status, "linked_record": record.name})
        actions.append(
            {"label": "View Cluster Dashboard", "href": f"/clusters/{record.id}"}
        )
    elif cls == "WeeklyFundRequest":
        fields.update(
            {
                "status": record.status.replace("_", " ").title(),
                "linked_record": label,
            }
        )
        chain = [
            ("Submitted", ["submitted_to_pl", "submitted_to_cd"]),
            ("Approved", ["approved_by_pl", "approved_by_cd", "sent_to_accountant"]),
            ("Disbursed", ["disbursed"]),
            ("Accounted", ["accounted"]),
        ]
        reached = True
        for label_s, statuses in chain:
            current = record.status in statuses
            timeline.append(
                {"label": label_s, "done": reached and not current, "current": current}
            )
            if current:
                reached = False
        actions.append({"label": "Open Fund Request", "href": "/fund-requests/weekly"})
    elif cls == "Leave":
        fields.update(
            {
                "owner": record.staff.user.name if record.staff else "—",
                "status": record.status.title(),
                "linked_record": label,
            }
        )
        actions.append({"label": "Open Leave Approvals", "href": "/leave/approvals"})
    elif cls == "PartnerAssignment":
        fields.update({"status": record.status, "linked_record": label})
        actions.append({"label": "Open Partner Assignment", "href": "/partners"})
    elif thread.context_type == "system":
        fields.update(
            {
                "status": "Delivered",
                "linked_record": thread.context_label or thread.subject,
            }
        )
        actions.append({"label": "Open Analytics", "href": "/analytics"})
    return {"fields": fields, "timeline": timeline, "actions": actions}


# ── Sending / replying ───────────────────────────────────────────────────────


def _thread_label(context_type, context_id):
    _, label = resolve_context_record(context_type, context_id)
    return label


def send(data: dict, principal) -> dict:
    to_ids = data.get("recipientIds") or []
    if data.get("recipientId"):
        to_ids = [data["recipientId"], *to_ids]
    to_ids = list(dict.fromkeys(to_ids))
    cc_ids = [c for c in (data.get("ccIds") or []) if c not in to_ids]
    if not to_ids:
        raise BadRequest("Recipient ID is required.")

    context_type = data.get("contextType")
    context_id = data.get("contextId")
    if not context_type or not context_id:
        raise BadRequest(
            "All new messages must have a context (contextType and contextId)."
        )

    sender_id = principal.user_id if hasattr(principal, "user_id") else principal.id
    if not can_access_context(principal, context_type, context_id):
        raise Forbidden("You cannot message about a record you cannot access.")

    recipients_users = []
    for rid in [*to_ids, *cc_ids]:
        if str(rid) == str(sender_id):
            raise BadRequest("You cannot add yourself as a recipient.")
        u = User.objects.filter(
            id=rid, deleted_at__isnull=True, status="active"
        ).first()
        if not u:
            raise NotFoundError("Recipient not found.")
        if not RolePermissionService.can_message_recipient(principal, u):
            raise Forbidden("Your active role is not permitted to message this user.")
        # A recipient must be allowed to open the same workflow record. Without
        # this, a sender could create a thread that the recipient can receive
        # but cannot safely read or reply to once the thread access gate runs.
        if not can_access_context(u, context_type, context_id):
            raise Forbidden("The recipient cannot access this workflow context.")
        recipients_users.append(u)

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not subject:
        raise BadRequest("Subject is required.")
    if len(subject) > 255:
        raise BadRequest("Subject cannot exceed 255 characters.")
    if not body:
        raise BadRequest("Message is required.")
    if len(body) > 50_000:
        raise BadRequest("Message cannot exceed 50,000 characters.")
    category = data.get("category")
    priority = (
        "high"
        if category in HIGH_PRIORITY_CATEGORIES
        else data.get("priority") or "normal"
    )

    # Direct 2-party sends reuse the (pair, context, subject) thread; group
    # sends always start a fresh thread.
    thread = None
    created = True
    if len(to_ids) == 1 and not cc_ids:
        pair = sorted([sender_id, to_ids[0]])
        thread, created = MessageThread.objects.get_or_create(
            participant_a_id=pair[0],
            participant_b_id=pair[1],
            context_type=context_type,
            context_id=context_id,
            subject=subject,
            defaults={
                "category": category,
                "priority": priority,
                "created_by": sender_id,
                "context_label": _thread_label(context_type, context_id),
            },
        )
    linked_items = []
    for item_id in data.get("linkedItems") or []:
        if item_id == context_id:
            continue
        _, item_label = resolve_context_record(context_type, item_id)
        linked_items.append({"id": item_id, "label": item_label})

    if thread is None:
        thread = MessageThread.objects.create(
            subject=subject,
            context_type=context_type,
            context_id=context_id,
            context_label=_thread_label(context_type, context_id),
            linked_items=linked_items,
            category=category,
            priority=priority,
            created_by=sender_id,
        )
    elif linked_items and not thread.linked_items:
        thread.linked_items = linked_items
        thread.save(update_fields=["linked_items"])

    # Ensure membership rows.
    MessageParticipant.objects.get_or_create(
        thread=thread, user_id=sender_id, defaults={"recipient_type": "to"}
    )
    for rid in to_ids:
        MessageParticipant.objects.get_or_create(
            thread=thread, user_id=rid, defaults={"recipient_type": "to"}
        )
    for rid in cc_ids:
        MessageParticipant.objects.get_or_create(
            thread=thread, user_id=rid, defaults={"recipient_type": "cc"}
        )

    msg = Message.objects.create(
        thread=thread,
        sender_id=sender_id,
        recipient_id=to_ids[0],
        body=body,
        category=category,
        context_type=context_type,
        context_id=context_id,
        target_route=data.get("targetRoute"),
        priority=priority,
        action_required=bool(data.get("actionRequired")),
    )
    thread.last_reply_at = msg.created_at
    thread.save(update_fields=["last_reply_at", "updated_at"])

    sender_read = MessageParticipant.objects.filter(thread=thread, user_id=sender_id)
    sender_read.update(last_read_at=timezone.now())

    for u in recipients_users:
        _notify_recipient(msg, principal, u.id)
    return _serialize(msg)


def reply(thread_id: str, data: dict, principal) -> dict:
    thread = _require_thread_access(thread_id, principal)
    sender_id = principal.user_id if hasattr(principal, "user_id") else principal.id
    body = (data.get("body") or "").strip()
    if not body:
        raise BadRequest("Reply message is required.")
    if len(body) > 50_000:
        raise BadRequest("Reply cannot exceed 50,000 characters.")
    messages = Message.objects.filter(thread_id=thread_id)
    first_msg = messages.first()
    if not first_msg:
        raise BadRequest("Thread is empty.")

    others = list(
        thread.participants.exclude(user_id=sender_id).values_list("user_id", flat=True)
    )
    if not others:
        if thread.is_system_generated:
            raise BadRequest("This system conversation is read-only.")
        # Legacy threads without membership rows.
        if thread.participant_a_id and thread.participant_b_id:
            others = [
                thread.participant_b_id
                if thread.participant_a_id == sender_id
                else thread.participant_a_id
            ]
        else:
            others = [
                first_msg.recipient_id
                if first_msg.sender_id == sender_id
                else first_msg.sender_id
            ]
    others = [recipient_id for recipient_id in others if recipient_id != sender_id]
    if not others:
        raise BadRequest("This system conversation is read-only.")

    msg = Message.objects.create(
        thread=thread,
        sender_id=sender_id,
        recipient_id=others[0] if others else None,
        body=body,
        context_type=thread.context_type,
        context_id=thread.context_id,
    )
    thread.last_reply_at = msg.created_at
    thread.save(update_fields=["last_reply_at", "updated_at"])
    MessageParticipant.objects.filter(thread=thread, user_id=sender_id).update(
        last_read_at=timezone.now()
    )
    for rid in others:
        if rid:
            _notify_recipient(msg, principal, rid)
    return _serialize(msg)


def archive_thread(thread_id: str, user, archived: bool = True) -> dict:
    t = _require_thread_access(thread_id, user)
    t.participants.filter(user_id=user.id).update(
        archived_at=timezone.now() if archived else None
    )
    return {"ok": True}


def toggle_star(thread_id: str, user) -> dict:
    t = _require_thread_access(thread_id, user)
    p = t.participants.filter(user_id=user.id).first()
    if p:
        p.starred = not p.starred
        p.save(update_fields=["starred"])
    return {"starred": bool(p and p.starred)}


# ── Drafts ───────────────────────────────────────────────────────────────────


def save_draft(data: dict, user) -> MessageDraft:
    draft_id = data.get("draftId")
    fields = {
        "subject": data.get("subject", ""),
        "category": data.get("category"),
        "context_type": data.get("contextType"),
        "context_id": data.get("contextId"),
        "recipient_ids": data.get("recipientIds") or [],
        "cc_ids": data.get("ccIds") or [],
        "body": data.get("body", ""),
    }
    if draft_id:
        d = MessageDraft.objects.filter(id=draft_id, user_id=user.id).first()
        if d:
            for k, v in fields.items():
                setattr(d, k, v)
            d.save()
            return d
    return MessageDraft.objects.create(user_id=user.id, **fields)


def drafts_for_user(user, limit=5):
    drafts = list(MessageDraft.objects.filter(user_id=user.id)[:limit])
    all_ids = {rid for d in drafts for rid in (d.recipient_ids or [])}
    names = dict(User.objects.filter(id__in=all_ids).values_list("id", "name"))
    for d in drafts:
        ids = d.recipient_ids or []
        shown = [names[i] for i in ids[:2] if i in names]
        label = ", ".join(shown)
        if len(ids) > 2:
            label += f" +{len(ids) - 2}"
        d.recipient_names = label
    return drafts


# ── Workflow-generated messages ──────────────────────────────────────────────


def workflow_message(
    *,
    context_type: str,
    context_id: str,
    subject: str,
    body: str,
    recipient_ids: list[str],
    category: str | None = None,
    priority: str = "normal",
    sender_id: str | None = None,
) -> MessageThread | None:
    """Create or extend a system-generated contextual thread for a workflow
    event. Best-effort: workflow actions must never fail on messaging."""
    try:
        thread = MessageThread.objects.filter(
            context_type=context_type,
            context_id=context_id,
            is_system_generated=True,
        ).first()
        if not thread:
            thread = MessageThread.objects.create(
                subject=subject,
                context_type=context_type,
                context_id=context_id,
                context_label=_thread_label(context_type, context_id),
                category=category,
                priority=priority,
                created_by=sender_id,
                is_system_generated=True,
            )
        for rid in {r for r in recipient_ids if r}:
            MessageParticipant.objects.get_or_create(
                thread=thread, user_id=rid, defaults={"recipient_type": "to"}
            )
        msg = Message.objects.create(
            thread=thread,
            sender_id=sender_id or "system",
            recipient_id=recipient_ids[0] if recipient_ids else None,
            body=body,
            category=category,
            context_type=context_type,
            context_id=context_id,
            priority=priority,
            is_system_generated=True,
        )
        thread.last_reply_at = msg.created_at
        thread.save(update_fields=["last_reply_at", "updated_at"])
        for rid in {r for r in recipient_ids if r and r != sender_id}:
            _notify_recipient(msg, None, rid)
        return thread
    except Exception:
        logger.exception(
            "Could not create workflow message for %s:%s",
            context_type,
            context_id,
        )
        return None


# ── Legacy-compatible helpers ────────────────────────────────────────────────


def recent(principal, query: dict) -> list[dict]:
    uid = principal.user_id if hasattr(principal, "user_id") else principal.id
    thread_ids = MessageParticipant.objects.filter(user_id=uid).values("thread_id")
    qs = Message.objects.filter(thread_id__in=thread_ids).order_by("-created_at")
    return [_serialize(m) for m in qs[:50]]


def counts(principal) -> dict:
    uid = principal.user_id if hasattr(principal, "user_id") else principal.id
    user = principal if hasattr(principal, "id") else User.objects.get(id=uid)
    total = MessageParticipant.objects.filter(
        user_id=uid, archived_at__isnull=True
    ).count()
    return {"unread": unread_thread_count(user), "total": total}


def contexts(query: dict) -> list[dict]:
    recipient_id = query.get("recipientId")
    qs = Message.objects.all()
    if recipient_id:
        qs = qs.filter(recipient_id=recipient_id)
    return [
        {"contextType": m["context_type"], "contextId": m["context_id"]}
        for m in qs.exclude(context_type__isnull=True).values(
            "context_type", "context_id", "id"
        )[:20]
    ]


def thread(thread_id: str, principal) -> list[dict]:
    t = MessageThread.objects.filter(id=thread_id).first()
    if not t:
        raise NotFoundError("Thread not found.")
    uid = principal.user_id if hasattr(principal, "user_id") else principal.id
    messages = Message.objects.filter(thread_id=thread_id).order_by("created_at")
    is_member = t.participants.filter(user_id=uid).exists()
    has_access = (
        is_member or messages.filter(Q(sender_id=uid) | Q(recipient_id=uid)).exists()
    )
    if not has_access and getattr(principal, "active_role", None) != "Admin":
        raise Forbidden("You are not a participant in this conversation thread.")
    return [_serialize(m) for m in messages]


def mark_read(message_id: str, principal) -> dict:
    uid = principal.user_id if hasattr(principal, "user_id") else principal.id
    m = Message.objects.filter(id=message_id).first()
    if m:
        is_recipient = (
            m.sender_id != uid
            and MessageParticipant.objects.filter(
                thread_id=m.thread_id, user_id=uid
            ).exists()
        )
        if not is_recipient:
            raise Forbidden("Cannot mark another user's message as read.")
        MessageParticipant.objects.filter(thread_id=m.thread_id, user_id=uid).update(
            last_read_at=timezone.now()
        )
        if m.recipient_id == uid:
            m.status = "read"
            m.save(update_fields=["status"])
    return {"ok": True}


def _notify_recipient(msg: Message, sender, recipient_id: str | None = None) -> None:
    """Surface a new message in the recipient's notification bell. Best-effort:
    a notification failure must never block the message itself."""
    try:
        from apps.notifications.services import WorkflowNotificationService

        rid = recipient_id or msg.recipient_id
        if not rid:
            return
        sender_name = getattr(sender, "name", None) or "Edify Workflow"
        preview = (msg.body or "").strip()
        if len(preview) > 120:
            preview = preview[:117] + "…"

        WorkflowNotificationService.trigger(
            event_type="message",
            category="messages",
            priority=msg.priority or "normal",
            title=f"New message from {sender_name}",
            body=preview,
            context_type="Message",
            context_id=msg.id,
            recipients=[rid],
        )
    except Exception:
        pass


def _serialize(m: Message) -> dict:
    return {
        "id": m.id,
        "threadId": m.thread_id,
        "senderId": m.sender_id,
        "recipientId": m.recipient_id,
        "body": m.body,
        "category": m.category,
        "priority": m.priority,
        "actionRequired": m.action_required,
        "status": m.status,
        "contextType": m.context_type,
        "contextId": m.context_id,
        "targetRoute": m.target_route,
        "createdAt": m.created_at.isoformat(),
    }


def get_user_threads(user, context_type: str | None = None) -> list[dict]:
    """Legacy list shape used by the old inbox view."""
    rows = threads_for_user(user, tab="all")
    if context_type:
        rows = [r for r in rows if r["context_type"] == context_type]
    return rows


def resolve_context_label(context_type: str | None, context_id: str | None) -> str:
    _, label = resolve_context_record(context_type, context_id)
    return label


def get_context_target_route(context_type: str | None, context_id: str | None) -> str:
    if not context_type:
        return "/dashboard"
    mapping = {
        "planning": "/planning",
        "execution": "/my-plan",
        "verification": "/ia/verification/",
        "evidence_upload": "/evidence/",
        "accountant_disbursement": "/fund-requests",
        "accountability_confirmation": "/debriefs",
        "school": "/schools",
        "cluster": "/clusters",
        "fund_request": "/fund-requests/weekly",
        "leave": "/leave/approvals",
        "project": "/projects",
        "system": "/analytics",
    }
    return mapping.get(context_type, "/dashboard")
