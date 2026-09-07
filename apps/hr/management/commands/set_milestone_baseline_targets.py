"""Give the linked milestones a target, so their meters can show a percentage.

THE REQUEST (owner, 2026-09-07)

"Set targets for the linked milestones so the percentages show."

A milestone's meter draws planned and completed work against its target; with
no target there is no percentage. Sixty-six of the sixty-eight FY2027
milestones arrived from the source document with no figure, and setting one
is the RVP's decision in Define metric. The owner asked for them to be set, so
this sets them — through that same governed path (define_milestone), as
DEFINED and not approved, with the derivation written into the metric's
description so the RVP can see exactly where each number came from and change
it.

WHERE A BASELINE COMES FROM

  1. Last year's delivery. If the milestone's own rules measured anything in
     the previous financial year (completed plus still-planned work), that is
     the floor: at least match last year.
  2. The normalized Uganda plan. Where it gives the equivalent milestone an
     explicit number, that number is a traceable baseline for the RVP row.
  3. Coverage. A coverage milestone with no history — visit coverage, SSA
     coverage, school training, schools trained — is a fraction of a school
     family, so its target is that family's size today: every core school,
     every client school, every school.
  4. Explicit cadence. "Monthly" means twelve sessions in the FY, "one per
     country" means one, and "at least twice" means two for Uganda.
  5. Otherwise one. This is a deliberately conservative draft baseline, not
     an invented delivery claim: it unlocks the percentage the owner asked
     for while remaining inactive until the RVP confirms or changes it.

Idempotent: a milestone that already has a target is left alone unless
--overwrite is passed. --dry-run computes and reports without writing.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

# The coverage milestones and the school family each one is a fraction of.
COVERAGE_FAMILIES = {
    "CORE_SCHOOL_VISIT_COVERAGE": "core",
    "CLIENT_SCHOOL_VISIT_COVERAGE": "client",
    "CORE_SSA_COVERAGE": "core",
    "CLIENT_SSA_COVERAGE": "client",
    "CORE_SCHOOL_TRAINING": "core",
    "CLIENT_SCHOOL_TRAINING": "client",
    "SCHOOLS_TRAINED": "all",
    # The regional row names ECD training but not a participant population;
    # its linked rule counts distinct schools, so the portfolio is the only
    # like-for-like denominator available.
    "ECD": "all",
}

# Exact figures already normalized from ``Priorities.docx (Uganda July Plan)``.
# Aliases bridge the short RVP-source codes to their equivalent Uganda rows.
# Values stay in the unit produced by the linked activity rule; percentage
# source rows are intentionally absent because this meter counts planned work,
# not a manual rate with a separate denominator.
SOURCE_BASELINES = {
    "DC_TRAINING": 4157,
    "CLA": 4119,
    "SEL": 650,
    "LITERACY": 7000,
    "TAM": 1000,
    "TEACHERS_TRAINED": 37000,
    "LEADERS_TRAINED": 18500,
    "MONTHLY_MFI_MEETINGS": 10,
    "ACCOUNTANTS_TRAINING": 1800,
    "EDTECH_FOUNDATIONS": 2000,
    "EDTECH_INTEGRATION": 300,
    "EDTECH_SKILLING": 150,
    "PARTNER_REVIEW_MEETINGS": 4,
}

CADENCE_BASELINES = {
    "MONTHLY_MFI_MENTORSHIP": (12, "twelve monthly sessions in the FY"),
    "EDTECH_CONFERENCE": (1, "one conference per country in the source plan"),
    "COUNTRY_OPERATION_VISITS": (
        2,
        "the source plan says each country or operation is visited at least twice",
    ),
}

UNIT_FOR = {
    "schools": "schools",
    "activities": "activities",
    "teachers": "teachers",
    "leaders": "leaders",
}


class Command(BaseCommand):
    help = "Set data-derived baseline targets on the plan-linked milestones (defined, not approved)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--fy",
            help="The cycle year to set targets for (default: newest draft cycle).",
        )
        parser.add_argument(
            "--baseline-fy",
            help="The year to read last delivery from (default: the year before the cycle).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace targets that already exist.",
        )
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        report = set_baseline_targets(
            fy=options["fy"],
            baseline_fy=options["baseline_fy"],
            overwrite=options["overwrite"],
            dry_run=options["dry_run"],
            actor_id=options["actor_id"],
        )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))


def family_sizes() -> dict[str, int]:
    from apps.hr.target_distribution import CLIENT_FAMILY, CORE_FAMILY
    from apps.schools.lifecycle_service import active_schools

    schools = active_schools()
    return {
        "core": schools.filter(school_type__in=CORE_FAMILY).count(),
        "client": schools.filter(school_type__in=CLIENT_FAMILY).count(),
        "all": schools.count(),
    }


def derive_baseline(
    milestone, measured: dict | None, sizes: dict[str, int]
) -> tuple[Decimal | None, str, str]:
    """Return the draft target, its plan unit, and its provenance."""

    unit = UNIT_FOR.get(
        (measured or {}).get("unit", ""), (measured or {}).get("unit", "activities")
    )
    if measured:
        last_year = int(measured["completed"]) + int(measured["planned"])
        if last_year > 0:
            return (
                Decimal(last_year),
                unit,
                f"last year delivered {measured['completed']} and planned {measured['planned']} — at least match it",
            )
    if milestone.code in SOURCE_BASELINES:
        target = SOURCE_BASELINES[milestone.code]
        return (
            Decimal(target),
            unit,
            f"equivalent Uganda July Plan target ({target:,})",
        )
    family = COVERAGE_FAMILIES.get(milestone.code)
    if family:
        size = sizes[family]
        if size > 0:
            label = {"core": "core school", "client": "client school", "all": "school"}[
                family
            ]
            return (
                Decimal(size),
                "schools",
                f"coverage of every {label} in the portfolio today ({size})",
            )
    cadence = CADENCE_BASELINES.get(milestone.code)
    if cadence:
        target, how = cadence
        return Decimal(target), unit, how
    return (
        Decimal("1"),
        unit,
        "minimum one-unit draft baseline; RVP confirmation required",
    )


def set_baseline_targets(
    *, fy=None, baseline_fy=None, overwrite=False, dry_run=False, actor_id="system"
) -> dict:
    from apps.audit.services import log as audit_log
    from apps.hr.models import (
        MilestoneActivityRule,
        PriorityMilestone,
        StrategicPriorityCycle,
    )
    from apps.hr.priority_seed import ROLE_APPLICABILITY
    from apps.hr.priority_services import define_milestone
    from apps.hr.target_distribution import milestone_plan_progress

    if not fy:
        fy = (
            StrategicPriorityCycle.objects.exclude(status="archived")
            .order_by("-financial_year")
            .values_list("financial_year", flat=True)
            .first()
        )
    baseline_fy = baseline_fy or str(int(fy) - 1)
    linked_ids = set(
        MilestoneActivityRule.objects.filter(active=True).values_list(
            "milestone_id", flat=True
        )
    )
    milestones = list(
        PriorityMilestone.objects.filter(id__in=linked_ids, priority__fy=fy)
        .select_related("priority")
        .order_by("priority__sequence", "source_order")
    )
    measured = milestone_plan_progress(milestones, fy=baseline_fy)
    sizes = family_sizes()
    report = {
        "fy": fy,
        "baselineFy": baseline_fy,
        "dryRun": dry_run,
        "set": [],
        "kept": [],
        "skipped": [],
    }

    with transaction.atomic():
        for milestone in milestones:
            if milestone.target_value and not overwrite:
                report["kept"].append(
                    {"code": milestone.code, "target": str(milestone.target_value)}
                )
                continue
            target, unit, how = derive_baseline(
                milestone, measured.get(milestone.id), sizes
            )
            if target is None:
                report["skipped"].append({"code": milestone.code, "why": how})
                continue
            roles = ROLE_APPLICABILITY.get(milestone.priority.code) or [
                "CountryDirector"
            ]
            payload = {
                "canonicalTitle": milestone.title,
                "metricKey": f"plan_{milestone.code.lower()}",
                "measurementType": "count",
                "targetValue": str(target),
                "targetUnit": unit,
                "dataSource": "activities.Activity",
                "canonicalService": "apps.hr.target_distribution.milestone_plan_progress",
                "qualityGate": "Plan-linked activity in a completed status",
                "dueDate": date(int(fy), 9, 30),
                "responsibleRoles": roles,
                "countingBasis": "milestone activity rules",
                "metricDescription": (
                    f"Baseline target, {how}. Set by set_milestone_baseline_targets on "
                    f"{date.today().isoformat()} for the RVP to confirm or change."
                ),
            }
            define_milestone(milestone, data=payload, principal=None)
            audit_log(
                action="milestone.baseline_target_set",
                subject_kind="milestone",
                subject_id=milestone.id,
                actor_id=actor_id,
                actor_role="system",
                payload={
                    "code": milestone.code,
                    "target": str(target),
                    "unit": unit,
                    "how": how,
                },
            )
            report["set"].append(
                {
                    "code": milestone.code,
                    "target": str(target),
                    "unit": unit,
                    "how": how,
                }
            )
        if dry_run:
            transaction.set_rollback(True)
    report["counts"] = {k: len(report[k]) for k in ("set", "kept", "skipped")}
    return report
