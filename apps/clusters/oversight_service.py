"""Clusters, grouped by the person accountable for them.

A cluster belongs to a CCEO. A CCEO reports to a Programme Lead. So the
question an oversight role asks — "who is carrying what?" — is answered by
grouping clusters up that line rather than by listing them flat.

Two lenses, one function, because they are the same question asked from
different heights:

* an oversight role (CD, IA, RVP, Accountant) groups by **Programme Lead** —
  the unit they hold accountable;
* a Programme Lead groups by **CCEO** — grouping their own clusters under
  themselves would produce one box containing everything, which is a list with
  extra steps.

Scope comes from `cluster_queryset`, so this page cannot show a cluster the
pickers would refuse: one definition of who may see what, and this is a
reader of it rather than a second opinion.
"""

from __future__ import annotations

from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.core.scoping import cluster_queryset, resolve_user_scope

#: A cluster with no responsible staff is unassigned, not unowned-by-accident.
#: It groups under its own heading rather than being dropped, because a cluster
#: nobody is carrying is exactly what an oversight page exists to surface.
UNASSIGNED = "__unassigned__"


def _staff_directory(owner_ids: set[str]) -> dict:
    """Resolve owner ids to staff, in both id spaces.

    `responsible_staff_id` holds a User id when the edit drawer wrote it and a
    StaffProfile id when another path did, so a lookup in one space silently
    drops half the rows — the trap `owner_ids` exists for.
    """
    from apps.accounts.models import StaffProfile
    from django.db.models import Q

    ids = {i for i in owner_ids if i}
    if not ids:
        return {}
    profiles = (
        StaffProfile.objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .select_related("user")
        .prefetch_related("supervisor_links__supervisor__user")
    )
    directory = {}
    for profile in profiles:
        for key in (profile.id, profile.user_id):
            if key:
                directory[key] = profile
    return directory


def _supervisor_of(profile):
    """The Programme Lead a CCEO reports to.

    Reads the direct reporting line only. IA and RVP rows exist in the same
    table as overlapping oversight, and treating one as the reporting line
    would file a CCEO's clusters under whoever last reviewed them.
    """
    if profile is None:
        return None
    role = getattr(getattr(profile, "user", None), "active_role", "")
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return profile
    for link in profile.supervisor_links.all():
        supervisor = link.supervisor
        role = getattr(getattr(supervisor, "user", None), "active_role", "")
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            return supervisor
    return None


def _last_delivered_dates(cluster_ids) -> dict:
    """Each cluster's most recent meeting or training that actually happened.

    Delivered means completed by the person who ran it: submitted and waiting
    for verification, or verified. A plan is not an activity until then, and
    plans are cancelled and moved all the time, so a planned, rescheduled or
    cancelled session never sets this date (owner, 2026-09-23). The delivery
    date the completion recorded wins over the date it was planned for.
    """
    from django.db.models import Max
    from django.db.models.functions import Coalesce

    from apps.activities.models import Activity
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    if not cluster_ids:
        return {}
    return {
        row["cluster_id"]: row["last_date"]
        for row in Activity.objects.filter(
            cluster_id__in=cluster_ids,
            deleted_at__isnull=True,
            activity_type__in=CLUSTER_MEETING_TYPES + TRAINING_TYPES,
            status__in=AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES,
        )
        .values("cluster_id")
        .annotate(last_date=Max(Coalesce("actual_delivery_date", "planned_date")))
        if row["last_date"]
    }


#: Status tones the session tables colour by (owner, 2026-09-24): green once the
#: work is verified, blue while it waits on its verifier.
TONE_COMPLETE = "complete"
TONE_PENDING = "pending"
TONE_RETURNED = "returned"
TONE_OPEN = "open"

#: Partner work waiting on Impact Assessment, Salesforce entry included.
_IA_PENDING_STATUSES = frozenset({"awaiting_ia_verification", "salesforce_id_required"})


