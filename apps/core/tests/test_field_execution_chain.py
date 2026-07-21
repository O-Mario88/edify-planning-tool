"""The field-execution chain: the CCEO/PL loop must actually be completable.

Three defects made the core loop unusable and are locked shut here:

  1. `Activity.responsible_staff_id` holds a StaffProfile id on rows written by
     the canonical create path and a User id on rows from other paths. The
     permission checks compared against one space only, so a CCEO was refused
     access to most of their own work.
  2. Returned work could not re-enter completion — every return path was a
     one-way door out of the workflow.
  3. The evidence / SF-ID / submit next-actions tested a status the canonical
     path never writes, so those To-Dos never appeared.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.activities.services import COMPLETABLE_STATUSES, SUBMITTABLE_STATUSES
from apps.core.exceptions import Forbidden
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole
from apps.core.scoping import owner_ids
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class OwnerIdentityTests(TestCase):
    """One person, two id spaces — every ownership check must accept both."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Chain Region")
        cls.district = District.objects.create(name="Chain District", region=cls.region)
        cls.school = School.objects.create(
            name="Chain Primary",
            school_id="CH-1",
            region_id=cls.region.id,
            district_id=cls.district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-chain@t.org", "Cara", EdifyRole.CCEO.value)
        self.sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )

    def _activity(self, responsible_id):
        return Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="completion_started",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=responsible_id,
            planned_date=timezone.now(),
        )

    def test_owner_ids_returns_both_spaces(self):
        ids = owner_ids(self.cceo)
        self.assertIn(self.cceo.id, ids)
        self.assertIn(self.sp.id, ids)

    def test_can_upload_evidence_in_staffprofile_space(self):
        """The canonical create path stamps the StaffProfile id — this is the
        case that was refused for ~94% of a CCEO's real activities."""
        act = self._activity(self.sp.id)
        self.assertTrue(RolePermissionService.can_upload_evidence(self.cceo, act))

    def test_can_upload_evidence_in_user_space(self):
        act = self._activity(self.cceo.id)
        self.assertTrue(RolePermissionService.can_upload_evidence(self.cceo, act))

    def test_a_stranger_still_cannot_upload(self):
        other = _user("other-chain@t.org", "Otto", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=other, title="CCEO", country="Uganda")
        act = self._activity(self.sp.id)
        self.assertFalse(RolePermissionService.can_upload_evidence(other, act))

    def test_monitoring_staff_may_review_partner_evidence(self):
        """Partner work carries no responsible_staff_id; the monitoring staff
        member is the one who must accept the evidence."""
        act = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="completion_started",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=None,
            monitored_by_staff_id=self.sp.id,
            planned_date=timezone.now(),
        )
        self.assertTrue(RolePermissionService.can_upload_evidence(self.cceo, act))


class ReturnedWorkIsResubmittableTests(TestCase):
    """Every return path must lead back into the workflow."""

    def test_returned_statuses_can_re_enter_completion(self):
        for status in ("returned", "returned_by_pl", "returned_by_ia"):
            self.assertIn(
                status,
                COMPLETABLE_STATUSES,
                f"'{status}' is a dead end — 'Fix and Resubmit' cannot succeed",
            )

    def test_returned_statuses_can_be_resubmitted_for_review(self):
        for status in ("returned", "returned_by_pl", "returned_by_ia"):
            self.assertIn(status, SUBMITTABLE_STATUSES)

    def test_work_in_progress_still_accepted(self):
        self.assertIn("completion_started", COMPLETABLE_STATUSES)
        self.assertIn("completed", SUBMITTABLE_STATUSES)


