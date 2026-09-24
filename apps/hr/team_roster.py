"""A Programme Lead's team, in one definition (owner, 2026-09-13).

The Programme Lead line-manages, supervises and supports the Christ-Centered
Education Officers assigned to them. Before this module at least eight
resolvers answered "who is on my team" differently — some counted the lead
themself, some counted departed staff, some ignored cover. Every Programme Lead
surface built for the role description (My Team, coaching, guidance, reviews)
reads `team_members` so they agree.

`build_team_roster` is the My Team page: one row per officer with the
signals a line manager acts on, and the list of manager-owned exceptions that
wait on the lead. Every signal reuses the definition another surface already
publishes, so My Team can never disagree with the page a row links to:

    delivery        the Programme Lead dashboard's CCEO performance count —
                    the FY's activities owned by the officer or in their
                    schools, verified when IA verified or closed them
    targets / risk  Team Targets' pacing bands (apps.targets.team_targets) —
                    the FY-to-date cell for the target column, and this
                    month's band for risk, the same band Team Oversight's
                    High-Risk Staff tile counts
    exceptions      HR's manager-overdue exception builders
                    (apps.hr.hr_exceptions), narrowed to the team
    coaching        apps.cce_leadership.coaching.last_coaching_by_cceo

The roster is read in a fixed number of queries whatever the team size: every
source is fetched once for the whole team and split in Python
(apps/hr/test_team_roster.py pins it).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Activity states the Programme Lead dashboard counts as verified delivery.
# A completion the officer submitted and the lead has not confirmed yet.
AWAITING_PL_STATUS = "submitted_to_pl"
# The review stages in which the next move is the manager's.
MANAGER_STAGES = ("priorities_manager_review", "manager_assessment")
# Team Targets bands that Team Oversight counts as high-risk staff.
HIGH_RISK_BANDS = ("High Risk", "Critical")

_RISK_WORDS = {
    "Critical": ("Critical", "danger"),
    "High Risk": ("High", "danger"),
    "Slightly Behind": ("Watch", "warning"),
    "On Track": ("Low", "success"),
    "Complete": ("Low", "success"),
    "Exceeded": ("Low", "success"),
}


def _profile_id(principal) -> str | None:
    return getattr(principal, "staff_profile_id", None) or getattr(
        getattr(principal, "staff_profile", None), "id", None
    )


def team_members(principal) -> list:
    """The officers this Programme Lead line-manages.

    Direct supervisees (StaffSupervisorAssignment) who hold the CCEO role and
    have not left, never the lead themself. A lead covering an absent
    Programme Lead also leads that lead's officers while the cover is active.
    """

    from apps.accounts.models import (
        StaffProfile,
        StaffSupervisorAssignment,
        TemporaryCoverageAssignment,
    )
    from apps.core.rbac import EdifyRole

    profile_id = _profile_id(principal)
    if not profile_id:
        return []
    now = timezone.now()
    covered = TemporaryCoverageAssignment.objects.filter(
        covering_staff_id=profile_id,
        start_datetime__lte=now,
        end_datetime__gte=now,
        status="active",
    ).values_list("original_staff_id", flat=True)
    supervisors = {profile_id}
    supervisors.update(
        StaffProfile.objects.filter(
            id__in=list(covered),
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        ).values_list("id", flat=True)
    )
    supervisee_ids = StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=supervisors
    ).values_list("supervisee_id", flat=True)
    return list(
        StaffProfile.objects.filter(
            id__in=list(supervisee_ids),
            deleted_at__isnull=True,
            user__deleted_at__isnull=True,
            user__is_active=True,
            user__active_role=EdifyRole.CCEO.value,
        )
        .exclude(id=profile_id)
        .select_related("user")
        .order_by("user__name")
    )


def team_member_ids(principal) -> list[str]:
    return [member.id for member in team_members(principal)]


def is_team_member(principal, staff_id: str | None) -> bool:
    """Whether a StaffProfile id is one of this lead's officers."""
    return bool(staff_id) and staff_id in set(team_member_ids(principal))


# ── The roster ───────────────────────────────────────────────────────────────


def _day(value) -> str:
    return f"{value:%-d %b}" if value else ""


