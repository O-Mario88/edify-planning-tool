"""The Strategic Milestones & Trackers sheet's 54 rows, read from the records.

Owner, 2026-10-20: the tab shows the live sheet's own milestones — its rows,
domains and delivery modes, with Impact Assessment the responsible lead of
every row — with the achieved figure computed from the database and the
target taken from the matching Uganda Master Priority Plan milestone (the
figures PLs and Project Coordinators allocate), "Not set" where the plan has
none. A row the platform keeps no record for (SSA cohort
years, ELP, BPV, the Alumni programme, HR usage) says "Not tracked".

Row kinds:

* ``count`` — the sum of its measures over the window;
* ``rate`` — its measure as a share of the eligible schools (Schools with DC);
* ``score`` — the mean of the year's latest uploaded SSA scores;
* ``untracked`` — no record in the platform.
"""

from __future__ import annotations

from dataclasses import dataclass

COUNT, RATE, SCORE, UNTRACKED = "count", "rate", "score", "untracked"
#: Who answers for every row of the sheet (owner, 2026-10-23).
RESPONSIBLE_LEAD = "Impact Assessment"


@dataclass(frozen=True)
class StrategicRow:
    domain: str
    title: str
    mode: str
    kind: str = COUNT
    measures: tuple[str, ...] = ()
    #: The Uganda Master Priority Plan milestone holding the target.
    plan: str = ""
    slice: str = ""
    #: The eligible schools a percentage target, or a rate row, is a share of.
    basis: str = ""

    @property
    def lead(self) -> str:
        """Owner, 2026-10-23: "Strategic Milestones & Operational Trackers -
        Responsible Lead is the Impact Assessment" — every row."""
        return RESPONSIBLE_LEAD

    @property
    def key(self) -> str:
        """The row's stable name, for the country target IA or Admin set."""
        from django.utils.text import slugify

        return f"strategic:{slugify(self.title)}-{slugify(self.mode)}"


Q, V, T, D, S, A, H = (
    "Program Quality",
    "School Visits",
    "Trainings",
    "Data and Metrics",
    "Stakeholders Engagement",
    "Alumni",
    "HR",
)


def _cohort(n: int, year: int) -> StrategicRow:
    return StrategicRow(
        Q,
        f"Core schools score improvement Cohort {n}",
        f"Cohort {n} ({year})",
        UNTRACKED,
    )


