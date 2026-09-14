"""Impact Assessment's collection worklist (IA review, 2026-09-13).

Every operationally active school in the officer's country, by what its
evidence needs next: never assessed, follow-up due, pending verification,
returned, collection scheduled, visit completed without scores, partner
collection pending — with special-project enrolments as one segment.

The Collection view used to read `ProjectSchoolAssignment` alone, so it listed
25 project enrolments out of 703 schools in scope while 394 active schools with
last year's confirmed SSA and none this year appeared nowhere. It also built
every row in Python and then paged it. Here each school's state is decided in
the database (one CASE over EXISTS subqueries), so the filters, the counts and
the page are three queries whatever the size of the country, and the page's
details are three more.

Row actions never plan into somebody else's portfolio (owner, 2026-09-02):
"Add SSA" keys scores IA holds, "Ask owner to collect" sends the owner a
`no_ssa` TeamAction that closes itself when a confirmed SSA lands, and
"Request SSA visit" opens the schedule drawer, which files a visit request
for the owner to approve.

Owner: IA-C implements; the signature and return shape are the contract.
"""

from __future__ import annotations

from django.core.paginator import EmptyPage, Paginator
from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Value,
    When,
)
from django.utils import timezone

PAGE_SIZE = 25
PAGE_PARAM = "collection_page"

NEVER_ASSESSED = "never_assessed"
FOLLOW_UP_DUE = "follow_up_due"
PENDING_VERIFICATION = "pending_verification"
RETURNED = "returned"
COLLECTION_SCHEDULED = "collection_scheduled"
VISIT_WITHOUT_SCORES = "visit_completed_without_scores"
PARTNER_PENDING = "partner_pending"
UP_TO_DATE = "up_to_date"

#: State → (label, what happens next, plain-text tone, sort order). The order
#: puts what someone can fix today first: a correction, then a verification.
STATES: dict[str, tuple[str, str, str, int]] = {
    RETURNED: (
        "Returned for correction",
        "The collector re-keys the scores a verifier returned.",
        "danger",
        1,
    ),
    PENDING_VERIFICATION: (
        "Pending verification",
        "A verifier other than the collector confirms the scores.",
        "warning",
        2,
    ),
    PARTNER_PENDING: (
        "Partner collection pending",
        "The partner's SSA Support is under way or awaiting confirmation.",
        "info",
        3,
    ),
    VISIT_WITHOUT_SCORES: (
        "Visit completed without scores",
        "An SSA visit this year closed with a reason; ask the owner to collect.",
        "danger",
        4,
    ),
    COLLECTION_SCHEDULED: (
        "Collection scheduled",
        "An SSA collection visit is planned.",
        "info",
        5,
    ),
    FOLLOW_UP_DUE: (
        "Follow-up due",
        "Confirmed before, nothing confirmed this financial year.",
        "warning",
        6,
    ),
    NEVER_ASSESSED: (
        "Never assessed",
        "No confirmed SSA exists: the baseline is missing.",
        "danger",
        7,
    ),
    UP_TO_DATE: (
        "Confirmed this year",
        "A confirmed SSA exists for this financial year.",
        "success",
        8,
    ),
}

WORK_STATES = tuple(key for key in STATES if key != UP_TO_DATE)

#: Collection activities still ahead of their visit.
OPEN_COLLECTION_STATUSES = (
    "awaiting_owner_approval",
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
)
#: Activity statuses that mean the visit happened.
DELIVERED_STATUSES = (
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
)


