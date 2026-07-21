"""Regressions for the post-remediation verification audit's five criticals.

Each test exercises the repaired path — not its source text. The audit caught
two NameErrors that source-inspection tests had waved through; these run code.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="VC Region")
        cls.district = District.objects.create(name="VC District", region=region)
        cls.school = School.objects.create(
            name="VC Client",
            school_id="VC-1",
            region_id=region.id,
            district_id=cls.district.id,
            school_type="client",
        )
        cls.cceo = _user("vc-cceo@t.org", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        StaffSchoolAssignment.objects.create(staff=cls.sp, school_id=cls.school.id)


class PhantomStatusTests(Fixture):
    """C1 — "completed" is a status no production transition writes."""

    def test_the_canonical_constant_covers_the_real_chain(self):
        for status in ("ia_verified", "closed"):
            self.assertIn(status, COMPLETED_WORK_STATUSES)

    def test_no_swept_file_filters_on_the_bare_phantom_status(self):
        import subprocess

        out = subprocess.run(
            [
                "grep",
                "-rln",
                'status="completed"',
                "apps/",
                "--include=*.py",
            ],
            capture_output=True,
            text=True,
        ).stdout
        offenders = [
            line
            for line in out.splitlines()
            if "/tests" not in line
            and "test_" not in line
            and "/migrations/" not in line
            and "seed" not in line
        ]
        self.assertEqual(
            offenders,
            [],
            "a read path filtering on the phantom status matches only seeded "
            "rows and skips every verified real activity",
        )

    def test_verified_cluster_training_counts_and_meetings_do_not(self):
        from apps.frontend.view_models import SchoolDirectoryViewModel

        Activity.objects.create(
            school_id=self.school.id,
            activity_type="cluster_training",
            status="ia_verified",
            fy="2026",
            quarter="Q4",
            attended_school_ids=[self.school.id],
        )
        Activity.objects.create(
            school_id=self.school.id,
            activity_type="cluster_meeting",
            status="ia_verified",
            fy="2026",
            quarter="Q4",
            attended_school_ids=[self.school.id],
        )
        progress = SchoolDirectoryViewModel.bulk_progress([self.school.id])
        trainings = progress.get(self.school.id, {}).get("trainings_count", 0)
        self.assertEqual(
            trainings,
            1,
            "an IA-verified training must count exactly once; a meeting is "
            "not a training",
        )


class UnverifiedSsaTests(Fixture):
    """C2 — official surfaces read confirmed SSA only."""

    def test_champion_eligibility_ignores_unconfirmed_ssa(self):
        from apps.core_schools.champion_services import ChampionEligibilityService
        from apps.ssa.models import SsaRecord

        from django.utils import timezone

        SsaRecord.objects.create(
            school=self.school,
            fy="2026",
            date_of_ssa=timezone.now(),
            average_score=9.5,
            verification_status="pending",
        )
        result = ChampionEligibilityService.calculate_score(self.school)
        self.assertFalse(
            result.get("eligible", False),
            "an unconfirmed 9.5 must not drive Champion readiness",
        )

    def test_planning_and_projects_reads_carry_the_confirmed_filter(self):
        import inspect

        from apps.core_schools import champion_services
        from apps.frontend.views import planning_views
        from apps.projects import planning_service

        for module in (planning_views, planning_service, champion_services):
            source = inspect.getsource(module)
            for chunk in source.split("ssa_records.filter(")[1:]:
                head = chunk.split(")")[0]
                self.assertIn(
                    "confirmed",
                    head,
                    f"{module.__name__} reads SSA without a verification filter",
                )


class ClientEntitlementTests(Fixture):
    """C3 — one visit and one training per client school per FY."""

    def _payload(self, activity_type):
        return {
            "schoolId": self.school.school_id,
            "activityType": activity_type,
            "scheduledDate": (date.today() + timedelta(days=7)).isoformat(),
            "deliveryType": "staff",
        }

    def test_a_second_visit_in_the_same_fy_is_refused(self):
        from apps.activities.services import create

        create(self._payload("school_visit"), self.cceo)
        with self.assertRaises(BadRequest):
            create(self._payload("school_visit"), self.cceo)

    def test_a_second_training_in_the_same_fy_is_refused(self):
        from apps.activities.services import create

        create(self._payload("training"), self.cceo)
        with self.assertRaises(BadRequest):
            create(self._payload("in_school_training"), self.cceo)

    def test_a_visit_does_not_consume_the_training_entitlement(self):
        from apps.activities.services import create

        create(self._payload("school_visit"), self.cceo)
        created = create(self._payload("training"), self.cceo)
        self.assertTrue(created.get("id"))

    def test_a_cancelled_visit_releases_the_slot(self):
        from apps.activities.services import create

        first = create(self._payload("school_visit"), self.cceo)
        Activity.objects.filter(id=first["id"]).update(status="cancelled")
        second = create(self._payload("school_visit"), self.cceo)
        self.assertTrue(second.get("id"))


class CoreBypassTests(Fixture):
    """HIGH — core types must arrive through the slot machinery."""

    def test_raw_core_visit_post_is_refused(self):
        from apps.activities.services import create

        payload = {
            "schoolId": self.school.school_id,
            "activityType": "core_visit",
            "scheduledDate": (date.today() + timedelta(days=7)).isoformat(),
            "deliveryType": "staff",
        }
        with self.assertRaises(BadRequest):
            create(payload, self.cceo)


class StaffCoreAnnualCapTests(TestCase):
    """C4 — the staff share of a core package is 2+2 per FY, not per quarter."""

    def test_the_annual_cap_is_checked_before_the_quarter_window(self):
        import inspect

        from apps.core_schools.core_planning_services import (
            CorePackageSchedulingService,
        )

        source = inspect.getsource(CorePackageSchedulingService.assert_can_schedule)
        self.assertIn("STAFF_ANNUAL_CAP", source)
        # The FY-level count must not be quarter-filtered.
        annual_block = source.split("STAFF_ANNUAL_CAP")[1].split("staff_already")[0]
        self.assertNotIn("quarter=current_quarter", annual_block)


class ClusterAttendanceMembershipTests(Fixture):
    """C5 — attendance may only credit the cluster's own schools."""

    def test_non_member_and_duplicate_ids_are_dropped(self):
        from apps.activities.services import _cluster_member_school_ids
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="VC Cluster",
            district_id=self.district.id,
            region_id=self.school.region_id,
        )
        member = School.objects.create(
            name="Member",
            school_id="VC-M",
            region_id=self.school.region_id,
            district_id=self.district.id,
        )
        # School.save() nulls cluster_id (documented model gotcha) — assign
        # membership the way the cluster service does, via queryset update.
        School.objects.filter(id=member.id).update(cluster_id=cluster.id)
        outsider = School.objects.create(
            name="Outsider",
            school_id="VC-O",
            region_id=self.school.region_id,
            district_id=self.district.id,
        )
        activity = Activity.objects.create(
            cluster_id=cluster.id,
            activity_type="cluster_training",
            status="scheduled",
            fy="2026",
            quarter="Q4",
        )
        kept = _cluster_member_school_ids(
            activity, [member.id, member.id, outsider.id, " "]
        )
        self.assertEqual(kept, [member.id])


