"""Planning Productivity Benchmark — the mechanical half of the 95% claim.

Section 2 requires the planning-time reduction to be measured against a
verified baseline, and forbids claiming it because automation exists. That
baseline has two halves, and only one of them can be produced from code:

**Mechanical** (measured here). For one scheduled activity, how many fields
must a human supply, how many the platform derives, how many pages are
involved, and how many round trips. These are properties of the workflow and
can be counted exactly.

**Human** (cannot be produced here). Elapsed time, active interaction time,
validation errors, abandoned attempts, and how long it takes someone to find
the next page. Section 2 asks for representative staff performing real tasks.
No amount of static analysis substitutes for watching a person do the work,
and a percentage derived without it would be the exact claim §2 prohibits.

So this module reports the mechanical ratio and states plainly that the time
reduction is unproven until the human half is collected. `record_observation`
is where those observations go when you have them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    name: str
    supplied_by: str  # "human" | "platform"
    source: str = ""


#: What creating one funded, scheduled activity actually requires.
#:
#: Derived by reading apps.activities.services.create and the planning views:
#: every field the Activity + ActivityBudgetLine + My Plan + weekly request
#: chain needs before the work is fundable. "platform" means the value is
#: resolved without the person typing or choosing it.
PLANNED_ACTIVITY_FIELDS: tuple[FieldSpec, ...] = (
    # The four decisions that are genuinely the planner's.
    FieldSpec("school_or_cluster", "human", "the planner chooses who to support"),
    FieldSpec("scheduled_date", "human", "the planner chooses when"),
    FieldSpec("executor", "human", "staff member or delivery partner"),
    FieldSpec("override_reason", "human", "only when departing from the recommendation"),
    # Everything else the platform resolves.
    FieldSpec("ssa_record", "platform", "apps.ssa.services.latest_applicable_record"),
    FieldSpec("target_intervention", "platform", "SSA weakest-intervention ranking"),
    FieldSpec("activity_type", "platform", "derived from the intervention"),
    FieldSpec("entitlement_slot", "platform", "client 1+1 / core 9-slot package"),
    FieldSpec("fy", "platform", "apps.core.fy.get_operational_fy"),
    FieldSpec("quarter", "platform", "apps.core.fy.get_quarter_for_date"),
    FieldSpec("planned_month", "platform", "derived from the date"),
    FieldSpec("planned_week", "platform", "derived from the date"),
    FieldSpec("cost_catalogue_item", "platform", "rate effective on the activity date"),
    FieldSpec("unit_cost", "platform", "cost catalogue"),
    FieldSpec("quantity", "platform", "daily visit batch size"),
    FieldSpec("total_cost", "platform", "unit cost x quantity"),
    FieldSpec("budget_line", "platform", "ActivityScheduleCostLine, created with the activity"),
    FieldSpec("my_plan_entry", "platform", "derived from the activity, never stored twice"),
    FieldSpec("weekly_fund_request_line", "platform", "generate_weekly_fund_request"),
    FieldSpec("monthly_budget_contribution", "platform", "monthly roll-up"),
    FieldSpec("annual_budget_contribution", "platform", "twelve monthly snapshots"),
    FieldSpec("approver", "platform", "routing by owner role"),
    FieldSpec("responsible_staff_id", "platform", "the executor's profile"),
    FieldSpec("notification", "platform", "workflow notification service"),
    FieldSpec("audit_event", "platform", "apps.audit.services.log"),
)


def mechanical_profile() -> dict:
    """Fields a human supplies versus fields the platform derives."""
    human = [f for f in PLANNED_ACTIVITY_FIELDS if f.supplied_by == "human"]
    platform = [f for f in PLANNED_ACTIVITY_FIELDS if f.supplied_by == "platform"]
    total = len(PLANNED_ACTIVITY_FIELDS)
    return {
        "fields_total": total,
        "fields_human": len(human),
        "fields_platform": len(platform),
        "human_field_names": [f.name for f in human],
        "automation_ratio": round(len(platform) / total * 100, 1),
        # Section 2's second gate: at least 90% reduction in repeated manual
        # entry. Nothing in the human list is re-typed downstream -- the same
        # school, date and executor flow through costing, My Plan, the weekly
        # request and the monthly budget without being asked for again.
        "repeated_entries": 0,
    }


@dataclass
class Observation:
    """One timed run of a planning task by a real person.

    The fields §2 names. Recorded, never inferred: `elapsed_seconds` is what a
    stopwatch said, not what a query estimated.
    """

    role: str
    task: str
    variant: str  # "baseline" | "optimised"
    elapsed_seconds: float
    active_seconds: float
    pages_visited: int
    clicks: int
    fields_typed: int
    repeated_entries: int
    validation_errors: int
    abandoned: bool = False
    notes: str = ""


@dataclass
class Benchmark:
    """A set of observations, and what may honestly be concluded from them."""

    observations: list[Observation] = field(default_factory=list)

    def record(self, observation: Observation) -> None:
        self.observations.append(observation)

    def _median(self, variant: str, attribute: str) -> float | None:
        values = sorted(
            getattr(o, attribute)
            for o in self.observations
            if o.variant == variant and not o.abandoned
        )
        if not values:
            return None
        middle = len(values) // 2
        if len(values) % 2:
            return float(values[middle])
        return (values[middle - 1] + values[middle]) / 2

    def reduction(self) -> dict:
        """The §2 conclusion, or an explicit refusal to draw one.

        Returns `verified: False` with a reason whenever the evidence is
        missing. A benchmark that reports a percentage from no observations is
        worse than one that reports nothing.
        """
        baseline = self._median("baseline", "active_seconds")
        optimised = self._median("optimised", "active_seconds")

        if baseline is None or optimised is None:
            return {
                "verified": False,
                "reason": (
                    "No paired baseline and optimised observations. Section 2 "
                    "requires representative staff performing real tasks; the "
                    "reduction cannot be computed from the code alone."
                ),
                "baseline_median_active_seconds": baseline,
                "optimised_median_active_seconds": optimised,
            }
        if baseline <= 0:
            return {"verified": False, "reason": "Baseline median is zero."}

        reduction = (baseline - optimised) / baseline * 100
        return {
            "verified": True,
            "baseline_median_active_seconds": baseline,
            "optimised_median_active_seconds": optimised,
            "reduction_percent": round(reduction, 1),
            "meets_95_percent_target": reduction >= 95.0,
            "sample_size": {
                "baseline": sum(
                    1 for o in self.observations if o.variant == "baseline"
                ),
                "optimised": sum(
                    1 for o in self.observations if o.variant == "optimised"
                ),
            },
        }


def report() -> dict:
    """What can be stated today about the planning-productivity goal."""
    return {
        "mechanical": mechanical_profile(),
        "time_reduction": Benchmark().reduction(),
    }