# ── Paging ───────────────────────────────────────────────────────────────────
def db_page(queryset, page, page_size: int = PAGE_SIZE) -> dict:
    """One page of a queryset fetched from the database, in the shape the
    shared pager (components/table_pager.html) reads. Out-of-range pages clamp
    to the last page, like `apps.core.pagination.paginate_rows`."""
    from apps.core.pagination import make_pagination_window

    try:
        number = max(1, int(page or 1))
    except (TypeError, ValueError):
        number = 1
    paginator = Paginator(queryset, page_size)
    try:
        current = paginator.page(number)
    except EmptyPage:
        current = paginator.page(paginator.num_pages)
    total = paginator.count
    window = list(current.object_list)
    start = (current.number - 1) * page_size
    return {
        "rows": window,
        "page": current.number,
        "number": current.number,
        "page_count": paginator.num_pages,
        "pages_total": paginator.num_pages,
        "page_size": page_size,
        "total": total,
        "has_previous": current.has_previous(),
        "has_next": current.has_next(),
        "previous_page": current.number - 1,
        "next_page": current.number + 1,
        "first_index": start + 1 if window else 0,
        "last_index": start + len(window),
        "paginated": paginator.num_pages > 1,
        "pages": make_pagination_window(
            current.number, paginator.num_pages, window_size=1
        ),
    }


# ── Population and state ─────────────────────────────────────────────────────
def collection_schools(principal):
    """Operationally active, not deleted schools in the principal's analytics
    scope: the country for IA and the Country Director, the deployment for
    Admin. Closed schools need no collection and are left out."""
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.schools.models import School

    scope = resolve_user_scope(principal)
    base = School.objects.filter(
        deleted_at__isnull=True, operational_status__in=("active", "reopened")
    )
    schools = scoped_school_queryset(scope, base=base)
    return schools if schools is not None else School.objects.none()


def annotate_states(schools, *, fy: str | None = None):
    """Annotate `collection_state` (and `state_order`) on a School queryset."""
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord

    fy = fy or get_operational_fy()
    records = SsaRecord.objects.filter(
        school_id=OuterRef("pk"), deleted_at__isnull=True
    )
    latest_status = records.order_by("-date_of_ssa", "-created_at").values(
        "verification_status"
    )[:1]
    latest_collector = records.order_by("-date_of_ssa", "-created_at").values(
        "collector_type"
    )[:1]
    collection = Activity.objects.filter(
        school_id=OuterRef("pk"),
        deleted_at__isnull=True,
        ssa_collection_expected=True,
    )
    annotated = schools.annotate(
        _latest_status=latest_status,
        _latest_collector=latest_collector,
        _confirmed_this_fy=Exists(
            records.filter(verification_status="confirmed", fy=fy)
        ),
        _confirmed_ever=Exists(records.filter(verification_status="confirmed")),
        _partner_open=Exists(
            collection.filter(
                delivery_type="partner", status__in=OPEN_COLLECTION_STATUSES
            )
        ),
        _staff_open=Exists(
            collection.exclude(delivery_type="partner").filter(
                status__in=OPEN_COLLECTION_STATUSES,
                ssa_not_collected_reason__isnull=True,
            )
        ),
        _visit_without_scores=Exists(
            collection.filter(fy=fy, status__in=DELIVERED_STATUSES)
            .exclude(ssa_not_collected_reason__isnull=True)
            .exclude(ssa_not_collected_reason="")
        ),
    )
    state = Case(
        When(_latest_status="returned", then=Value(RETURNED)),
        When(
            Q(_latest_status="pending") & Q(_latest_collector="partner"),
            then=Value(PARTNER_PENDING),
        ),
        When(_latest_status="pending", then=Value(PENDING_VERIFICATION)),
        When(_confirmed_this_fy=True, then=Value(UP_TO_DATE)),
        When(_partner_open=True, then=Value(PARTNER_PENDING)),
        When(_staff_open=True, then=Value(COLLECTION_SCHEDULED)),
        When(_visit_without_scores=True, then=Value(VISIT_WITHOUT_SCORES)),
        When(_confirmed_ever=True, then=Value(FOLLOW_UP_DUE)),
        default=Value(NEVER_ASSESSED),
        output_field=CharField(),
    )
    order = Case(
        *[
            When(collection_state=key, then=Value(meta[3]))
            for key, meta in STATES.items()
        ],
        default=Value(99),
        output_field=IntegerField(),
    )
    return annotated.annotate(collection_state=state).annotate(state_order=order)


def state_counts(principal, *, fy: str | None = None) -> dict:
    """{state: n} over the whole collection population, one query."""
    counts = {key: 0 for key in STATES}
    rows = (
        annotate_states(collection_schools(principal), fy=fy)
        .order_by()
        .values("collection_state")
        .annotate(n=Count("id"))
    )
    for row in rows:
        counts[row["collection_state"]] = row["n"]
    return counts


