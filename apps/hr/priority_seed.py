"""FY2027 strategic source preserved from the RVP implementation brief."""

PRIORITIES = [
    (
        "PROGRAM_GROWTH_AND_EXPANSION",
        "Program Growth and Expansion",
        [
            (
                "NEW_SCHOOLS",
                "New Schools in operational countries — 5,000 to reach 30,000",
                5000,
                "schools",
            ),
            ("SCHOOLS_WITH_DCS", "Schools with DCs — 255", 255, "needs_definition"),
            (
                "NEW_CORE_SCHOOLS",
                "New Core Schools — 730 to make 2,500",
                730,
                "schools",
            ),
            (
                "ACTIVE_SOCIAL_MEDIA",
                "Keep active social media and internal marketing",
                None,
                "needs_definition",
            ),
            (
                "CONNECT_MOVEMENT",
                "Operationalise Connect movement in all countries and document progress",
                None,
                "needs_definition",
            ),
        ],
    ),
    (
        "PROGRAM_QUALITY",
        "Program Quality",
        [
            (code, title, None, "needs_definition")
            for code, title in [
                ("SCHOOL_VISITS", "School Visits"),
                ("CLIENT_SCHOOL_VISIT_COVERAGE", "Client School Visit coverage"),
                ("CORE_SCHOOL_VISIT_COVERAGE", "Core School Visit coverage"),
                ("ENROLMENT_DATA_METRICS", "Data Metrics: Enrolment"),
                ("DCS_DATA_METRICS", "Data Metrics: DCs"),
                ("EDTECH_DATA_METRICS", "Data Metrics: EdTech data"),
                ("EXAM_SCORE_DATA_METRICS", "Data Metrics: Exam Scores"),
                ("CORE_SSA_COVERAGE", "SSA: Core School coverage"),
                ("CLIENT_SSA_COVERAGE", "SSA: Client School coverage"),
                ("CLUSTER_COVERAGE", "Cluster coverage"),
                ("CORE_SCHOOL_TRAINING", "Training: Core School training"),
                ("CLIENT_SCHOOL_TRAINING", "Training: Client School training"),
                ("ONLINE_TRAINING", "Training: Online training"),
                ("SCHOOLS_TRAINED", "Training: Schools trained"),
                ("DC_TRAINING", "Training: DC training"),
                ("CLA", "Training: CLA"),
                ("SEL", "Training: SEL"),
                ("LITERACY", "Training: Literacy"),
                ("ECD", "Training: ECD"),
                ("IDE", "Training: IDE"),
                ("TAM", "Training: TAM"),
                ("TEACHERS_TRAINED", "Teachers trained"),
                ("LEADERS_TRAINED", "Leaders trained"),
                ("TRANSFORMATION_FROM_SSA", "Transformation based on SSA"),
                ("MSCS", "MSCS"),
                ("CORE_SCHOOL_GRADUATION", "Core School graduation"),
                (
                    "SSA_SUPPORT_CORRELATION",
                    "Country analysis of SSA and correlation with Trainings and Visits",
                ),
                ("PARENT_SURVEY", "Parent survey"),
                ("STUDENT_IMPACT", "Student-impact measurement"),
                ("STUDENT_ALUMNI", "Student Alumni programme"),
                ("AMBIGUOUS_CORE_200_PERCENT", "Core 200% — ?? definition required"),
            ]
        ],
    ),
    (
        "BUSINESS_TRANSFORMATION",
        "Business Transformation",
        [
            (code, title, None, "needs_definition")
            for code, title in [
                ("NUMBER_OF_LOANS", "Number of Loans"),
                ("PERCENTAGE_EDTECH_LOANS", "Percentage of EdTech Loans"),
                ("MONTHLY_MFI_MENTORSHIP", "Monthly Goshen/MFI mentorship sessions"),
                ("CREATIVE_VIDEOS", "Creative Videos"),
                ("MONTHLY_MFI_MEETINGS", "Monthly MFI meetings"),
                ("ACCOUNTANTS_TRAINING", "Accountants Training"),
                ("LOAN_USE_VERIFICATION", "Verification of Loan Use"),
            ]
        ],
    ),
    (
        "EDUCATION_TECHNOLOGY",
        "Education Technology",
        [
            (code, title, None, "needs_definition")
            for code, title in [
                ("EDTECH_PIPELINE", "EdTech Pipeline"),
                ("EDTECH_FOUNDATIONS", "EdTech Foundations"),
                ("EDTECH_ACCESS", "EdTech Access"),
                ("EDTECH_INTEGRATION", "EdTech Integration"),
                ("EDTECH_SKILLING", "EdTech Skilling"),
                ("EDTECH_CONFERENCE", "Conference"),
                ("LEARNING_PLATFORM_USAGE", "Country-specific Learning Platform usage"),
                ("VENDOR_LENDING", "Vendor lending exploration"),
            ]
        ],
    ),
    (
        "GOVERNANCE_AND_PEOPLE_MANAGEMENT",
        "Governance and People Management",
        [
            (code, title, None, "needs_definition")
            for code, title in [
                (
                    "ANNUAL_PLAN_BUDGETS",
                    "Annual Plan and Budgets completed by September",
                ),
                ("PTO_USAGE", "PTO usage"),
                ("PDF_USAGE", "PDF usage — 90% (acronym needs definition)"),
                ("ONE_ON_ONES", "One-on-Ones"),
                ("NEW_PARTNERSHIPS", "New Partnerships"),
                ("CHURCH_PARTNERSHIPS", "Church partnerships or engagement"),
                ("PARTNER_REVIEW_MEETINGS", "Partner Review Meetings"),
                ("PARTNER_MOUS", "Partner MOUs"),
                ("SAFEGUARDING_TRAINING", "Safeguarding Training"),
                ("QUARTERLY_BOARD_MEETINGS", "Quarterly Board Meetings"),
                ("MENTORING_HIGHER_ROLES", "Mentoring staff for higher roles"),
                ("COUNTRY_OPERATION_VISITS", "Country or operation Visits"),
                (
                    "STAKEHOLDER_PLANNING",
                    "Stakeholder involvement in Planning and Reviews",
                ),
                ("GOVERNMENT_COMPLIANCE", "Government Reporting and Compliance"),
                ("GOVERNANCE_SCHOOL_VISITS", "School Visits"),
                ("REGIONAL_TEAM_PERFORMANCE", "Regional Team performance"),
                ("REGIONAL_INITIATIVES", "Regional Initiatives"),
            ]
        ],
    ),
]


