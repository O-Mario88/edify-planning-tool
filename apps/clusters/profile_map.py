"""Where every figure of the Cluster Profile comes from.

Owner's brief, 2026-10-10: "For every profile metric, create an explicit
mapping: Metric → Authoritative source → Filter → Aggregation → Drilldown
destination ... This documentation should exist in the implementation."

`METRICS` is that mapping, one entry per figure of the profile's Executive
Summary and of each section. It is drawn on the profile's Sources tab, so the
reader of a number can see which records it was counted from, and it is
checked by `test_cluster_page_and_profile`: every entry's `opens` is a tab of
the profile or a record list of `apps.analytics.profile_records.RECORDS`, so
no entry can describe a figure that opens nothing.

Nothing here is computed and nothing is stored: the figures themselves are
read by `apps.analytics.profile_intelligence` over the cluster's schools
(`cluster_scope`: the operating schools whose `cluster_id` is this cluster —
membership, never the school's district, so a cluster approved for a
neighbouring district keeps those schools) and by `apps.clusters`'
`profile_insights`, `outcomes`, `interventions` and `scores`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["METRICS", "Metric", "sections"]

_MEMBERS = "School belongs to the cluster (School.cluster_id), operating schools"


@dataclass(frozen=True)
class Metric:
    section: str
    figure: str
    source: str
    filters: str
    aggregation: str
    #: Where the figure opens: ``tab:<key>`` or ``what:<record list>``.
    opens: str
    drilldown: str


METRICS: tuple[Metric, ...] = (
    # ── Executive Summary ────────────────────────────────────────────────
    Metric(
        "Executive Summary",
        "Schools",
        "schools.School",
        _MEMBERS,
        "Count of schools",
        "tab:school_ssa",
        "Cluster → Schools → School profile",
    ),
    Metric(
        "Executive Summary",
        "SSA Score",
        "ssa.SsaRecord, ssa.SsaScore",
        f"{_MEMBERS}; FY = the year chosen; confirmed record; the latest "
        "record of the year for each school",
        "Mean of each intervention's school scores, then the mean of the "
        "interventions (ssa.year_comparison.intervention_comparison); the "
        "baseline is the same reading of the year before",
        "tab:ssa",
        "Cluster → SSA Performance → Schools → School profile",
    ),
    Metric(
        "Executive Summary",
        "Teachers Trained",
        "activities.Activity.teachers_attended, "
        "activities.ClusterActivityAttendance.teachers",
        f"{_MEMBERS}; FY; completed trainings (in school), and the schools' "
        "register lines at completed group trainings",
        "Sum of teachers recorded",
        "what:teachers_trained",
        "Cluster → the trainings and register lines that recorded them",
    ),
    Metric(
        "Executive Summary",
        "School Leaders Trained",
        "activities.Activity.leaders_attended, "
        "activities.ClusterActivityAttendance.leaders",
        f"{_MEMBERS}; FY; completed trainings and group-training registers",
        "Sum of school leaders recorded",
        "what:leaders_trained",
        "Cluster → the trainings and register lines that recorded them",
    ),
    Metric(
        "Executive Summary",
        "Students Impacted",
        "schools.School.enrollment",
        _MEMBERS,
        "Sum of the enrolment on each school's record",
        "what:enrolment",
        "Cluster → Enrolment by school → School profile",
    ),
    Metric(
        "Executive Summary",
        "Enrolment Growth",
        "schools.SchoolEnrollmentHistory (the enrolment of each completed year)",
        f"{_MEMBERS}; schools with a figure in the FY and in the year before",
        "Like for like: (this year − last year) ÷ last year, over the "
        "schools with both (clusters.outcomes.enrolment_by_cluster)",
        "what:enrolment_growth",
        "Cluster → Students → each school's two years",
    ),
    Metric(
        "Executive Summary",
        "Exam Performance",
        "impact.LearningAssessmentResult (clusters.outcomes.learning_by_cluster)",
        f"{_MEMBERS}; schools with results in the FY and in the year before",
        "Mean score this year of the schools compared; the change is this "
        "year's mean less last year's",
        "what:learning",
        "Cluster → Learning Results → each school's results",
    ),
    Metric(
        "Executive Summary",
        "Training Attendance",
        "activities.ClusterActivityAttendance",
        f"{_MEMBERS}; FY; completed group and online trainings",
        "Schools recorded as attending ÷ schools invited",
        "tab:work",
        "Cluster → Training By Channel → sessions → register",
    ),
    Metric(
        "Executive Summary",
        "Meeting Attendance",
        "activities.ClusterActivityAttendance",
        f"{_MEMBERS}; FY; cluster meetings held",
        "Invitations attended ÷ invitations",
        "tab:attendance",
        "Cluster → Meetings & Attendance → sessions → schools",
    ),
    Metric(
        "Executive Summary",
        "MSCS",
        "targets.MostSignificantChangeStory",
        f"{_MEMBERS}; stories dated in the FY",
        "Count of stories; approved and waiting counted apart",
        "what:stories",
        "Cluster → MSCS → the story",
    ),
    # ── SSA Performance ──────────────────────────────────────────────────
    Metric(
        "SSA Performance",
        "Baseline, Current and Change by intervention",
        "ssa.SsaRecord, ssa.SsaScore",
        f"{_MEMBERS}; a school is compared where it has a confirmed SSA in "
        "the FY and in the year before",
        "Mean of the compared schools' scores each year; Improved / No "
        "Change / Declined by the one improvement rule (ssa.change_rules)",
        "tab:ssa",
        "Each count → its schools → School profile",
    ),
    Metric(
        "SSA Performance",
        "School SSA, Strongest and Struggling Intervention",
        "ssa.SsaRecord, ssa.SsaScore",
        f"{_MEMBERS}; each school's latest confirmed record of the FY",
        "The record's average; the intervention scored highest and lowest "
        "on that record (clusters.profile_insights.school_ssa_standing)",
        "tab:ssa",
        "School → School profile (the same record)",
    ),
    # ── Schools ──────────────────────────────────────────────────────────
    Metric(
        "Schools",
        "Best performing, needing the most support, improving, declining",
        "ssa.SsaRecord",
        f"{_MEMBERS}; confirmed SSA in the FY (and the year before for the "
        "two movers' lists)",
        "Ranked by the year's average SSA; level scores by the bigger "
        "change, then the name. The figures a rank was made from are in "
        "the row",
        "tab:portfolio",
        "School → School profile",
    ),
    # ── Training and visits ──────────────────────────────────────────────
    Metric(
        "Training & Visits",
        "School visits: in the plan, completed, upcoming, past their date",
        "activities.Activity",
        f"{_MEMBERS}; FY of the planned day; visit types; cancelled, "
        "rejected and deferred work left out",
        "Count of activities by status",
        "what:visits",
        "Cluster → the visits → the activity",
    ),
    Metric(
        "Training & Visits",
        "Training by channel: in school, group, online",
        "activities.Activity, partners.PartnerAssignment, "
        "activities.ClusterActivityAttendance",
        f"{_MEMBERS}; FY; training types. Assigned to a partner is a "
        "hand-over the partner holds; Dated by a partner is a subset of it",
        "Counted once each: Assigned ≠ Scheduled ≠ Completed, and the three "
        "channels add up to the Trainings line",
        "what:trainings",
        "Cluster → the trainings → the activity",
    ),
    Metric(
        "Training & Visits",
        "Online training: in the plan, completed, attendance",
        "activities.Activity (programme_delivery_mode = online), "
        "activities.ClusterActivityAttendance",
        f"{_MEMBERS}; FY; online trainings",
        "Count of sessions; schools attending ÷ schools invited",
        "what:trainings_online",
        "Cluster → the online trainings → the activity",
    ),
    # ── Meetings ─────────────────────────────────────────────────────────
    Metric(
        "Meetings & Attendance",
        "Meetings in the plan, held, upcoming, past their date",
        "activities.Activity",
        "Activity.cluster_id = this cluster; FY; cluster meeting types",
        "Count of meetings by status",
        "what:meetings",
        "Cluster → the meetings → the activity",
    ),
    Metric(
        "Meetings & Attendance",
        "Invited, attended, attendance, consecutive misses by school",
        "activities.ClusterActivityAttendance",
        f"{_MEMBERS}; sessions of this cluster delivered in the FY with at "
        "least one school ticked",
        "Per school: invitations, attendances and the run of sessions "
        "missed in a row (alert at three)",
        "tab:attendance",
        "School → its sessions → School profile",
    ),
    # ── Students and results ─────────────────────────────────────────────
    Metric(
        "Students",
        "Enrolment by school, this year and last",
        "schools.SchoolEnrollmentHistory, schools.School.enrollment",
        f"{_MEMBERS}; FY and the year before",
        "Each school's recorded enrolment; growth over schools with both " "years",
        "tab:students",
        "School → School profile",
    ),
    Metric(
        "Learning Results",
        "Mean learning score by school, this year and last",
        "impact.LearningAssessmentResult",
        f"{_MEMBERS}; FY and the year before",
        "Each school's mean score; improved and declined counted over the "
        "schools with both years",
        "tab:learning",
        "School → its results",
    ),
    # ── Loans and Business Transformation ────────────────────────────────
    Metric(
        "Loans & BT",
        "School loans, schools funded, amount disbursed",
        "business_transformation loans (scoped_loans: the reader's own loans)",
        f"{_MEMBERS}; the loans the reader may see",
        "Count of loans and of schools; sum of confirmed disbursements",
        "what:loans",
        "Cluster → the loans → the loan record",
    ),
    Metric(
        "Loans & BT",
        "Business Transformation cases",
        "business_transformation.TransformationCase",
        _MEMBERS,
        "Count of cases, open ones apart",
        "what:cases",
        "Cluster → the cases → the case",
    ),
    # ── Stories, projects, timeline, scores, history ─────────────────────
    Metric(
        "MSCS",
        "Stories: total, approved, with a reviewer, by intervention",
        "targets.MostSignificantChangeStory",
        _MEMBERS,
        "Count of stories by status and by intervention",
        "tab:stories",
        "Story → the story's record",
    ),
    Metric(
        "Projects",
        "Projects with schools here, capacity, work planned and completed",
        "projects.Project, projects.ProjectStaffCapacity, activities.Activity",
        f"{_MEMBERS}; schools assigned to a project; FY",
        "Count of schools and of activities; capacity is the staff "
        "allocations added up",
        "tab:projects",
        "Project → Project Monitoring",
    ),
    Metric(
        "Impact Timeline",
        "Interventions delivered and the SSA outcome that followed",
        "activities.Activity, activities.ClusterActivityAttendance, loans, "
        "ssa.SsaRecord",
        f"{_MEMBERS}; work delivered in the FY",
        "In date order. An outcome is shown only where the school has a "
        "confirmed SSA before and after in the intervention's own SSA "
        "area; no link is drawn that the records do not hold",
        "tab:interventions",
        "Intervention → the activity; outcome → the school's SSA",
    ),
    Metric(
        "Health & Impact",
        "Cluster Health, Cluster Impact, maturity",
        "clusters.ClusterScoreSetting (weights), and the reads above",
        "This cluster; FY",
        "Weighted mean of the parts that can be measured; a part with no "
        "record is left out, and fewer than three parts gives no score",
        "tab:scores",
        "Each part → the records it was read from",
    ),
    Metric(
        "Membership History",
        "Every school that has belonged to the cluster",
        "clusters.SchoolClusterMembership",
        "This cluster, every year",
        "One row per membership: joined, left, by whom and why",
        "tab:history",
        "School → School profile",
    ),
)


def sections() -> list[dict]:
    """`METRICS` grouped by section, in order, for the Sources tab."""
    grouped: dict[str, list[Metric]] = {}
    for metric in METRICS:
        grouped.setdefault(metric.section, []).append(metric)
    return [{"section": name, "metrics": rows} for name, rows in grouped.items()]