def session_status(item) -> tuple[str, str]:
    """The Status a group training or cluster meeting shows, and its tone.

    A CCEO's completion waits on their Programme Lead ("PL Pending") and the
    Lead's Verify makes it complete; everyone else's — a Programme Lead's own
    session, or partner work — waits on Impact Assessment ("IA Pending").
    Complete means verified, as on the Planning badges: the legacy
    ``completed`` value was never verified, so it reads as waiting.
    """
    from apps.core.enums import ActivityStatus
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        NEEDS_REPLANNING_STATUSES,
        VERIFIED_STATUSES,
    )

    status = item.activity_status or ""
    if item.is_awaiting_partner_schedule:
        return "Partner yet to schedule", TONE_OPEN
    if status in VERIFIED_STATUSES:
        return "Complete", TONE_COMPLETE
    if status == "submitted_to_pl":
        return "PL Pending", TONE_PENDING
    if status in _IA_PENDING_STATUSES:
        return "IA Pending", TONE_PENDING
    if status == "completed":
        return "Awaiting Verification", TONE_PENDING
    if status in AWAITING_VERIFICATION_STATUSES:
        return _words(status, ActivityStatus), TONE_PENDING
    if status in NEEDS_REPLANNING_STATUSES:
        return _words(status, ActivityStatus), TONE_RETURNED
    return _words(status, ActivityStatus) or "—", TONE_OPEN


def _words(value: str, choices) -> str:
    """A stored token as its choice label, or plainly spaced when unknown."""
    if not value:
        return ""
    try:
        return choices(value).label
    except ValueError:
        return value.replace("_", " ").title()


def _decorate_sessions(principal, items) -> None:
    """What each session row shows beyond the planning item itself.

    Status and tone, the people invited, the topic and intervention as words,
    and the one verification this reader may perform on it: a Programme
    Lead's Verify on a completion waiting on them (the rule
    ``pl_review.services.confirm`` enforces), or Impact Assessment's Verify on
    work waiting on IA. A fixed number of queries whatever the row count.
    """
    from apps.activities.cluster_attendance import invited_head_counts
    from apps.core.activity_types import TRAINING_TYPES
    from apps.core.enums import SsaIntervention
    from apps.core.permissions import RolePermissionService, has_permission
    from apps.core.rbac import Permission
    from apps.core.scoping import owner_ids
    from apps.pl_review.services import review_rule

    if not items:
        return
    head_counts = invited_head_counts(
        (item.activity_id, item.cluster_id) for item in items if item.activity_id
    )
    own = {str(i) for i in owner_ids(principal) if i}
    can_view = RolePermissionService.can_view_page
    may_review = (
        review_rule(principal) if can_view(principal, "pl_review_queue") else None
    )
    ia_verifies = has_permission(principal, Permission.IA_VERIFY.value)
    ia_staff_page = ia_verifies and can_view(principal, "ia_review_workspace")
    ia_partner_page = ia_verifies and can_view(principal, "ia_partner_evidence")

    for item in items:
        item.session_status, item.session_tone = session_status(item)
        if item.activity_id in head_counts:
            item.participants = head_counts[item.activity_id]
        item.intervention_label = _words(item.target_intervention, SsaIntervention)
        training = item.training_name if item.training_name != "—" else ""
        purpose = item.purpose_of_visit if item.purpose_of_visit != "—" else ""
        is_training = item.activity_type in TRAINING_TYPES
        item.topic = (
            (training if is_training else "")
            or purpose
            or item.operational_rationale
            or ("Group training" if is_training else "Cluster meeting")
        )
        item.is_owner = bool(
            {str(item.operational_owner_id or ""), str(item.executor_id or "")} & own
        )
        # The owner of a completion under review, as pl_review reads it.
        owner = item.planned_by_id
        item.pl_verify = bool(
            may_review
            and item.activity_id
            and item.activity_status == "submitted_to_pl"
            and may_review(owner)
        )
        # Partner work is verified on Partner Evidence, which carries the
        # Salesforce entry step; staff work in the IA review workspace.
        item.ia_verify_url = ""
        item.ia_return_url = ""
        if (
            item.activity_id
            and item.activity_status in _IA_PENDING_STATUSES
            and str(owner or "") not in own
        ):
            if item.is_partner_work and ia_partner_page:
                item.ia_verify_url = f"/ia/partner-evidence/{item.activity_id}/"
                # The partner evidence page carries both decisions itself.
                item.ia_return_url = item.ia_verify_url
            elif (
                not item.is_partner_work
                and ia_staff_page
                and item.activity_status == "awaiting_ia_verification"
            ):
                item.ia_verify_url = f"/ia/verification/{item.activity_id}/"
                # Opens the workspace with the Return panel already open.
                item.ia_return_url = f"{item.ia_verify_url}?return=1"