ACTIVITY_MAPPINGS = {
    "CLA": ["CLA_CHARACTER_DEVELOPMENT"],
    "SEL": ["CC_SEL"],
    "LITERACY": ["LITERACY_NUMERACY_PROJECT"],
    "TAM": ["TAM_I", "TAM_II"],
    "ECD": ["EARLY_CHILDHOOD_EDUCATION_PROJECT"],
    "ACCOUNTANTS_TRAINING": ["ACCOUNTING_FINANCIAL_MANAGEMENT"],
    "EDTECH_FOUNDATIONS": ["EDTECH_FOUNDATIONS"],
    "EDTECH_INTEGRATION": ["EDTECH_INTEGRATION"],
    "EDTECH_SKILLING": ["TECH_SKILLS_EMPLOYABLE_FUTURE"],
    "CLIENT_SCHOOL_VISIT_COVERAGE": ["CLIENT_SCHOOL_FOLLOWUP_VISIT"],
    "CORE_SCHOOL_VISIT_COVERAGE": ["CORE_SCHOOL_FOLLOWUP_VISIT"],
}

# ─── Linked to the plan (owner, 2026-09-07) ──────────────────────────────────
# "Add activity rules to the milestones so the bars actually fill."
#
# The eleven mappings above name a CURRICULUM item per milestone (CLA, SEL,
# TAM …). The milestones below are about the SHAPE of the work rather than a
# title — every school visit, every cluster meeting, every training — so they
# link to the catalogue's standard-support items, the ones the scheduling
# drawer itself resolves a purpose to. A milestone that is not activity-shaped
# (new schools, loans, data metrics, MOUs, social media) is deliberately absent:
# nothing in the plan is that milestone, and a rule would count the wrong thing.
ACTIVITY_MAPPINGS.update(
    {
        # Visits
        "SCHOOL_VISITS": [
            "STANDARD_SCHOOL_VISIT",
            "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
            "STANDARD_IN_SCHOOL_SUPPORT",
            "STANDARD_IN_SCHOOL_COACHING_VISIT",
            "STANDARD_TRAINING_FOLLOW_UP_VISIT",
            "CORE_SCHOOL_FOLLOWUP_VISIT",
            "CLIENT_SCHOOL_FOLLOWUP_VISIT",
        ],
        "GOVERNANCE_SCHOOL_VISITS": ["STANDARD_SCHOOL_VISIT"],
        "COUNTRY_OPERATION_VISITS": ["STANDARD_DONOR_VISIT"],
        # SSA coverage: the visit that collects it, per school family
        "CORE_SSA_COVERAGE": [
            "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
            "ASA_SSA_DATA_GATHERING",
        ],
        "CLIENT_SSA_COVERAGE": [
            "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
            "ASA_SSA_DATA_GATHERING",
        ],
        # Clusters
        "CLUSTER_COVERAGE": ["STANDARD_CLUSTER_MEETING", "STANDARD_CLUSTER_TRAINING"],
        # Trainings
        "CORE_SCHOOL_TRAINING": [
            "STANDARD_IN_SCHOOL_TRAINING",
            "STANDARD_CLUSTER_TRAINING",
        ],
        "CLIENT_SCHOOL_TRAINING": [
            "STANDARD_IN_SCHOOL_TRAINING",
            "STANDARD_CLUSTER_TRAINING",
        ],
        "SCHOOLS_TRAINED": ["STANDARD_IN_SCHOOL_TRAINING", "STANDARD_CLUSTER_TRAINING"],
        "TEACHERS_TRAINED": [
            "STANDARD_IN_SCHOOL_TRAINING",
            "STANDARD_CLUSTER_TRAINING",
        ],
        "LEADERS_TRAINED": [
            "SCHOOL_LEADERSHIP",
            "TEACHER_LEADERSHIP_CONFERENCE",
            "CORE_SCHOOL_ORIENTATION",
            "NEW_SCHOOL_ORIENTATION",
        ],
        "DC_TRAINING": ["DISCIPLESHIP_DYNAMICS"],
        "SAFEGUARDING_TRAINING": ["STANDARD_IN_SCHOOL_TRAINING"],
        # Meetings and events
        "PARTNER_REVIEW_MEETINGS": ["PARTNER_MEETINGS_ADMIN"],
        "MONTHLY_MFI_MEETINGS": ["BT_UG_MONTHLY_MFI_REVIEW"],
        "MONTHLY_MFI_MENTORSHIP": ["BT_UG_MFI_MENTORSHIP"],
        "LOAN_USE_VERIFICATION": ["BT_UG_LOAN_USE_VERIFICATION"],
        "EDTECH_CONFERENCE": ["FIELD_CONFERENCE"],
    }
)

