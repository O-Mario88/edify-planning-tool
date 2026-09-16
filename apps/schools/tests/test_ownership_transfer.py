"""Reassigning school and district portfolio ownership (owner, 2026-09-15).

Admin and Impact Assessment move a school, or a district's schools, from one
staff member to another. Geography never moves with it, assignment history is
kept, settled work keeps the person who did it, and approved targets are
flagged for reconciliation rather than rewritten.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.notifications.models import Notification
from apps.schools import ownership_transfer as transfers
from apps.schools.models import (
    DistrictPortfolioTransfer,
    School,
    SchoolOwnershipTransfer,
)

FY = get_operational_fy()


class OwnershipFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Transfer Region")
        self.district = District.objects.create(
            name="Transfer District", region=self.region
        )
        self.other_district = District.objects.create(
            name="Other Transfer District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Transfer SC", district=self.district
        )
        self.admin = self._user("tr-admin@edify.org", "Admin")
        self.ia = self._user("tr-ia@edify.org", "ImpactAssessment")
        self.pl_user = self._user("tr-pl@edify.org", "Program Lead")
        self.pl = StaffProfile.objects.create(user=self.pl_user, country="Uganda")
        self.old_user = self._user("tr-old@edify.org", "CCEO")
        self.old = StaffProfile.objects.create(user=self.old_user, country="Uganda")
        self.new_user = self._user("tr-new@edify.org", "CCEO")
        self.new = StaffProfile.objects.create(user=self.new_user, country="Uganda")
        self.accountant_user = self._user("tr-acc@edify.org", "Accountant")
        self.accountant = StaffProfile.objects.create(
            user=self.accountant_user, country="Uganda"
        )
        for staff in (self.old, self.new):
            StaffSupervisorAssignment.objects.create(
                supervisee=staff, supervisor=self.pl
            )
        self.school = self._school("TR-1", "Transfer Primary")

    def _user(self, email, role):
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0].title(),
            roles=[role],
            active_role=role,
            password="x",
        )

    def _school(self, code, name, owner=None, district=None):
        owner = owner or self.old
        school = School.objects.create(
            school_id=code,
            name=name,
            region=self.region,
            district=district or self.district,
            sub_county=self.sub_county
            if (district or self.district) == self.district
            else None,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_name_raw=owner.user.name,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def _activity(self, school, status, owner=None):
        return Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate() + datetime.timedelta(days=7),
            status=status,
            responsible_staff_id=(owner or self.old).id,
            delivery_type="staff",
        )

    def _payload(self, **extra):
        return {
            "newOwnerId": self.new.id,
            "reason": "The officer left the district.",
            "effectiveDate": timezone.localdate().isoformat(),
            **extra,
        }


class SchoolOwnerTransferTest(OwnershipFixture):
    def test_admin_and_ia_may_transfer_and_nobody_else(self):
        for principal in (self.admin, self.ia):
            with self.subTest(role=principal.active_role):
                self.assertTrue(transfers.may_transfer_school(principal))
        for principal in (self.pl_user, self.old_user, self.accountant_user):
            with self.subTest(role=principal.active_role):
                self.assertFalse(transfers.may_transfer_school(principal))
                with self.assertRaises(Forbidden):
                    transfers.transfer_school_owner(
                        self.school.id, self._payload(), principal
                    )
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.old.id)

    def test_a_transfer_moves_ownership_and_keeps_geography_and_history(self):
        record = transfers.transfer_school_owner(
            self.school.id, self._payload(), self.admin
        )
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.new.id)
        self.assertEqual(self.school.account_owner_name_raw, self.new.user.name)
        # Geography untouched.
        self.assertEqual(self.school.district_id, self.district.id)
        self.assertEqual(self.school.sub_county_id, self.sub_county.id)
        # One active assignment; the history row keeps the old owner.
        assignments = StaffSchoolAssignment.objects.filter(school_id=self.school.id)
        self.assertEqual([a.staff_id for a in assignments], [self.new.id])
        self.assertEqual(record.from_staff_id, self.old.id)
        self.assertEqual(record.to_staff_id, self.new.id)
        self.assertEqual(record.reason, "The officer left the district.")
        row = AuditLog.objects.get(
            action="school.owner_transferred", subject_id=self.school.id
        )
        self.assertEqual(row.payload["previous"]["ownerStaffId"], self.old.id)
        self.assertEqual(row.payload["new"]["ownerStaffId"], self.new.id)
        self.assertEqual(row.payload["new"]["districtId"], self.district.id)

    def test_the_new_owner_must_be_an_active_portfolio_role(self):
        with self.assertRaisesMessage(BadRequest, "cannot hold a school portfolio"):
            transfers.transfer_school_owner(
                self.school.id,
                self._payload(newOwnerId=self.accountant.id),
                self.admin,
            )
        User.objects.filter(id=self.new_user.id).update(is_active=False)
        with self.assertRaisesMessage(BadRequest, "not active"):
            transfers.transfer_school_owner(self.school.id, self._payload(), self.admin)

    def test_a_reason_is_required(self):
        with self.assertRaisesMessage(BadRequest, "reason"):
            transfers.transfer_school_owner(
                self.school.id, self._payload(reason=""), self.admin
            )

    def test_open_activities_stay_unless_the_transfer_says_otherwise(self):
        open_one = self._activity(self.school, "scheduled")
        settled = self._activity(self.school, "ia_verified")
        record = transfers.transfer_school_owner(
            self.school.id, self._payload(), self.admin
        )
        open_one.refresh_from_db()
        settled.refresh_from_db()
        self.assertEqual(open_one.responsible_staff_id, self.old.id)
        self.assertEqual(settled.responsible_staff_id, self.old.id)
        self.assertEqual(record.transferred_activity_ids, [])
        self.assertIn(open_one.id, record.kept_activity_ids)

    def test_choosing_to_transfer_moves_only_the_eligible_open_work(self):
        open_one = self._activity(self.school, "scheduled")
        returned = self._activity(self.school, "returned_by_pl")
        verified = self._activity(self.school, "ia_verified")
        completed = self._activity(self.school, "completed")
        record = transfers.transfer_school_owner(
            self.school.id,
            self._payload(openActivityDecision="transfer"),
            self.admin,
        )
        for activity in (open_one, returned):
            activity.refresh_from_db()
            self.assertEqual(activity.responsible_staff_id, self.new.id)
        for activity in (verified, completed):
            activity.refresh_from_db()
            self.assertEqual(
                activity.responsible_staff_id,
                self.old.id,
                "settled work keeps the person who did it",
            )
        self.assertEqual(
            set(record.transferred_activity_ids), {open_one.id, returned.id}
        )
        self.assertTrue(
            AuditLog.objects.filter(action="activity.ownership_transferred").exists()
        )

    def test_the_old_owner_new_owner_and_supervisor_are_told(self):
        with self.captureOnCommitCallbacks(execute=True):
            transfers.transfer_school_owner(self.school.id, self._payload(), self.admin)
        recipients = set(
            Notification.objects.filter(
                source_event_type="school_ownership_transferred"
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(
            recipients, {self.old_user.id, self.new_user.id, self.pl_user.id}
        )

    def test_scope_follows_the_transfer(self):
        from apps.core.scoping import direct_portfolio_schools, resolve_user_scope

        transfers.transfer_school_owner(self.school.id, self._payload(), self.admin)
        old_scope = direct_portfolio_schools(resolve_user_scope(self.old_user))
        new_scope = direct_portfolio_schools(resolve_user_scope(self.new_user))
        self.assertNotIn(self.school.id, {s.id for s in old_scope})
        self.assertIn(self.school.id, {s.id for s in new_scope})

    def test_the_drawer_previews_then_transfers(self):
        self._activity(self.school, "scheduled")
        self.client.force_login(self.ia)
        url = f"/schools/{self.school.school_id}/transfer-owner"
        drawer = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(drawer, "Reassign School Owner")
        self.assertContains(drawer, "unchanged by this transfer")
        # Without the confirmation nothing moves.
        unconfirmed = self.client.post(
            url,
            {
                "new_owner_id": self.new.id,
                "reason": "Handover",
                "effective_date": timezone.localdate().isoformat(),
                "open_activity_decision": "keep",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(unconfirmed, "then confirm the transfer")
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.old.id)
        done = self.client.post(
            url,
            {
                "new_owner_id": self.new.id,
                "reason": "Handover",
                "effective_date": timezone.localdate().isoformat(),
                "open_activity_decision": "keep",
                "confirm": "yes",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(done.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.new.id)

    def test_a_programme_lead_is_refused_the_drawer(self):
        self.client.force_login(self.pl_user)
        response = self.client.get(
            f"/schools/{self.school.school_id}/transfer-owner", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 403)


class DistrictPortfolioTransferTest(OwnershipFixture):
    def setUp(self):
        super().setUp()
        self.second = self._school("TR-2", "Second Transfer Primary")
        self.elsewhere = self._school(
            "TR-3", "Elsewhere Primary", district=self.other_district
        )

    def test_the_preview_counts_what_would_move(self):
        self._activity(self.school, "scheduled")
        preview = transfers.preview_district_transfer(self.district, self.old, self.new)
        self.assertEqual(preview.school_count, 2)
        self.assertEqual(preview.open_activities, 1)
        self.assertEqual(preview.current_owner_name, self.old_user.name)

    def test_the_batch_moves_only_that_districts_schools(self):
        with self.captureOnCommitCallbacks(execute=True):
            batch = transfers.transfer_district_portfolio(
                self.district.id,
                {"fromStaffId": self.old.id, **self._payload()},
                self.ia,
            )
        self.assertEqual(batch.school_count, 2)
        for school in (self.school, self.second):
            school.refresh_from_db()
            self.assertEqual(school.account_owner_id, self.new.id)
            self.assertEqual(school.district_id, self.district.id)
        self.elsewhere.refresh_from_db()
        self.assertEqual(self.elsewhere.account_owner_id, self.old.id)
        # One school row per school, all pointing at the batch.
        self.assertEqual(SchoolOwnershipTransfer.objects.filter(batch=batch).count(), 2)
        self.assertTrue(
            AuditLog.objects.filter(action="district.portfolio_transferred").exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                source_event_type="district_portfolio_transferred"
            ).exists()
        )

    def test_a_district_the_person_does_not_hold_is_refused(self):
        # self.new holds nothing in the other district; self.old holds one.
        with self.assertRaisesMessage(BadRequest, "holds no school"):
            transfers.transfer_district_portfolio(
                self.other_district.id,
                {
                    "fromStaffId": self.new.id,
                    "newOwnerId": self.old.id,
                    "reason": "Nothing to move.",
                    "effectiveDate": timezone.localdate().isoformat(),
                },
                self.admin,
            )

    def test_the_page_is_for_admin_and_ia_only(self):
        self.client.force_login(self.ia)
        page = self.client.get("/ownership-transfers/")
        self.assertContains(page, "Ownership Transfers")
        self.client.force_login(self.pl_user)
        refused = self.client.get("/ownership-transfers/")
        self.assertRedirects(refused, "/dashboard", fetch_redirect_response=False)

    def test_the_page_transfers_a_district_portfolio(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            "/ownership-transfers/",
            {
                "action": "transfer_district",
                "district_id": self.district.id,
                "from_staff_id": self.old.id,
                "new_owner_id": self.new.id,
                "reason": "Restructure",
                "effective_date": timezone.localdate().isoformat(),
                "open_activity_decision": "keep",
                "confirm": "yes",
            },
        )
        self.assertRedirects(
            response, "/ownership-transfers/", fetch_redirect_response=False
        )
        self.assertEqual(DistrictPortfolioTransfer.objects.count(), 1)


class TargetReconciliationTest(OwnershipFixture):
    def _approved_allocation(self):
        from apps.hr.models import (
            MilestoneAllocation,
            PriorityMilestone,
            StrategicPriority,
            StrategicPriorityCycle,
        )

        cycle = StrategicPriorityCycle.objects.create(
            financial_year=FY, title=f"FY{FY} cycle"
        )
        priority = StrategicPriority.objects.create(
            cycle=cycle,
            code="P1",
            fy=FY,
            level="country",
            title="Priority",
            strategic_purpose="Portfolio coverage",
        )
        milestone = PriorityMilestone.objects.create(
            priority=priority,
            code="M1",
            title="Visits",
            source_text="x",
            milestone_type="output",
            measurement_type="count",
            progress_source="activities",
        )
        return MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="employee",
            employee=self.old,
            allocated_target=10,
            denominator=10,
            allocation_reason="Portfolio size",
            allocated_by=self.ia.id,
            effective_date=timezone.localdate(),
            status="approved",
        )

    def test_targets_are_flagged_not_rewritten_and_can_be_reconciled(self):
        allocation = self._approved_allocation()
        with self.captureOnCommitCallbacks(execute=True):
            record = transfers.transfer_school_owner(
                self.school.id, self._payload(), self.ia
            )
        self.assertEqual(record.target_reconciliation_status, "required")
        allocation.refresh_from_db()
        # Untouched: the figure, its owner and its status all stand.
        self.assertEqual(allocation.employee_id, self.old.id)
        self.assertEqual(allocation.allocated_target, 10)
        self.assertEqual(allocation.status, "approved")
        self.assertTrue(
            Notification.objects.filter(
                source_event_type="target_reconciliation_required",
                context_id=record.id,
            ).exists()
        )
        resolved = transfers.resolve_target_reconciliation(
            record.id, self.ia, note="Amended the FY allocation."
        )
        self.assertEqual(resolved.target_reconciliation_status, "resolved")
        self.assertTrue(
            AuditLog.objects.filter(action="targets.reconciliation_resolved").exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                source_event_type="target_reconciliation_required",
                context_id=record.id,
                resolved_at__isnull=True,
            ).exists()
        )

    def test_a_transfer_with_no_affected_target_is_not_flagged(self):
        record = transfers.transfer_school_owner(
            self.school.id, self._payload(), self.admin
        )
        self.assertEqual(record.target_reconciliation_status, "not_required")
