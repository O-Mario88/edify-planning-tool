"""The governed 28-item Edify source catalogue, plus standard field support.

Source wording is intentionally repeated verbatim here.  Stable codes are the
only keys used for upsert; display names are never identities.

Two lists, deliberately kept apart:

``SOURCE_CATALOGUE_ITEMS`` is the programme's 28 named interventions — EdTech
Foundations, TAM I, CC-SEL. Choosing one is a curriculum decision, and the SSA
engine ranks them against a school's weakest scores.

``STANDARD_SUPPORT_ITEMS`` is ordinary field support: a school visit, an
in-school training, a cluster meeting. These are not curriculum choices and no
SSA ranking selects them — an officer decides a school needs a visit. They
were missing entirely, and their absence is what made ordinary support
unschedulable: the drawer derives an activity's costing from its purpose, and
with no catalogue row costing ``school_visit`` there was nothing to derive.
Five of the eight interventions are answered ONLY by cluster-delivered named
trainings, so a school whose weakest area was Financial Health had no
school-level response at all and was told to go find a Project or a Cluster.

They carry ``standard_support=True``: schedulable in their planning context on
a target intervention and a stated rationale alone, never requiring a Special
Project and never having to be the engine's top-ranked pick.
"""

from apps.core.enums import ActivityType, ParticipantMode, SsaIntervention

from .models import (
    CatalogueActivityType as Type,
    DeliveryMethod as Delivery,
    MappingMode,
)


INTERVENTION = SsaIntervention


#: Workflow kinds whose participant total is the cluster's active school count
#: multiplied by a per-school figure the planner enters.
_PER_SCHOOL_KINDS = {
    ActivityType.CLUSTER_MEETING,
    ActivityType.CLUSTER_TRAINING,
    ActivityType.CLUSTER_MEETING_SSA_REVIEW,
    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
}

#: Workflow kinds delivered to a room of people at one school or venue, where
#: the planner states the total directly.
_DIRECT_TOTAL_KINDS = {
    ActivityType.IN_SCHOOL_TRAINING,
    ActivityType.SCHOOL_IMPROVEMENT_TRAINING,
    ActivityType.TRAINING,
    ActivityType.CORE_TRAINING,
    ActivityType.PROGRAMME_EVENT,
}


def default_participant_mode(workflow_kind: str, participant_counts: bool) -> str:
    """Everything else is a visit, and a visit has no participant quantity."""
    if workflow_kind in _PER_SCHOOL_KINDS:
        return ParticipantMode.PER_SCHOOL
    if workflow_kind in _DIRECT_TOTAL_KINDS or participant_counts:
        return ParticipantMode.DIRECT_TOTAL
    return ParticipantMode.NONE