def _label(profile) -> str:
    if profile is None:
        return "Unassigned"
    user = getattr(profile, "user", None)
    return getattr(user, "name", "") or getattr(user, "email", "") or "Unnamed"


def grouped_clusters(principal) -> dict:
    """Clusters the caller may see, grouped by who is accountable for them.

    Returns the groups plus the totals they were folded from, so a heading and
    the rows beneath it cannot disagree — the count is the length of the list
    it labels rather than a second query.
    """
    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value

    clusters = list(
        (cluster_queryset(scope) or Cluster.objects.none())
        .select_related("district", "sub_county")
        .order_by("name")
    )
    directory = _staff_directory({c.responsible_staff_id for c in clusters})

    # School counts in one query rather than one per cluster.
    from django.db.models import Count

    from apps.schools.models import School

    counts = {
        row["cluster_id"]: row["n"]
        for row in School.objects.filter(
            cluster_id__in=[c.id for c in clusters], deleted_at__isnull=True
        )
        .values("cluster_id")
        .annotate(n=Count("id"))
    }

    # 7-column metrics for cluster tables
    cluster_ids = [c.id for c in clusters]
    from apps.ssa.models import SsaRecord, SsaScore
    from django.db.models import Avg
    from apps.core.enums import SsaIntervention

    ssa_avgs = {
        row["school__cluster_id"]: row["avg_score"]
        for row in SsaRecord.objects.filter(
            school__cluster_id__in=cluster_ids, deleted_at__isnull=True
        )
        .values("school__cluster_id")
        .annotate(avg_score=Avg("average_score"))
    }

    cluster_intervention_scores: dict[str, list] = {}
    for row in (
        SsaScore.objects.filter(
            ssa_record__school__cluster_id__in=cluster_ids,
            ssa_record__deleted_at__isnull=True,
        )
        .values("ssa_record__school__cluster_id", "intervention")
        .annotate(avg=Avg("score"))
    ):
        cid = row["ssa_record__school__cluster_id"]
        cluster_intervention_scores.setdefault(cid, []).append(
            (row["intervention"], row["avg"])
        )

    least_interventions: dict[str, str] = {}
    for cid, scores in cluster_intervention_scores.items():
        scores.sort(key=lambda x: x[1])
        int_code, min_score = scores[0]
        try:
            int_label = SsaIntervention(int_code).label
        except Exception:
            int_label = int_code.replace("_", " ").title()
        least_interventions[cid] = f"{int_label} ({round(min_score, 1)})"

    last_activities = {
        cluster_id: day.strftime("%b %d, %Y")
        for cluster_id, day in _last_delivered_dates(cluster_ids).items()
    }

    groups: dict[str, dict] = {}
    for cluster in clusters:
        owner = directory.get((cluster.responsible_staff_id or "").strip())
        # A PL's page groups by the CCEO who holds the cluster; everyone
        # else's groups by the PL that CCEO reports to.
        head = owner if is_programme_lead else _supervisor_of(owner)
        key = getattr(head, "id", None) or UNASSIGNED
        group = groups.setdefault(
            key,
            {
                "key": key,
                "label": _label(head),
                "role": getattr(getattr(head, "user", None), "active_role", ""),
                "is_unassigned": key == UNASSIGNED,
                "clusters": [],
                "schools": 0,
            },
        )
        c_avg = ssa_avgs.get(cluster.id)
        avg_str = f"{round(c_avg, 1)}" if c_avg is not None else "—"
        group["clusters"].append(
            {
                "id": cluster.id,
                "cluster_id": cluster.id,
                "cluster": cluster,
                "name": cluster.name,
                "owner": _label(owner) if owner else "",
                "district": getattr(cluster.district, "name", "") or "—",
                "cluster_leader_name": cluster.cluster_leader_name or "—",
                "cluster_leader_phone": cluster.cluster_leader_phone or "—",
                "ssa_score_avg": avg_str,
                "least_performing_intervention": least_interventions.get(
                    cluster.id, "—"
                ),
                "last_activity_date": last_activities.get(cluster.id, "—"),
                "schools": counts.get(cluster.id, 0),
                "schools_count": counts.get(cluster.id, 0),
            }
        )
        group["schools"] += counts.get(cluster.id, 0)

    ordered = sorted(
        groups.values(),
        # Unassigned last: it is the exception, and leading with it would push
        # the people actually carrying work below the fold.
        key=lambda g: (g["is_unassigned"], g["label"].casefold()),
    )
    for group in ordered:
        group["count"] = len(group["clusters"])

    return {
        "groups": ordered,
        "grouped_by": "cceo" if is_programme_lead else "programme_lead",
        "total_clusters": len(clusters),
        "total_schools": sum(counts.values()),
        "unassigned": sum(g["count"] for g in ordered if g["is_unassigned"]),
    }


