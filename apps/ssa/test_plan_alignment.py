"""Every school activity plan is SSA informed (owner, 2026-09-13).

These tests drive the canonical scheduling funnel the way each entry point
does and check what the plan records: the intervention it targets and where
that came from, the verified evidence it was judged on, the verdict, and the
recommendation it answers through to delivery.
"""

from __future__ import annotations

import datetime
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)
from apps.schools.models import School
from apps.ssa import plan_alignment
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.plan_alignment import SsaAlignment
from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation
from apps.ssa.recommendation_service import generate_for_school


def _assess_member(school, scores: dict):
    record = SsaRecord.objects.create(
        school=school,
        fy=get_operational_fy(),
        date_of_ssa=timezone.localdate() - datetime.timedelta(days=20),
        verification_status="confirmed",
    )
    for intervention, score in scores.items():
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
    return record


class SchoolPlanAlignmentTest(StandardSupportBase):
    def test_a_school_visit_with_no_focus_targets_the_top_ssa_need(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            activityPurposeText="Routine support visit",
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.focus_intervention, SsaIntervention.FINANCIAL_HEALTH)
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        evidence = activity.recommendation_source["ssa"]
        self.assertEqual(evidence["focusSource"], "ssa_default")
        self.assertEqual(evidence["school"]["ssaId"], self.record.id)
        self.assertEqual(evidence["school"]["focusRank"], 1)
        self.assertEqual(activity.source_ssa_id, self.record.id)
        self.assertIn("Financial Health", evidence["reason"])

    def test_a_planner_choice_the_ssa_does_not_prioritise_is_visible(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.CHRISTLIKE_BEHAVIOUR,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(
            activity.focus_intervention, SsaIntervention.CHRISTLIKE_BEHAVIOUR
        )
        self.assertEqual(activity.ssa_alignment, SsaAlignment.OFF_PRIORITY)
        reason = activity.recommendation_source["ssa"]["reason"]
        self.assertIn("Financial Health", reason, "names the need the SSA ranks first")

    def test_a_stated_priority_is_kept_and_judged_a_priority(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertEqual(
            activity.recommendation_source["ssa"]["focusSource"], "planner"
        )

    def test_collection_and_relationship_work_are_informed_without_a_target(self):
        collection = Activity.objects.get(
            id=self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_SCHOOL_VISIT_SSA_COLLECTION").id,
                purposeType="ssa_support",
                ssaCollectionExpected=True,
            )["id"]
        )
        self.assertEqual(collection.ssa_alignment, SsaAlignment.SSA_COLLECTION)
        self.assertIsNone(collection.focus_intervention)

        donor = Activity.objects.get(
            id=self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_DONOR_VISIT").id,
            )["id"]
        )
        self.assertEqual(donor.ssa_alignment, SsaAlignment.NOT_APPLICABLE)
        self.assertIsNone(donor.focus_intervention, "a donor visit names no target")

    def test_a_school_with_no_verified_ssa_is_planned_but_flagged(self):
        unassessed = School.objects.create(
            school_id="STD-NOSSA",
            name="Unassessed School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=unassessed.id)
        activity = Activity.objects.get(
            id=self.schedule(
                schoolId=unassessed.school_id,
                catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            )["id"]
        )
        self.assertEqual(activity.ssa_alignment, SsaAlignment.NO_SSA)
        self.assertIsNone(activity.focus_intervention)
        self.assertIn(
            "No verified SSA", activity.recommendation_source["ssa"]["reason"]
        )


class ClusterPlanAlignmentTest(StandardSupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        members = School.objects.filter(school_id__startswith="STD-MEM-").order_by(
            "school_id"
        )
        for index, member in enumerate(members):
            _assess_member(
                member,
                {
                    SsaIntervention.LEADERSHIP: 3.0 + index * 0.2,
                    SsaIntervention.FINANCIAL_HEALTH: 6.5,
                    SsaIntervention.ENROLMENT: 7.5,
                },
            )

    def test_a_cluster_meeting_with_no_focus_targets_the_weakest_member_need(self):
        activity = Activity.objects.get(
            id=self.schedule(
                clusterId=self.cluster.id,
                catalogueItemId=self.item("STANDARD_CLUSTER_MEETING").id,
                participantsPerSchool=2,
            )["id"]
        )
        self.assertEqual(activity.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        cluster = activity.recommendation_source["ssa"]["cluster"]
        self.assertEqual(cluster["members"], 5)
        self.assertEqual(cluster["assessedSchools"], 5)
        self.assertEqual(cluster["focusRank"], 1)

    def test_the_cluster_need_is_exposed_for_the_drawer(self):
        need = plan_alignment.cluster_need(self.cluster.id)
        # Leadership averages 3.3 across the five schools; Financial Health
        # 5.6, pulled down by the standard-support school's 2.0.
        self.assertEqual(need.rows[0]["intervention"], SsaIntervention.LEADERSHIP)
        self.assertEqual(need.rows[0]["schoolsBelow"], 5)
        self.assertEqual(
            need.priorities,
            [
                SsaIntervention.LEADERSHIP,
                SsaIntervention.FINANCIAL_HEALTH,
                SsaIntervention.GOVERNMENT_REQUIREMENT,
            ],
        )


class RecommendationLifecycleTest(StandardSupportBase):
    def setUp(self):
        super().setUp()
        generate_for_school(self.school, fy=get_operational_fy())

    def recommendation(self, intervention):
        return SsaRecommendation.objects.get(
            school=self.school, intervention=intervention
        )

    def test_a_plan_marks_its_recommendation_planned_then_delivered(self):
        activity = Activity.objects.get(
            id=self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            )["id"]
        )
        recommendation = self.recommendation(SsaIntervention.FINANCIAL_HEALTH)
        self.assertEqual(recommendation.state, RecommendationState.PLANNED)
        self.assertEqual(recommendation.planned_activity_id, activity.id)
        self.assertEqual(activity.ssa_recommendation_id, recommendation.id)

        activity.status = "ia_verified"
        activity.save(update_fields=["status", "updated_at"])
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.state, RecommendationState.DELIVERED)

    def test_a_cancelled_plan_puts_the_need_back_in_the_queue(self):
        activity = Activity.objects.get(
            id=self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            )["id"]
        )
        activity.status = "cancelled"
        activity.save(update_fields=["status", "updated_at"])
        recommendation = self.recommendation(SsaIntervention.FINANCIAL_HEALTH)
        self.assertEqual(recommendation.state, RecommendationState.ACCEPTED)
        self.assertIsNone(recommendation.planned_activity_id)
        self.assertIn("cancelled", recommendation.decision_reason)

    def test_a_cluster_session_delivers_only_for_the_schools_that_attended(self):
        member = School.objects.filter(school_id="STD-MEM-0").get()
        _assess_member(member, {SsaIntervention.FINANCIAL_HEALTH: 3.0})
        generate_for_school(member, fy=get_operational_fy())
        activity = Activity.objects.get(
            id=self.schedule(
                clusterId=self.cluster.id,
                catalogueItemId=self.item("STANDARD_CLUSTER_MEETING").id,
                focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
                participantsPerSchool=2,
                invitedSchoolIds=[self.school.id, member.id],
            )["id"]
        )
        planned = SsaRecommendation.objects.filter(
            planned_activity=activity, state=RecommendationState.PLANNED
        )
        self.assertEqual(planned.count(), 2)

        ClusterActivityAttendance.objects.filter(
            activity=activity, school=self.school
        ).update(attended=True)
        activity.status = "ia_verified"
        activity.save(update_fields=["status", "updated_at"])
        self.assertEqual(
            self.recommendation(SsaIntervention.FINANCIAL_HEALTH).state,
            RecommendationState.DELIVERED,
        )
        self.assertEqual(
            SsaRecommendation.objects.get(
                school=member, intervention=SsaIntervention.FINANCIAL_HEALTH
            ).state,
            RecommendationState.ACCEPTED,
        )