def _item(
    stable_code,
    source_name,
    activity_type,
    delivery_method,
    workflow_kind,
    *,
    intervention=None,
    mapping_mode=MappingMode.FIXED,
    target_audience="School staff",
    evidence_profile="TRAINING_ATTENDANCE",
    salesforce_record_type="TRAINING",
    salesforce_expected_prefix="TS-",
    costing_profile="CLUSTER_TRAINING",
    staff=True,
    partner=True,
    school=True,
    cluster=False,
    project=True,
    requires_ssa=True,
    requires_source=False,
    new_school_only=False,
    client_visit=False,
    client_training=False,
    core_slot_type="",
    support_objective="SSA_INTERVENTION_SUPPORT",
    non_school=True,
    multi_day=False,
    participant_counts=False,
    programme_category="",
    standard_support=False,
    participant_mode=None,
    certified_agency=False,
    requires_project=False,
):
    return {
        "stable_code": stable_code,
        "source_name": source_name,
        "display_name": source_name,
        "description": "",
        "activity_type": activity_type,
        "delivery_method": delivery_method,
        "workflow_kind": workflow_kind,
        "target_audience": target_audience,
        "staff_delivery_allowed": staff,
        "partner_delivery_allowed": partner,
        "individual_school_allowed": school,
        "cluster_delivery_allowed": cluster,
        "project_delivery_allowed": project,
        "requires_school": school and not cluster,
        "requires_cluster": cluster and not school,
        "requires_project": requires_project,
        "standard_support": standard_support,
        "certified_agency_delivery_allowed": certified_agency,
        # Derived from the workflow kind unless stated. The derivation is the
        # operational truth: cluster work multiplies participants per member
        # school, in-school training takes a total, and a visit takes none.
        "participant_mode": participant_mode
        or default_participant_mode(workflow_kind, participant_counts),
        "requires_current_ssa": requires_ssa,
        "requires_source_activity": requires_source,
        "new_school_only": new_school_only,
        "counts_toward_client_visit": client_visit,
        "counts_toward_client_training": client_training,
        "core_slot_type": core_slot_type or None,
        "salesforce_record_type": salesforce_record_type,
        "salesforce_expected_prefix": salesforce_expected_prefix,
        "evidence_profile": evidence_profile,
        "costing_profile": costing_profile,
        "support_objective": support_objective,
        "follow_up_required": requires_source,
        "mapping_mode": mapping_mode,
        "intervention": intervention,
        # Every governed activity can also be entered as a dated central
        # programme-budget line. This is additive: the school/cluster flags
        # above still govern operational delivery, while this flag makes the
        # same approved title available in the non-school Work Plan drawer so
        # its date and catalogue cost enter the budget.
        "non_school_allowed": non_school,
        "multi_day_allowed": multi_day,
        "requires_participant_counts": participant_counts,
        "programme_category": programme_category,
    }