# ── Filters ──────────────────────────────────────────────────────────────────
def _owner_names(owner_ids) -> dict[str, str]:
    """{owner id: name} for account owners recorded in either id space."""
    from apps.accounts.models import StaffProfile

    ids = {str(i) for i in owner_ids if i}
    if not ids:
        return {}
    names: dict[str, str] = {}
    for profile_id, user_id, name in StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).values_list("id", "user_id", "user__name"):
        for key in (profile_id, user_id):
            if key and str(key) in ids:
                names[str(key)] = name or "Staff member"
    return names


def _project_segment(principal, schools):
    from apps.projects.models import LIVE_PROJECT_STATUSES, ProjectSchoolAssignment

    return ProjectSchoolAssignment.objects.filter(
        school__in=schools,
        project__deleted_at__isnull=True,
        project__status__in=[s.value for s in LIVE_PROJECT_STATUSES],
    )


def _filter_options(principal, schools) -> dict:
    from apps.projects.models import Project

    districts = list(
        schools.exclude(district__isnull=True)
        .order_by("district__name")
        .values_list("district_id", "district__name")
        .distinct()
    )
    owner_ids = list(
        schools.exclude(account_owner_id__isnull=True)
        .exclude(account_owner_id="")
        .order_by()
        .values_list("account_owner_id", flat=True)
        .distinct()
    )
    names = _owner_names(owner_ids)
    owners = sorted(
        ((oid, names.get(str(oid), "Unmatched owner")) for oid in owner_ids),
        key=lambda pair: pair[1].lower(),
    )
    school_types = sorted(
        {
            t
            for t in schools.order_by().values_list("school_type", flat=True).distinct()
            if t
        }
    )
    project_ids = (
        _project_segment(principal, schools)
        .values_list("project_id", flat=True)
        .distinct()
    )
    projects = list(
        Project.objects.filter(id__in=project_ids)
        .order_by("name")
        .values_list("id", "name")
    )
    return {
        "districts": [{"value": str(v), "label": label} for v, label in districts],
        "owners": [{"value": str(v), "label": label} for v, label in owners],
        "school_types": [
            {"value": t, "label": t.replace("_", " ").title()} for t in school_types
        ],
        "states": [{"value": key, "label": meta[0]} for key, meta in STATES.items()],
        "projects": [{"value": str(v), "label": label} for v, label in projects],
    }


def _clean_query(query) -> dict:
    getter = query.get if hasattr(query, "get") else dict(query or {}).get
    return {
        key: (getter(key) or "").strip()
        for key in ("district", "owner", "school_type", "state", "project")
    }


# ── Rows ─────────────────────────────────────────────────────────────────────
def _page_details(schools: list, fy: str) -> tuple[dict, dict]:
    """Latest SSA and the open collection activity for one page of schools:
    two queries, whatever the page size."""
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord

    ids = [s.id for s in schools]
    latest: dict = {}
    for record in SsaRecord.objects.filter(
        school_id__in=ids, deleted_at__isnull=True
    ).order_by("school_id", "-date_of_ssa", "-created_at"):
        latest.setdefault(record.school_id, record)
    open_visit: dict = {}
    for activity in Activity.objects.filter(
        school_id__in=ids,
        deleted_at__isnull=True,
        ssa_collection_expected=True,
        status__in=OPEN_COLLECTION_STATUSES,
    ).order_by("school_id", "planned_date"):
        open_visit.setdefault(activity.school_id, activity)
    return latest, open_visit