class SsaInformedAuditCommandTest(StandardSupportBase):
    def test_the_audit_backfills_recommendations_and_verdicts(self):
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(_schedulable_date()),
            quarter="Q1",
            planned_date=_schedulable_date(),
            scheduled_date=_at(_schedulable_date()),
            status="scheduled",
            focus_intervention=SsaIntervention.LEADERSHIP,
        )
        out = StringIO()
        call_command(
            "audit_ssa_informed_plans",
            "--generate",
            "--stamp",
            "--fy",
            activity.fy,
            stdout=out,
        )
        activity.refresh_from_db()
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertTrue(activity.recommendation_source["ssa"]["backfilled"])
        self.assertEqual(
            SsaRecommendation.objects.get(
                school=self.school, intervention=SsaIntervention.LEADERSHIP
            ).state,
            RecommendationState.PLANNED,
        )
        report = out.getvalue()
        self.assertIn("SSA-informed plans", report)
        self.assertIn("SSA informed: 1 (100%)", report)


class NightlySyncJudgesUnjudgedPlansTest(StandardSupportBase):
    def test_the_nightly_job_judges_a_live_plan_that_has_no_verdict(self):
        from unittest.mock import patch

        from apps.realtime import jobs

        planned = _schedulable_date()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(planned),
            quarter="Q1",
            planned_date=planned,
            scheduled_date=_at(planned),
            status="scheduled",
            focus_intervention=SsaIntervention.LEADERSHIP,
        )
        with patch("apps.core.fy.get_operational_fy", return_value=activity.fy):
            jobs._do_ssa_recommendation_sync()
        activity.refresh_from_db()
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertTrue(activity.recommendation_source["ssa"]["backfilled"])