SOURCE_CATALOGUE_ITEMS = [
    _item(
        "EDTECH_FOUNDATIONS",
        "EdTech Foundations",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        costing_profile="IN_SCHOOL_TRAINING",
        client_training=True,
    ),
    _item(
        "EDTECH_INTEGRATION",
        "EdTech Integration",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        costing_profile="IN_SCHOOL_TRAINING",
        client_training=True,
    ),
    _item(
        "LEARNER_CENTERED_APPROACHES",
        "Learner-Centered Approaches",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        costing_profile="IN_SCHOOL_TRAINING",
        client_training=True,
    ),
    _item(
        "TECH_SKILLS_EMPLOYABLE_FUTURE",
        "Technology Skills for an Employable Future",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        costing_profile="IN_SCHOOL_TRAINING",
        client_training=True,
    ),
    _item(
        "POST_TRAINING_FOLLOWUP_MEETINGS",
        "Post Training Followup Meetings",
        Type.TRAINING,
        Delivery.CLUSTER_MEETING,
        ActivityType.CLUSTER_MEETING,
        mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        intervention=None,
        requires_source=True,
        cluster=True,
        school=False,
        costing_profile="CLUSTER_MEETING",
        evidence_profile="FOLLOW_UP_MEETING",
        support_objective="GENERAL_FOLLOW_UP",
    ),
    _item(
        "SCHOOL_LEADERSHIP",
        "School Leadership",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.LEADERSHIP,
        cluster=True,
        school=False,
    ),
    _item(
        "ACCOUNTING_FINANCIAL_MANAGEMENT",
        "Accounting and Financial Management",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.FINANCIAL_HEALTH,
        target_audience="School leaders and accountants",
        cluster=True,
        school=False,
    ),
    _item(
        "FEES_ENROLMENT_MARKETING",
        "Fees, Enrollment, and Marketing Management",
        Type.TRAINING,
        Delivery.CLUSTER_MEETING,
        ActivityType.CLUSTER_MEETING,
        intervention=INTERVENTION.ENROLMENT,
        target_audience="School leaders",
        cluster=True,
        school=False,
        costing_profile="CLUSTER_MEETING",
    ),
    _item(
        "GOVERNMENT_STATUTORY_REQUIREMENTS",
        "Government and Statutory Requirements",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.GOVERNMENT_REQUIREMENT,
        cluster=True,
        school=False,
        support_objective="STATUTORY_REQUIREMENT",
    ),
    _item(
        "LEARNING_ENVIRONMENT_TRAINING",
        "Learning Environment",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        cluster=True,
        school=False,
    ),
    _item(
        "BIBLICAL_INTEGRATION",
        "Biblical Integration",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.EXPOSURE_TO_WORD_OF_GOD,
        cluster=True,
        school=False,
    ),
    _item(
        "TAM_I",
        "Teaching as a Mission (TAM) I",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.TEACHING_ENVIRONMENT,
        target_audience="Teachers",
        cluster=True,
        school=False,
    ),
    _item(
        "DISCIPLESHIP_DYNAMICS",
        "Discipleship Dynamics",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.EXPOSURE_TO_WORD_OF_GOD,
        cluster=True,
        school=False,
    ),
    _item(
        "TAM_II",
        "Teaching as a Mission (TAM) II",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.TEACHING_ENVIRONMENT,
        target_audience="Teachers",
        cluster=True,
        school=False,
    ),
    _item(
        "CLA_CHARACTER_DEVELOPMENT",
        "CLA Character Development",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.CHRISTLIKE_BEHAVIOUR,
        cluster=True,
        school=False,
    ),
    _item(
        "LITERACY_NUMERACY_PROJECT",
        "Literacy/Numeracy Project",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        project=True,
        cluster=True,
        school=False,
        support_objective="PROJECT_REQUIREMENT",
    ),
    _item(
        "EARLY_CHILDHOOD_EDUCATION_PROJECT",
        "Early Childhood Education Project",
        Type.TRAINING,
        Delivery.ONLINE,
        ActivityType.TRAINING,
        intervention=INTERVENTION.TEACHING_ENVIRONMENT,
        target_audience="Early childhood teachers",
        costing_profile="ONLINE_TRAINING",
        support_objective="PROJECT_REQUIREMENT",
    ),
    _item(
        "CORE_SCHOOL_FOLLOWUP_VISIT",
        "Core School Visits/Meetings School visits",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.CORE_VISIT,
        mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        intervention=None,
        requires_source=True,
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="SVE-",
        costing_profile="STAFF_SCHOOL_VISIT",
        core_slot_type="VISIT",
        client_visit=False,
        support_objective="GENERAL_FOLLOW_UP",
    ),
    _item(
        "CLIENT_SCHOOL_FOLLOWUP_VISIT",
        "Client School Visits/Meetings School visits",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.FOLLOW_UP_VISIT,
        mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        intervention=None,
        requires_source=True,
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="SVE-",
        costing_profile="STAFF_SCHOOL_VISIT",
        client_visit=True,
        support_objective="GENERAL_FOLLOW_UP",
    ),
    _item(
        "NEW_SCHOOL_ORIENTATION",
        "New School Orientation",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.LEADERSHIP,
        new_school_only=True,
        cluster=True,
        school=False,
        support_objective="NEW_SCHOOL_ORIENTATION",
    ),
    _item(
        "PARTNER_MEETINGS_ADMIN",
        "Partner Meetings Admin budget",
        Type.ADMIN,
        Delivery.ADMIN,
        ActivityType.PARTNER_ACTIVITY,
        mapping_mode=MappingMode.ADMINISTRATIVE,
        intervention=None,
        target_audience="Partners and authorized staff",
        evidence_profile="ADMIN_NONE",
        salesforce_record_type="NONE",
        salesforce_expected_prefix="",
        costing_profile="ADMIN_PARTNER_MEETING",
        school=False,
        cluster=False,
        project=False,
        requires_ssa=False,
        support_objective="ADMIN_OPERATION",
    ),
    _item(
        "ASA_SSA_DATA_GATHERING",
        "Data Gathering - ASA/SSA Project",
        Type.TRAINING,
        Delivery.SCHOOL_VISIT,
        ActivityType.BASELINE_SSA_VISIT,
        mapping_mode=MappingMode.SSA_COMPLETION_PREREQUISITE,
        intervention=None,
        evidence_profile="SSA_DATA_GATHERING",
        salesforce_record_type="SSA_DATA_GATHERING",
        salesforce_expected_prefix="",
        costing_profile="SSA_DATA_GATHERING",
        requires_ssa=False,
        support_objective="SSA_COMPLETION",
    ),
    _item(
        "STUDENT_TRAINING_YOUTH_CAMPS",
        "Student Training - Youth camps",
        Type.YOUTH_CAMP,
        Delivery.GROUP,
        ActivityType.TRAINING,
        intervention=INTERVENTION.CHRISTLIKE_BEHAVIOUR,
        target_audience="Students",
        evidence_profile="YOUTH_CAMP_SAFEGUARDING",
        costing_profile="PROGRAMME_EVENT",
        non_school=True,
        multi_day=True,
        participant_counts=True,
        programme_category="Student Programmes",
    ),
    _item(
        "STUDENT_LEADERSHIP_CAMPS",
        "Student Leadership Training - Students Camps",
        Type.YOUTH_CAMP,
        Delivery.GROUP,
        ActivityType.TRAINING,
        intervention=INTERVENTION.CHRISTLIKE_BEHAVIOUR,
        target_audience="Student leaders",
        evidence_profile="YOUTH_CAMP_SAFEGUARDING",
        costing_profile="PROGRAMME_EVENT",
        non_school=True,
        multi_day=True,
        participant_counts=True,
        programme_category="Student Programmes",
    ),
    _item(
        "STUDENT_CONFERENCE_CAMPS",
        "Student Conference/Camps - Student camps",
        Type.YOUTH_CAMP,
        Delivery.GROUP,
        ActivityType.TRAINING,
        intervention=INTERVENTION.CHRISTLIKE_BEHAVIOUR,
        target_audience="Students",
        evidence_profile="YOUTH_CAMP_SAFEGUARDING",
        costing_profile="PROGRAMME_EVENT",
        non_school=True,
        multi_day=True,
        participant_counts=True,
        programme_category="Student Programmes",
    ),
    _item(
        "TEACHER_PEDAGOGY_PROFESSIONALISM",
        "Teacher Pedagogy/Professionalism",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        intervention=INTERVENTION.LEARNING_ENVIRONMENT,
        target_audience="Teachers",
        cluster=True,
        school=False,
    ),
    _item(
        "TEACHER_LEADERSHIP_CONFERENCE",
        "Teacher Leadership Conference/Camp/Retreat",
        Type.TRAINING,
        Delivery.GROUP,
        ActivityType.TRAINING,
        intervention=INTERVENTION.TEACHING_ENVIRONMENT,
        target_audience="Teachers and school leaders",
        costing_profile="PROGRAMME_EVENT",
        non_school=True,
        multi_day=True,
        participant_counts=True,
        programme_category="People Development",
    ),
    _item(
        "CC_SEL",
        "CC-SEL",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        intervention=INTERVENTION.CHRISTLIKE_BEHAVIOUR,
        costing_profile="IN_SCHOOL_TRAINING",
        support_objective="PROJECT_REQUIREMENT",
        client_training=True,
    ),
]