def _detail(state: str, record, visit, names) -> str:
    def day(value):
        if value is None:
            return ""
        if hasattr(value, "tzinfo") and getattr(value, "hour", None) is not None:
            value = timezone.localtime(value).date()
        return f"{value:%-d %b %Y}"

    if state == RETURNED and record is not None:
        return f"Returned {day(record.returned_at)}: {record.return_reason or 'no reason recorded'}"
    if (
        state in (PENDING_VERIFICATION, PARTNER_PENDING)
        and record is not None
        and (record.verification_status == "pending")
    ):
        return f"Scores dated {day(record.date_of_ssa)} wait for a verifier"
    if state in (COLLECTION_SCHEDULED, PARTNER_PENDING) and visit is not None:
        who = names.get(str(visit.responsible_staff_id or ""), "")
        return (
            f"Planned {day(visit.planned_date)}" + (f" · {who}" if who else "")
        ).strip()
    if state == FOLLOW_UP_DUE and record is not None:
        return f"Last SSA FY{record.fy} ({record.get_verification_status_display().lower()})"
    return STATES[state][1]


def collection_worklist(principal, query) -> dict:
    """{"rows": [...], "counts": {state: n}, "filters": {...}, "page": {...}}.

    `query` is the request's GET (or a dict): district, owner, school_type,
    state, project and `collection_page`. Every filter it renders reaches the
    queryset; a filter with nothing to choose comes back with no options, so
    the view can hide it. With no state chosen the rows are every school that
    needs something (confirmed-this-year schools are counted, not listed).
    """
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole

    fy = get_operational_fy()
    chosen = _clean_query(query)
    schools = collection_schools(principal)
    options = _filter_options(principal, schools)

    filtered = schools
    if chosen["district"] and any(
        o["value"] == chosen["district"] for o in options["districts"]
    ):
        filtered = filtered.filter(district_id=chosen["district"])
    else:
        chosen["district"] = ""
    if chosen["owner"] and any(
        o["value"] == chosen["owner"] for o in options["owners"]
    ):
        filtered = filtered.filter(account_owner_id=chosen["owner"])
    else:
        chosen["owner"] = ""
    if chosen["school_type"] in {o["value"] for o in options["school_types"]}:
        filtered = filtered.filter(school_type=chosen["school_type"])
    else:
        chosen["school_type"] = ""
    if chosen["project"] and any(
        o["value"] == chosen["project"] for o in options["projects"]
    ):
        filtered = filtered.filter(
            id__in=_project_segment(principal, schools)
            .filter(project_id=chosen["project"])
            .values("school_id")
        )
    else:
        chosen["project"] = ""

    annotated = annotate_states(filtered, fy=fy)
    counts = {key: 0 for key in STATES}
    for row in annotated.order_by().values("collection_state").annotate(n=Count("id")):
        counts[row["collection_state"]] = row["n"]

    if chosen["state"] in STATES:
        listed = annotated.filter(collection_state=chosen["state"])
    else:
        chosen["state"] = ""
        listed = annotated.filter(collection_state__in=WORK_STATES)

    getter = query.get if hasattr(query, "get") else dict(query or {}).get
    page = db_page(
        listed.select_related("district").order_by("state_order", "name", "id"),
        getter(PAGE_PARAM),
    )

    page_schools = page["rows"]
    latest, open_visit = _page_details(page_schools, fy)
    names = _owner_names(
        [s.account_owner_id for s in page_schools]
        + [v.responsible_staff_id for v in open_visit.values()]
    )
    can_ask = getattr(principal, "active_role", "") == EdifyRole.IMPACT_ASSESSMENT.value
    rows = []
    for school in page_schools:
        state = school.collection_state
        label, _next, tone, _order = STATES[state]
        owner = names.get(str(school.account_owner_id or ""), "")
        record = latest.get(school.id)
        visit = open_visit.get(school.id)
        actions = [
            {
                "label": "Add SSA",
                "href": f"/ssa/manual/?school_id={school.school_id}",
                "method": "get",
            }
        ]
        if (
            can_ask
            and owner
            and state in (NEVER_ASSESSED, FOLLOW_UP_DUE, VISIT_WITHOUT_SCORES)
        ):
            actions.append(
                {
                    "label": "Ask owner to collect",
                    "href": f"/ia/collection/{school.id}/ask-owner",
                    "method": "post",
                }
            )
        if state in (NEVER_ASSESSED, FOLLOW_UP_DUE, VISIT_WITHOUT_SCORES, RETURNED):
            actions.append(
                {
                    "label": "Request SSA visit",
                    "href": f"/planning/schedule-modal?school_id={school.school_id}",
                    "method": "drawer",
                }
            )
        rows.append(
            {
                "school_pk": school.id,
                "school_id": school.school_id,
                "school": school.name,
                "district": getattr(school.district, "name", "") or "",
                "owner": owner
                or ("Unmatched owner" if school.account_owner_id else "No owner"),
                "school_type": (school.school_type or "").replace("_", " ").title(),
                "state": state,
                "state_label": label,
                "state_tone": tone,
                "detail": _detail(state, record, visit, names),
                "school_url": f"/schools/{school.id}",
                "actions": actions,
            }
        )

    project_counts = _project_counts(principal, filtered)
    return {
        "rows": rows,
        "counts": {
            **counts,
            **project_counts,
            "needs_work": sum(counts[k] for k in WORK_STATES),
        },
        "filters": {"chosen": chosen, "options": options},
        "page": {key: value for key, value in page.items() if key != "rows"},
        "fy": fy,
    }


