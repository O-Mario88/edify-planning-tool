"""The Core Schools page's plan self-heal: bounded, gated, and bulk.

The page gives every core school in the reader's scope its package for the
year, on read. On a 16,000-school estate that cost a Country Director ~550
single-row INSERTs per load (3 of 6 seconds), and 50 core schools without a
confirmed SSA were re-selected forever, blocking every school after them
(performance rescue, 2026-09-23). These pin the corrected behaviour.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools import core_planning_services as planning
from apps.core_schools.core_planning_services import CoreSchoolsService
from apps.core_schools.models import (
    CoreActivitySlot,
    CorePlan,
    CoreSchoolProfile,
    cplan_id,
    cprof_id,
)
from apps.core_schools.services import EXPECTED_CORE_SLOTS
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()
FY = get_operational_fy()


class CoreSelfHealTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Heal R")
        cls.district = District.objects.create(
            name="Heal D", region=cls.region, district_type="primary"
        )
        cls.cceo = User.objects.create_user(
            email="heal@core.org",
            name="Heal Cceo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        cls.sp = StaffProfile.objects.create(user=cls.cceo, title="CCEO")

    def _schools(self, count, *, prefix, with_ssa):
        schools = School.objects.bulk_create(
            [
                School(
                    school_id=f"{prefix}{i:04d}",
                    name=f"{prefix} School {i}",
                    region=self.region,
                    district=self.district,
                    school_type="core",
                    account_owner_id=self.sp.user_id,
                )
                for i in range(count)
            ]
        )
        StaffSchoolAssignment.objects.bulk_create(
            [StaffSchoolAssignment(staff=self.sp, school_id=s.id) for s in schools]
        )
        if with_ssa:
            SsaRecord.objects.bulk_create(
                [
                    SsaRecord(
                        school_id=s.id,
                        fy=FY,
                        quarter="Q1",
                        date_of_ssa=timezone.now(),
                        average_score=6.5,
                        verification_status="confirmed",
                        uploaded_by="test",
                    )
                    for s in schools
                ]
            )
        return schools

    def _scope(self):
        qs, _scope = CoreSchoolsService.base_queryset(self.cceo, lens="direct")
        return qs

    def test_schools_without_ssa_no_longer_block_the_rest(self):
        # More un-healable schools than one batch, sorting ahead of the rest.
        self._schools(planning.SELF_HEAL_BATCH + 5, prefix="A", with_ssa=False)
        healable = self._schools(3, prefix="Z", with_ssa=True)
        healed = CoreSchoolsService.self_heal_plans(self._scope(), FY, self.cceo)
        self.assertEqual(healed, 3)
        self.assertEqual(
            set(CorePlan.objects.filter(fy=FY).values_list("school_id", flat=True)),
            {s.school_id for s in healable},
        )

    def test_a_batch_costs_the_same_statements_whatever_its_size(self):
        self._schools(2, prefix="S", with_ssa=True)
        scope = self._scope()
        with CaptureQueriesContext(connection) as small:
            CoreSchoolsService.self_heal_plans(scope, FY, self.cceo)
        CorePlan.objects.all().delete()
        self._schools(40, prefix="L", with_ssa=True)
        scope = self._scope()
        with CaptureQueriesContext(connection) as large:
            CoreSchoolsService.self_heal_plans(scope, FY, self.cceo)
        # Candidates, latest SSA, then plan / profile / slot bulk writes inside
        # one savepoint — not ~11 statements per school.
        self.assertLessEqual(len(large), len(small))
        self.assertLessEqual(len(large), 10)

    def test_healing_is_complete_and_idempotent(self):
        schools = self._schools(4, prefix="I", with_ssa=True)
        CoreSchoolsService.self_heal_plans(self._scope(), FY, self.cceo)
        CoreSchoolsService.self_heal_plans(self._scope(), FY, self.cceo)
        for school in schools:
            plan = CorePlan.objects.get(school_id=school.school_id, fy=FY)
            self.assertEqual(plan.id, cplan_id(school.school_id, fy=FY))
            self.assertEqual(plan.baseline_average, 6.5)
            self.assertEqual(plan.created_by_id, self.cceo.id)
            self.assertEqual(
                CoreActivitySlot.objects.filter(core_plan=plan).count(),
                EXPECTED_CORE_SLOTS,
            )
            profile = CoreSchoolProfile.objects.get(id=cprof_id(school.school_id))
            self.assertEqual(profile.core_plan_id, plan.id)
            self.assertEqual(profile.core_start_fy, FY)
        self.assertEqual(CorePlan.objects.count(), 4)

    def test_an_existing_profile_is_repointed_at_the_new_plan(self):
        """update_or_create semantics: last year's profile follows the package."""
        (school,) = self._schools(1, prefix="P", with_ssa=True)
        old_plan = CorePlan.objects.create(
            id=cplan_id(school.school_id, fy=str(int(FY) - 1)),
            school_id=school.school_id,
            fy=str(int(FY) - 1),
        )
        CoreSchoolProfile.objects.create(
            id=cprof_id(school.school_id),
            school_id=school.school_id,
            core_plan=old_plan,
            core_start_fy=old_plan.fy,
        )
        CoreSchoolsService.self_heal_plans(self._scope(), FY, self.cceo)
        profile = CoreSchoolProfile.objects.get(id=cprof_id(school.school_id))
        self.assertEqual(profile.core_plan_id, cplan_id(school.school_id, fy=FY))
        self.assertEqual(profile.core_start_fy, FY)

    def test_nothing_to_heal_costs_one_query(self):
        self._schools(3, prefix="N", with_ssa=False)
        scope = self._scope()
        with self.assertNumQueries(1):
            self.assertEqual(
                CoreSchoolsService.self_heal_plans(scope, FY, self.cceo), 0
            )

    def test_a_batch_reaches_the_newest_schools_first(self):
        """Which schools one load heals is the order it always was (School's
        own newest-first ordering), so the bulk rewrite does not change which
        schools a reader sees healed first."""
        from datetime import timedelta

        older = self._schools(planning.SELF_HEAL_BATCH, prefix="O", with_ssa=True)
        newer = self._schools(3, prefix="N", with_ssa=True)
        School.objects.filter(id__in=[s.id for s in older]).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        CoreSchoolsService.self_heal_plans(self._scope(), FY, self.cceo)
        healed = set(CorePlan.objects.filter(fy=FY).values_list("school_id", flat=True))
        self.assertEqual(len(healed), planning.SELF_HEAL_BATCH)
        self.assertTrue({s.school_id for s in newer} <= healed)