# How each of those rules COUNTS, and what it is allowed to match.
#   counting_basis     the unit the bar is drawn in — distinct schools for the
#                      coverage milestones, teachers/leaders where the milestone
#                      names people, activities otherwise
#   school_type        "core" / "client" narrows a rule to that school family
#   target_intervention ALWAYS blank here: these milestones are about the shape
#                      of the work, not one of the eight interventions, and a
#                      gate would silently exclude every visit whose planner
#                      named a different focus
#   delivery_method    "online" for the online-training milestone only
ACTIVITY_RULE_OPTIONS = {
    "SCHOOL_VISITS": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "GOVERNANCE_SCHOOL_VISITS": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "COUNTRY_OPERATION_VISITS": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "CORE_SSA_COVERAGE": {
        "counting_basis": "UNIQUE_SCHOOLS_SUPPORTED",
        "school_type": "core",
    },
    "CLIENT_SSA_COVERAGE": {
        "counting_basis": "UNIQUE_SCHOOLS_SUPPORTED",
        "school_type": "client",
    },
    "CLUSTER_COVERAGE": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "CORE_SCHOOL_TRAINING": {
        "counting_basis": "UNIQUE_SCHOOLS_TRAINED",
        "school_type": "core",
    },
    "CLIENT_SCHOOL_TRAINING": {
        "counting_basis": "UNIQUE_SCHOOLS_TRAINED",
        "school_type": "client",
    },
    "SCHOOLS_TRAINED": {"counting_basis": "UNIQUE_SCHOOLS_TRAINED"},
    "TEACHERS_TRAINED": {"counting_basis": "TEACHERS_TRAINED"},
    "LEADERS_TRAINED": {"counting_basis": "SCHOOL_LEADERS_TRAINED"},
    "DC_TRAINING": {"counting_basis": "UNIQUE_SCHOOLS_TRAINED"},
    "SAFEGUARDING_TRAINING": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "PARTNER_REVIEW_MEETINGS": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "MONTHLY_MFI_MEETINGS": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "MONTHLY_MFI_MENTORSHIP": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "LOAN_USE_VERIFICATION": {"counting_basis": "ACTIVITIES_DELIVERED"},
    "EDTECH_CONFERENCE": {"counting_basis": "ACTIVITIES_DELIVERED"},
}


ROLE_APPLICABILITY = {
    "PROGRAM_GROWTH_AND_EXPANSION": [
        "RegionalVicePresident",
        "CountryDirector",
        "Program Lead",
        "CCEO",
    ],
    "PROGRAM_QUALITY": [
        "RegionalVicePresident",
        "CountryDirector",
        "Program Lead",
        "CCEO",
        "ImpactAssessment",
        "ProjectCoordinator",
    ],
    "BUSINESS_TRANSFORMATION": [
        "RegionalVicePresident",
        "CountryDirector",
        "Program Lead",
        "Accountant",
    ],
    "EDUCATION_TECHNOLOGY": [
        "RegionalVicePresident",
        "CountryDirector",
        "Program Lead",
        "CCEO",
        "ProjectCoordinator",
    ],
    "GOVERNANCE_AND_PEOPLE_MANAGEMENT": [
        "RegionalVicePresident",
        "CountryDirector",
        "Program Lead",
        "HumanResources",
        "Accountant",
    ],
}


assert len(PRIORITIES) == 5
