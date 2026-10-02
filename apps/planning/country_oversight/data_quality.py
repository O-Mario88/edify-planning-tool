"""Planning Oversight Data Quality — the checks behind the figures.

Impact Assessment holds data-quality authority, so the page gives IA (and the
Country Director) a compact queue of every inconsistency that could make a
planning figure wrong: a school in two families or with two owners, work that
fills no slot, a handover with no slot, a session with no roster, a closed
school with work on it, a school in several clusters, and a total that does not
reconcile. Each check says what it means, how many records it found, and shows
the first of them with a link to where the record is corrected.

Nothing here edits anything. A finding is corrected through the workflow that
owns the record — the school profile, the Staff Setup Queue, the Core Schools
package repair, the cluster register — never from the oversight table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.planning.country_oversight import policy
from apps.planning.country_oversight.coverage import (
    P_SCHED_T,
    _partner_totals,
    duplicate_reasons,
)
from apps.planning.country_oversight.hierarchy import IDX, add_into, blank
from apps.planning.country_oversight.requirements import NO_LEAD_KEY, NO_OWNER_KEY

SAMPLE = 10


@dataclass
class Check:
    key: str
    label: str
    meaning: str
    count: int = 0
    severity: str = "info"  # "info" | "warning" | "critical"
    samples: list = field(default_factory=list)
    correct_at: str = ""


def _school_sample(school) -> dict:
    return {
        "label": school.name,
        "detail": school.code,
        "url": f"/schools/{school.code}" if school.code else "",
    }


def checks(dataset, tree) -> list[Check]:
    """Every check over the reader's dataset, in the order IA works them."""
    facts = dataset.facts
    owners = dataset.owners
    fy = dataset.window.fy
    results: list[Check] = []

    # 1. No governed family.
    unmapped = [s for s in facts.values() if not s.is_governed]
    reasons = sorted({s.school_type or "blank" for s in unmapped})
    results.append(
        Check(
            "unmapped_family",
            "School type with no planning rule",
            " ".join(
                policy.PENDING_FAMILY_DECISIONS.get(
                    t, f"'{t}' is not a school type the planning rulebook knows."
                )
                for t in reasons
            )
            or "Every school's type is one the planning rulebook knows.",
            len(unmapped),
            "warning" if unmapped else "info",
            [_school_sample(s) for s in unmapped[:SAMPLE]],
            "Product-owner decision, then the school profile",
        )
    )

    # 2. Several active owners, or an owner the assignment table disagrees with.
    from apps.accounts.models import StaffSchoolAssignment

    school_ids = list(facts)
    multi = (
        StaffSchoolAssignment.objects.filter(school_id__in=school_ids)
        .values("school_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by()
    )
    multi_ids = [row["school_id"] for row in multi]
    mismatched = []
    owner_ids_of: dict[str, set] = {}
    for school_id, staff_id, user_id in StaffSchoolAssignment.objects.filter(
        school_id__in=school_ids
    ).values_list("school_id", "staff_id", "staff__user_id"):
        owner_ids_of.setdefault(school_id, set()).update({staff_id, user_id})
    for school in facts.values():
        linked = owner_ids_of.get(school.id)
        if school.raw_owner_id and linked and school.raw_owner_id not in linked:
            mismatched.append(school)
    several = {pk for pk in multi_ids} | {s.id for s in mismatched}
    samples = [facts[pk] for pk in list(several)[:SAMPLE] if pk in facts]
    lead_in_team = []
    for school in facts.values():
        owner = owners.get(school.owner_key)
        linked = owner_ids_of.get(school.id) or set()
        if owner and owner.kind == "cceo" and owner.lead_key in linked:
            lead_in_team.append(school)
    results.append(
        Check(
            "several_owners",
            "School with several active owners",
            "The account owner and the staff-school assignment disagree, or more "
            "than one person holds the school. The account owner is counted.",
            len(several),
            "critical" if several else "info",
            [_school_sample(s) for s in samples],
            "School ownership transfer (Admin or Impact Assessment)",
        )
    )
    results.append(
        Check(
            "lead_in_personal_scope",
            "PL team school appearing in PL personal scope",
            "A Programme Lead holds an assignment to a school their CCEO owns. "
            "The school stays in the CCEO's portfolio; the Lead's personal "
            "figures never include it.",
            len(lead_in_team),
            "warning" if lead_in_team else "info",
            [_school_sample(s) for s in lead_in_team[:SAMPLE]],
            "School ownership transfer",
        )
    )

    # 3. Nobody holds the school, or somebody who cannot hold a portfolio.
    no_owner = [
        s for s in facts.values() if s.is_governed and s.owner_key == NO_OWNER_KEY
    ]
    results.append(
        Check(
            "no_owner",
            "School with no account owner",
            "Its Core staff slots count as a capacity deficit and its one "
            "client-rule visit falls to Partners until somebody holds it.",
            len(no_owner),
            "critical" if no_owner else "info",
            [_school_sample(s) for s in no_owner[:SAMPLE]],
            "Staff Setup Queue",
        )
    )
    odd_owner = [
        s
        for s in facts.values()
        if s.is_governed
        and s.owner_key != NO_OWNER_KEY
        and owners.get(s.owner_key) is not None
        and (owners[s.owner_key].kind == "other" or not owners[s.owner_key].active)
    ]
    results.append(
        Check(
            "non_portfolio_owner",
            "School held by an inactive person or a non-portfolio role",
            "Only CCEOs and Programme Leads carry staff visit capacity; any other "
            "holder's schools show their Core staff slots as a deficit.",
            len(odd_owner),
            "warning" if odd_owner else "info",
            [
                {
                    **_school_sample(s),
                    "detail": f"{s.code} · {owners[s.owner_key].name} ({owners[s.owner_key].role or 'no role'})",
                }
                for s in odd_owner[:SAMPLE]
            ],
            "School ownership transfer",
        )
    )

    # 4. Officers with no Programme Lead, or with several.
    officers = [o for o in owners.values() if o.kind == "cceo"]
    no_lead = [o for o in officers if o.lead_key == NO_LEAD_KEY]
    several_leads = [o for o in officers if len(o.lead_keys) > 1]
    results.append(
        Check(
            "cceo_lead_line",
            "CCEO with no Programme Lead, or with several",
            "A CCEO's schools sit under the Lead they report to directly. With "
            "none they sit under 'No Programme Lead'; with several, the first "
            "by name is used.",
            len(no_lead) + len(several_leads),
            "warning" if (no_lead or several_leads) else "info",
            [
                {
                    "label": o.name,
                    "detail": "No Programme Lead",
                    "url": f"/staff/{o.key}",
                }
                for o in no_lead[:SAMPLE]
            ]
            + [
                {
                    "label": o.name,
                    "detail": f"{len(o.lead_keys)} Programme Leads",
                    "url": f"/staff/{o.key}",
                }
                for o in several_leads[:SAMPLE]
            ],
            "Staff supervisor assignment",
        )
    )

    # 5. Visit or training at a Core school that fills no package slot.
    from apps.core_schools.package_credit import (
        uncredited_package_work,
        unreserved_core_handovers,
    )

    uncredited = uncredited_package_work(fy=fy).filter(school_id__in=school_ids)
    results.append(
        Check(
            "unlinked_core_work",
            "Visit activity not linked to an eligible slot",
            "Core-school visits and trainings that fill no package slot (V1–V4, "
            "T1–T4). They still count here by type, but the package does not "
            "know them.",
            uncredited.count(),
            "warning",
            [
                {
                    "label": a.school.name if a.school_id else a.id,
                    "detail": f"{a.activity_type} · {a.planned_date or 'undated'}",
                    "url": f"/team-planning-oversight/detail?activity_id={a.id}",
                }
                for a in uncredited[:SAMPLE]
            ],
            "manage.py repair_core_data / package repair",
        )
    )
    handovers = [h for h in unreserved_core_handovers() if h.school_id in facts]
    results.append(
        Check(
            "handover_without_slot",
            "Partner assignment with no slot",
            "An open Core-school handover that holds no package slot.",
            len(handovers),
            "warning" if handovers else "info",
            [
                {
                    "label": h.school.name if h.school_id else h.id,
                    "detail": getattr(h.partner, "name", ""),
                    "url": "/partner-oversight/",
                }
                for h in handovers[:SAMPLE]
            ],
            "Partner Oversight",
        )
    )

    # 6. More planned work than slots: the extra work claims nothing.
    over = []
    twice = []
    for school in facts.values():
        if not school.is_governed:
            continue
        requirement = policy.requirement_for(school.family)
        partner_totals, _ = _partner_totals(school, None)
        if school.family == policy.CORE_FAMILY:
            beyond = max(0, partner_totals[P_SCHED_T] - requirement.partner_visit_slots)
            beyond += max(0, school.staff[2] - requirement.staff_visit_slots)
        elif school.family == policy.CLIENT_FAMILY:
            beyond = max(0, school.staff[2] + partner_totals[P_SCHED_T] - 1)
        else:
            # Outreach only: whatever counted visit was planned claims nothing.
            beyond = school.staff[2] + partner_totals[P_SCHED_T]
        if beyond:
            over.append((beyond, school))
        reasons = duplicate_reasons(school)
        if reasons:
            twice.append((reasons, school))
    over.sort(key=lambda pair: -pair[0])
    duplicate_slot_links = _duplicate_slot_links(school_ids)
    results.append(
        Check(
            "over_claimed",
            "Two activities claiming the same slot",
            "Schools with more planned visits than visit slots, and package "
            "slots linked to the same activity twice. Each slot is counted "
            "once; the extra work claims nothing.",
            len(over) + duplicate_slot_links,
            "warning" if over or duplicate_slot_links else "info",
            [
                {
                    **_school_sample(school),
                    "detail": f"{school.code} · {beyond} beyond the slots",
                }
                for beyond, school in over[:SAMPLE]
            ],
            "The school's plan (cancel the duplicate)",
        )
    )
    from apps.planning.country_oversight import rules

    results.append(
        Check(
            "planned_twice",
            "School planned twice",
            "A Client, Core Trained or Core Graduate school is visited by staff "
            "or by a Partner, never both, and once for each kind of visit; a "
            "Core school takes two staff and two Partner visits. These carry "
            "more. Each is counted once as coverage, and the Schools Planned "
            "Twice table lists every plan at every one of them.",
            len(twice),
            "warning" if twice else "info",
            [
                {
                    **_school_sample(school),
                    "detail": f"{school.code} · "
                    + "; ".join(rules.DUPLICATE_LABELS[r] for r in reasons),
                }
                for reasons, school in twice[:SAMPLE]
            ],
            "The school's plan (cancel the duplicate)",
        )
    )

    # 7. Partner work with no handover behind it.
    from apps.activities.models import Activity, ClusterActivityAttendance

    orphan_partner = (
        Activity.objects.filter(
            fy=str(fy),
            deleted_at__isnull=True,
            delivery_type="partner",
            status__in=policy.PLANNED_STATES,
            school_id__in=school_ids,
            originating_partner_assignment__isnull=True,
        )
        .select_related("school")
        .order_by("planned_date")
    )
    results.append(
        Check(
            "schedule_without_assignment",
            "Partner schedule without assignment",
            "Partner-delivered visits with no handover recorded behind them. "
            "They count as Partner-scheduled; the handover history is missing.",
            orphan_partner.count(),
            "info",
            [
                {
                    "label": a.school.name if a.school_id else a.id,
                    "detail": f"{a.activity_type} · {a.planned_date or ''}",
                    "url": f"/team-planning-oversight/detail?activity_id={a.id}",
                }
                for a in orphan_partner[:SAMPLE]
            ],
            "Partner Oversight",
        )
    )

    # 8. Cluster sessions with no planned roster: they cover no school.
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES

    sessions = (
        Activity.objects.filter(
            fy=str(fy),
            deleted_at__isnull=True,
            status__in=policy.PLANNED_STATES,
            cluster__isnull=False,
            activity_type__in=(*CLUSTER_MEETING_TYPES, *TRAINING_TYPES),
        )
        .annotate(
            invited=Count(
                "school_attendance", filter=Q(school_attendance__invited=True)
            )
        )
        .filter(invited=0)
        .select_related("cluster")
        .order_by("planned_date")
    )
    results.append(
        Check(
            "session_without_roster",
            "Training or cluster meeting with no planned school roster",
            "A cluster session covers only the schools on its planned roster, "
            "never the whole cluster — so these cover no school at all.",
            sessions.count(),
            "warning",
            [
                {
                    "label": getattr(a.cluster, "name", "") or a.id,
                    "detail": f"{a.activity_type} · {a.planned_date or ''}",
                    "url": f"/team-planning-oversight/detail?activity_id={a.id}",
                }
                for a in sessions[:SAMPLE]
            ],
            "Cluster Oversight (the session's invitations)",
        )
    )
    walk_ins = ClusterActivityAttendance.objects.filter(
        activity__fy=str(fy),
        activity__deleted_at__isnull=True,
        invited=False,
        attended=True,
        school_id__in=school_ids,
    )
    results.append(
        Check(
            "attended_not_invited",
            "Cluster meeting counting schools not on the roster",
            "Schools recorded as attending a session they were not invited to. "
            "They are not counted as planned coverage.",
            walk_ins.count(),
            "info",
            [],
            "Cluster Oversight",
        )
    )

    # 9. Closed schools with planned work — outside the denominator.
    closed_with_work = _closed_with_work(dataset)
    results.append(
        Check(
            "closed_with_plans",
            "Closed school in the portfolio",
            "Closed schools are never in the denominator; these still carry "
            "planned work for the year, which is counted nowhere.",
            len(closed_with_work),
            "warning" if closed_with_work else "info",
            closed_with_work[:SAMPLE],
            "Closed Schools",
        )
    )

    # 10. Several clusters, or a cluster that is not active.
    from apps.clusters.models import SchoolClusterAssignment

    projection = {}
    for school_id, cluster_id in SchoolClusterAssignment.objects.filter(
        school_id__in=school_ids
    ).values_list("school_id", "cluster_id"):
        projection.setdefault(school_id, set()).add(cluster_id)
    cluster_issues = []
    for school in facts.values():
        linked = projection.get(school.id, set())
        if len(linked) > 1 or (
            school.raw_cluster_id and linked and school.raw_cluster_id not in linked
        ):
            cluster_issues.append((school, "several cluster records"))
        elif school.raw_cluster_id and school.cluster_id is None:
            cluster_issues.append((school, "its cluster is not active"))
        elif school.cluster_status == "clustered" and not school.raw_cluster_id:
            cluster_issues.append((school, "marked clustered with no cluster"))
    results.append(
        Check(
            "several_clusters",
            "School with several active clusters",
            "Counted once, by its canonical cluster, and only when that cluster "
            "is active.",
            len(cluster_issues),
            "warning" if cluster_issues else "info",
            [
                {**_school_sample(school), "detail": f"{school.code} · {why}"}
                for school, why in cluster_issues[:SAMPLE]
            ],
            "Clusters",
        )
    )

    # 11. Capacity the requirement exceeds — shown as a deficit, never moved.
    deficits = []
    for lead in tree.leads:
        for owner in lead.owners:
            if owner.tally.deficit:
                deficits.append(owner)
    results.append(
        Check(
            "capacity_deficit",
            "Visit requirement exceeding capacity",
            "Core staff slots beyond the holder's annual staff ceiling. They stay "
            "staff slots and show as a deficit until reassigned or resolved.",
            len(deficits),
            "warning" if deficits else "info",
            [
                {
                    "label": owner.label
                    if owner.kind != "pl_personal"
                    else f"{owner.name} (personal)",
                    "detail": f"{owner.tally.deficit:,} slots over a {owner.ceiling:,} ceiling",
                    "url": f"/staff/{owner.key}" if owner.key != NO_OWNER_KEY else "",
                }
                for owner in deficits[:SAMPLE]
            ],
            "Staffing decision (Country Director)",
        )
    )

    # 12. Totals that must reconcile.
    mismatches = _reconciliation(tree)
    results.append(
        Check(
            "reconciliation",
            "Totals that do not reconcile",
            "The country total must equal the sum of its Programme Leads, and "
            "each Lead the sum of their CCEOs and personal delivery.",
            len(mismatches),
            "critical" if mismatches else "info",
            [{"label": text, "detail": "", "url": ""} for text in mismatches[:SAMPLE]],
            "Engineering",
        )
    )

    # 13. Possible duplicate records, still counted.
    count, samples = _potential_duplicates(school_ids)
    results.append(
        Check(
            "potential_duplicates",
            "Possible duplicate school records",
            "Flagged as possible duplicates and still counted; confirmed and "
            "merged duplicates are already excluded.",
            count,
            "info",
            samples,
            "School Directory duplicate review",
        )
    )
    return results


def _duplicate_slot_links(school_ids) -> int:
    from apps.core_schools.models import CoreActivitySlot
    from apps.schools.models import School

    codes = School.objects.filter(id__in=school_ids).values("school_id")
    return (
        CoreActivitySlot.objects.filter(activity_id__isnull=False, school_id__in=codes)
        .values("activity_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by()
        .count()
    )


def _potential_duplicates(school_ids) -> tuple[int, list]:
    from apps.schools.models import School

    flagged = School.objects.filter(id__in=school_ids, duplicate_status="potential")
    samples = [
        {"label": name, "detail": code, "url": f"/schools/{code}"}
        for name, code in flagged.values_list("name", "school_id")[:SAMPLE]
    ]
    return flagged.count(), samples


def _closed_with_work(dataset) -> list[dict]:
    from apps.activities.models import Activity
    from apps.schools.lifecycle_models import CLOSED_STATUSES

    rows = (
        Activity.objects.filter(
            fy=dataset.window.fy,
            deleted_at__isnull=True,
            status__in=policy.PLANNED_STATES,
            school__operational_status__in=[str(s) for s in CLOSED_STATUSES],
        )
        .values("school_id", "school__name", "school__school_id")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return [
        {
            "label": row["school__name"],
            "detail": f"{row['school__school_id']} · {row['n']} planned",
            "url": f"/schools/{row['school__school_id']}",
        }
        for row in rows[:50]
    ]


def _reconciliation(tree) -> list[str]:
    problems = []
    total = blank()
    for lead in tree.leads:
        add_into(total, lead.tally.values)
        members = blank()
        for owner in lead.owners:
            add_into(members, owner.tally.values)
        if members != lead.tally.values:
            problems.append(f"{lead.name}: the Lead row is not the sum of its people")
    country = list(tree.country.values)
    country[IDX["unmapped_schools"]] = total[IDX["unmapped_schools"]]
    if total != country:
        problems.append("Country: the total is not the sum of its Programme Leads")
    return problems


def summary(user, filters) -> dict:
    """The queue, for the drawer: every check and how many are open."""
    from apps.planning.country_oversight.service import dataset_for, fold

    dataset = dataset_for(user, filters.window)
    tree = fold(dataset, filters.without_school_filters())
    found = checks(dataset, tree)
    return {
        "checks": found,
        "open": sum(1 for check in found if check.count and check.severity != "info"),
        "as_of": dataset.as_of,
        "built_at": dataset.built_at,
    }
