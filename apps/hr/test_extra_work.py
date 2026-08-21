"""Extra Assigned Work (§18): authority, workflow, verification, scoring."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import BadRequest, Forbidden
from apps.hr import extra_work
from apps.hr.models import ExtraWorkScoringPolicy


def _user(role, email):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    staff = StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user, staff


class ExtraWorkFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd, cls.cd_sp = _user("CountryDirector", "cd@xw.test")
        cls.pl, cls.pl_sp = _user("Program Lead", "pl@xw.test")
        cls.pl2, cls.pl2_sp = _user("Program Lead", "pl2@xw.test")
        cls.cceo, cls.cceo_sp = _user("CCEO", "cceo@xw.test")
        cls.other_cceo, cls.other_sp = _user("CCEO", "other@xw.test")
        cls.ia, cls.ia_sp = _user("ImpactAssessment", "ia@xw.test")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl2_sp, supervisee=cls.other_sp
        )

    def _assign(self, principal=None, assignee=None, **overrides):
        data = {
            "assignee_id": (assignee or self.cceo).id,
            "title": "Prepare the district review pack",
            "instruction": "Compile SSA + visit data for the review meeting.",
            "category": "operational_support",
            "due_date": date.today() + timedelta(days=7),
        }
        data.update(overrides)
        return extra_work.create_assignment(principal or self.cd, data)


class AuthorityTests(ExtraWorkFixture):
    def test_cd_assigns_to_pl_and_cceo(self):
        self.assertEqual(self._assign(assignee=self.pl).status, "assigned")
        self.assertEqual(self._assign(assignee=self.cceo).status, "assigned")

    def test_pl_assigns_only_to_supervised_cceos(self):
        a = self._assign(principal=self.pl, assignee=self.cceo)
        self.assertEqual(a.assigner_role, "Program Lead")
        with self.assertRaises(Forbidden):
            self._assign(principal=self.pl, assignee=self.other_cceo)
        with self.assertRaises(Forbidden):
            self._assign(principal=self.pl, assignee=self.pl2)

    def test_other_roles_cannot_assign(self):
        with self.assertRaises(Forbidden):
            self._assign(principal=self.ia)
        with self.assertRaises(Forbidden):
            self._assign(principal=self.cceo, assignee=self.other_cceo)

    def test_no_self_assignment_and_no_assignee_reviewer(self):
        with self.assertRaises(BadRequest):
            self._assign(principal=self.cd, assignee=self.cd)
        with self.assertRaises(BadRequest):
            self._assign(reviewer_id=str(self.cceo.id))

    def test_cd_direct_to_cceo_records_supervising_pl(self):
        a = self._assign(assignee=self.cceo)
        self.assertEqual(a.supervising_pl_id, str(self.pl.id))


class WorkflowTests(ExtraWorkFixture):
    def test_full_chain_submit_return_correct_verify_once(self):
        a = self._assign()
        extra_work.acknowledge(self.cceo, a.id)
        extra_work.start(self.cceo, a.id)
        with self.assertRaises(BadRequest):
            # evidence required, none given
            extra_work.submit(self.cceo, a.id, {"outcome": "Done"})
        extra_work.submit(
            self.cceo, a.id, {"outcome": "Pack ready", "evidence_note": "Doc v1"}
        )
        a.refresh_from_db()
        self.assertEqual(a.status, "submitted")

        extra_work.return_work(self.cd, a.id, "Missing the SSA annexe.")
        a.refresh_from_db()
        self.assertEqual(a.status, "returned")
        self.assertEqual(a.return_count, 1)

        extra_work.submit(
            self.cceo, a.id, {"outcome": "Pack + annexe", "evidence_note": "Doc v2"}
        )
        extra_work.verify(self.cd, a.id)
        a.refresh_from_db()
        self.assertEqual(a.status, "verified")
        self.assertEqual(a.verified_by, str(self.cd.id))
        # No approved policy → tracked but unscored, never invented.
        self.assertIsNone(a.contribution_points)

    def test_assignee_can_never_verify_even_via_service(self):
        a = self._assign()
        extra_work.submit(self.cceo, a.id, {"outcome": "Done", "evidence_note": "n"})
        with self.assertRaises(Forbidden):
            extra_work.verify(self.cceo, a.id)

    def test_only_reviewer_returns_and_only_assigner_cancels(self):
        a = self._assign()
        extra_work.submit(self.cceo, a.id, {"outcome": "x", "evidence_note": "n"})
        with self.assertRaises(Forbidden):
            extra_work.return_work(self.pl, a.id, "not yours")
        with self.assertRaises(Forbidden):
            extra_work.cancel(self.pl, a.id, "not yours")
        extra_work.cancel(self.cd, a.id, "no longer needed")
        a.refresh_from_db()
        self.assertEqual(a.status, "cancelled")

    def test_cancelled_contributes_nothing(self):
        a = self._assign()
        extra_work.cancel(self.cd, a.id, "scope change")
        summary = extra_work.performance_summary(str(self.cceo.id), a.fy)
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["verified"], 0)


class ScoringTests(ExtraWorkFixture):
    def _verified(self, **overrides):
        a = self._assign(**overrides)
        extra_work.submit(self.cceo, a.id, {"outcome": "x", "evidence_note": "n"})
        extra_work.verify(self.cd, a.id)
        a.refresh_from_db()
        return a

    def test_approved_policy_scores_once_by_complexity(self):
        a0 = self._assign()
        ExtraWorkScoringPolicy.objects.create(
            fy=a0.fy,
            status="approved",
            complexity_weights={"low": 1, "medium": 2, "high": 4},
            max_contribution_points=Decimal("10"),
        )
        a = self._assign(complexity="high", title="Second task")
        extra_work.submit(self.cceo, a.id, {"outcome": "x", "evidence_note": "n"})
        extra_work.verify(self.cd, a.id)
        a.refresh_from_db()
        self.assertEqual(a.contribution_points, Decimal("4"))
        # Verification is terminal — no second scoring pass.
        with self.assertRaises(BadRequest):
            extra_work.verify(self.cd, a.id)

    def test_draft_policy_never_scores(self):
        a0 = self._assign()
        ExtraWorkScoringPolicy.objects.create(
            fy=a0.fy, status="draft", complexity_weights={"medium": 2}
        )
        a = self._verified(title="Unscored task")
        self.assertIsNone(a.contribution_points)

    def test_extra_work_never_touches_milestone_credits(self):
        from apps.hr.models import MilestoneProgressCredit

        before = MilestoneProgressCredit.objects.count()
        self._verified(title="No credit task")
        self.assertEqual(MilestoneProgressCredit.objects.count(), before)
