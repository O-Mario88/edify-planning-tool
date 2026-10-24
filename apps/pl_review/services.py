"""PL review queue — CCEO completions routed to the supervising PL.

Every function here previously ignored its `principal`: `queue()` returned every
`submitted_to_pl` activity in the country, and `confirm()`/`return_activity()`
performed the transition with no supervision check, no self-check and no audit
row. Because the API is gated on `planning.view` — a permission Partner roles
also hold — a partner user could confirm another team's completions, and a CCEO
could confirm their own.

The rule this module enforces: a completion is reviewable only by the person who
supervises the staff member who submitted it (or an Admin), and never by the
submitter, except a Programme Lead's own field work, which the lead verifies
(owner, 2026-10-14: "IA does not verify CCEO and PL work. it is the PL to
verify everything"; lead_clears_own_work).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

#: The statuses a completion waits on its Programme Lead in. Program Leads
#: verify their CCEOs' field work — visits, trainings and cluster meetings
#: (owner, 2026-10-12) — and their own (2026-10-14), so such a staff-delivered
#: completion is the lead's whichever path filed it: the review path writes ``submitted_to_pl``; an
#: older path, or a submission somebody else pressed for the officer, left it
#: ``awaiting_ia_verification`` with Impact Assessment, where the lead could
#: not clear it. Partner work is never here: it is verified where its
#: Salesforce entry and payment are decided.
LEAD_REVIEWABLE_STATUSES = ("submitted_to_pl", "awaiting_ia_verification")


#: The roles whose staff-delivered work a Programme Lead verifies, never
#: Impact Assessment (owner, 2026-10-14: "IA does not verify CCEO and PL work.
#: it is the PL to verify everything"): a CCEO's by their lead, and a lead's
#: own by the lead (owner, same day: "The PL verifies it").
LEAD_VERIFIED_ROLES = (EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value)


def _lead_verified_profiles():
    """The staff whose staff-delivered work a Programme Lead verifies: every
    CCEO and lead, and anyone else a Programme Lead supervises (owner,
    2026-10-19: "Only Partner work is verified by Impact Assessment (IA).
    Staff work is verified by PL"). A staff member no lead supervises has no
    lead to send work to, so IA keeps theirs rather than it waiting on
    nobody."""
    from apps.accounts.models import StaffProfile

    holds = Q()
    for role in LEAD_VERIFIED_ROLES:
        holds |= Q(user__roles__contains=[role])
    supervised_by_lead = Q(
        supervisor_links__supervisor__user__roles__contains=[
            EdifyRole.COUNTRY_PROGRAM_LEAD.value
        ],
        supervisor_links__supervisor__deleted_at__isnull=True,
    )
    return StaffProfile.objects.filter(
        holds | supervised_by_lead, deleted_at__isnull=True
    ).distinct()


def lead_verified_owner_q(field: str = "responsible_staff_id") -> Q:
    """Work owned by a CCEO or a Programme Lead, in either id space.

    ``Activity.responsible_staff_id`` holds a StaffProfile id or a User id
    depending on the path that wrote it (``scoping.owner_ids``), so both are
    asked. Two subqueries, no literal id list, however many officers there
    are.
    """
    profiles = _lead_verified_profiles()
    return Q(**{f"{field}__in": profiles.values("id")}) | Q(
        **{f"{field}__in": profiles.values("user_id")}
    )


def lead_verified_q() -> Q:
    """Staff-delivered work whose completion a Programme Lead verifies — the
    work Impact Assessment's staff queue must not offer."""
    return lead_verified_owner_q() & ~Q(delivery_type="partner")


def lead_verified_owner_ids() -> frozenset[str]:
    """Every id a CCEO's or a lead's work may be filed under, for callers
    deciding row by row (Cluster Oversight) without a query per row."""
    ids: set[str] = set()
    for profile_id, user_id in _lead_verified_profiles().values_list("id", "user_id"):
        ids.add(str(profile_id))
        if user_id:
            ids.add(str(user_id))
    return frozenset(ids)


def owner_is_lead_verified(activity) -> bool:
    owner = _owning_staff_id(activity)
    return (
        bool(owner)
        and _lead_verified_profiles().filter(Q(id=owner) | Q(user_id=owner)).exists()
    )


def lead_verifies(activity) -> bool:
    """Whether this completion is a Programme Lead's to verify, not IA's."""
    return activity.delivery_type != "partner" and owner_is_lead_verified(activity)


def routes_to_lead(activity, principal) -> bool:
    """Where a completion goes when it is submitted: a Programme Lead for a
    CCEO's or a lead's staff-delivered work, Impact Assessment otherwise.

    Read from the work's OWNER as well as the submitter's role: a completion a
    lead or an Admin presses Submit on for an officer is still the officer's
    field work, and used to detour to Impact Assessment, where the lead could
    not clear it (owner, 2026-10-12). A lead's own work is the lead's too
    (owner, 2026-10-14), found by its owner like a CCEO's: a lead pressing
    Submit on work of staff no lead verifies (a coordinator's, at a school the
    lead holds) sends it to IA, never to a lead's queue nobody could clear.
    Partner work goes to IA whoever presses the button (§10, 2026-08-19
    audit).
    """
    if activity.delivery_type == "partner":
        return False
    if getattr(principal, "active_role", "") == EdifyRole.CCEO.value:
        return True
    return owner_is_lead_verified(activity)


def lead_clears_own_work(principal) -> bool:
    """A Programme Lead verifies their own staff field work (owner,
    2026-10-14: "The PL verifies it"). Read from the role HELD as well as the
    one in use: an officer acting as a lead for a month does not clear their
    own work. Partner work the lead monitors is never theirs to clear (§10).

    Not `apps.core.permissions.verifies_own_work`, which answers the opposite
    question (is this person responsible for the work, so must be refused)."""
    lead = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    return getattr(principal, "active_role", "") == lead and lead in (
        getattr(principal, "roles", None) or []
    )


def _reviewer_staff_ids(principal) -> set[str]:
    """The staff whose completions this principal may review, in BOTH id spaces.

    `supervised_staff_ids` holds StaffProfile ids, but
    `Activity.responsible_staff_id` may hold either a StaffProfile id or a User
    id depending on which path wrote it (see `scoping.owner_ids`). Matching
    only one space would refuse legitimate reviews.

    Reads from the shared scope service, so active temporary coverage confers
    review authority exactly as it does for leave and PD approvals.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(principal)
    staff_ids = set(scope.supervised_staff_ids or [])
    if not staff_ids:
        return staff_ids
    user_ids = StaffProfile.objects.filter(id__in=staff_ids).values_list(
        "user_id", flat=True
    )
    return staff_ids | {u for u in user_ids if u}


def _is_admin(principal) -> bool:
    return getattr(principal, "active_role", "") == EdifyRole.ADMIN.value


def _own_ids(principal) -> set[str]:
    """Both id spaces a completion may be attributed to for this principal.

    `Activity.responsible_staff_id` holds either a User id or a StaffProfile id
    depending on the writer, so a self-check must cover both.
    """
    return {
        i
        for i in (
            getattr(principal, "user_id", None),
            getattr(principal, "staff_profile_id", None),
        )
        if i
    }


def _owning_staff_id(activity) -> str | None:
    """Who this completion belongs to for review purposes.

    Partner-delivered activities carry `responsible_staff_id=None` and record
    the scheduling staff member on `monitored_by_staff_id` instead — that
    person submits the completion, so they are who the reviewer supervises.
    """
    return activity.responsible_staff_id or getattr(
        activity, "monitored_by_staff_id", None
    )


def may_review(principal, activity) -> bool:
    """The review rule as a yes/no, for callers deciding whether to offer it.

    `RolePermissionService.can_review_activity` used to answer this for a
    Programme Lead from `supervised_staff_ids` alone: one id space, no monitor
    fallback and no self-check. A completion filed under the CCEO's User id, or
    a partner activity attributed to its monitor, was therefore refused at the
    page while the service below would have accepted it — the queue listed the
    row and its Approve button answered "you do not supervise the owner". Both
    doors now ask this one function, so they cannot disagree again.

    Status is not part of the answer: whether the work is *waiting* for review
    is the service's question (`_get_reviewable`), not the permission's.
    """
    if activity is None:
        return False
    return review_rule(principal)(
        _owning_staff_id(activity), partner=activity.delivery_type == "partner"
    )


def review_rule(principal):
    """`may_review` for many rows: whose completions this reviewer may decide.

    Returns a predicate over the owning staff id (either id space), told
    whether the row is partner work. The reviewer's reach is resolved once, so
    a table can ask it of every row without a query per row — Cluster
    Oversight offers Verify only where the decision itself would accept it.
    """
    if _is_admin(principal):
        return lambda owner, partner=False: True
    mine = _own_ids(principal)
    reviewable = _reviewer_staff_ids(principal)
    clears_own = lead_clears_own_work(principal)

    def rule(owner, partner=False) -> bool:
        if not owner:
            return False
        if owner in mine:
            return clears_own and not partner
        return owner in reviewable

    return rule


def _queue_queryset(principal):
    """The completions waiting on THIS reviewer, as an unevaluated queryset.

    Work the review path filed under the lead, and a CCEO's or a lead's
    staff-delivered work an older path left with Impact Assessment: both are
    the lead's to clear (LEAD_REVIEWABLE_STATUSES). A lead's own staff
    completions are listed for them too (lead_clears_own_work); partner work
    they monitor never is (§10).
    """
    qs = Activity.objects.filter(deleted_at__isnull=True).filter(
        Q(status="submitted_to_pl")
        | (Q(status="awaiting_ia_verification") & lead_verified_q())
    )
    if _is_admin(principal):
        return qs
    reviewable = _reviewer_staff_ids(principal)
    mine = _own_ids(principal)
    clears_own = lead_clears_own_work(principal)
    if not reviewable and not clears_own:
        return qs.none()

    def filed_under(ids) -> Q:
        # Staff-delivered work is attributed by responsible_staff_id; partner
        # work by the monitoring staff member — in either id space.
        return Q(responsible_staff_id__in=ids) | Q(
            responsible_staff_id__isnull=True, monitored_by_staff_id__in=ids
        )

    # Nobody else's own submission is surfaced to them.
    waiting = filed_under(reviewable) & ~filed_under(mine)
    if clears_own:
        waiting |= Q(responsible_staff_id__in=mine) & ~Q(delivery_type="partner")
    return qs.filter(waiting)


def waiting_count(principal) -> int:
    """How many completions wait on THIS reviewer: the rows of their
    Completion Reviews register (`review_register`), counted in one query."""
    return _queue_queryset(principal).count()


def _people(owner_ids) -> tuple[dict[str, str], dict[str, str]]:
    """Names and StaffProfile ids for people filed under either id space.

    One query. Returns ``(names, profile_of)`` keyed by every id a person's
    work may carry, so a row filed under a User id and one filed under the
    StaffProfile id resolve to the same name and the same filter value.
    """
    from django.db.models import Q

    from apps.accounts.models import StaffProfile

    ids = {i for i in owner_ids if i}
    names: dict[str, str] = {}
    profile_of: dict[str, str] = {}
    if not ids:
        return names, profile_of
    for profile_id, user_id, name in StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).values_list("id", "user_id", "user__name"):
        for key in (profile_id, user_id):
            if key:
                names[key] = name or ""
                profile_of[key] = profile_id
    return names, profile_of


def queue(principal) -> list[dict]:
    """Activities awaiting THIS reviewer's confirmation.

    Each row carries the cluster's name and the submitter's name as well as
    the school's, so a To-Do built from it can say "Cluster training at Mukono
    North from Grace" rather than "Activity at the field". Both come from one
    join and one name lookup, whatever the queue's length.
    """
    from apps.activities.services import _serialize

    activities = list(
        _queue_queryset(principal)
        .select_related("school", "cluster")
        .order_by("-updated_at")
    )
    names, _profile_of = _people(_owning_staff_id(a) for a in activities)
    return [
        _serialize(a, owner_name=names.get(_owning_staff_id(a) or "", ""))
        for a in activities
    ]


#: Days a completion may wait before the register reads it as late. The review
#: carries no service-level agreement of its own; a working week is when a
#: completion the officer submitted starts holding up Impact Assessment.
REVIEW_WAIT_ALERT_DAYS = 7


def _attendance_label(activity) -> str:
    """Who the session reached, as the officer recorded it at completion."""
    parts = []
    if activity.teachers_attended:
        parts.append(f"{activity.teachers_attended} teachers")
    if activity.leaders_attended:
        parts.append(f"{activity.leaders_attended} leaders")
    if activity.other_participants:
        parts.append(f"{activity.other_participants} others")
    schools = len(activity.attended_school_ids or [])
    if activity.cluster_id and not activity.school_id and schools:
        parts.append(f"{schools} school{'s' if schools != 1 else ''}")
    return " · ".join(parts)


def review_register(principal, *, cceo: str = "", today=None) -> dict:
    """The review queue as the register the Completion Reviews page shows.

    One row per completion waiting on this reviewer, oldest first — the one
    that has waited longest is the one holding up Impact Assessment. Every
    column is read in bulk: the activities with their school and cluster in one
    join, the submitters' names in one lookup, the evidence counts in one
    grouped query and the submission moments in one more. Nothing is fetched
    per row, so a lead with forty completions waiting pays what a lead with
    one does.

    `cceo` narrows to one submitter (a StaffProfile or User id); the options
    offered are the submitters actually present, so the filter never offers a
    name that returns nothing.
    """
    from django.db.models import Count

    from apps.activities.models import ActivityCompletionVerification
    from apps.core.interventions import INTERVENTION_LABELS, intervention_abbr
    from apps.evidence.models import EvidenceRecord

    today = today or timezone.localdate()
    activities = list(
        _queue_queryset(principal).select_related(
            "school", "cluster", "school__district"
        )
    )
    # Owner options are keyed by the StaffProfile id where there is one, so the
    # filter value is the same whichever id space a row was filed under.
    owner_keys = {_owning_staff_id(a) for a in activities} - {None, ""}
    names, profile_of = _people(owner_keys)

    wanted = (cceo or "").strip()
    wanted_profile = profile_of.get(wanted, wanted)
    options = sorted(
        {
            (profile_of.get(owner, owner), names.get(owner, "") or "Unnamed officer")
            for owner in owner_keys
        },
        key=lambda pair: pair[1].lower(),
    )
    if wanted:
        activities = [
            a
            for a in activities
            if profile_of.get(_owning_staff_id(a) or "", _owning_staff_id(a))
            == wanted_profile
        ]

    ids = [a.id for a in activities]
    evidence = {
        row["activity_id"]: row["n"]
        for row in EvidenceRecord.objects.filter(activity_id__in=ids, quarantined=False)
        .values("activity_id")
        .annotate(n=Count("id"))
    }
    submitted = dict(
        ActivityCompletionVerification.objects.filter(activity_id__in=ids).values_list(
            "activity_id", "updated_at"
        )
    )

    rows = []
    for a in activities:
        owner = _owning_staff_id(a) or ""
        # The completion row is written at the moment of submission and not
        # again until review, so it dates the wait; work an older path sent to
        # Impact Assessment is dated by that submission; updated_at is the
        # fallback for rows submitted before completions carried either.
        since = submitted.get(a.id) or a.submitted_to_ia_at or a.updated_at
        waited = max((today - timezone.localtime(since).date()).days, 0) if since else 0
        when = a.actual_delivery_date or a.planned_date
        if when is None and a.scheduled_date:
            when = timezone.localtime(a.scheduled_date).date()
        files = evidence.get(a.id, 0)
        if a.school_id:
            where, where_kind = a.school.name, "School"
        elif a.cluster_id:
            where, where_kind = a.cluster.name, "Cluster"
        else:
            where, where_kind = (a.venue or "", "Venue")
        rows.append(
            {
                "id": a.id,
                "owner_id": owner,
                "cceo": names.get(owner, "") or "Unnamed officer",
                "activity": a.activity_name_snapshot or a.get_activity_type_display(),
                "where": where,
                "where_kind": where_kind,
                "school_code": a.school.school_id if a.school_id else "",
                "district": (
                    getattr(a.school.district, "name", "")
                    if a.school_id and a.school.district_id
                    else ""
                ),
                "date": when,
                "intervention": intervention_abbr(a.focus_intervention)
                if a.focus_intervention
                else "",
                "intervention_label": INTERVENTION_LABELS.get(
                    a.focus_intervention or "", ""
                ),
                "attendance": _attendance_label(a),
                "evidence_files": files,
                "evidence": (
                    f"{files} file{'s' if files != 1 else ''}" if files else "No files"
                ),
                "evidence_tone": "" if files else "warning",
                "salesforce_id": a.salesforce_activity_id or "",
                "days_waiting": waited,
                "wait_tone": "danger" if waited >= REVIEW_WAIT_ALERT_DAYS else "",
                "delivery_type": a.delivery_type,
            }
        )
    rows.sort(key=lambda row: (-row["days_waiting"], row["cceo"].lower()))
    return {"rows": rows, "cceo_options": options, "cceo": wanted_profile}


def reviewable_activity(activity_id: str, principal) -> Activity:
    """The one completion, only if it is waiting on this reviewer.

    The drawers read through here so a guessed id answers with the same
    refusal the decision itself would give.
    """
    return _get_reviewable(activity_id, principal)


def _get_reviewable(activity_id: str, principal) -> Activity:
    a = (
        Activity.objects.filter(id=activity_id, deleted_at__isnull=True)
        .select_related("school", "cluster")
        .first()
    )
    return _check_reviewable(a, principal)


def _lock_reviewable(activity_id: str, principal) -> Activity:
    """`_get_reviewable` again, under a row lock, inside the decision.

    The first read is a courtesy that refuses early; this is the guard — the
    same two layers as `ActivityCertificationService.certify_activity`. Two
    requests that both read "submitted to PL" before either wrote (a
    double-click, two tabs, two leads over one officer) both used to apply:
    two approvals, two notices to the officer and two Salesforce syncs, or an
    approval and a return with the last writer winning, so a completion could
    end "returned" with its evidence accepted and its credit recorded. The
    loser now waits for the lock and is refused.
    """
    a = (
        Activity.objects.select_for_update(of=("self",))
        .filter(id=activity_id, deleted_at__isnull=True)
        .select_related("school", "cluster")
        .first()
    )
    return _check_reviewable(a, principal)


def _check_reviewable(a: Activity | None, principal) -> Activity:
    if not a:
        raise NotFoundError("Activity not found.")
    if a.status not in LEAD_REVIEWABLE_STATUSES:
        raise BadRequest("Activity is not awaiting PL review.")
    if a.status == "awaiting_ia_verification" and not lead_verifies(a):
        # Partner work, or a coordinator's own field work: Impact
        # Assessment's, as it always was.
        raise BadRequest("This work is verified by Impact Assessment.")
    if _is_admin(principal):
        return a
    owner = _owning_staff_id(a)
    if owner and owner in _own_ids(principal):
        if lead_clears_own_work(principal) and a.delivery_type != "partner":
            return a
        raise Forbidden("You cannot review your own completion.")
    if owner not in _reviewer_staff_ids(principal):
        raise Forbidden("This completion belongs to another Program Lead's team.")
    return a


def _audit(action: str, activity: Activity, principal, reason: str | None = None):
    audit_log(
        action=action,
        subject_kind="Activity",
        subject_id=activity.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "schoolId": activity.school_id,
            "activityType": activity.activity_type,
            "responsibleStaffId": activity.responsible_staff_id,
            "status": activity.status,
        },
    )


def _close_review_notice(activity) -> None:
    """The PL's review queue no longer holds this activity.

    `activity_submitted_for_review` is fired at the supervising PL when a
    completion arrives. Nothing closed it: once the PL confirmed or returned
    the work, the derived To-Do disappeared while the notification stayed
    unread and was later promoted to urgent by the staleness job.
    """
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition("activity_submitted_for_review", "Activity", activity.id)
    except Exception:  # noqa: BLE001 - never fail a review over bookkeeping
        pass


def _close_ia_notice(activity) -> None:
    """Impact Assessment was told this work was waiting for them; it is not."""
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            "activity_submitted_for_verification", "activity", str(activity.id)
        )
    except Exception:  # noqa: BLE001 - never fail a review over bookkeeping
        pass


def programme_lead_owner(activity) -> str | None:
    """The user id of the Programme Lead whose own staff work this is, or
    None.

    Read from the role the owner HOLDS: an officer acting as a lead for a
    month holds CCEO, and their own work still goes to their lead (owner,
    2026-10-07: acting is following up, never deciding). Partner work is
    never a lead's own (§10).
    """
    owner = activity.responsible_staff_id
    if not owner or activity.delivery_type == "partner":
        return None
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(
            Q(id=owner) | Q(user_id=owner),
            deleted_at__isnull=True,
            user__roles__contains=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
        )
        .values_list("user_id", flat=True)
        .first()
    )


def _approve(a: Activity, reviewer_id: str) -> None:
    """Write the approval on a locked, reviewable completion: the work is
    approved and counted from now (owner, 2026-10-15). Inside the caller's
    transaction."""
    from apps.activities.ia_models import IAVerification
    from apps.activities.services import sf_kind_for_activity
    from apps.core.enums import ActivityStatus, EvidenceStatus, VerificationStatus
    from apps.evidence.models import EvidenceRecord
    from apps.hr.milestone_progress import record_activity_progress
    from apps.integrations.services import enqueue_activity_salesforce_sync

    # No completion is verified without its Salesforce ID (owner, 2026-10-19:
    # "make sure that all completion should have salesforce ID"). The drawer
    # hides Verified without one; this holds for a direct post, and for work
    # handed in before the rule reached SSA data-gathering visits.
    if (
        sf_kind_for_activity(a) is not None
        and not (a.salesforce_activity_id or "").strip()
    ):
        raise BadRequest(
            "This completion has no Salesforce ID. Return it to the officer "
            "to enter the ID; it cannot be verified without one."
        )
    reviewed_at = timezone.now()
    was_with_ia = a.status == "awaiting_ia_verification"
    a.status = ActivityStatus.IA_VERIFIED
    a.ia_verification_status = VerificationStatus.CONFIRMED
    a.pl_reviewed_at = reviewed_at
    a.pl_reviewed_by = reviewer_id
    a.ia_confirmed_at = reviewed_at
    a.ia_confirmed_by = reviewer_id
    a.evidence_status = "accepted"
    a.save(
        update_fields=[
            "status",
            "ia_verification_status",
            "pl_reviewed_at",
            "pl_reviewed_by",
            "ia_confirmed_at",
            "ia_confirmed_by",
            "evidence_status",
            "updated_at",
        ]
    )
    EvidenceRecord.objects.filter(activity=a, quarantined=False).update(
        status=EvidenceStatus.ACCEPTED,
        reviewed_by=reviewer_id,
        reviewed_at=reviewed_at,
    )
    # The IA workspace's own record, where the work had one: it must not go on
    # reading "pending" for work the lead has approved.
    IAVerification.objects.filter(activity=a).update(
        status=VerificationStatus.CONFIRMED,
        verified_by=reviewer_id,
        verified_at=reviewed_at,
    )
    # The SSA scores keyed on the visit count from its approval (owner,
    # 2026-10-16: "when PL approves they will reflect").
    from apps.ssa.pl_confirmation import confirm_visit_ssa

    confirm_visit_ssa(a, reviewer_id)
    _close_review_notice(a)
    if was_with_ia:
        _close_ia_notice(a)
    transaction.on_commit(lambda: record_activity_progress(a))
    enqueue_activity_salesforce_sync(a.id)


def confirm(activity_id: str, principal) -> dict:
    """PL approves and verifies a CCEO completion and evidence directly.

    Per organization workflow, the supervising PL manages and verifies their
    team members' activities and evidence directly (earning milestone progress
    credit and syncing to Salesforce), rather than routing staff work to IA.
    IA verifies evidence for partner completed activities to process partner payments.
    """
    from apps.activities.services import _serialize

    _get_reviewable(activity_id, principal)

    with transaction.atomic():
        a = _lock_reviewable(activity_id, principal)
        _approve(a, principal.user_id)
        _audit("pl_review_confirm", a, principal)

    # Notify CCEO
    owner = _owning_staff_id(a)
    _notify_after_review(
        a,
        "activity_verified_by_pl",
        "Your completion was approved and verified",
        "Your Program Lead approved and verified your activity completion and evidence.",
        [owner],
        priority="normal",
    )

    return _serialize(a)


def approve_on_hand_in(activity) -> bool:
    """A Programme Lead's own work is approved the moment it is handed in
    (owner, 2026-10-15: "it is the PL who approves for CCEO and theirs are
    approved automatically"). Nobody is asked, so nobody is told. True when
    it was approved."""
    if activity.status not in LEAD_REVIEWABLE_STATUSES:
        return False
    lead_user_id = programme_lead_owner(activity)
    if not lead_user_id:
        return False
    with transaction.atomic():
        a = Activity.objects.select_for_update().get(pk=activity.pk)
        if a.status not in LEAD_REVIEWABLE_STATUSES:
            return False
        _approve(a, lead_user_id)
        audit_log(
            action="pl_review_auto_approve",
            subject_kind="Activity",
            subject_id=a.id,
            actor_id=lead_user_id,
            actor_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            reason="A Programme Lead's own work is approved when it is handed in.",
            payload={
                "schoolId": a.school_id,
                "activityType": a.activity_type,
                "responsibleStaffId": a.responsible_staff_id,
                "status": a.status,
            },
        )
    return True


def return_activity(activity_id: str, data: dict, principal) -> dict:
    """PL returns a completion to the CCEO for correction."""
    from apps.activities.services import _serialize

    from apps.activities.return_notes import compose

    _get_reviewable(activity_id, principal)
    # The reasons ticked (return_notes.COMMON_REASONS) and what the lead
    # wrote, as one note the officer reads (owner, 2026-09-26). "reason"
    # alone, the written part, is how every door has sent it until now.
    data = data or {}
    reasons = data.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    written = str(data.get("comment") or data.get("reason") or "").strip()
    reason = compose(reasons, written)
    if not reason:
        # The officer is told why in the notification below; a return with no
        # reason arrives as "fix this" with nothing to fix. The form marks the
        # field required, and this is the rule behind it for every door.
        raise BadRequest("Say what needs correcting before returning a completion.")
    with transaction.atomic():
        a = _lock_reviewable(activity_id, principal)
        a.status = "returned_by_pl"
        a.pl_review_note = reason
        a.pl_reviewed_at = timezone.now()
        a.pl_reviewed_by = principal.user_id
        a.save(
            update_fields=[
                "status",
                "pl_review_note",
                "pl_reviewed_at",
                "pl_reviewed_by",
                "updated_at",
            ]
        )
        _audit("pl_review_return", a, principal, reason=reason)
    _close_review_notice(a)
    # The submitter must be told, WITH the reason — returning work silently is
    # how a completion sat untouched until someone happened to reopen My Plan.
    owner = _owning_staff_id(a)
    _notify_after_review(
        a,
        "activity_returned_by_pl",
        "Your completion was returned",
        reason or "Your Program Lead returned this completion for correction.",
        [owner],
        priority="high",
    )
    return _serialize(a)


def _notify_after_review(
    activity, event_type, title, body, recipients, priority="normal"
):
    """Best-effort — a notification failure must not undo the review."""
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="activity",
            priority=priority,
            title=title,
            body=body,
            context_type="Activity",
            context_id=activity.id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001
        pass