def _standard(
    stable_code,
    display_name,
    activity_type,
    delivery_method,
    workflow_kind,
    *,
    costing_profile,
    evidence_profile,
    salesforce_record_type,
    salesforce_expected_prefix="",
    participant_mode=None,
    cluster=False,
    school=True,
    certified_agency=False,
    target_audience="School staff",
    support_objective="STANDARD_FIELD_SUPPORT",
    description="",
):
    """Ordinary field support — always available, never Project-gated.

    ``requires_ssa=False`` is the point of the whole exercise. Intervention
    support drawn from the programme's named curriculum still requires an
    applicable SSA; a school visit does not, and blocking one on a missing
    assessment is how a field officer ends up unable to visit a school.
    The target intervention is still recorded whenever the planner names one,
    so SSA-guided support keeps its analytics lineage either way.
    """
    return _item(
        stable_code,
        display_name,
        activity_type,
        delivery_method,
        workflow_kind,
        intervention=None,
        mapping_mode=MappingMode.ANY_SSA_INTERVENTION,
        target_audience=target_audience,
        evidence_profile=evidence_profile,
        salesforce_record_type=salesforce_record_type,
        salesforce_expected_prefix=salesforce_expected_prefix,
        costing_profile=costing_profile,
        school=school,
        cluster=cluster,
        requires_ssa=False,
        support_objective=support_objective,
        # Standard support is planned against a school or cluster, not as a
        # standalone dated programme line at a venue.
        non_school=False,
        standard_support=True,
        participant_mode=participant_mode,
        certified_agency=certified_agency,
    ) | {"description": description}


