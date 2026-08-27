"""PROJ-01 — a Special Project's impact must be able to become an answer.

`ssa_impact.refresh_follow_up` is the only code that writes
`follow_up_score`, `follow_up_ssa_id`, `follow_up_due_on`, or any
`impact_classification` beyond the two values `_capture_baseline` sets at
assignment time. It is complete, careful and tested — it withholds a verdict
until the window opens, it refuses to judge on an unconfirmed assessment, and
it is explicitly idempotent.

Nothing called it.

The whole Special Project subsystem exists to answer one question: did this
project move the SSA intervention it was created to move? `project_impact`
answers it by counting schools that have a baseline, a verified delivery and a
confirmed follow-up. With no caller for `refresh_follow_up`, no school could
ever reach that third state, so the answer was permanently "not measured yet"
— for every project, in every financial year, no matter how much verified work
was done or how many follow-up assessments were collected.

That is the same defect class as GOV-01 and D5 — a designed capability with
readers and no writers — and it is the first instance found at function level
rather than model level. It is also the quietest, because the readers are
scrupulously honest about it. `project_impact` reports `awaiting_follow_up`
and withholds a rate; the To-Do page carries a comment saying an uncollected
assessment "reads forever as 'not yet measurable', which is honest but never
becomes an answer". Every surface told the truth. The truth was just always
the same one.

The second half is worse than the first. The To-Do designed to chase a missing
follow-up filters on `follow_up_due_on__lte=today`, and `follow_up_due_on` is
written only by `refresh_follow_up` — so the reminder that exists to stop this
happening could itself never fire.

These tests hold both halves: the classification must move when the evidence
arrives, and the due date must be set when delivery is verified.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.geography.models import District, Region
from apps.projects import ssa_impact
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

INTERVENTION = "christlike_behaviour"


class ProjectImpactBecomesAnAnswerTest(TestCase):
    """One school, one delivery, one follow-up — and a measured verdict."""

    def setUp(self):
        self.region = Region.objects.create(name="Proj Impact Region")
        self.district = District.objects.create(
            name="Proj Impact District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="S-PROJ-01",
            name="Proj Impact School",
            region=self.region,
            district=self.district,
            enrollment=200,
        )
        self.project = Project.objects.create(
            name="Christlike Behaviour Uplift",
            code="PROJ01",
            intervention=INTERVENTION,
            target_interventions=[INTERVENTION],
        )

    def _drain(self):
        """Run the outbox, as the scheduled `outbox_drain` job does.

        The refresh is deferred rather than inline for the same reason the
        Business Transformation bridge beside it is: a confirmed SSA arrives
        one at a time from a verification screen and several hundred at a
        time from an import, and the upload path has a query budget a per-row
        projection would break. So the walk drains, because production does.
        """
        from apps.outbox.services import drain

        return drain()

    def _ssa(self, on, score, *, status="confirmed"):
        record = self._make_ssa(on, score, status=status)
        # Drained here, not at the end of the test. An event enqueued by an
        # EARLIER step and processed late re-derives everything from current
        # state, so a single stale event can silently cover for a bridge that
        # never fires — which is exactly what a first version of this file
        # did, and why killing either bridge left it green. Draining after
        # every step means each trigger has to carry its own step.
        self._drain()
        return record

    def _make_ssa(self, on, score, *, status="confirmed"):
        record = SsaRecord.objects.create(
            school=self.school,
            fy="2026",
            quarter="Q1",
            average_score=score,
            verification_status=status,
            date_of_ssa=on,
            uploaded_by="proj-01",
        )
        SsaScore.objects.create(
            ssa_record=record, intervention=INTERVENTION, score=score
        )
        return record

    def _assignment_with_baseline(self, baseline_score=3.0):
        from apps.projects.services import _capture_baseline

        self._make_ssa(timezone.now() - datetime.timedelta(days=400), baseline_score)
        assignment = ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=self.school,
            matched_intervention=INTERVENTION,
        )
        _capture_baseline(assignment, INTERVENTION)
        assignment.save()
        # Clear anything the baseline assessment enqueued, so the steps that
        # follow are measured on their own triggers.
        self._drain()
        self.assertEqual(assignment.baseline_score, baseline_score)
        return assignment

    def _verified_delivery(self, days_ago=200):
        """An IA-verified activity is what opens the measurement window."""
        from apps.activities.models import Activity

        activity = Activity.objects.create(
            school=self.school,
            # Activity.project_id is a plain char column, not a relation.
            project_id=self.project.id,
            activity_type="school_visit",
            status="ia_verified",
            fy="2026",
            scheduled_date=timezone.now() - datetime.timedelta(days=days_ago),
            ia_confirmed_at=timezone.now() - datetime.timedelta(days=days_ago),
        )
        self._drain()
        return activity

    def test_a_confirmed_follow_up_moves_the_school_out_of_awaiting(self):
        """PROJ-01. Evidence arrives; the verdict must follow it."""
        assignment = self._assignment_with_baseline()
        self._verified_delivery()
        self._ssa(timezone.now() - datetime.timedelta(days=30), 8.0)

        refreshed = ProjectSchoolAssignment.objects.get(id=assignment.id)
        self.assertIsNotNone(
            refreshed.follow_up_score,
            "a confirmed follow-up assessment for a school with a baseline and "
            "a verified delivery must reach the assignment — nothing in "
            "production called refresh_follow_up, so it never did (PROJ-01)",
        )
        self.assertEqual(refreshed.follow_up_score, 8.0)
        self.assertIn(
            refreshed.impact_classification,
            ssa_impact.MEASURED,
            "with a baseline, a verified delivery and a confirmed follow-up "
            "the school is measurable, and must be counted as measured",
        )

    def test_the_project_can_therefore_state_its_position(self):
        """The question the whole subsystem exists to answer."""
        self._assignment_with_baseline()
        self._verified_delivery()
        self._ssa(timezone.now() - datetime.timedelta(days=30), 8.0)

        impact = ssa_impact.project_impact(self.project, intervention=INTERVENTION)
        self.assertEqual(
            impact["pipeline"]["measured"],
            1,
            "project_impact could never report a measured school, for any "
            "project, in any year (PROJ-01)",
        )
        self.assertEqual(impact["pipeline"]["awaiting_follow_up"], 0)
        self.assertEqual(impact["improved"], 1)
        self.assertEqual(impact["average_change"], 5.0)

    def test_verified_delivery_sets_the_due_date_the_reminder_needs(self):
        """The second half, and the worse one.

        The To-Do that chases a missing follow-up filters on
        `follow_up_due_on__lte=today`. That column is written only by
        refresh_follow_up, so the reminder designed to stop this problem could
        itself never fire.
        """
        assignment = self._assignment_with_baseline()
        self._verified_delivery(days_ago=200)

        refreshed = ProjectSchoolAssignment.objects.get(id=assignment.id)
        self.assertIsNotNone(
            refreshed.follow_up_due_on,
            "verified delivery must set the follow-up due date, or the "
            "'Complete Follow-Up SSA' to-do can never appear (PROJ-01)",
        )

    def test_an_unconfirmed_follow_up_is_still_not_evidence(self):
        """Guard the fix from over-correcting.

        Wiring the refresh must not make the platform accept a draft
        assessment as a verdict. `refresh_follow_up` already refuses; this
        holds the refusal across the new trigger.
        """
        assignment = self._assignment_with_baseline()
        self._verified_delivery()
        self._ssa(timezone.now() - datetime.timedelta(days=30), 9.0, status="draft")

        refreshed = ProjectSchoolAssignment.objects.get(id=assignment.id)
        self.assertIsNone(
            refreshed.follow_up_score,
            "an unconfirmed assessment must never become a follow-up score",
        )

    def test_a_follow_up_before_delivery_does_not_judge_the_delivery(self):
        """Also a guard: the assessment must post-date the work."""
        assignment = self._assignment_with_baseline()
        self._ssa(timezone.now() - datetime.timedelta(days=300), 9.0)
        self._verified_delivery(days_ago=200)

        refreshed = ProjectSchoolAssignment.objects.get(id=assignment.id)
        self.assertIsNone(
            refreshed.follow_up_score,
            "an assessment taken before the work cannot be evidence of it",
        )
