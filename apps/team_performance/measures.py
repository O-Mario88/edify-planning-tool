"""The Weekly Report's categories, each defined once.

Every row of the workbook's country and CCEO sheets is a `Measure`: what is
counted (distinct schools, sessions, stories, loans or participants), which
records feed it (`source`, or the work it `match`es), which Uganda
Master Priority Plan milestone holds its target and which slice of it, and
which schools are its denominator when the target is a coverage rate. The
definitions are docs/team-performance-report.md.

A measure the records cannot give is `tracked=False`: the page says "Not
tracked" rather than showing 0.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple


class Facts(NamedTuple):
    """What one piece of work was, planned or done, for matching measures."""

    kind: str  # visit | training | meeting | event | other
    core: bool | None  # the school's family; None for work at no school
    topic: str  # the catalogue stable code of the course or the activity
    online: bool
    partner: bool
    activity_type: str
    #: A cluster meeting's kind (`MeetingKind`): training, only_meeting or
    #: cluster_leaders.
    meeting: str = ""
    #: Work under the Alumni project.
    alumni: bool = False


#: The units a measure counts. "participants" sums each session's headcount
#: once; every other unit is a distinct count of schools, sessions or records.
SCHOOLS, SESSIONS, PARTICIPANTS, STORIES, LOANS = (
    "schools",
    "sessions",
    "participants",
    "stories",
    "loans",
)

#: The eligible schools a coverage target is a share of.
PORTFOLIO, CORE, CLIENT = "portfolio", "core", "client"
CORE_CONTINUING = "core_continuing"  # Core schools not recruited this year
SSA_CORE, SSA_CLIENT = "ssa_core", "ssa_client"  # with an SSA this year


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    section: str
    unit: str = SCHOOLS
    #: The work this measure counts, by its facts.
    match: Callable[[Facts], bool] | None = None
    #: A non-work source the ledger reads (recruits, ssa_client, core_visit_2 …).
    source: str = ""
    #: The Uganda Master Priority Plan milestone holding the target, and the
    #: slice of it this row is ("core" / "client"), if any.
    milestone: str = ""
    slice: str = ""
    #: The eligible schools a coverage target is a share of, and the target
    #: itself when no milestone gives one (the workbook's "of the Core
    #: schools" rows).
    basis: str = ""
    tracked: bool = True
    #: Shown on the Weekly Report; False for milestone-only figures.
    weekly: bool = True
    note: str = ""
    #: Whom a participants row counts: "teachers", "leaders" or both ("").
    people: str = ""


# ── Work predicates ─────────────────────────────────────────────────────────
def _training(*topics, core=None, online=None) -> Callable[[Facts], bool]:
    wanted = frozenset(topics)

    def match(f: Facts) -> bool:
        return (
            f.kind == "training"
            and (not wanted or f.topic in wanted)
            and (core is None or f.core is core)
            and (online is None or f.online is online)
        )

    return match


def _visit(*, core, partner=None) -> Callable[[Facts], bool]:
    def match(f: Facts) -> bool:
        return (
            f.kind == "visit"
            and f.core is core
            and (partner is None or f.partner is partner)
        )

    return match


def _meeting(activity_type=None, core=None) -> Callable[[Facts], bool]:
    def match(f: Facts) -> bool:
        # A meeting held as a Training is a training and still a meeting.
        return (
            (f.kind == "meeting" or f.meeting == "training")
            and (activity_type is None or f.activity_type == activity_type)
            and (core is None or f.core is core)
        )

    return match


def _topics(*topics) -> Callable[[Facts], bool]:
    wanted = frozenset(topics)
    return lambda f: f.topic in wanted


EDTECH_INTEGRATION = "EDTECH_INTEGRATION"
DISTRICT_MEETING = "FIELD_DISTRICT_MEETING"
EDTECH_FOUNDATIONS = "EDTECH_FOUNDATIONS"
SKILLING = "TECH_SKILLS_EMPLOYABLE_FUTURE"
GOVERNMENT = "GOVERNMENT_STATUTORY_REQUIREMENTS"
SSA_LEADERSHIP = ("SSA_TRAINING", "SCHOOL_LEADERSHIP")
CC_SEL = "CC_SEL"
TAM_BI = ("BIBLICAL_INTEGRATION", "TAM_I", "TAM_II")
ECE = "EARLY_CHILDHOOD_EDUCATION_PROJECT"
CAMPS = (
    "STUDENT_CONFERENCE_CAMPS",
    "STUDENT_LEADERSHIP_CAMPS",
    "STUDENT_TRAINING_YOUTH_CAMPS",
)
SSA_REVIEW = "cluster_meeting_ssa_review"

GROWTH = "Program Growth"
DATA = "Data Gathering"
VISITS = "Visits"
LOANS_SECTION = "Loans"
CORE_TRAININGS = "Core School Trainings"
ONLINE = "Online Trainings"
CLIENT_TRAININGS = "Client School Trainings"
PROGRAMMES = "Clusters & Programmes"
COURSES = "Trainings by Course"

SECTIONS = (
    GROWTH,
    DATA,
    VISITS,
    LOANS_SECTION,
    CORE_TRAININGS,
    ONLINE,
    CLIENT_TRAININGS,
    PROGRAMMES,
    COURSES,
)

#: The workbook's trainings-by-course block: each catalogue course, the
#: schools it reached.
COURSE_ROWS = (
    ("TEACHER_PEDAGOGY_PROFESSIONALISM", "Teacher Pedagogy/Professionalism"),
    ("SCHOOL_LEADERSHIP", "Leadership"),
    ("LITERACY_NUMERACY_PROJECT", "Literacy/ Numeracy"),
    ("LEARNING_ENVIRONMENT_TRAINING", "Learning environment"),
    ("EDTECH_FOUNDATIONS", "EdTech Foundations Training"),
    ("GOVERNMENT_STATUTORY_REQUIREMENTS", "Government and Statutory requirements"),
    ("TAM_I", "Teaching as Mission (TAM)"),
    ("CLA_CHARACTER_DEVELOPMENT", "Christ-like Character Training"),
    ("FINANCIAL_MANAGEMENT", "Financial Management"),
    ("NEW_SCHOOL_ORIENTATION", "New School Orientation"),
    ("DISCIPLESHIP_DYNAMICS", "Discipleship Dynamics"),
    ("FEES_ENROLMENT_MARKETING", "Fees, Enrolment, and Marketing Management"),
    ("ACCOUNTING_FINANCIAL_MANAGEMENT", "Accounting and Financial Policies"),
    ("EARLY_CHILDHOOD_EDUCATION_PROJECT", "Early Childhood Education"),
    ("EDTECH_INTEGRATION", "EdTech Integration"),
    ("BUDGETING", "Budgeting"),
    ("TAM_II", "Teaching as Mission (TAM) II"),
    ("TECH_SKILLS_EMPLOYABLE_FUTURE", "Technology Skills for an Employable Future"),
    ("LEARNER_CENTERED_APPROACHES", "Learner-centered Approaches"),
)

MEASURES: tuple[Measure, ...] = (
    # ── Program Growth ──────────────────────────────────────────────────────
    # A new Core school is a Core school given its Core School Orientation
    # (owner, 2026-10-20), the training the Master Plan files under
    # NEW_CORE_SCHOOLS (`hr.uganda_master_seed`).
    Measure(
        "core_recruitment",
        "Core School Recruitment",
        GROWTH,
        match=_training("CORE_SCHOOL_ORIENTATION", core=True),
        milestone="NEW_CORE_SCHOOLS",
        note="Core schools whose Core School Orientation was completed this year.",
    ),
    # A new school is any school added to the platform in the year, typed in
    # or uploaded (owner, 2026-10-20).
    Measure(
        "new_schools",
        "New Schools",
        GROWTH,
        source="new_schools",
        milestone="NEW_SCHOOLS",
        note="Schools added to the platform this year, typed in or uploaded.",
    ),
    Measure(
        "active_schools",
        "Active Schools",
        GROWTH,
        source="active",
        basis=PORTFOLIO,
        note="Operating schools, of the portfolio.",
    ),
    Measure(
        "church_engagement",
        "Church Engagement",
        GROWTH,
        milestone="CHURCH_PARTNERSHIPS",
        tracked=False,
    ),
    # ── Data Gathering ──────────────────────────────────────────────────────
    Measure(
        "ssa_core_baseline",
        "SSA – Core Baseline",
        DATA,
        source="ssa_core_baseline",
        milestone="NEW_CORE_SCHOOLS",
        note="Core schools onboarded this year with an SSA uploaded.",
    ),
    Measure(
        "ssa_core_followup",
        "SSA – Core (Year 1–3)",
        DATA,
        source="ssa_core_followup",
        milestone="CORE_SSA_COVERAGE",
        basis=CORE_CONTINUING,
    ),
    Measure(
        "ssa_client",
        "SSA – Client",
        DATA,
        source="ssa_client",
        milestone="CLIENT_SSA_COVERAGE",
        basis=CLIENT,
    ),
    Measure("onetest", "OneTest", DATA, source="onetest", milestone="ONE_TEST_DATA"),
    Measure(
        "msc", "MSC Stories", DATA, unit=STORIES, source="msc", milestone="MSC_STORIES"
    ),
    Measure(
        "core_exam_scores",
        "Core School Exam Scores",
        DATA,
        source="core_exam_scores",
        basis=CORE,
    ),
    Measure(
        "dc_clubs",
        "Discipleship Clubs",
        DATA,
        source="dc_clubs",
        milestone="SCHOOLS_WITH_DCS",
        basis=PORTFOLIO,
        note="Schools whose uploaded DC record shows active groups.",
    ),
    Measure(
        "dc_data",
        "Discipleship Club Data Collected",
        DATA,
        source="dc_data",
        basis=PORTFOLIO,
        weekly=False,
    ),
    Measure(
        "ssa_review_core",
        "SSA Review – Core",
        DATA,
        match=_meeting(SSA_REVIEW, core=True),
        basis=SSA_CORE,
    ),
    Measure(
        "ssa_review_client",
        "SSA Review – Client",
        DATA,
        match=_meeting(SSA_REVIEW, core=False),
        basis=SSA_CLIENT,
    ),
    Measure(
        "enrolment",
        "Enrolment",
        DATA,
        source="enrolment",
        milestone="DATA_METRICS",
        basis=PORTFOLIO,
    ),
    Measure(
        "parent_survey",
        "Parent Survey",
        DATA,
        milestone="PARENT_SURVEY",
        tracked=False,
    ),
    Measure(
        "schools_with_metrics",
        "Schools with Metrics",
        DATA,
        source="metrics",
        milestone="DATA_METRICS",
        basis=PORTFOLIO,
        note="Enrolment, a Discipleship Club record or exam results this year.",
    ),
    # ── Visits ──────────────────────────────────────────────────────────────
    *(
        Measure(
            f"core_visit_{n}",
            f"Core Visit {n}",
            VISITS,
            source=f"core_visit_{n}",
            basis=CORE,
        )
        for n in (1, 2, 3, 4)
    ),
    Measure(
        "core_two_plus",
        "Core Schools with 2 or more Visits",
        VISITS,
        source="core_visit_2",
        basis=CORE,
    ),
    Measure(
        "client_visit_staff",
        "Client Visit – Staff",
        VISITS,
        match=_visit(core=False, partner=False),
        basis=CLIENT,
    ),
    Measure(
        "client_visit_partner",
        "Client Visit – Partner",
        VISITS,
        match=_visit(core=False, partner=True),
        basis=CLIENT,
    ),
    Measure(
        "client_visit_total",
        "Client Visit",
        VISITS,
        match=_visit(core=False),
        milestone="CLIENT_VISIT_COVERAGE",
        basis=CLIENT,
    ),
    # ── Loans ───────────────────────────────────────────────────────────────
    Measure(
        "edtech_loans",
        "EdTech Loans",
        LOANS_SECTION,
        unit=LOANS,
        source="edtech_loans",
        milestone="EDTECH_LOANS",
    ),
    Measure(
        "development_loans",
        "Development Loans",
        LOANS_SECTION,
        unit=LOANS,
        source="development_loans",
        note="Disbursed loans whose purpose is not EdTech.",
    ),
    Measure(
        "loans",
        "Loans (all)",
        LOANS_SECTION,
        unit=LOANS,
        source="loans",
        milestone="LOANS",
        weekly=False,
    ),
    # ── Core School Trainings ───────────────────────────────────────────────
    *(
        Measure(
            f"core_training_{n}",
            f"Core Training {n}",
            CORE_TRAININGS,
            source=f"core_training_{n}",
            milestone="CORE_TRAINING_COMPLIANCE" if n == 4 else "",
            basis=CORE,
        )
        for n in (1, 2, 3, 4)
    ),
    Measure(
        "edtech_integration_core",
        "EdTech Integration",
        CORE_TRAININGS,
        match=_training(EDTECH_INTEGRATION, core=True),
        milestone="EDTECH_INTEGRATION",
        slice="core",
    ),
    Measure(
        "edtech_foundation_core",
        "EdTech Foundation",
        CORE_TRAININGS,
        match=_training(EDTECH_FOUNDATIONS, core=True),
        milestone="EDTECH_FOUNDATIONS",
        slice="core",
    ),
    Measure(
        "skilling_core",
        "Skilling",
        CORE_TRAININGS,
        match=_training(SKILLING, core=True),
        milestone="EDTECH_SKILLING",
        slice="core",
    ),
    Measure(
        "government_core",
        "Government and Statutory Requirements",
        CORE_TRAININGS,
        match=_training(GOVERNMENT, core=True),
    ),
    Measure(
        "government_core_participants",
        "Government and Statutory Requirements – Participants",
        CORE_TRAININGS,
        unit=PARTICIPANTS,
        match=_training(GOVERNMENT, core=True),
    ),
    Measure(
        "ssa_leadership_core",
        "SSA & Leadership Trainings",
        CORE_TRAININGS,
        match=_training(*SSA_LEADERSHIP, core=True),
    ),
    Measure(
        "cc_sel_core",
        "CC-SEL",
        CORE_TRAININGS,
        match=_training(CC_SEL, core=True),
        milestone="SEL_TRAINING",
        slice="core",
    ),
    Measure(
        "core_online",
        "Core Schools Trained Online",
        CORE_TRAININGS,
        match=_training(core=True, online=True),
    ),
    # ── Online Trainings ────────────────────────────────────────────────────
    Measure(
        "online_sessions",
        "Online Training Sessions",
        ONLINE,
        unit=SESSIONS,
        match=_training(online=True),
    ),
    Measure(
        "online_schools",
        "Schools Trained Online",
        ONLINE,
        match=_training(online=True),
    ),
    Measure(
        "tam_bi_online_sessions",
        "TAM / Biblical Integration Online – Sessions",
        ONLINE,
        unit=SESSIONS,
        match=_training(*TAM_BI, online=True),
    ),
    Measure(
        "tam_bi_online_schools",
        "TAM / Biblical Integration Online – Schools",
        ONLINE,
        match=_training(*TAM_BI, online=True),
    ),
    Measure("ece", "Early Childhood Education", ONLINE, match=_training(ECE)),
    Measure(
        "ece_teachers",
        "Early Childhood Education – Teachers",
        ONLINE,
        unit=PARTICIPANTS,
        people="teachers",
        match=_training(ECE),
        milestone="ECD_TEACHERS",
        weekly=False,
    ),
    Measure("ide", "IDE", ONLINE, milestone="IDE_TEACHERS", tracked=False),
    # ── Client School Trainings ─────────────────────────────────────────────
    Measure(
        "client_trained",
        "Client Schools Trained",
        CLIENT_TRAININGS,
        match=_training(core=False),
        milestone="CLIENT_TRAINING_COMPLIANCE",
        basis=CLIENT,
    ),
    Measure(
        "client_online",
        "Client Schools Trained Online",
        CLIENT_TRAININGS,
        match=_training(core=False, online=True),
    ),
    Measure(
        "teacher_pedagogy",
        "Teacher Pedagogy/Professionalism",
        CLIENT_TRAININGS,
        match=_training("TEACHER_PEDAGOGY_PROFESSIONALISM", core=False),
        milestone="TEACHER_PEDAGOGY",
        slice="client",
    ),
    Measure(
        "discipleship_dynamics",
        "Discipleship Dynamics",
        CLIENT_TRAININGS,
        match=_training("DISCIPLESHIP_DYNAMICS", core=False),
        milestone="DC_TRAINING",
        slice="client",
    ),
    Measure(
        "christlike_character",
        "Christ-like Character Training",
        CLIENT_TRAININGS,
        match=_training("CLA_CHARACTER_DEVELOPMENT", core=False),
        milestone="CLA_TRAINING",
        slice="client",
    ),
    Measure(
        "literacy_numeracy",
        "Literacy/ Numeracy",
        CLIENT_TRAININGS,
        match=_training("LITERACY_NUMERACY_PROJECT", core=False),
        milestone="LITERACY_TRAINING",
        slice="client",
    ),
    Measure(
        "school_improvement",
        "School Improvement (SSA & Leadership)",
        CLIENT_TRAININGS,
        match=_training(*SSA_LEADERSHIP, core=False),
    ),
    Measure(
        "cc_sel_client",
        "CC-SEL",
        CLIENT_TRAININGS,
        match=_training(CC_SEL, core=False),
        milestone="SEL_TRAINING",
        slice="client",
    ),
    Measure(
        "edtech_integration_client",
        "EdTech Integration",
        CLIENT_TRAININGS,
        match=_training(EDTECH_INTEGRATION, core=False),
        milestone="EDTECH_INTEGRATION",
        slice="client",
    ),
    Measure(
        "edtech_foundation_client",
        "EdTech Foundation",
        CLIENT_TRAININGS,
        match=_training(EDTECH_FOUNDATIONS, core=False),
        milestone="EDTECH_FOUNDATIONS",
        slice="client",
    ),
    # ── Clusters & Programmes ───────────────────────────────────────────────
    Measure(
        "schools_in_clusters",
        "Schools in Clusters",
        PROGRAMMES,
        source="in_clusters",
        milestone="CLUSTER_COVERAGE",
        basis=PORTFOLIO,
    ),
    Measure(
        "cluster_meetings",
        "Cluster Meetings Held",
        PROGRAMMES,
        unit=SESSIONS,
        match=_meeting(),
    ),
    Measure(
        "cluster_meeting_schools",
        "Cluster Meeting Attendance",
        PROGRAMMES,
        match=_meeting(),
        note="Schools that attended a cluster meeting.",
    ),
    Measure(
        "student_camps",
        "Student Conferences / Camps",
        PROGRAMMES,
        unit=SESSIONS,
        match=_topics(*CAMPS),
        milestone="STUDENT_LEADER_CONFERENCES",
    ),
    Measure("ide_recruitment", "IDE School Recruitment", PROGRAMMES, tracked=False),
    # Owner, 2026-10-20: "cluster leader meeting should be fetched from the
    # district meeting plan and completion" — the District Meetings planned
    # and completed, with any cluster meeting held as a Cluster Leaders
    # Meeting.
    Measure(
        "cluster_leaders_meetings",
        "Quarterly Cluster Leaders Meeting",
        PROGRAMMES,
        unit=SESSIONS,
        match=lambda f: f.topic == DISTRICT_MEETING or f.meeting == "cluster_leaders",
        note="District Meetings, and cluster meetings held as Cluster Leaders Meetings.",
    ),
    Measure(
        "partner_review_meetings",
        "Partner Review Meetings",
        PROGRAMMES,
        unit=SESSIONS,
        match=_topics("PARTNER_MEETINGS_ADMIN"),
        milestone="PARTNER_REVIEW_MEETINGS",
    ),
    Measure(
        "district_reports", "Quarterly District Reports", PROGRAMMES, tracked=False
    ),
    Measure(
        "district_meetings",
        "District MOU Formalization (District Meetings)",
        PROGRAMMES,
        unit=SESSIONS,
        match=_topics(DISTRICT_MEETING),
    ),
    # Owner, 2026-10-20: "Alumni data should be fetched from project" — the
    # schools the Alumni project's work reached.
    Measure(
        "alumni_data",
        "Alumni Data",
        PROGRAMMES,
        match=lambda f: f.alumni,
        milestone="STUDENT_ALUMNI",
        basis=PORTFOLIO,
        note="Schools reached by work under the Alumni project.",
    ),
    # Milestone-only figures: the Strategic Milestones tab reads them.
    Measure(
        "tam_training",
        "Schools Trained on TAM",
        PROGRAMMES,
        match=_training("TAM_I", "TAM_II"),
        milestone="TAM_TRAINING",
        weekly=False,
    ),
    Measure(
        "biblical_integration",
        "Biblical Integration",
        PROGRAMMES,
        match=_training("BIBLICAL_INTEGRATION"),
        milestone="BIBLICAL_INTEGRATION",
        weekly=False,
    ),
    Measure(
        "sip_leaders",
        "Leaders Trained – SIP",
        PROGRAMMES,
        unit=PARTICIPANTS,
        people="leaders",
        match=_training("SCHOOL_LEADERSHIP"),
        milestone="SIP_LEADERS",
        weekly=False,
    ),
    Measure(
        "accountants_training",
        "Accountants Training",
        PROGRAMMES,
        match=_training("BT_UG_ACCOUNTANT_TRAINING"),
        milestone="ACCOUNTANTS_TRAINING",
        weekly=False,
    ),
    Measure(
        "dc_training_core",
        "Discipleship Dynamics – Core",
        PROGRAMMES,
        match=_training("DISCIPLESHIP_DYNAMICS", core=True),
        milestone="DC_TRAINING",
        slice="core",
        weekly=False,
    ),
    # Visit counts, staff and partner, for the Strategic Milestones tab.
    *(
        Measure(
            f"{family}_visits_{side}_n",
            f"{family.title()} School Visits by {side.title()}",
            VISITS,
            unit=SESSIONS,
            match=_visit(core=family == "core", partner=side == "partner"),
            milestone=f"{family.upper()}_VISITS_{side.upper()}",
            weekly=False,
        )
        for family in ("client", "core")
        for side in ("staff", "partner")
    ),
    Measure(
        "core_trained",
        "Core Schools Trained",
        CORE_TRAININGS,
        match=_training(core=True),
        weekly=False,
    ),
    Measure(
        "ssa_all",
        "Schools with an SSA",
        DATA,
        source="ssa_all",
        weekly=False,
    ),
    Measure(
        "dc_clubs_core",
        "Core Schools with DC",
        DATA,
        source="dc_clubs_core",
        weekly=False,
    ),
    Measure(
        "dc_clubs_client",
        "Client Schools with DC",
        DATA,
        source="dc_clubs_client",
        weekly=False,
    ),
    Measure(
        "edtech_foundations_online",
        "EdTech Foundations – Online",
        PROGRAMMES,
        match=_training(EDTECH_FOUNDATIONS, online=True),
        weekly=False,
    ),
    Measure(
        "edtech_foundations_in_school",
        "EdTech Foundations – In-School",
        PROGRAMMES,
        match=_training(EDTECH_FOUNDATIONS, online=False),
        weekly=False,
    ),
    # Trainings by Course: each course's schools, Core and client together.
    *(
        Measure(f"course_{code.lower()}", label, COURSES, match=_training(code))
        for code, label in COURSE_ROWS
    ),
)

BY_KEY: dict[str, Measure] = {m.key: m for m in MEASURES}
WORK_MEASURES: tuple[Measure, ...] = tuple(m for m in MEASURES if m.match)
#: Measures whose figure is each session's headcount, counted once.
PARTICIPANT_KEYS = frozenset(m.key for m in MEASURES if m.unit == PARTICIPANTS)


def get(key: str) -> Measure:
    return BY_KEY[key]


def weekly_sections() -> list[tuple[str, list[Measure]]]:
    """The Weekly Report's rows, in the workbook's order, by section."""
    return [
        (section, [m for m in MEASURES if m.section == section and m.weekly])
        for section in SECTIONS
    ]