def _iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def build_team_roster(principal, fy: str, today=None) -> dict:
    """The My Team page: one row per officer and the actions waiting on the
    lead.

    Returns ``{"rows": [...], "needs_action": [...], "summary": {...}}``. A
    source that fails is logged and left empty rather than taking the page
    down — the lead still sees their team.
    """
    from apps.core.request_cache import scoped

    today = today or timezone.localdate()
    with scoped():
        members = team_members(principal)
        if not members:
            return {
                "rows": [],
                "needs_action": [],
                "summary": _summary([], [], fy),
            }
        return _build(principal, members, fy, today)


def _build(principal, members, fy: str, today: date) -> dict:
    staff_ids = [m.id for m in members]
    user_ids = [m.user_id for m in members if m.user_id]
    owner_of = {}
    for m in members:
        owner_of[m.id] = m.id
        if m.user_id:
            owner_of[m.user_id] = m.id

    schools = _portfolio(members)
    delivery, completions = _delivery(owner_of, schools, staff_ids, fy)
    ssa = _ssa_coverage(schools, fy)
    leave = _leave(staff_ids, today)
    targets = _target_bands(members, fy, today, leave["approved_rows"])
    reviews = _reviews(staff_ids, fy)
    development = _pd_waiting(staff_ids)
    escalations = _escalations(principal, user_ids)
    extra_work = _extra_work_waiting(principal, user_ids)
    policies = _policies_overdue(user_ids, today)
    coaching = _coaching(principal, staff_ids)

    rows = []
    for m in members:
        user = m.user
        waiting = {
            "completions": completions.get(m.id, 0),
            "development": len(development.get(m.id, ())),
            "leave": leave["pending"].get(m.id, 0),
            "escalations": len(escalations.get(m.user_id, ())),
            "extra_work": extra_work.get(m.user_id, 0),
        }
        waiting["total"] = sum(waiting.values())
        planned, verified = delivery.get(m.id, (0, 0))
        portfolio = schools["by_staff"].get(m.id, set())
        assessed = len(portfolio & ssa)
        band = targets.get(m.id) or {}
        risk_text, risk_tone = _RISK_WORDS.get(band.get("month_status"), ("—", ""))
        review = reviews.get(m.id)
        last = coaching.get(m.id)
        rows.append(
            {
                "staff_id": m.id,
                "user_id": m.user_id,
                "name": getattr(user, "name", "") or m.title or "CCEO",
                "profile_url": f"/staff/{m.user_id}?from=/my-team",
                "district": schools["district_of"].get(m.id, "") or "—",
                "delivery": {
                    "planned": planned,
                    "verified": verified,
                    "text": f"{verified} of {planned}"
                    if planned
                    else "Nothing planned",
                    "pct": round(verified / planned * 100) if planned else None,
                },
                "target": {
                    "text": band.get("fy_text", "No targets agreed"),
                    "tone": band.get("fy_tone", "neutral"),
                    "status": band.get("fy_status", "Not Assigned"),
                },
                "ssa": {
                    "assessed": assessed,
                    "portfolio": len(portfolio),
                    "text": f"{assessed} of {len(portfolio)}"
                    if portfolio
                    else "No schools",
                    "tone": (
                        ""
                        if not portfolio
                        else "success"
                        if assessed == len(portfolio)
                        else "warning"
                    ),
                },
                "waiting": {
                    **waiting,
                    "text": _waiting_text(waiting),
                    "tone": "warning" if waiting["total"] else "",
                },
                "review": _review_cell(review, fy),
                "coaching": _coaching_cell(last),
                "leave": _leave_cell(leave, m.id),
                "policies_overdue": policies.get(m.user_id, 0),
                "risk": {
                    "text": risk_text,
                    "tone": risk_tone,
                    "band": band.get("month_status", ""),
                },
                "coaching_url": f"/team/coaching?cceo={m.id}",
                "conversation_url": f"/performance-conversation?staff={m.id}",
            }
        )

    needs_action = _needs_action(
        principal,
        members,
        today=today,
        fy=fy,
        reviews=reviews,
        completions=completions,
        development=development,
        escalations=escalations,
        extra_work=extra_work,
    )
    return {
        "rows": rows,
        "needs_action": needs_action,
        "summary": _summary(rows, needs_action, fy),
    }


def _summary(rows, needs_action, fy) -> dict:
    return {
        "fy": fy,
        "team_size": len(rows),
        "on_track": sum(
            1
            for r in rows
            if r["target"]["status"] in ("On Track", "Complete", "Exceeded")
        ),
        "at_risk": sum(1 for r in rows if r["risk"]["band"] in HIGH_RISK_BANDS),
        "waiting_on_you": sum(r["waiting"]["total"] for r in rows),
        "needs_action": len(needs_action),
        "on_leave_now": sum(1 for r in rows if r["leave"]["away_now"]),
        "ssa_assessed": sum(r["ssa"]["assessed"] for r in rows),
        "ssa_portfolio": sum(r["ssa"]["portfolio"] for r in rows),
        "policies_overdue": sum(r["policies_overdue"] for r in rows),
    }


