"""What changed at a cluster's schools: enrolment, learning, loans, stories.

Owner brief, 2026-10-08 (Cluster Management): "Student impact ... Enrollment
baseline, current, growth %", "Exam performance", "Loan Program integration",
"Most Significant Change Story". Each is a read of the record that already
owns the figure — ``SchoolEnrollmentHistory``, ``LearningAssessmentResult``,
the loan register through ``scoped_loans`` (so a reader sees the loans the
register itself would show them, and no others), and
``MostSignificantChangeStory`` — grouped by the school's cluster.

Growth is like for like: a year-on-year figure counts only the schools that
have a figure in both years, and says how many that is. Adding the totals of
two different sets of schools would report a new school's arrival as growth.

Every ``*_by_cluster`` read answers for many clusters in the same queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .profile_insights import member_schools


def _growth_pct(before, after) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return round(100 * (after - before) / before, 1)


# ── Enrolment ────────────────────────────────────────────────────────────────


@dataclass
class EnrolmentSummary:
    fy: str
    previous_fy: str
    rows: list[dict] = field(default_factory=list)
    compared: int = 0
    before: int = 0
    after: int = 0
    latest_total: int = 0
    with_latest: int = 0

    @property
    def change(self) -> int | None:
        return (self.after - self.before) if self.compared else None

    @property
    def growth_pct(self) -> float | None:
        return _growth_pct(self.before, self.after) if self.compared else None

    @property
    def school_count(self) -> int:
        return len(self.rows)


def enrolment_by_cluster(
    cluster_ids, *, fy: str, members=None
) -> dict[str, EnrolmentSummary]:
    """Each cluster's enrolment in fiscal year ``fy`` against the year before.

    The yearly figure is the one recorded when the school's SSA visit was
    completed (``SchoolEnrollmentHistory``); the latest figure is the school
    record's own. Two queries: the schools and the yearly figures.
    """
    from apps.schools.models import School, SchoolEnrollmentHistory

    cluster_ids = list(cluster_ids)
    fy = str(fy)
    previous_fy = str(int(fy) - 1)
    members = members if members is not None else member_schools(cluster_ids)
    school_ids = [s["id"] for rows in members.values() for s in rows]
    latest = {
        row["id"]: row
        for row in School.objects.filter(id__in=school_ids).values(
            "id", "enrollment", "last_enrollment_date"
        )
    }
    yearly: dict[str, dict[str, int]] = {}
    for school_id, year, enrolment in SchoolEnrollmentHistory.objects.filter(
        school_id__in=school_ids, fy__in=[fy, previous_fy]
    ).values_list("school_id", "fy", "enrollment"):
        yearly.setdefault(school_id, {})[str(year)] = enrolment

    out = {}
    for cid in cluster_ids:
        summary = EnrolmentSummary(fy=fy, previous_fy=previous_fy)
        for school in members.get(cid, []):
            figures = yearly.get(school["id"], {})
            before, after = figures.get(previous_fy), figures.get(fy)
            now = latest.get(school["id"], {})
            if before is not None and after is not None:
                summary.compared += 1
                summary.before += before
                summary.after += after
            if now.get("enrollment"):
                summary.latest_total += now["enrollment"]
                summary.with_latest += 1
            summary.rows.append(
                {
                    "id": school["id"],
                    "code": school["school_id"] or "",
                    "name": school["name"],
                    "before": before,
                    "after": after,
                    "change": (
                        after - before
                        if before is not None and after is not None
                        else None
                    ),
                    "growth_pct": _growth_pct(before, after),
                    "latest": now.get("enrollment"),
                    "latest_on": now.get("last_enrollment_date"),
                }
            )
        out[cid] = summary
    return out


def cluster_enrolment(cluster, *, fy: str) -> EnrolmentSummary:
    return enrolment_by_cluster([cluster.id], fy=fy)[cluster.id]


# ── Learning results ─────────────────────────────────────────────────────────


@dataclass
class LearningSummary:
    fy: str
    previous_fy: str
    rows: list[dict] = field(default_factory=list)
    compared: int = 0
    before: float | None = None
    after: float | None = None
    improved: int = 0
    declined: int = 0
    unchanged: int = 0

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return round(self.after - self.before, 1)

    @property
    def school_count(self) -> int:
        return len(self.rows)


def _school_scores(school_ids, years) -> dict[str, dict[str, dict]]:
    """{school: {fy: {"pct", "learners", "results"}}} from confirmed results.

    A school's score for a year is the mean of its class results as a share of
    the marks available, weighted by the learners tested, so a class of 80
    counts for more than a class of 8. A result with no maximum mark has no
    share to take and is left out.
    """
    from apps.core.enums import VerificationStatus
    from apps.impact.models import LearningAssessmentResult

    totals: dict[tuple[str, str], list[float]] = {}
    for row in LearningAssessmentResult.objects.filter(
        school_id__in=list(school_ids),
        fy__in=list(years),
        deleted_at__isnull=True,
        verification_status=VerificationStatus.CONFIRMED.value,
        mean_score__isnull=False,
        max_score__gt=0,
    ).values("school_id", "fy", "mean_score", "max_score", "learners_tested"):
        weight = row["learners_tested"] or 0
        if not weight:
            continue
        share = float(row["mean_score"]) / float(row["max_score"]) * 100
        bucket = totals.setdefault((row["school_id"], str(row["fy"])), [0.0, 0.0, 0])
        bucket[0] += share * weight
        bucket[1] += weight
        bucket[2] += 1
    scores: dict[str, dict[str, dict]] = {}
    for (school_id, year), (weighted, learners, results) in totals.items():
        scores.setdefault(school_id, {})[year] = {
            "pct": round(weighted / learners, 1),
            "learners": int(learners),
            "results": results,
        }
    return scores


def learning_by_cluster(
    cluster_ids, *, fy: str, members=None
) -> dict[str, LearningSummary]:
    """Each cluster's confirmed learning results, ``fy`` against the year before.

    One query for the results. A school is compared where it has a confirmed
    result in both years; the cluster's figure is the mean of those schools.
    """
    cluster_ids = list(cluster_ids)
    fy = str(fy)
    previous_fy = str(int(fy) - 1)
    members = members if members is not None else member_schools(cluster_ids)
    school_ids = [s["id"] for rows in members.values() for s in rows]
    scores = _school_scores(school_ids, [fy, previous_fy]) if school_ids else {}

    out = {}
    for cid in cluster_ids:
        summary = LearningSummary(fy=fy, previous_fy=previous_fy)
        before_values, after_values = [], []
        for school in members.get(cid, []):
            years = scores.get(school["id"], {})
            before = (years.get(previous_fy) or {}).get("pct")
            after = (years.get(fy) or {}).get("pct")
            change = (
                round(after - before, 1)
                if before is not None and after is not None
                else None
            )
            if change is not None:
                summary.compared += 1
                before_values.append(before)
                after_values.append(after)
                if change > 0:
                    summary.improved += 1
                elif change < 0:
                    summary.declined += 1
                else:
                    summary.unchanged += 1
            summary.rows.append(
                {
                    "id": school["id"],
                    "code": school["school_id"] or "",
                    "name": school["name"],
                    "before": before,
                    "after": after,
                    "change": change,
                    "learners": (years.get(fy) or {}).get("learners"),
                    "results": (years.get(fy) or {}).get("results", 0),
                }
            )
        if before_values:
            summary.before = round(sum(before_values) / len(before_values), 1)
            summary.after = round(sum(after_values) / len(after_values), 1)
        out[cid] = summary
    return out


def cluster_learning(cluster, *, fy: str) -> LearningSummary:
    return learning_by_cluster([cluster.id], fy=fy)[cluster.id]


# ── Loans ────────────────────────────────────────────────────────────────────

#: Loans that put money in a school: disbursed, being repaid, or repaid.
_FUNDED = ("disbursed", "active", "repaid")


@dataclass
class LoanSummary:
    rows: list[dict] = field(default_factory=list)
    schools: set = field(default_factory=set)
    funded_schools: set = field(default_factory=set)
    disbursed: Decimal = Decimal("0")
    by_status: dict = field(default_factory=dict)
    edtech: int = 0

    @property
    def loan_count(self) -> int:
        return len(self.rows)

    @property
    def school_count(self) -> int:
        return len(self.schools)

    @property
    def funded_school_count(self) -> int:
        return len(self.funded_schools)

    @property
    def status_counts(self) -> list[tuple[str, int]]:
        return sorted(self.by_status.items())


def loans_by_cluster(cluster_ids, principal, *, members=None) -> dict[str, LoanSummary]:
    """Each cluster's school loans, as far as ``principal`` may read them.

    The loan register decides who reads a loan
    (``business_transformation.services.scoped_loans``): a reader the register
    shows nothing to is shown nothing here. One query.
    """
    from apps.business_transformation.services import scoped_loans

    cluster_ids = list(cluster_ids)
    members = members if members is not None else member_schools(cluster_ids)
    school_cluster = {s["id"]: cid for cid, rows in members.items() for s in rows}
    codes = {s["id"]: s["school_id"] or "" for rows in members.values() for s in rows}
    out = {cid: LoanSummary() for cid in cluster_ids}
    if not school_cluster:
        return out
    loans = (
        scoped_loans(principal)
        .filter(school_id__in=list(school_cluster), deleted_at__isnull=True)
        .exclude(status="canceled")
        .order_by("school__name", "-disbursement_date", "-created_at")
    )
    for loan in loans:
        summary = out[school_cluster[loan.school_id]]
        funded = loan.status in _FUNDED
        summary.schools.add(loan.school_id)
        if funded:
            summary.funded_schools.add(loan.school_id)
            summary.disbursed += loan.disbursed_amount or Decimal("0")
        label = loan.get_status_display()
        summary.by_status[label] = summary.by_status.get(label, 0) + 1
        if loan.purpose_id and loan.purpose.is_edtech:
            summary.edtech += 1
        summary.rows.append(
            {
                "id": loan.id,
                "school_pk": loan.school_id,
                "code": codes.get(loan.school_id, ""),
                "name": loan.school.name,
                "lender": loan.mfi.name if loan.mfi_id else "",
                "purpose": loan.purpose.label if loan.purpose_id else "",
                "approved": loan.approved_amount,
                "disbursed": loan.disbursed_amount,
                "currency": loan.currency,
                "disbursed_on": loan.disbursement_date,
                "status": loan.status,
                "status_label": label,
                "tone": {
                    "repaid": "success",
                    "active": "info",
                    "disbursed": "info",
                    "defaulted": "danger",
                }.get(loan.status, "neutral"),
            }
        )
    return out


def cluster_loans(cluster, principal) -> LoanSummary:
    return loans_by_cluster([cluster.id], principal)[cluster.id]


# ── Most Significant Change stories ──────────────────────────────────────────


@dataclass
class StorySummary:
    rows: list[dict] = field(default_factory=list)
    approved: int = 0
    waiting: int = 0

    @property
    def story_count(self) -> int:
        return len(self.rows)


def stories_by_cluster(
    cluster_ids, *, fy: str | None = None, members=None
) -> dict[str, StorySummary]:
    """Each cluster's change stories: those written about one of its schools
    and those filed against the cluster itself.

    Drafts are their author's own and are not listed. Only an approved story
    counts as evidence (``targets.MostSignificantChangeStory``), so the
    summary keeps approved apart from those still with a reviewer. Two
    queries: the stories and their authors' names.
    """
    from django.db.models import Q

    from apps.accounts.models import User
    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_fy_date_range
    from apps.targets.models import MostSignificantChangeStory, MSCSStatus

    cluster_ids = list(cluster_ids)
    members = members if members is not None else member_schools(cluster_ids)
    school_cluster = {s["id"]: cid for cid, rows in members.items() for s in rows}
    codes = {s["id"]: s["school_id"] or "" for rows in members.values() for s in rows}
    out = {cid: StorySummary() for cid in cluster_ids}
    if not cluster_ids:
        return out
    stories = (
        MostSignificantChangeStory.objects.filter(
            Q(cluster_id__in=cluster_ids) | Q(school_id__in=list(school_cluster))
        )
        .exclude(status=MSCSStatus.DRAFT)
        .select_related("school")
        .order_by("-story_date", "-created_at")
    )
    if fy:
        start, end = get_fy_date_range(str(fy))
        stories = stories.filter(
            story_date__gte=start.date(), story_date__lt=end.date()
        )
    stories = list(stories)
    names = dict(
        User.objects.filter(id__in={s.user_id for s in stories}).values_list(
            "id", "name"
        )
    )
    areas = dict(SsaIntervention.choices)
    for story in stories:
        cid = (
            story.cluster_id
            if story.cluster_id in out
            else school_cluster.get(story.school_id)
        )
        if cid not in out:
            continue
        summary = out[cid]
        if story.status == MSCSStatus.APPROVED:
            summary.approved += 1
        elif story.status in (MSCSStatus.SUBMITTED, MSCSStatus.RETURNED):
            summary.waiting += 1
        summary.rows.append(
            {
                "id": story.id,
                "title": story.title,
                "date": story.story_date,
                "school_pk": story.school_id,
                "code": codes.get(story.school_id)
                or (story.school.school_id if story.school_id else ""),
                "school": story.school.name if story.school_id else "",
                "author": names.get(story.user_id, ""),
                "area": areas.get(story.intervention, ""),
                "status": story.status,
                "status_label": story.get_status_display(),
                "tone": {
                    MSCSStatus.APPROVED: "success",
                    MSCSStatus.SUBMITTED: "info",
                    MSCSStatus.RETURNED: "warning",
                    MSCSStatus.REJECTED: "danger",
                }.get(story.status, "neutral"),
                "has_evidence": bool(story.evidence_uri),
            }
        )
    return out


def cluster_stories(cluster, *, fy: str | None = None) -> StorySummary:
    return stories_by_cluster([cluster.id], fy=fy)[cluster.id]


__all__ = [
    "EnrolmentSummary",
    "LearningSummary",
    "LoanSummary",
    "StorySummary",
    "cluster_enrolment",
    "cluster_learning",
    "cluster_loans",
    "cluster_stories",
    "enrolment_by_cluster",
    "learning_by_cluster",
    "loans_by_cluster",
    "stories_by_cluster",
]
