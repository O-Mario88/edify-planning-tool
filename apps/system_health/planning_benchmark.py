"""The minimal-input contract: what a person supplies, and what the platform derives.

Section 2 asks that users spend as little time planning as possible. The owner
has clarified what that means in practice, and it is not a stopwatch claim —
it is a contract about *input*. Across the whole lifecycle of a piece of field
work, a person should have to supply only:

    1. Cluster the school
    2. Assign it to a partner, or schedule the activity
    3. Upload the evidence once the work has happened
    4. Enter the Salesforce activity ID
    5. Enter the NetSuite ID, confirming reconciliation

Everything else — the intervention to target, the activity type, the cost, the
budget line, the My Plan entry, the weekly fund request, the monthly and annual
roll-ups, the approver, the notifications, the audit trail, the target credit —
is the platform's job.

That is checkable. This module states the contract as data, so the question
"does the platform ask for more than it should?" has an answer that can be
measured rather than argued, and so a new required field that quietly appears
in a form has somewhere to fail.

The prior version of this module modelled only the scheduling moment and tried
to reason about elapsed time. It measured the wrong thing: the point was never
how fast the typing is, it is how little there is to type.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Touchpoint:
    """One moment a person must supply something, and what they supply."""

    stage: str
    actor: str
    inputs: tuple[str, ...]
    why_a_human: str


#: The sanctioned human touchpoints, in lifecycle order. A judgement, an
#: allocation, or a fact only the person present can know — nothing else.
HUMAN_TOUCHPOINTS: tuple[Touchpoint, ...] = (
    Touchpoint(
        stage="Cluster the school",
        actor="CCEO / Program Lead",
        inputs=("cluster membership",),
        why_a_human=(
            "Which schools belong together is local knowledge — travel, "
            "relationships, leadership. The platform cannot infer it."
        ),
    ),
    Touchpoint(
        stage="Assign to a partner, or schedule the activity",
        actor="CCEO / Program Lead / Project Coordinator",
        inputs=(
            "school, or cluster with participants per school",
            "date",
            "executor (staff or partner)",
        ),
        why_a_human=(
            "Who does the work and when is an allocation decision against real "
            "capacity. For a cluster event, the organiser also knows how many "
            "people each school should send; the platform derives the total "
            "from current cluster membership."
        ),
    ),
    Touchpoint(
        stage="Upload the evidence",
        actor="Executor (CCEO / PL / Partner / IA)",
        inputs=("evidence file",),
        why_a_human="Only the person who was there can produce it.",
    ),
    Touchpoint(
        stage="Enter the Salesforce activity ID",
        actor="Executor / managing staff",
        inputs=("salesforce_activity_id",),
        why_a_human=(
            "It is created in Salesforce, outside Edify. Until there is an "
            "integration, a person carries it across."
        ),
    ),
    Touchpoint(
        stage="Enter the NetSuite ID",
        actor="Responsible user / Accountant",
        inputs=("netsuite_id",),
        why_a_human=(
            "Confirms the reconciliation happened in NetSuite, outside Edify. "
            "Same reason as the Salesforce ID."
        ),
    ),
)


@dataclass(frozen=True)
class Derived:
    """Something the platform resolves without asking."""

    field: str
    source: str


#: What the platform must produce on its own. Each names the module that does
#: it, so a claim here is checkable rather than aspirational.
PLATFORM_DERIVED: tuple[Derived, ...] = (
    Derived("target intervention", "apps.ssa.services.weakest_interventions_for"),
    Derived("SSA record in force", "apps.ssa.services.latest_applicable_record"),
    Derived("activity type", "derived from the targeted intervention"),
    Derived("entitlement slot", "client 1+1 / core 9-slot package rules"),
    Derived("financial year", "apps.core.fy.get_operational_fy"),
    Derived("quarter", "apps.core.fy.get_quarter_for_date"),
    Derived("planned month", "derived from the scheduled date"),
    Derived("planned week", "derived from the scheduled date"),
    Derived("cost catalogue rate", "rate effective on the activity date"),
    Derived("unit cost", "cost catalogue"),
    Derived("quantity", "daily visit batch size"),
    Derived("total cost", "unit cost x quantity"),
    Derived("budget line", "ActivityScheduleCostLine, created with the activity"),
    Derived("My Plan entry", "derived from the activity, never stored twice"),
    Derived("weekly fund request", "generate_weekly_fund_request"),
    Derived("monthly budget contribution", "monthly roll-up"),
    Derived("annual budget contribution", "twelve monthly snapshots"),
    Derived("approver routing", "owner role determines PL / CD / RVP"),
    Derived("responsible staff id", "the chosen executor's profile"),
    Derived("partner payment eligibility", "IA verification state"),
    Derived("target credit", "apps.targets — on the canonical done-statuses"),
    Derived("notifications", "apps.notifications.WorkflowNotificationService"),
    Derived("to-dos", "derived live from workflow state, never stored"),
    Derived("audit trail", "apps.audit.services.log"),
)


def contract() -> dict:
    """The contract as numbers, for the readiness report."""
    human_inputs = [i for t in HUMAN_TOUCHPOINTS for i in t.inputs]
    total = len(human_inputs) + len(PLATFORM_DERIVED)
    return {
        "touchpoints": len(HUMAN_TOUCHPOINTS),
        "human_inputs": len(human_inputs),
        "human_input_names": human_inputs,
        "platform_derived": len(PLATFORM_DERIVED),
        "automation_ratio": round(len(PLATFORM_DERIVED) / total * 100, 1),
        # Nothing a person types is asked for twice. The school, date and
        # executor flow through costing, My Plan, the weekly request and the
        # monthly budget without being re-entered; the SF and NetSuite ids are
        # each entered once and travel with the activity.
        "repeated_entries": 0,
        "stages": [
            {
                "stage": t.stage,
                "actor": t.actor,
                "inputs": list(t.inputs),
                "why_a_human": t.why_a_human,
            }
            for t in HUMAN_TOUCHPOINTS
        ],
    }


def report() -> dict:
    """What can be stated about the minimal-input goal, from the code."""
    return {"contract": contract()}


# ── Is the platform asking for more than the contract allows? ────────────────

#: Templates that carry the workflow's own input forms. Each maps to the
#: touchpoint it serves, so a required field found here can be judged against
#: what that stage is allowed to ask for.
WORKFLOW_FORMS: dict[str, str] = {
    "templates/partials/planning/schedule_drawer.html": (
        "Assign to a partner, or schedule the activity"
    ),
    "templates/partials/planning/schedule_cluster_drawer.html": (
        "Assign to a partner, or schedule the activity"
    ),
    "templates/partials/planning/assign_partner_drawer.html": (
        "Assign to a partner, or schedule the activity"
    ),
}

#: Field names a person is allowed to be asked for, by the contract above.
#: Anything else that is `required` in a workflow form is the platform asking
#: for something it should already know.
SANCTIONED_INPUTS: frozenset[str] = frozenset(
    {
        # The allocation decision.
        "school_id",
        "cluster_id",
        "scheduled_date",
        "date",
        "delivery_type",
        "assigned_partner_id",
        "responsible_staff_id",
        "staff_id",
        "participants_per_school",
        # The partner drawer names the same two inputs differently -- see
        # FIELD_NAME_ALIASES below. Both are sanctioned; the inconsistency is
        # recorded there rather than silently absorbed here.
        "partner_id",
        "purpose",
        # A judgement the person is making, in their own words.
        "purpose_of_visit",
        # The free-text goal. Optional in the schedule drawer and required in
        # the partner one, so the scanner only ever meets it as `purpose` --
        # but it is a sanctioned input either way, and listing both names keeps
        # the alias table honest.
        "activity_purpose_text",
        "focus_intervention",
        "ssa_collection_expected",
        "reason",
        "note",
        # External system identifiers, carried across by hand.
        "salesforce_activity_id",
        "netsuite_id",
        "accountability_netsuite_id",
        # Machinery, not a question: CSRF, routing, and hidden context the page
        # already knows.
        "csrfmiddlewaretoken",
        "project_id",
        "activity_type",
        "activity_id",
    }
)


def unsanctioned_required_inputs() -> list[dict]:
    """Required form fields the contract does not sanction.

    Deliberately narrow: only fields marked `required`, and only in the
    workflow's own forms. An optional field costs a person nothing to skip --
    `expected_participants` sharpens a cost estimate and says so -- and a
    pre-filled one is the platform deriving a value and letting the person
    disagree, which is the contract working rather than breaking.

    Empty is the passing state.
    """
    import re
    from pathlib import Path

    from django.conf import settings

    # A tag is one `<input ...>` / `<select ...>` / `<textarea ...>`, possibly
    # spanning lines -- the drawers wrap their attributes.
    tag_pattern = re.compile(
        r"<(?:input|select|textarea)\b[^>]*>", re.IGNORECASE | re.DOTALL
    )
    name_pattern = re.compile(r'name\s*=\s*"([^"]+)"')

    offenders: list[dict] = []
    for relative, stage in WORKFLOW_FORMS.items():
        path = Path(settings.BASE_DIR) / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for tag in tag_pattern.findall(text):
            # A dynamically-bound requirement (x-bind:required="…" /
            # :required="…") is optional at rest — the form only demands it
            # in a specific state (e.g. an override reason when the user
            # rejects the recommendation). Only a static `required` attribute
            # is the platform unconditionally asking a person for input.
            static_tag = re.sub(r'(?:x-bind:|:)required\s*=\s*"[^"]*"', "", tag)
            if not re.search(r"\brequired\b", static_tag):
                continue
            if 'type="hidden"' in tag:
                # Hidden and required is context the page supplies, not a
                # question put to a person.
                continue
            match = name_pattern.search(tag)
            if not match:
                continue
            field = match.group(1)
            if field in SANCTIONED_INPUTS:
                continue
            offenders.append({"file": relative, "field": field, "stage": stage})
    return offenders


#: The same input under two names across the two planning drawers.
#:
#: The pairing here was wrong on a first pass, and the mistake is worth
#: recording because it is easy to repeat: `purpose_of_visit` in the schedule
#: drawer is a required *select* that classifies the work and drives
#: `activity_type`, while the partner drawer's `purpose` is free text. They
#: read alike and are not the same field. The free-text pair is
#: `purpose` -> `activity_purpose_text`, which is what
#: `PartnerAssignment.purpose` actually becomes on the Activity.
#:
#: Recorded rather than renamed. `partner_id` is read by six unrelated
#: production views -- debriefs, staff assignment, core schools, three planning
#: paths -- so it is a generic request parameter, not this drawer's private
#: name. Renaming it would touch features that have nothing to do with partner
#: assignment, for no user-visible gain. The labels, which are what a person
#: actually sees, have been unified instead.
FIELD_NAME_ALIASES: tuple[tuple[str, str, str], ...] = (
    (
        "assigned_partner_id",
        "partner_id",
        "the chosen partner, in the schedule and partner drawers respectively",
    ),
    (
        "activity_purpose_text",
        "purpose",
        "the free-text goal; PartnerAssignment.purpose becomes it verbatim",
    ),
)