def _waiting_text(waiting: dict) -> str:
    parts = []
    if waiting["completions"]:
        parts.append(_plural(waiting["completions"], "completion"))
    if waiting["development"]:
        parts.append(_plural(waiting["development"], "PD request"))
    if waiting["leave"]:
        parts.append(_plural(waiting["leave"], "leave request"))
    if waiting["escalations"]:
        parts.append(_plural(waiting["escalations"], "escalation"))
    if waiting["extra_work"]:
        parts.append(f"{waiting['extra_work']} extra work")
    return " · ".join(parts) or "Nothing"


# ── Sources (each one query or a fixed few for the whole team) ──────────────


def _portfolio(members) -> dict:
    """Each officer's active portfolio schools and the district most of them
    sit in (the Programme Lead dashboard's region column), else the district
    on their People record."""
    from collections import Counter

    from apps.accounts.models import StaffSchoolAssignment
    from apps.geography.models import District
    from apps.schools.models import School

    staff_ids = [m.id for m in members]

    assignments = list(
        StaffSchoolAssignment.objects.filter(staff_id__in=staff_ids).values_list(
            "staff_id", "school_id"
        )
    )
    district_of_school = dict(
        School.objects.filter(id__in={s for _, s in assignments}).values_list(
            "id", "district__name"
        )
    )
    by_staff: dict[str, set] = {}
    for staff_id, school_id in assignments:
        # School.objects is soft-delete filtered: a stale assignment to a
        # closed school never counts.
        if school_id in district_of_school:
            by_staff.setdefault(staff_id, set()).add(school_id)
    home_district_ids = {
        m.primary_district_id
        for m in members
        if getattr(m, "primary_district_id", None)
    }
    home = (
        dict(
            District.objects.filter(id__in=home_district_ids).values_list("id", "name")
        )
        if home_district_ids
        else {}
    )
    district_of = {}
    for m in members:
        counts = Counter(
            district_of_school[s]
            for s in by_staff.get(m.id, ())
            if district_of_school.get(s)
        )
        district_of[m.id] = (
            counts.most_common(1)[0][0]
            if counts
            else home.get(getattr(m, "primary_district_id", None), "")
        )
    return {
        "by_staff": by_staff,
        "all": set(district_of_school),
        "district_of": district_of,
    }


def _delivery(owner_of: dict, schools: dict, staff_ids, fy: str):
    """(planned, verified) per officer, and completions waiting on the lead.

    Planned and verified follow ProgramLeadDashboardService.cceo_performance:
    the FY's activities an officer is responsible for, or that sit in one of
    their schools. Completions waiting follow the completion review queue
    (apps.pl_review.services.queue): the officer's own submissions, and
    partner work they monitor.
    """
    from apps.accounts.models import StaffSchoolAssignment
    from apps.activities.models import Activity

    # The portfolio as a semi-join, not a literal id list: one officer can hold
    # hundreds of schools, and an IN-list of them costs more than the join.
    portfolio_ref = StaffSchoolAssignment.objects.filter(staff_id__in=staff_ids).values(
        "school_id"
    )
    school_owner: dict[str, list[str]] = {}
    for staff_id, school_ids in schools["by_staff"].items():
        for school_id in school_ids:
            school_owner.setdefault(school_id, []).append(staff_id)

    rows = (
        Activity.objects.filter(fy=fy, deleted_at__isnull=True)
        .filter(
            Q(responsible_staff_id__in=list(owner_of))
            | Q(
                responsible_staff_id__isnull=True,
                monitored_by_staff_id__in=list(owner_of),
            )
            | Q(school_id__in=portfolio_ref)
        )
        .values("responsible_staff_id", "monitored_by_staff_id", "school_id", "status")
        .annotate(n=Count("id"))
        .order_by()
    )
    from apps.analytics.pl_analytics_service import (
        VERIFIED_STATUSES as verified_statuses,
    )

    delivery: dict[str, list[int]] = {}
    completions: dict[str, int] = {}
    for row in rows:
        n = row["n"]
        owners = set(school_owner.get(row["school_id"], ()))
        responsible = owner_of.get(row["responsible_staff_id"])
        if responsible:
            owners.add(responsible)
        for staff_id in owners:
            counts = delivery.setdefault(staff_id, [0, 0])
            counts[0] += n
            if row["status"] in verified_statuses:
                counts[1] += n
        if row["status"] == AWAITING_PL_STATUS:
            submitter = (
                responsible
                if row["responsible_staff_id"]
                else owner_of.get(row["monitored_by_staff_id"])
            )
            if submitter:
                completions[submitter] = completions.get(submitter, 0) + n
    return {k: tuple(v) for k, v in delivery.items()}, completions