class BulkPlanningIsScopedAndSsaInformedTest(StandardSupportBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_bulk_schedule_targets_each_schools_top_need(self):
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "schedule",
                "school_ids": [self.school.school_id],
                "scheduled_date": _schedulable_date().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        activity = Activity.objects.get(school=self.school)
        # No named school-level activity answers Financial Health, so a
        # standard visit targets it rather than a named one for a lesser need.
        self.assertEqual(activity.focus_intervention, SsaIntervention.FINANCIAL_HEALTH)
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)

    def test_bulk_actions_refuse_schools_outside_the_portfolio(self):
        outside = School.objects.create(
            school_id="STD-OUTSIDE",
            name="Another Portfolio School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        response = self.client.post(
            "/planning/bulk-action",
            {"action": "export", "school_ids": [outside.school_id]},
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"Another Portfolio School", response.content)


class EditedFocusIsRejudgedTest(StandardSupportBase):
    def test_changing_a_plans_intervention_moves_its_verdict_and_recommendation(self):
        from apps.activities.services import patch_activity

        generate_for_school(self.school, fy=get_operational_fy())
        activity = Activity.objects.get(
            id=self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            )["id"]
        )
        financial = SsaRecommendation.objects.get(
            school=self.school, intervention=SsaIntervention.FINANCIAL_HEALTH
        )
        self.assertEqual(financial.state, RecommendationState.PLANNED)

        patch_activity(
            activity.id,
            {"focusIntervention": SsaIntervention.CHRISTLIKE_BEHAVIOUR},
            self.user,
        )
        activity.refresh_from_db()
        financial.refresh_from_db()
        self.assertEqual(activity.ssa_alignment, SsaAlignment.OFF_PRIORITY)
        self.assertEqual(financial.state, RecommendationState.ACCEPTED)
        self.assertIsNone(financial.planned_activity_id)

        patch_activity(
            activity.id, {"focusIntervention": SsaIntervention.LEADERSHIP}, self.user
        )
        activity.refresh_from_db()
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertEqual(
            SsaRecommendation.objects.get(
                school=self.school, intervention=SsaIntervention.LEADERSHIP
            ).state,
            RecommendationState.PLANNED,
        )