#: §3/§6 — the standard responses every planning context must be able to
#: schedule. One per workflow kind: the drawer derives an activity's costing
#: from the purpose the planner chose, and two standard items costing the same
#: kind would leave the resolver unable to choose (which is precisely the
#: ambiguity that blocked in-school training, with five candidates and no way
#: to pick between them).
STANDARD_SUPPORT_ITEMS = [
    _standard(
        "STANDARD_SCHOOL_VISIT",
        "School Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.SCHOOL_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        description=(
            "Ordinary support visit to one school. Scheduled against the "
            "intervention it is meant to move; no participant quantity."
        ),
    ),
    _standard(
        "STANDARD_IN_SCHOOL_TRAINING",
        "In-School Training",
        Type.TRAINING,
        Delivery.IN_SCHOOL_TRAINING,
        ActivityType.IN_SCHOOL_TRAINING,
        costing_profile="IN_SCHOOL_TRAINING",
        evidence_profile="TRAINING_ATTENDANCE",
        salesforce_record_type="TRAINING",
        salesforce_expected_prefix="TS-",
        participant_mode=ParticipantMode.BY_CATEGORY,
        certified_agency=True,
        description=(
            "Training delivered at one school against a target intervention, "
            "outside the programme's named curriculum titles."
        ),
    ),
    _standard(
        "STANDARD_CLUSTER_MEETING",
        "Cluster Meeting",
        Type.TRAINING,
        Delivery.CLUSTER_MEETING,
        ActivityType.CLUSTER_MEETING,
        costing_profile="CLUSTER_MEETING",
        evidence_profile="FOLLOW_UP_MEETING",
        salesforce_record_type="TRAINING",
        salesforce_expected_prefix="TS-",
        participant_mode=ParticipantMode.PER_SCHOOL,
        cluster=True,
        school=False,
        certified_agency=True,
        target_audience="School leaders",
        description=(
            "Cluster-wide meeting. Participants are planned per member school "
            "and the total is derived from live cluster membership."
        ),
    ),
    _standard(
        "STANDARD_CLUSTER_TRAINING",
        "Cluster Training",
        Type.TRAINING,
        Delivery.CLUSTER_TRAINING,
        ActivityType.CLUSTER_TRAINING,
        costing_profile="CLUSTER_TRAINING",
        evidence_profile="TRAINING_ATTENDANCE",
        salesforce_record_type="TRAINING",
        salesforce_expected_prefix="TS-",
        participant_mode=ParticipantMode.PER_SCHOOL,
        cluster=True,
        school=False,
        certified_agency=True,
        description=(
            "Cluster-wide training outside the programme's named curriculum "
            "titles. Participants are planned per member school."
        ),
    ),
    _standard(
        "STANDARD_IN_SCHOOL_COACHING_VISIT",
        "In-School Coaching Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.IN_SCHOOL_COACHING_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        description="One-to-one coaching at the school. No participant quantity.",
    ),
    _standard(
        "STANDARD_TRAINING_FOLLOW_UP_VISIT",
        "Training Follow-up Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.TRAINING_FOLLOW_UP_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        description="Follow-up on training already delivered at the school.",
    ),
    _standard(
        "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
        "School Visit + SSA Collection",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
        costing_profile="SSA_DATA_GATHERING",
        evidence_profile="SSA_DATA_GATHERING",
        salesforce_record_type="SSA_DATA_GATHERING",
        support_objective="SSA_COLLECTION",
        description="Support visit that also collects the school's SSA.",
    ),
    _standard(
        "STANDARD_IN_SCHOOL_SUPPORT",
        "In-School Support",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.IN_SCHOOL_SUPPORT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        description="General in-school support against a target intervention.",
    ),
    _standard(
        "STANDARD_DONOR_VISIT",
        "Donor Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.DONOR_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        target_audience="Donors and school staff",
        support_objective="RELATIONSHIP",
        description="Hosting a donor or supporter at a school.",
    ),
    _standard(
        "STANDARD_STORY_GATHERING_VISIT",
        "Content Gathering Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.STORY_GATHERING_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        support_objective="CONTENT_GATHERING",
        description="Gathering stories, photography or content at a school.",
    ),
    _standard(
        "STANDARD_SCHOOL_INVITATION",
        "School Invitation",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.SCHOOL_INVITATION,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        support_objective="RELATIONSHIP",
        description="Attending a school event Edify was invited to.",
    ),
    _standard(
        "STANDARD_SOCIAL_VISIT",
        "Social Visit",
        Type.SCHOOL_VISIT,
        Delivery.SCHOOL_VISIT,
        ActivityType.SOCIAL_VISIT,
        costing_profile="STAFF_SCHOOL_VISIT",
        evidence_profile="SCHOOL_VISIT_FORM",
        salesforce_record_type="VISIT",
        salesforce_expected_prefix="VS-",
        support_objective="RELATIONSHIP",
        description="Relationship visit with no assessment or training component.",
    ),
]