def _ssa_coverage(schools: dict, fy: str) -> set:
    """Portfolio schools with an IA-confirmed self-assessment this FY."""
    from apps.ssa.models import SsaRecord

    if not schools["all"]:
        return set()
    return set(
        SsaRecord.objects.filter(
            school_id__in=list(schools["all"]),
            fy=fy,
            verification_status="confirmed",
        )
        .values_list("school_id", flat=True)
        .distinct()
    )


def _leave(staff_ids, today: date) -> dict:
    """Away now, next away, and requests waiting for a decision."""
    from apps.accounts.models import Leave

    rows = list(
        Leave.objects.filter(
            staff_id__in=staff_ids, status__in=("approved", "pending")
        ).values("staff_id", "status", "start_date", "end_date")
    )
    away_now: dict[str, date] = {}
    next_away: dict[str, date] = {}
    pending: dict[str, int] = {}
    approved_rows = {sid: [] for sid in staff_ids}
    for row in rows:
        if row["status"] == "pending":
            pending[row["staff_id"]] = pending.get(row["staff_id"], 0) + 1
            continue
        start, end = _iso(row["start_date"]), _iso(row["end_date"])
        approved_rows[row["staff_id"]].append((start, end))
        if not start or not end:
            continue
        if start <= today <= end:
            current = away_now.get(row["staff_id"])
            away_now[row["staff_id"]] = max(current, end) if current else end
        elif start > today:
            upcoming = next_away.get(row["staff_id"])
            next_away[row["staff_id"]] = min(upcoming, start) if upcoming else start
    return {
        "away_now": away_now,
        "next_away": next_away,
        "pending": pending,
        "approved_rows": approved_rows,
    }


def _prime_leave_days(approved_rows: dict) -> None:
    """Hand Team Targets' pace calendar the team's approved leave.

    `FinancialYearCalendarService._all_leave_days` reads one person's approved
    leave per call and memoises it per request under ("leave_all", staff id).
    The roster already read every officer's leave in one query, so the same
    day sets are placed under that key and the pace arithmetic reads them
    instead of querying once per officer. The query-budget test fails if the
    key ever drifts.
    """
    from apps.core.request_cache import store

    bucket = store()
    if bucket is None:
        return
    for staff_id, spans in approved_rows.items():
        days: set = set()
        for start, end in spans:
            if not start or not end:
                continue
            day = start
            while day <= end:
                days.add(day)
                day += timedelta(days=1)
        bucket.setdefault(("leave_all", staff_id), frozenset(days))


def _target_bands(members, fy: str, today: date, approved_rows: dict) -> dict:
    """Team Targets' status for each officer, computed the way Team Oversight
    computes it (PLTeamTargetsService.get_page's roster path)."""
    try:
        from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
        from apps.targets.ledger_sync import refresh_many
        from apps.targets.my_targets import (
            MyTargetQueryService,
            priority_target_areas_for_users,
        )
        from apps.targets.team_targets import PLTeamTargetsService

        users = []
        for m in members:
            user = m.user
            user._staff_profile_id_cache = m.id
            users.append(user)
        month = Cal.month_of_fy_for(today, fy)
        is_current_fy = month is not None
        month = month or 12
        m_start, m_end = Cal.month_range(fy, month)
        _prime_leave_days(approved_rows)

        areas_by_user = priority_target_areas_for_users(users, fy)
        refresh_many(users, fy)
        area_keys = sorted(
            {a.key for u in users for a in areas_by_user.get(str(u.id), [])}
        )
        explicit = MyTargetQueryService._explicit_targets(users, fy, area_keys)
        profiles = MyTargetQueryService._target_profiles(users, fy)
        ledger = MyTargetQueryService._validated_ledger(users, fy, area_keys)

        out = {}
        for user in users:
            member = PLTeamTargetsService._member(
                user,
                areas_by_user.get(str(user.id), []),
                fy,
                month,
                today,
                m_start,
                m_end,
                is_current_fy,
                prepared=(
                    explicit.get(user.id, {}),
                    profiles.get(user.staff_profile_id),
                    ledger.get(user.id, ()),
                ),
            )
            fy_cell = member["matrix_cells"][-1]
            pct = fy_cell["display_pct"]
            status = fy_cell["status"]
            if status == "Not Assigned":
                text = "No targets agreed"
            elif pct is None:
                text = status
            else:
                text = f"{pct}% · {status}"
            out[user.staff_profile_id] = {
                "fy_status": status,
                "fy_tone": fy_cell["tone"],
                "fy_text": text,
                "month_status": member["status"] if is_current_fy else "",
            }
        return out
    except Exception:  # noqa: BLE001 - the roster renders without targets
        logger.exception("My Team target bands failed")
        return {}