def cluster_oversight_table_data(principal, *, fy: str | None = None) -> dict:
    """Full database-driven cluster oversight dataset.

    Returns:
    - Clusters formatted with:
      Cluster Name, District, Cluster leader's Name, Cluster leader's Phone number,
      # School SSA scores average, Least performing intervention, Date of last activity.
    - Tab hierarchy:
      - For PL: Level 1 tabs are their supervised CCEOs.
      - For IA, CD, RPL: Level 1 tabs are Supervising Program Leads,
        Level 2 tabs are CCEOs under each PL.
    - Responsible CCEO column is excluded from table rows (represented by the active tab).
    - Executive Cluster Performance metrics (total clusters, active/dormant, sessions, reach, budget).
    """
    from apps.core.enums import SsaIntervention
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import any_id, cluster_queryset, resolve_user_scope
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.planning.oversight_service import system_program_leads
    from django.db.models import Avg

    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value
    uses_member_tabs = is_programme_lead or scope.active_role == EdifyRole.CCEO.value

    clusters = list(
        cluster_queryset(
            scope,
            base=Cluster.objects.filter(deleted_at__isnull=True),
        )
        .select_related("district")
        .order_by("name")
    )
    cluster_ids = [c.id for c in clusters]

    # The group trainings and cluster meetings, from the same planning records
    # My Plan reads. The operational year reads forward into the years ahead:
    # in September people plan October, which is the next fiscal year, and a
    # page limited to the operational year showed empty tables while My Plan
    # listed the sessions (owner, 2026-09-23).
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import owner_ids
    from apps.planning import oversight_service as planning
    from apps.planning.fy_policy import horizon_label, planning_horizon

    page_fy = str(fy or get_operational_fy())
    plan_fys = planning_horizon(page_fy)
    cluster_work = [
        item
        for item in planning.build_items(
            principal,
            fy=page_fy,
            fys=plan_fys,
            activity_types=tuple(CLUSTER_MEETING_TYPES + TRAINING_TYPES),
            cluster_work_only=True,
        )
        if item.cluster_id
        and not item.is_in_school_training
        and item.activity_type in CLUSTER_MEETING_TYPES + TRAINING_TYPES
    ]

    # Keep the activity ledger within this page's cluster/team scope, even
    # when a development account also carries superuser privileges.
    allowed_people = planning._both_id_spaces(
        set(owner_ids(principal)) | set(scope.supervised_staff_ids or [])
    )
    cluster_work = [
        item
        for item in cluster_work
        if item.cluster_id in cluster_ids
        or (uses_member_tabs and item.operational_owner_id in allowed_people)
    ]
    _decorate_sessions(principal, cluster_work)

    # One directory for the people holding clusters and the people running
    # the sessions. A person's work is filed by the same profile and the same
    # Programme Lead as their clusters, in either id space: resolving the two
    # separately filed a CCEO's clusters under one tab and their sessions
    # under another, or under a second tab of the same name.
    owners = _staff_directory(
        {c.responsible_staff_id for c in clusters}
        | {item.operational_owner_id for item in cluster_work}
    )
    placements = []
    for item in cluster_work:
        worker = owners.get((item.operational_owner_id or "").strip())
        placements.append((item, worker, _supervisor_of(worker)))

    # 1. School counts & mapping
    schools = list(
        School.objects.filter(
            cluster_id__in=cluster_ids, deleted_at__isnull=True
        ).values("id", "cluster_id")
    )
    school_to_cluster = {s["id"]: s["cluster_id"] for s in schools}
    cluster_schools_count: dict[str, int] = {}
    for s in schools:
        cid = s["cluster_id"]
        cluster_schools_count[cid] = cluster_schools_count.get(cid, 0) + 1

    # 2. SSA average per cluster. The member schools go as one array: a
    # country's clusters hold tens of thousands of schools, and one bind
    # parameter each cost more to build and plan than the query took to run.
    ssa_filter = {"deleted_at__isnull": True}
    if fy:
        ssa_filter["fy"] = str(fy)

    ssa_avgs = {
        row["school__cluster_id"]: row["avg_score"]
        for row in SsaRecord.objects.filter(
            any_id("school_id", school_to_cluster), **ssa_filter
        )
        .values("school__cluster_id")
        .annotate(avg_score=Avg("average_score"))
    }

    # 3. Least performing intervention per cluster
    score_filter = {"ssa_record__deleted_at__isnull": True}
    if fy:
        score_filter["ssa_record__fy"] = str(fy)

    cluster_intervention_scores: dict[str, list] = {}
    for row in (
        SsaScore.objects.filter(
            any_id("ssa_record__school_id", school_to_cluster), **score_filter
        )
        .values("ssa_record__school__cluster_id", "intervention")
        .annotate(avg=Avg("score"))
    ):
        cid = row["ssa_record__school__cluster_id"]
        cluster_intervention_scores.setdefault(cid, []).append(
            (row["intervention"], row["avg"])
        )

    least_interventions: dict[str, str] = {}
    for cid, scores in cluster_intervention_scores.items():
        scores.sort(key=lambda x: x[1])
        int_code, min_score = scores[0]
        try:
            int_label = SsaIntervention(int_code).label
        except Exception:
            int_label = int_code.replace("_", " ").title()
        least_interventions[cid] = f"{int_label} ({round(min_score, 1)})"

    # 4. Date of last activity: the last meeting or training delivered.
    last_activities = _last_delivered_dates(cluster_ids)

    # 5. Format cluster table rows (excluding Responsible CCEO column)
    formatted_clusters = []
    for cluster in clusters:
        owner = owners.get((cluster.responsible_staff_id or "").strip())
        lead = _supervisor_of(owner)
        c_avg = ssa_avgs.get(cluster.id)
        avg_str = f"{round(c_avg, 1)}" if c_avg is not None else "—"
        least_str = least_interventions.get(cluster.id, "—")
        last_act = last_activities.get(cluster.id)
        last_act_str = last_act.strftime("%b %d, %Y") if last_act else "—"

        formatted_clusters.append(
            {
                "cluster_id": cluster.id,
                "name": cluster.name,
                "district": getattr(cluster.district, "name", "") or "—",
                "cluster_leader_name": cluster.cluster_leader_name or "—",
                "cluster_leader_phone": cluster.cluster_leader_phone or "—",
                "ssa_score_avg": avg_str,
                "least_performing_intervention": least_str,
                "last_activity_date": last_act_str,
                "schools_count": cluster_schools_count.get(cluster.id, 0),
                "owner_id": getattr(owner, "id", None),
                "owner_user_id": getattr(owner, "user_id", None),
                "owner_name": _label(owner) if owner else "Unassigned",
                "lead_id": getattr(lead, "id", None),
                "lead_user_id": getattr(lead, "user_id", None),
                "lead_name": _label(lead) if lead else "Unassigned",
            }
        )

    # 6. Build hierarchy tabs (Unified across PL, IA, CD, RPL)
    sys_pls = system_program_leads()
    if not scope.country_scope:
        visible_lead_ids = {
            str(identifier)
            for row in formatted_clusters
            for identifier in (row["lead_id"], row["lead_user_id"])
            if identifier
        }
        visible_lead_ids.update(
            str(lead.id) for _item, _worker, lead in placements if lead
        )
        sys_pls = [
            pl for pl in sys_pls if visible_lead_ids.intersection(map(str, pl["ids"]))
        ]
    pl_lookup: dict[str, dict] = {}
    leads_data = []
    for pl in sys_pls:
        pl_dict = {
            "id": pl["id"],
            "name": pl["name"],
            "cceos": {},
            "count": 0,
            "schools": 0,
        }
        leads_data.append(pl_dict)
        for pid in pl["ids"]:
            pl_lookup[pid] = pl_dict

    unassigned_pl: dict = {
        "id": "__unassigned__",
        "name": "Unassigned",
        "cceos": {},
        "count": 0,
        "schools": 0,
    }

    for row in formatted_clusters:
        target_pl = pl_lookup.get(row["lead_id"]) if row["lead_id"] else None
        if not target_pl and row["lead_user_id"]:
            target_pl = pl_lookup.get(row["lead_user_id"])
        if not target_pl:
            target_pl = unassigned_pl

        target_pl["count"] += 1
        target_pl["schools"] += row["schools_count"]

        oid = row["owner_id"] or "__unassigned__"
        cceo_entry = target_pl["cceos"].setdefault(
            oid,
            {
                "id": oid,
                "name": row["owner_name"],
                "clusters": [],
                "count": 0,
                "schools": 0,
            },
        )
        cceo_entry["clusters"].append(row)
        cceo_entry["count"] += 1
        cceo_entry["schools"] += row["schools_count"]

    # Convert cceos dict to sorted list for each PL
    for pl_entry in leads_data:
        pl_entry["cceo_tabs"] = sorted(
            pl_entry["cceos"].values(),
            key=lambda g: (g["id"] == "__unassigned__", g["name"].casefold()),
        )

    def lead_entry(lead):
        return pl_lookup.get(str(lead.id)) if lead else None

    if unassigned_pl["count"] > 0 or any(
        lead_entry(lead) is None for _item, _worker, lead in placements
    ):
        unassigned_pl["cceo_tabs"] = sorted(
            unassigned_pl["cceos"].values(),
            key=lambda g: (g["id"] == "__unassigned__", g["name"].casefold()),
        )
        leads_data.append(unassigned_pl)

    # Determine default selected PL tab (preselect viewing PL if applicable)
    user_staff_ids = set(owner_ids(principal))
    selected_program_lead = None
    for pl_entry in leads_data:
        if pl_entry["id"] in user_staff_ids:
            selected_program_lead = pl_entry["id"]
            break
        for pl in sys_pls:
            if pl["id"] == pl_entry["id"] and any(
                pid in user_staff_ids for pid in pl["ids"]
            ):
                selected_program_lead = pl_entry["id"]
                break
        if selected_program_lead:
            break

    cceo_tabs = []
    if uses_member_tabs:
        own_rows = [
            row
            for row in formatted_clusters
            if str(row["owner_id"]) in user_staff_ids
            or str(row["owner_user_id"]) in user_staff_ids
        ]
        cceo_tabs = [
            {
                "id": "my-clusters",
                "name": "My Clusters",
                "clusters": own_rows,
                "count": len(own_rows),
                "schools": sum(row["schools_count"] for row in own_rows),
            }
        ]
        officer_tabs = [
            tab
            for lead in leads_data
            for tab in lead["cceo_tabs"]
            if str(tab["id"]) not in user_staff_ids
        ]
        # Every officer on the roster is a tab and a series, holding clusters
        # or not: an officer with none is a zero row, never a missing one, so
        # the chart reads as the team and nobody's colour shifts when a
        # colleague has nothing to show.
        listed = {str(tab["id"]) for tab in officer_tabs}
        for member in planning.program_lead_members(principal.id):
            if str(member["id"]) in listed or member["ids"].intersection(
                user_staff_ids
            ):
                continue
            officer_tabs.append(
                {
                    "id": member["id"],
                    "name": member["name"],
                    "clusters": [],
                    "count": 0,
                    "schools": 0,
                }
            )
        officer_tabs.sort(
            key=lambda tab: (tab["id"] == "__unassigned__", tab["name"].casefold())
        )
        cceo_tabs.extend(officer_tabs)

    # Populate each person's single tab with their clusters and the work they
    # are responsible for, even if a different team member holds the cluster.
    def member_tab(member):
        return {
            "id": member["id"],
            "name": member["name"],
            "clusters": [],
            "count": 0,
            "schools": 0,
        }

    def session_list(tab, item):
        key = "meetings" if item.activity_type in CLUSTER_MEETING_TYPES else "trainings"
        return tab.setdefault(key, [])

    def worker_key(worker):
        return str(worker.id) if worker else UNASSIGNED

    def worker_name(item, worker):
        return (
            _label(worker) if worker else (item.operational_owner_name or "Unassigned")
        )

    # Every Lead's roster in two queries, not two per Lead.
    rosters = planning.program_lead_rosters([lead["id"] for lead in leads_data])

    for lead in leads_data:
        roster = rosters.get(str(lead["id"]), [])
        existing = {tab["id"]: tab for tab in lead["cceo_tabs"]}
        ordered = [existing.pop(member["id"], member_tab(member)) for member in roster]
        lead["cceo_tabs"] = ordered + list(existing.values())
        for tab in lead["cceo_tabs"]:
            tab["meetings"], tab["trainings"] = [], []
    lead_tabs = {
        id(lead): {str(tab["id"]): tab for tab in lead["cceo_tabs"]}
        for lead in leads_data
    }
    for item, worker, lead in placements:
        target = lead_entry(lead) or unassigned_pl
        tabs = lead_tabs.get(id(target))
        if tabs is None:
            continue
        key = worker_key(worker)
        tab = tabs.get(key)
        if tab is None:
            tab = member_tab({"id": key, "name": worker_name(item, worker)})
            target["cceo_tabs"].append(tab)
            tabs[key] = tab
        session_list(tab, item).append(item)

    if uses_member_tabs:
        tabs = {str(tab["id"]): tab for tab in cceo_tabs}
        for tab in cceo_tabs:
            tab["meetings"], tab["trainings"] = [], []
        for item, worker, _lead in placements:
            mine = item.operational_owner_id in user_staff_ids or (
                worker is not None
                and bool({str(worker.id), str(worker.user_id)} & user_staff_ids)
            )
            key = "my-clusters" if mine else worker_key(worker)
            if key not in tabs:
                tab = member_tab({"id": key, "name": worker_name(item, worker)})
                cceo_tabs.append(tab)
                tabs[key] = tab
            session_list(tabs[key], item).append(item)

    from apps.planning.school_planning_badges import PLANNED_STATUSES

    def plan_counts(items):
        live = {
            item.activity_id: item
            for item in items
            if item.activity_status in PLANNED_STATUSES
        }
        return {
            "meetings_planned": sum(
                item.activity_type in CLUSTER_MEETING_TYPES for item in live.values()
            ),
            "trainings_planned": sum(
                item.activity_type in TRAINING_TYPES for item in live.values()
            ),
        }

    for member in cceo_tabs + [tab for lead in leads_data for tab in lead["cceo_tabs"]]:
        member.update(
            plan_counts(member.get("meetings", []) + member.get("trainings", []))
        )
    for lead in leads_data:
        lead["meetings_planned"] = sum(
            tab["meetings_planned"] for tab in lead["cceo_tabs"]
        )
        lead["trainings_planned"] = sum(
            tab["trainings_planned"] for tab in lead["cceo_tabs"]
        )

    # 7. Cluster performance executive overview
    from apps.planning.cluster_performance_service import (
        NO_LEAD_KEY,
        NO_OWNER_KEY,
        cluster_performance,
    )

    officer_activity: list[dict] = []
    lead_activity: list[dict] = []
    try:
        perf = cluster_performance(principal, fy=page_fy)
        raw_totals = perf.get("totals", {})
        perf_totals = {
            "active_clusters": max(0, len(clusters) - raw_totals.get("dormant", 0)),
            "dormant_clusters": raw_totals.get("dormant", 0),
            "sessions_held": raw_totals.get("sessions_done", 0),
            "sessions_delivered": raw_totals.get("sessions_done", 0),
            "unique_schools_reached": raw_totals.get("reached", 0),
            "total_spend": raw_totals.get("budget", 0),
            "budget_allocated": raw_totals.get("budget", 0),
        }
        # The same measured rows, folded per person for the chart that reads
        # each officer (or each Lead) as a series. The tab a person owns and
        # the bars they wear come from one list, so they cannot disagree.
        # Bounded to the clusters this page lists, so the bars and the tabs
        # count the same clusters.
        listed = set(cluster_ids)
        measured = [
            entry["row"]
            for entry in perf.get("rows", [])
            if entry["row"].cluster_id in listed
        ]
        if uses_member_tabs:
            own_label = f"{getattr(principal, 'name', '') or 'My clusters'} (you)"
            officer_activity = [
                cluster_activity_by_person(
                    own_label if tab["id"] == "my-clusters" else tab["name"],
                    measured,
                    lambda row, tab=tab: (
                        str(row.owner_id) in user_staff_ids
                        if tab["id"] == "my-clusters"
                        else row.owner_id == NO_OWNER_KEY
                        if tab["id"] == "__unassigned__"
                        else str(row.owner_id) == str(tab["id"])
                    ),
                )
                for tab in cceo_tabs
            ]
        else:
            lead_activity = [
                cluster_activity_by_person(
                    lead["name"],
                    measured,
                    lambda row, lead=lead: (
                        row.lead_id == NO_LEAD_KEY
                        if lead["id"] == "__unassigned__"
                        else str(row.lead_id) == str(lead["id"])
                    ),
                )
                for lead in leads_data
            ]
    except Exception:
        perf_totals = {
            "active_clusters": len(clusters),
            "dormant_clusters": 0,
            "sessions_held": 0,
            "sessions_delivered": 0,
            "unique_schools_reached": len(schools),
            "total_spend": 0,
            "budget_allocated": 0,
        }

    return {
        "is_programme_lead": is_programme_lead,
        "uses_member_tabs": uses_member_tabs,
        **plan_counts(cluster_work),
        "plan_fys": plan_fys,
        "plan_period_label": horizon_label(plan_fys),
        "selected_program_lead": selected_program_lead
        or (leads_data[0]["id"] if leads_data else ""),
        "leads": leads_data,
        "cceo_tabs": cceo_tabs,
        "officer_activity": officer_activity,
        "lead_activity": lead_activity,
        "total_clusters": len(clusters),
        "total_schools": len(schools),
        "perf_totals": perf_totals,
    }


def cluster_activity_by_person(name: str, rows, belongs) -> dict:
    """One person's cluster activity, folded from the measured cluster rows.

    ``rows`` are the ClusterRow records cluster_performance measured and
    ``belongs`` says which of them this person carries. Active and dormant
    use the same rule as the headline tiles (a cluster with nothing planned is
    dormant), so a person's bars sum to the strip above them.
    """
    mine = [row for row in rows if belongs(row)]
    dormant = sum(1 for row in mine if row.is_dormant)
    return {
        "name": name,
        "clusters": len(mine),
        "active_clusters": len(mine) - dormant,
        "dormant_clusters": dormant,
        "sessions_held": sum(row.sessions_done for row in mine),
        "schools_reached": sum(row.schools_reached for row in mine),
    }
