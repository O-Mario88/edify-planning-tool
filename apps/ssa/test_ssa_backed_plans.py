"""Every planned activity is SSA backed (owner, 2026-09-14).

The audit of 2026-09-14 found the plan verdict recorded but toothless: a
planner could target any intervention without a word, nobody saw the verdict,
an SSA years old counted as current, a newer SSA waiting for its verifier went
unmentioned, and finished work carried no verdict at all. These pin each fix.
"""

from __future__ import annotations

import datetime
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.planning.test_standard_support_scheduling import StandardSupportBase
from apps.ssa import plan_alignment
from apps.ssa.models import SsaRecord
from apps.ssa.plan_alignment import SsaAlignment


class ReasonForDepartingFromTheSsaTest(StandardSupportBase):
    def test_a_departure_from_the_ssa_schedules_without_a_reason(self):
        """The reason is asked for, not required.

        It used to be mandatory, which made the SSA recommendation a
        requirement in practice: a planner who knew the school could not act
        on that knowledge without writing an essay first. The plan now goes
        through — and is still judged OFF_PRIORITY, so the departure stays
        visible to everyone who reviews it.
        """
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.CHRISTLIKE_BEHAVIOUR,
            requireSsaReason=True,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.ssa_alignment, SsaAlignment.OFF_PRIORITY)
        self.assertEqual(activity.ssa_deviation_reason, "")
        self.assertEqual(plan_alignment.verdict_display(activity)["tone"], "warning")

    def test_the_drawers_ask_why_a_plan_departs_from_the_ssa(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.CHRISTLIKE_BEHAVIOUR,
            requireSsaReason=True,
            ssaDeviationReason="Head teacher asked for chapel support after a crisis.",
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.ssa_alignment, SsaAlignment.OFF_PRIORITY)
        self.assertEqual(
            activity.ssa_deviation_reason,
            "Head teacher asked for chapel support after a crisis.",
        )
        self.assertEqual(
            activity.recommendation_source["ssa"]["deviationReason"],
            "Head teacher asked for chapel support after a crisis.",
        )
        verdict = plan_alignment.verdict_display(activity)
        self.assertEqual(verdict["tone"], "warning")
        self.assertIn("chapel support", verdict["deviation_reason"])

    def test_a_priority_plan_needs_no_reason(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            requireSsaReason=True,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertEqual(activity.ssa_deviation_reason, "")

    def test_programmatic_paths_are_judged_without_being_asked(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.CHRISTLIKE_BEHAVIOUR,
        )
        self.assertEqual(
            Activity.objects.get(id=result["id"]).ssa_alignment,
            SsaAlignment.OFF_PRIORITY,
        )

    def test_the_school_drawer_carries_the_priorities_it_warns_against(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/planning/schedule-modal", {"school_id": self.school.school_id}
        )
        self.assertContains(response, "data-ssa-deviation")
        self.assertContains(response, 'name="ssa_deviation_reason"')
        self.assertContains(response, "financial_health")


class OutOfDateAndPendingSsaTest(StandardSupportBase):
    def test_an_ssa_older_than_last_year_marks_the_plan_out_of_date(self):
        old_fy = str(int(str(get_operational_fy())[-4:]) - 3)
        SsaRecord.objects.filter(id=self.record.id).update(fy=old_fy)
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.ssa_alignment, SsaAlignment.STALE_SSA)
        self.assertIn("out of date", activity.recommendation_source["ssa"]["reason"])
        self.assertIn(SsaAlignment.STALE_SSA, plan_alignment.UNINFORMED)

    def test_a_newer_ssa_waiting_for_its_verifier_is_named(self):
        SsaRecord.objects.filter(id=self.record.id).update(
            verification_status="pending"
        )
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
        )
        evidence = Activity.objects.get(id=result["id"]).recommendation_source["ssa"]
        self.assertEqual(evidence["alignment"], SsaAlignment.NO_SSA)
        self.assertTrue(evidence["pendingSsaDate"])
        self.assertIn("waiting for verification", evidence["reason"])


class FinishedWorkIsJudgedAgainstTheSsaOfItsDayTest(StandardSupportBase):
    def _finished(self, planned: datetime.date, focus):
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="ia_verified",
            fy=get_operational_fy(),
            quarter="Q1",
            planned_date=planned,
            focus_intervention=focus,
            responsible_staff_id=self.staff.id,
        )

    def test_history_uses_the_ssa_verified_when_the_work_was_planned(self):
        before = self._finished(
            self.record.date_of_ssa.date()
            if hasattr(self.record.date_of_ssa, "date")
            else self.record.date_of_ssa,
            SsaIntervention.FINANCIAL_HEALTH,
        )
        long_before = self._finished(
            timezone.localdate() - datetime.timedelta(days=400),
            SsaIntervention.FINANCIAL_HEALTH,
        )
        out = StringIO()
        call_command(
            "audit_ssa_informed_plans",
            "--history",
            fy=get_operational_fy(),
            stdout=out,
        )
        self.assertIn("History: 2 finished plan(s) judged.", out.getvalue())
        before.refresh_from_db()
        long_before.refresh_from_db()
        self.assertEqual(before.ssa_alignment, SsaAlignment.PRIORITY)
        self.assertTrue(before.recommendation_source["ssa"]["historical"])
        # No SSA had been verified when this one was planned.
        self.assertEqual(long_before.ssa_alignment, SsaAlignment.NO_SSA)


class VerdictIsVisibleTest(StandardSupportBase):
    def test_the_activity_record_and_the_work_plan_show_the_verdict(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.CHRISTLIKE_BEHAVIOUR,
            requireSsaReason=True,
            ssaDeviationReason="Requested by the proprietor.",
        )
        self.client.force_login(self.user)
        page = self.client.get(f"/my-plan/{result['id']}")
        self.assertContains(page, 'data-ssa-verdict="off_priority"')
        self.assertContains(page, "Requested by the proprietor.")
        plan = self.client.get("/work-plan", {"view": "fy", "fy": get_operational_fy()})
        self.assertEqual(plan.status_code, 200)
        self.assertContains(plan, 'data-ssa-verdict="off_priority"')