def _reviews(staff_ids, fy: str) -> dict:
    """The FY's performance agreement per officer."""
    from apps.hr.models import PerformanceReview

    out = {}
    for review in PerformanceReview.objects.filter(
        staff_id__in=staff_ids, fy=fy, review_type="annual_priorities"
    ).order_by("created_at"):
        out[review.staff_id] = review
    return out


def _review_cell(review, fy: str) -> dict:
    from apps.hr.models import ReviewStage

    if review is None:
        return {"text": f"No FY{fy} agreement", "tone": "danger", "stage": ""}
    label = dict(ReviewStage.choices).get(review.stage, review.stage)
    if review.stage in MANAGER_STAGES:
        return {
            "text": f"{label} · waiting on you",
            "tone": "warning",
            "stage": review.stage,
        }
    tone = "success" if review.stage in ("closed", "signed_and_archived") else ""
    return {"text": label, "tone": tone, "stage": review.stage}


def _pd_waiting(staff_ids) -> dict:
    """Development requests at the supervisor stage, per officer."""
    from apps.professional_development.models import (
        PDStatus,
        ProfessionalDevelopmentRequest,
    )

    out: dict[str, list] = {}
    for req in ProfessionalDevelopmentRequest.objects.filter(
        staff_id__in=staff_ids, status=PDStatus.SUBMITTED_TO_SUPERVISOR
    ).only("id", "staff_id", "course_name", "submitted_at"):
        out.setdefault(req.staff_id, []).append(req)
    return out


def _escalations(principal, user_ids) -> dict:
    """Open escalations an officer raised that this lead may decide — the
    escalation board's own addressed-to-me rule, so the two never disagree."""
    from apps.flags.escalation_service import _addressed_to_me_q
    from apps.flags.models import EscalationStatus, LeadershipEscalation

    inbox = _addressed_to_me_q(principal)
    if inbox is None or not user_ids:
        return {}
    out: dict[str, list] = {}
    for esc in (
        LeadershipEscalation.objects.filter(inbox, raised_by_user_id__in=user_ids)
        .exclude(status=EscalationStatus.RESOLVED)
        .order_by("created_at")
    ):
        out.setdefault(esc.raised_by_user_id, []).append(esc)
    return out


def _extra_work_waiting(principal, user_ids) -> dict:
    """Extra work an officer submitted that this lead verifies."""
    from apps.hr.models import ExtraAssignment

    me = getattr(principal, "id", None)
    if not me or not user_ids:
        return {}
    return dict(
        ExtraAssignment.objects.filter(
            assignee_id__in=user_ids, reviewer_id=str(me), status="submitted"
        )
        .values("assignee_id")
        .annotate(n=Count("id"))
        .values_list("assignee_id", "n")
    )


def _policies_overdue(user_ids, today: date) -> dict:
    """Policy acknowledgements past their due date, per officer (the Policy
    Compliance register's overdue rule)."""
    from apps.documents.models import (
        READABLE_STATUSES,
        AcknowledgementState,
        DocumentAcknowledgement,
    )

    if not user_ids:
        return {}
    return dict(
        DocumentAcknowledgement.objects.filter(
            user_id__in=user_ids,
            state=AcknowledgementState.PENDING,
            due_date__lt=today,
            document__status__in=READABLE_STATUSES,
        )
        .values("user_id")
        .annotate(n=Count("id"))
        .values_list("user_id", "n")
    )