ROWS: tuple[StrategicRow, ...] = (
    _cohort(3, 2027),
    _cohort(4, 2028),
    _cohort(5, 2029),
    _cohort(6, 2030),
    StrategicRow(
        Q,
        "Client schools score improvement",
        "Client Schools",
        SCORE,
    ),
    StrategicRow(
        Q,
        "Most significant Change Stories target",
        "Qualitative Impact Case Stories",
        measures=("msc",),
        plan="MSC_STORIES",
    ),
    StrategicRow(
        Q,
        "Engaging Champion and Core Graduate Schools",
        "Champion & Graduate Network",
        UNTRACKED,
    ),
    StrategicRow(
        Q,
        "Schools with DC",
        "Discipleship Curriculum Rollout – Core",
        RATE,
        ("dc_clubs_core",),
        "SCHOOLS_WITH_DCS",
        basis="core",
    ),
    StrategicRow(
        Q,
        "Schools with DC",
        "Discipleship Curriculum Rollout – Client",
        RATE,
        ("dc_clubs_client",),
        "SCHOOLS_WITH_DCS",
        basis="client",
    ),
    StrategicRow(
        Q,
        "Core Schools Recruitment",
        "Core School Orientation",
        measures=("core_recruitment",),
        plan="NEW_CORE_SCHOOLS",
    ),
    StrategicRow(
        Q,
        "New School Recruitment",
        "School Scouting & Ingestion",
        measures=("new_schools",),
        plan="NEW_SCHOOLS",
    ),
    StrategicRow(
        V,
        "Client School Visits by staff",
        "In-Person Monitoring Visits",
        measures=("client_visits_staff_n",),
        plan="CLIENT_VISITS_STAFF",
    ),
    StrategicRow(
        V,
        "Client School Visits by Partner",
        "Partner Joint Monitoring",
        measures=("client_visits_partner_n",),
        plan="CLIENT_VISITS_PARTNER",
    ),
    StrategicRow(
        V,
        "Core school visit target by staff",
        "In-Person Staff Coaching",
        measures=("core_visits_staff_n",),
        plan="CORE_VISITS_STAFF",
    ),
    StrategicRow(
        V,
        "Core school visit target by Partners",
        "Partner Coaching & Mentoring",
        measures=("core_visits_partner_n",),
        plan="CORE_VISITS_PARTNER",
    ),
    StrategicRow(
        T,
        "Client school training Target",
        "Capacity Building Workshops",
        measures=("client_trained",),
        plan="CLIENT_TRAINING_COMPLIANCE",
        basis="client",
    ),
    StrategicRow(
        T,
        "Cluster meeting target",
        "Peer Learning Clusters",
        measures=("cluster_meetings",),
    ),
    StrategicRow(
        T,
        "Core school trainings",
        "Dedicated Core School Training",
        measures=("core_trained",),
    ),
    StrategicRow(
        T,
        "Online Training Target (No of schools)",
        "Digital Modules & Webinars",
        measures=("online_schools",),
    ),
    StrategicRow(
        T,
        "EdTech Foundations Training",
        "Online",
        measures=("edtech_foundations_online",),
    ),
    StrategicRow(
        T,
        "EdTech Foundations Training",
        "In-School",
        measures=("edtech_foundations_in_school",),
    ),
    StrategicRow(
        T,
        "EdTech Integration",
        "In-School",
        measures=("course_edtech_integration",),
        plan="EDTECH_INTEGRATION",
    ),
    StrategicRow(
        T,
        "Student Skilling & EdTech Conferences",
        "In-School",
        measures=("course_tech_skills_employable_future",),
        plan="EDTECH_SKILLING",
    ),
    StrategicRow(T, "ELP", "In-School", UNTRACKED),
    StrategicRow(T, "BPV", "In-School", UNTRACKED),
    StrategicRow(
        T,
        "Leadership",
        "Cluster (leaders trained)",
        measures=("sip_leaders",),
        plan="SIP_LEADERS",
    ),
    StrategicRow(
        T,
        "Christ-like Character Training – CC-SEL",
        "In-School",
        measures=("cc_sel_core", "cc_sel_client"),
        plan="SEL_TRAINING",
    ),
    StrategicRow(
        T,
        "New School Orientation",
        "Group",
        # The orientation trainings; New Schools now counts schools added.
        measures=("course_new_school_orientation",),
        plan="NEW_SCHOOLS",
    ),
    StrategicRow(
        T,
        "Data Gathering – One test",
        "In-school",
        measures=("onetest",),
        plan="ONE_TEST_DATA",
    ),
    StrategicRow(
        T,
        "Teacher Pedagogy/Professionalism (Academic Seminars)",
        "Cluster",
        measures=("course_teacher_pedagogy_professionalism",),
        plan="TEACHER_PEDAGOGY",
    ),
    StrategicRow(
        T,
        "Biblical integration",
        "In-School, Online",
        measures=("biblical_integration",),
        plan="BIBLICAL_INTEGRATION",
    ),
    StrategicRow(
        T,
        "Teaching as a Mission (TAM) I",
        "Online, In-School",
        measures=("course_tam_i",),
        plan="TAM_TRAINING",
    ),
    StrategicRow(
        T,
        "Discipleship Dynamics",
        "Cluster, Online",
        measures=("course_discipleship_dynamics",),
        plan="DC_TRAINING",
    ),
    StrategicRow(
        T,
        "Christ-like Character Training – CLA",
        "In-School, Online",
        measures=("course_cla_character_development",),
        plan="CLA_TRAINING",
    ),
    StrategicRow(
        T,
        "Literacy/Numeracy",
        "Cluster, Group",
        measures=("course_literacy_numeracy_project",),
        plan="LITERACY_TRAINING",
    ),
    StrategicRow(
        T,
        "Early Childhood Education",
        "Online (teachers trained)",
        measures=("ece_teachers",),
        plan="ECD_TEACHERS",
    ),
    StrategicRow(T, "Certificate Training (IDE)", "Online", UNTRACKED),
    StrategicRow(
        D,
        "Data Gathering – ASA/SSA",
        "In-School",
        measures=("ssa_all",),
    ),
    StrategicRow(
        D,
        "SSA – Core Baseline Cohort 6",
        "In-School",
        measures=("ssa_core_baseline",),
        plan="NEW_CORE_SCHOOLS",
    ),
    StrategicRow(D, "SSA – Core Cohort 4 & 5", "In-School", UNTRACKED),
    StrategicRow(D, "SSA – Core Cohort 3", "In-School", UNTRACKED),
    StrategicRow(
        D,
        "SSA – Client",
        "In-School",
        measures=("ssa_client",),
        plan="CLIENT_SSA_COVERAGE",
        basis="client",
    ),
    StrategicRow(
        D,
        "Client Schools SSA target (Data review)",
        "Client Schools",
        measures=("ssa_review_client",),
        basis="ssa_client",
    ),
    StrategicRow(
        D,
        "Core school SSA target (Data review)",
        "Core Schools",
        measures=("ssa_review_core",),
        basis="ssa_core",
    ),
    StrategicRow(
        D,
        "Enrollment & metrics",
        "All Schools",
        measures=("schools_with_metrics",),
        plan="DATA_METRICS",
        basis="portfolio",
    ),
    StrategicRow(
        D,
        "Exam Scores target (core schools)",
        "Core Schools",
        measures=("core_exam_scores",),
        basis="core",
    ),
    StrategicRow(
        S,
        "Partner engagement",
        "Strategic Partner Dialogues",
        measures=("partner_review_meetings",),
        plan="PARTNER_REVIEW_MEETINGS",
    ),
    StrategicRow(
        S,
        "District MOUs and engagement Meetings",
        "District Engagements",
        measures=("district_meetings",),
    ),
    StrategicRow(S, "Church engagement", "Church Forums", UNTRACKED),
    StrategicRow(
        A,
        "Schools trained on Alumni program",
        "Alumni Program",
        UNTRACKED,
    ),
    StrategicRow(
        A,
        "Schools with active Alumni programs",
        "Active Chapters",
        UNTRACKED,
    ),
    StrategicRow(
        A,
        "Alumni Program initiative Target",
        "CCEO Direct Target",
        UNTRACKED,
    ),
    StrategicRow(H, "PDF", "Internal Staff", UNTRACKED),
    StrategicRow(
        H,
        "PTO & Personal spiritual retreat day",
        "Staff Retreats",
        UNTRACKED,
    ),
)

DOMAINS = tuple(dict.fromkeys(row.domain for row in ROWS))