def _project_counts(principal, schools) -> dict:
    """The special-project segment: enrolments in the filtered population by
    baseline state (apps.projects.baselines keeps "not captured" apart from
    "no confirmed SSA")."""
    from apps.projects import baselines

    enrolments = list(
        _project_segment(principal, schools)
        .filter(baseline_score__isnull=True)
        .select_related("project")
    )
    states = baselines.baseline_states(enrolments) if enrolments else {}
    return {
        "project_enrolments": _project_segment(principal, schools).count(),
        "project_baseline_not_captured": sum(
            1 for s in states.values() if s == baselines.NOT_CAPTURED
        ),
        "project_no_confirmed_ssa": sum(
            1 for s in states.values() if s == baselines.NO_CONFIRMED_SSA
        ),
    }


def collection_tiles(principal, worklist: dict) -> list[dict]:
    """The Collection view's KPI tiles, through the reconciled registry
    (apps.core.metrics.ia_collection_metrics)."""
    from apps.core.metrics import render_precomputed_metric_for_source

    counts = worklist.get("counts") or {}
    unmatched = unmatched_rows_in_reach(principal).count()

    def tile(label, value, helper, tone):
        return render_precomputed_metric_for_source(
            "apps.analytics.ia_collection:collection_tiles",
            label,
            value,
            helper=helper,
            tone=tone,
        )

    return [
        tile(
            "Schools Never Assessed",
            counts.get(NEVER_ASSESSED, 0),
            "no confirmed SSA on record",
            "danger",
        ),
        tile(
            "SSA Follow-up Due",
            counts.get(FOLLOW_UP_DUE, 0),
            f"confirmed before, none in FY{worklist.get('fy', '')}",
            "warning",
        ),
        tile(
            "SSA Awaiting Verification",
            counts.get(PENDING_VERIFICATION, 0) + counts.get(PARTNER_PENDING, 0),
            "schools whose latest scores wait for a verifier",
            "info",
        ),
        tile(
            "Unmatched SSA Import Rows",
            unmatched,
            "imported rows no school in your country matched",
            "warning",
        ),
    ]


def unmatched_rows_in_reach(principal, statuses=("pending", "hold")):
    """Unmatched import rows inside the principal's country: placed by who
    uploaded the batch, else by the school the importer suggested. A legacy
    row with neither belongs to no country and is read only by an unbounded
    reader. `statuses=None` keeps every status (the queue's own filter)."""
    from apps.core.scoping import country_bound, country_user_ids, resolve_user_scope
    from apps.schools.models import UnmatchedSSARecord

    scope = resolve_user_scope(principal)
    rows = UnmatchedSSARecord.objects.all()
    if statuses:
        rows = rows.filter(status__in=statuses)
    if country_bound(scope):
        rows = rows.filter(
            Q(batch__uploaded_by__in=country_user_ids(scope))
            | Q(suggested_school__region__country=scope.country)
        )
    return rows


__all__ = [
    "STATES",
    "WORK_STATES",
    "annotate_states",
    "collection_schools",
    "collection_tiles",
    "collection_worklist",
    "db_page",
    "state_counts",
    "unmatched_rows_in_reach",
]