class NextActionCoversRealStatusesTests(TestCase):
    """The next-action ladder must key off the status the platform writes."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="NA Region")
        district = District.objects.create(name="NA District", region=region)
        cls.school = School.objects.create(
            name="NA Primary",
            school_id="NA-1",
            region_id=region.id,
            district_id=district.id,
        )

    def _act(self, **kw):
        defaults = dict(
            school_id=self.school.id,
            activity_type="school_visit",
            status="completion_started",
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
            evidence_status="none",
        )
        defaults.update(kw)
        return Activity.objects.create(**defaults)

    def test_completion_started_asks_for_evidence(self):
        from apps.my_plan.services import compute_next_action

        act = self._act()
        action = compute_next_action(act, date.today())
        self.assertEqual(
            action["action"],
            "evidence",
            "start_completion writes completion_started; the evidence step "
            "must fire on it or the CCEO never gets the To-Do",
        )

    def test_evidence_uploaded_asks_for_salesforce_id(self):
        from apps.my_plan.services import compute_next_action

        act = self._act(evidence_status="uploaded")
        action = compute_next_action(act, date.today())
        self.assertEqual(action["action"], "sf_id")

    def test_returned_work_offers_a_way_back(self):
        from apps.my_plan.services import compute_next_action

        for status in ("returned", "returned_by_pl", "returned_by_ia"):
            act = self._act(status=status)
            action = compute_next_action(act, date.today())
            self.assertIsNotNone(action.get("url"))


class PlReviewAuthorizationTests(TestCase):
    """The review queue was country-wide, unauthorized and unaudited — and the
    API gate (planning.view) is a permission Partner roles also hold."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Rev Region")
        district = District.objects.create(name="Rev District", region=region)
        cls.school = School.objects.create(
            name="Rev Primary",
            school_id="RV-1",
            region_id=region.id,
            district_id=district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-rev@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        self.pl = _user("pl-rev@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.pl_sp = StaffProfile.objects.create(
            user=self.pl, title="PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        self.other_pl = _user(
            "pl2-rev@t.org", "Pia", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        StaffProfile.objects.create(user=self.other_pl, title="PL", country="Uganda")

        self.act = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=timezone.now(),
        )

    def test_supervising_pl_sees_and_can_confirm(self):
        from apps.pl_review import services

        rows = services.queue(self.pl)
        self.assertEqual([r["id"] for r in rows], [self.act.id])
        services.confirm(self.act.id, self.pl)
        self.act.refresh_from_db()
        self.assertEqual(self.act.status, "awaiting_ia_verification")

    def test_unrelated_pl_sees_nothing_and_is_refused(self):
        from apps.pl_review import services

        self.assertEqual(services.queue(self.other_pl), [])
        with self.assertRaises(Forbidden):
            services.confirm(self.act.id, self.other_pl)

    def test_submitter_cannot_confirm_their_own_work(self):
        from apps.pl_review import services

        with self.assertRaises(Forbidden):
            services.confirm(self.act.id, self.cceo)

    def test_review_decisions_are_audited(self):
        from apps.audit.models import AuditLog
        from apps.pl_review import services

        services.return_activity(self.act.id, {"reason": "Evidence unclear"}, self.pl)
        entry = AuditLog.objects.filter(
            action="pl_review_return", subject_id=self.act.id
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.reason, "Evidence unclear")


class CountryEnvelopeSeparationOfDutiesTests(TestCase):
    """The Accountant executes payments; they do not close the country's books."""

    def setUp(self):
        from apps.monthly_work_plan.models import (
            MonthlyWorkPlanBudget,
            MonthlyWorkPlanBudgetStatus,
        )

        self.acct = _user("acct-sod@t.org", "Ada", EdifyRole.PROGRAM_ACCOUNTANT.value)
        StaffProfile.objects.create(user=self.acct, title="Accountant", country="Uganda")
        self.budget = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-05",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT,
            total_amount=5_000_000,
        )

    def test_accountant_cannot_mark_the_month_disbursed(self):
        from apps.monthly_work_plan import reconciliation_service as recon

        with self.assertRaises(Forbidden):
            recon.mark_disbursed(self.budget.id, self.acct)

    def test_accountant_cannot_close_the_month(self):
        from apps.monthly_work_plan import reconciliation_service as recon

        with self.assertRaises(Forbidden):
            recon.close_month(self.budget.id, self.acct)