def _coaching(principal, staff_ids) -> dict:
    try:
        from apps.cce_leadership.coaching import last_coaching_by_cceo

        return last_coaching_by_cceo(principal, staff_ids) or {}
    except Exception:  # noqa: BLE001 - coaching is one column, not the page
        logger.exception("My Team last coaching failed")
        return {}


def _coaching_cell(last: dict | None) -> dict:
    if not last:
        return {"text": "Not coached yet", "tone": "warning"}
    parts = [_day(last.get("held_on")), last.get("kind_label") or ""]
    text = " · ".join(p for p in parts if p)
    if last.get("open_follow_up"):
        return {"text": f"{text} · follow-up open", "tone": "warning"}
    if last.get("shared") and not last.get("acknowledged"):
        return {"text": f"{text} · not acknowledged", "tone": "info"}
    return {"text": text or "Coached", "tone": ""}


def _leave_cell(leave: dict, staff_id: str) -> dict:
    until = leave["away_now"].get(staff_id)
    if until:
        return {
            "text": f"On leave until {_day(until)}",
            "tone": "warning",
            "away_now": True,
        }
    upcoming = leave["next_away"].get(staff_id)
    if upcoming:
        return {"text": f"Away from {_day(upcoming)}", "tone": "", "away_now": False}
    return {"text": "—", "tone": "", "away_now": False}


# ── Needs your action ────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def _needs_action(
    principal,
    members,
    *,
    today,
    fy,
    reviews,
    completions,
    development,
    escalations,
    extra_work,
) -> list[dict]:
    """Manager-owned exceptions and handoffs, each with a link the Programme
    Lead can open. HR's own exception builders supply the leave and review
    rules so HR Today and My Team can never disagree about what is late."""
    from apps.hr.hr_exceptions import (
        _leave_decisions_overdue,
        _leave_without_coverage,
        _reviews_overdue,
    )

    staff_ids = [m.id for m in members]
    name_of = {m.id: getattr(m.user, "name", "") for m in members}
    name_of_user = {m.user_id: getattr(m.user, "name", "") for m in members}
    items: list[dict] = []

    def add(kind, title, detail, url, *, person="", severity="medium", due=""):
        items.append(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "url": url,
                "person": person,
                "severity": severity,
                "due_label": due,
            }
        )

    for builder in (
        _leave_decisions_overdue,
        _reviews_overdue,
        _leave_without_coverage,
    ):
        try:
            for exc in builder(staff_ids, today):
                add(
                    exc.kind,
                    exc.title,
                    exc.detail,
                    exc.url,
                    person=exc.person,
                    severity=exc.severity,
                    due=exc.due_label,
                )
        except Exception:  # noqa: BLE001
            logger.exception("My Team exception builder %s failed", builder.__name__)

    # No agreement for the year: the conversation page is where the lead and
    # the officer start it. HR's own builder links to the HR console instead.
    for m in members:
        if m.id not in reviews and getattr(m, "onboarding_state", "") == "active":
            add(
                "no_agreement",
                "No performance agreement",
                f"No FY{fy} agreement yet, so none of their delivery counts towards it.",
                f"/performance-conversation?staff={m.id}",
                person=name_of[m.id],
                severity="high",
            )

    for staff_id, count in completions.items():
        add(
            "completions_waiting",
            "Completions waiting for your review",
            f"{_plural(count, 'completed activity')} submitted for your confirmation.",
            "/pl/review-queue",
            person=name_of.get(staff_id, ""),
            severity="high",
        )
    for staff_id, requests in development.items():
        for req in requests:
            add(
                "pd_supervisor_review",
                "Development request waiting for you",
                req.course_name or "Professional development request",
                f"/my-professional-development/request?id={req.id}",
                person=name_of.get(staff_id, ""),
            )
    for user_id, rows in escalations.items():
        for esc in rows:
            add(
                "escalation_to_decide",
                f"Decide escalation from {name_of_user.get(user_id) or esc.raised_by_name or 'your officer'}",
                esc.subject,
                "/escalations",
                person=name_of_user.get(user_id, ""),
                severity="high" if esc.severity != "normal" else "medium",
                due=f"open {esc.age_days}d",
            )
    for user_id, count in extra_work.items():
        add(
            "extra_work_to_verify",
            "Extra work to verify",
            f"{_plural(count, 'submitted assignment')} waiting for your verification.",
            "/extra-work",
            person=name_of_user.get(user_id, ""),
        )

    items.sort(key=lambda i: (_SEVERITY_ORDER.get(i["severity"], 3), i["person"]))
    return items
