from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    User,
)
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SsaPerformanceExportTest(TestCase):
    """The SSA Performance page is retired with the Analytics entry (owner,
    2026-10-19); /ssa opens the reader's profile. Its export still answers."""

    def setUp(self):
        self.fy = get_operational_fy()
        self.quarter = get_quarter_for_date()
        self.north = Region.objects.create(name="SSA North")
        self.south = Region.objects.create(name="SSA South")
        self.kitgum = District.objects.create(name="Kitgum SSA", region=self.north)
        self.gulu = District.objects.create(name="Gulu SSA", region=self.south)
        self.own_school = self._school("SSA-OWN", "Bright Future P/S", self.kitgum)
        self.other_school = self._school("SSA-OTHER", "Outside Scope P/S", self.gulu)

        self.cceo = self._user("ssa-cceo@edify.test", EdifyRole.CCEO.value)
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.own_school.id
        )

    def _user(self, email: str, role: str) -> User:
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0],
            roles=[role],
            active_role=role,
            password="password123",
            is_active=True,
        )

    def _school(self, code: str, name: str, district: District) -> School:
        return School.objects.create(
            school_id=code,
            name=name,
            region=district.region,
            district=district,
            current_fy_ssa_status="done",
        )

    def _ssa(
        self,
        school: School,
        average: float,
        *,
        status: str = "confirmed",
        days_ago: int = 0,
        weak_score: float | None = None,
    ) -> SsaRecord:
        record = SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            quarter=self.quarter,
            date_of_ssa=timezone.now() - timedelta(days=days_ago),
            average_score=average,
            verification_status=status,
        )
        for intervention in SsaIntervention:
            score = (
                weak_score
                if intervention == SsaIntervention.TEACHING_ENVIRONMENT
                and weak_score is not None
                else average
            )
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention.value, score=score
            )
        return record

    def test_export_obeys_role_capability(self):
        self._ssa(self.own_school, 7.0)
        client = Client()
        client.force_login(self.cceo)
        denied = client.get(f"/ssa/export?fy={self.fy}&quarter={self.quarter}")
        self.assertEqual(denied.status_code, 403)

        admin = self._user("ssa-admin@edify.test", EdifyRole.ADMIN.value)
        client.force_login(admin)
        allowed = client.get(f"/ssa/export?fy={self.fy}&quarter={self.quarter}")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["Content-Type"], "text/csv")
        self.assertContains(allowed, "Bright Future P/S")
