"""The four-weakest backfill must repair what it can and refuse to invent the rest.

Production carries 244 active CorePlans whose `interventions` is empty because
they were onboarded before that field was written. The recommendation drives
which four interventions a school's nine-slot package targets and which two go
to a Partner, so a wrong value sends real staff to real schools for the wrong
reason. The command therefore only ever writes what the canonical verified-SSA
service derives.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.core_schools.models import CorePlan, cplan_id
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


FY = "2026"

# Ascending score order -> the four weakest are financial_health (2.0),
# leadership (3.0), enrolment (4.0), learning_environment (5.0).
SCORES = {
    "financial_health": 2.0,
    "leadership": 3.0,
    "enrolment": 4.0,
    "learning_environment": 5.0,
    "christlike_behaviour": 7.5,
    "exposure_to_word_of_god": 7.6,
    "government_requirements": 7.7,
    "teachers_environment": 7.8,
}


def _school(tag):
    """A core school in its own geography, so classes never collide."""
    region = Region.objects.create(name=f"Backfill Region {tag}")
    district = District.objects.create(name=f"Backfill District {tag}", region=region)
    return School.objects.create(
        school_id=f"SCH-BF-{tag}",
        name=f"Backfill {tag} Primary",
        region=region,
        district=district,
        school_type="core",
    )


def _confirmed_ssa(school, scores):
    # "Verified" SSA is verification_status="confirmed" — there is no separate
    # boolean, and conflating the two silently reads unverified data as
    # authoritative.
    # SsaRecord.school is a FK to School.id (a cuid). CorePlan.school_id holds
    # the BUSINESS school_id instead — the two key spaces are easy to swap and
    # the swap only shows up as a foreign-key violation at commit.
    record = SsaRecord.objects.create(
        school_id=school.id,
        fy=FY,
        verification_status="confirmed",
        date_of_ssa=date(int(FY), 1, 15),
    )
    for intervention, score in scores.items():
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
    return record


def _plan(school, baseline_id=None, interventions=None):
    # CorePlan's primary key is the deterministic cplan-{schoolId}, not an
    # auto-generated cuid — omitting it inserts an empty-string pk.
    return CorePlan.objects.create(
        id=cplan_id(school.school_id),
        school_id=school.school_id,
        fy=FY,
        status="Active",
        baseline_ssa_record_id=baseline_id or "",
        interventions=interventions,
    )


class _Fixture(TestCase):
    pass


class BackfillWritesOnlyDerivableRecommendationsTest(_Fixture):
    def setUp(self):
        self.weak = _school("WEAK")
        record = _confirmed_ssa(self.weak, SCORES)
        self.weak_plan = _plan(self.weak, baseline_id=record.id)

        # No SSA at all -> nothing may be written for this plan.
        self.blind = _school("BLIND")
        self.blind_plan = _plan(self.blind)

    def _run(self, *args):
        out = StringIO()
        call_command(
            "repair_ecosystem_data", "--only", "core-recommendations", *args, stdout=out
        )
        return out.getvalue()

    def test_dry_run_reports_but_writes_nothing(self):
        output = self._run()

        self.weak_plan.refresh_from_db()
        self.assertIsNone(
            self.weak_plan.interventions, "a dry run must not touch the database"
        )
        self.assertIn("DRY-RUN", output)

    def test_apply_persists_the_four_weakest_in_priority_order(self):
        self._run("--apply")

        self.weak_plan.refresh_from_db()
        recommended = self.weak_plan.interventions["recommended"]
        self.assertEqual(
            [row["code"] for row in recommended],
            [
                "financial_health",
                "leadership",
                "enrolment",
                "learning_environment",
            ],
        )
        self.assertEqual(
            [row["owner"] for row in recommended],
            ["Partner", "Partner", "Staff", "Staff"],
            "the two most critical interventions belong to a Partner",
        )

    def test_backfilled_records_are_marked_and_keep_their_baseline_anchor(self):
        self._run("--apply")

        self.weak_plan.refresh_from_db()
        stored = self.weak_plan.interventions
        self.assertTrue(
            stored["backfilled"],
            "a repaired record must never read as an onboarding-time capture",
        )
        self.assertEqual(
            stored["source_ssa_record_id"], self.weak_plan.baseline_ssa_record_id
        )

    def test_a_school_without_verified_ssa_is_left_for_manual_review(self):
        output = self._run("--apply")

        self.blind_plan.refresh_from_db()
        self.assertIsNone(
            self.blind_plan.interventions,
            "inventing a support priority for an unassessed school is the one "
            "thing this repair must never do",
        )
        self.assertIn("1 MANUAL REVIEW (no verified SSA)", output)

    def test_rerunning_changes_nothing(self):
        self._run("--apply")
        self.weak_plan.refresh_from_db()
        first = self.weak_plan.interventions

        second_output = self._run("--apply")

        self.weak_plan.refresh_from_db()
        self.assertEqual(
            self.weak_plan.interventions,
            first,
            "a repaired plan must be byte-identical after a second run",
        )
        # The only remaining candidate is the school with no verified SSA. It
        # stays reported for manual review on every run by design — that is a
        # standing question for a human, not a failure to converge.
        self.assertIn("core-recommendations: 1 active plan(s)", second_output)
        self.assertIn("0 derivable", second_output)
        self.assertIn("1 MANUAL REVIEW (no verified SSA)", second_output)


class BackfillSkipsPlansThatAlreadyHaveOneTest(_Fixture):
    def setUp(self):
        self.school = _school("DONE")
        _confirmed_ssa(self.school, SCORES)
        self.plan = _plan(
            self.school,
            interventions={
                "recommended": [{"code": "leadership", "owner": "Partner"}],
                "maintenance": False,
                "algorithm_version": 1,
            },
        )

    def test_an_existing_recommendation_is_never_overwritten(self):
        out = StringIO()
        call_command(
            "repair_ecosystem_data",
            "--only",
            "core-recommendations",
            "--apply",
            stdout=out,
        )

        self.plan.refresh_from_db()
        self.assertEqual(
            [row["code"] for row in self.plan.interventions["recommended"]],
            ["leadership"],
            "the historical rationale a package was planned on is immutable",
        )
        self.assertIn("core-recommendations: 0 active plan(s)", out.getvalue())


class StrongSchoolsGetMaintenanceNotForcedSupportTest(_Fixture):
    def setUp(self):
        self.school = _school("STRONG")
        record = _confirmed_ssa(self.school, {key: 9.0 for key in SCORES})
        self.plan = _plan(self.school, baseline_id=record.id)

    def test_all_strong_scores_persist_maintenance_with_no_recommended_rows(self):
        out = StringIO()
        call_command(
            "repair_ecosystem_data",
            "--only",
            "core-recommendations",
            "--apply",
            stdout=out,
        )

        self.plan.refresh_from_db()
        self.assertTrue(self.plan.interventions["maintenance"])
        self.assertEqual(self.plan.interventions["recommended"], [])
        self.assertIn("1 derivable", out.getvalue())