CATALOGUE_ITEMS = [*SOURCE_CATALOGUE_ITEMS, *STANDARD_SUPPORT_ITEMS]


ALTERNATE_STABLE_CODES = {
    "TECHNOLOGY_SKILLS_EMPLOYABLE_FUTURE": "TECH_SKILLS_EMPLOYABLE_FUTURE",
    "FEES_ENROLMENT_MARKETING_MANAGEMENT": "FEES_ENROLMENT_MARKETING",
    "CORE_SCHOOL_VISIT_FOLLOWUP": "CORE_SCHOOL_FOLLOWUP_VISIT",
    "CLIENT_SCHOOL_VISIT_FOLLOWUP": "CLIENT_SCHOOL_FOLLOWUP_VISIT",
    "PARTNER_MEETING_ADMIN": "PARTNER_MEETINGS_ADMIN",
    "DATA_GATHERING_ASA_SSA": "ASA_SSA_DATA_GATHERING",
}


# The programme's 28 named interventions are governed source data and their
# count is pinned deliberately — an item appearing or vanishing there is a
# curriculum change, not a code change. Standard field support is counted
# separately so the two can never be confused for one another.
assert len(SOURCE_CATALOGUE_ITEMS) == 28
assert len(STANDARD_SUPPORT_ITEMS) == 12
assert len(CATALOGUE_ITEMS) == 40
assert len({row["stable_code"] for row in CATALOGUE_ITEMS}) == 40

# One standard-support item per workflow kind (mirrored by a database
# constraint). Without this the purpose → costing derivation has no single
# answer and ordinary support silently becomes unschedulable again.
_standard_kinds = [row["workflow_kind"] for row in STANDARD_SUPPORT_ITEMS]
assert len(_standard_kinds) == len(set(_standard_kinds)), sorted(_standard_kinds)
