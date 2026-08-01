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