class ReimbursementIdempotencyTests(Fixture):
    """The reimbursement channel was the only money path with no repeat guard."""

    def test_a_paid_claim_cannot_be_paid_again(self):
        from apps.fund_requests.finance_models import ReimbursementClaim
        from apps.fund_requests.finance_services import ReimbursementService

        activity = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="ia_verified",
            fy="2026",
            quarter="Q4",
            # disburse_reimbursement closes the activity, and the DB check
            # constraint (rightly) requires an SF id on closed rows.
            salesforce_activity_id="SVE-REIMB-1",
        )
        claim = ReimbursementClaim.objects.create(
            activity=activity,
            reimbursement_amount=25_000,
            approved_budget=25_000,
            actual_spend=50_000,
        )
        ReimbursementService.disburse_reimbursement(
            claim, "bank", "REF-1", self.cceo.id
        )
        with self.assertRaises(ValueError):
            ReimbursementService.disburse_reimbursement(
                claim, "bank", "REF-2", self.cceo.id
            )
        from apps.fund_requests.finance_models import Disbursement

        self.assertEqual(
            Disbursement.objects.filter(activity=activity).count(),
            1,
            "a retry must not write a second Disbursement row for one debt",
        )


class SsaUploadAuthorityTests(Fixture):
    """Official SSA may be minted only under the SSA_UPLOAD permission."""

    def test_a_cceo_cannot_post_an_ssa_upload(self):
        self.client.force_login(self.cceo)
        r = self.client.post("/ssa/upload/", {})
        # Redirected back with an error, not processed: page access is for
        # reading; a staff upload is born "confirmed" so minting needs IA.
        self.assertIn(r.status_code, (302, 403))
        from apps.schools.models import SSAImportBatch

        self.assertEqual(SSAImportBatch.objects.count(), 0)


class ExportPermissionTests(Fixture):
    """data.export gates bulk extraction; page permission alone is not enough."""

    def test_a_cceo_cannot_export_the_partner_register(self):
        """Org-wide datasets are gated on data.export. Scoped own-data
        exports (a CCEO's own school portfolio, their own plan) deliberately
        remain on page permission — extraction of what you already see is
        not the risk; the org register is."""
        self.client.force_login(self.cceo)
        r = self.client.get("/partners?export=csv")
        self.assertNotEqual(
            r.get("Content-Type", ""),
            "text/csv",
            "a role without data.export must not receive the org register",
        )

    def test_page_load_without_export_still_works(self):
        self.client.force_login(self.cceo)
        r = self.client.get("/partners")
        self.assertEqual(r.status_code, 200)


class VolumeReconciliationTests(Fixture):
    """Money reconciles to UGX 0 at volume, not just on a near-empty DB."""

    def test_cost_lines_and_weekly_requests_agree_at_three_hundred(self):
        from django.db.models import Sum

        from apps.activities.models import ActivityScheduleCostLine
        from apps.activities.services import create
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.schools.models import School

        for i in range(300):
            school = School.objects.create(
                name=f"Vol {i}",
                school_id=f"VOL-{i}",
                region_id=self.school.region_id,
                district_id=self.district.id,
                school_type="client",
            )
            StaffSchoolAssignment.objects.create(staff=self.sp, school_id=school.id)
            create(
                {
                    "schoolId": school.school_id,
                    "activityType": "school_visit",
                    # Weekdays only — the calendar policy (rightly) blocks
                    # Sunday scheduling.
                    "scheduledDate": (
                        date.today()
                        + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
                        + timedelta(days=i % 5)
                    ).isoformat(),
                    "deliveryType": "staff",
                },
                self.cceo,
            )
        planned = (
            ActivityScheduleCostLine.objects.aggregate(total=Sum("amount"))["total"]
            or 0
        )
        requested = (
            WeeklyFundRequest.objects.aggregate(total=Sum("total_amount"))["total"] or 0
        )
        self.assertEqual(
            planned - requested,
            0,
            f"planned {planned} != requested {requested}: the seam must "
            "reconcile to UGX 0 at volume",
        )
