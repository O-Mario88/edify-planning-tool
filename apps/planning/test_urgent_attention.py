"""§14 — the urgent-attention card's precedence rules, each executed.

The old card ranked portfolio-wide risk and happily labelled a school
"Financial Health — Critical" off no current SSA at all. The resolver is
SSA-first: no verified current-FY SSA means No SSA and nothing else.
"""

from __future__ import annotations


from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.planning.urgent_attention import (
    monthly_urgent_schools,
    resolve_urgent_issue,
)
from apps.schools.models import School
from apps.ssa.models import SsaRecord


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
        region = Region.objects.create(name="UA Region")
        cls.district = District.objects.create(name="UA District", region=region)
        cls.cceo = _user("ua-cceo@t.org", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        cls.fy = "2026"

    def _school(self, sid):
        school = School.objects.create(
            name=f"UA {sid}",
            school_id=sid,
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=self.sp, school_id=school.id)
        return school

    def _ssa(self, school, status="confirmed", fy=None):
        return SsaRecord.objects.create(
            school=school,
            fy=fy or self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status=status,
        )

    def _plan(self, school, activity_type="school_visit", status="scheduled", day=15):
        return Activity.objects.create(
            school_id=school.id,
            activity_type=activity_type,
            status=status,
            responsible_staff_id=self.sp.id,
            fy=self.fy,
            quarter="Q4",
            planned_date=timezone.make_aware(timezone.datetime(2026, 7, day, 9, 0)),
        )


class PrecedenceTests(Fixture):
    def test_no_current_ssa_shows_no_ssa_and_nothing_else(self):
        school = self._school("UA-1")
        acts = [self._plan(school)]
        issue = resolve_urgent_issue(school, self.fy, acts)
        self.assertEqual(issue["key"], "no_ssa")
        self.assertEqual(issue["severity"], "critical")
        self.assertNotIn(
            "·", issue["label"], "no intervention conclusion without an SSA"
        )

    def test_unverified_ssa_does_not_satisfy_the_requirement(self):
        school = self._school("UA-2")
        self._ssa(school, status="pending")
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "no_ssa")

    def test_prior_fy_ssa_does_not_satisfy_the_requirement(self):
        school = self._school("UA-3")
        self._ssa(school, fy="2025")
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "no_ssa")

    def test_ssa_but_no_support_shows_no_visit_or_training(self):
        school = self._school("UA-4")
        self._ssa(school)
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "no_visit_or_training")

    def test_visit_done_but_no_training_shows_no_training(self):
        school = self._school("UA-5")
        self._ssa(school)
        Activity.objects.create(
            school_id=school.id,
            activity_type="school_visit",
            status="ia_verified",
            fy=self.fy,
            quarter="Q3",
        )
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "no_training")

    def test_training_done_but_no_visit_shows_no_visit(self):
        school = self._school("UA-6")
        self._ssa(school)
        Activity.objects.create(
            school_id=school.id,
            activity_type="training",
            status="ia_verified",
            fy=self.fy,
            quarter="Q3",
        )
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "no_visit")

    def test_all_support_done_shows_the_canonical_recommendation(self):
        school = self._school("UA-7")
        record = self._ssa(school)
        from apps.ssa.models import SsaScore

        SsaScore.objects.create(
            ssa_record=record, intervention="financial_health", score=3.1
        )
        for kind in ("school_visit", "training"):
            Activity.objects.create(
                school_id=school.id,
                activity_type=kind,
                status="ia_verified",
                fy=self.fy,
                quarter="Q3",
            )
        issue = resolve_urgent_issue(school, self.fy, [self._plan(school)])
        self.assertEqual(issue["key"], "intervention_critical")
        self.assertIn("Financial Health", issue["label"])

    def test_scheduled_but_incomplete_shows_as_secondary_context(self):
        school = self._school("UA-8")
        self._ssa(school)
        acts = [self._plan(school, activity_type="training", day=18)]
        issue = resolve_urgent_issue(school, self.fy, acts)
        self.assertEqual(issue["key"], "no_visit_or_training")
        self.assertIn("scheduled for 18 Jul", issue["context"] or "")

    def test_partner_yet_to_schedule_is_named(self):
        school = self._school("UA-9")
        self._ssa(school)
        acts = [
            self._plan(school, activity_type="training", status="assigned_to_partner")
        ]
        issue = resolve_urgent_issue(school, self.fy, acts)
        self.assertEqual(issue["context"], "Partner yet to schedule")


class MonthScopeTests(Fixture):
    def test_only_this_months_planned_schools_appear_deduped(self):
        in_month = self._school("UA-M1")
        self._plan(in_month, day=10)
        self._plan(in_month, activity_type="training", day=20)  # same school twice
        out_month = self._school("UA-M2")
        Activity.objects.create(
            school_id=out_month.id,
            activity_type="school_visit",
            status="scheduled",
            fy=self.fy,
            quarter="Q4",
            planned_date=timezone.make_aware(timezone.datetime(2026, 8, 5, 9, 0)),
        )
        cancelled = self._school("UA-M3")
        self._plan(cancelled, status="cancelled")

        card = monthly_urgent_schools(self.cceo, fy=self.fy, month=7)
        names = [r["name"] for r in card["rows"]]
        self.assertIn("UA UA-M1", names)
        self.assertNotIn("UA UA-M2", names, "another month's school leaked in")
        self.assertNotIn("UA UA-M3", names, "a cancelled activity qualified a school")
        self.assertEqual(names.count("UA UA-M1"), 1, "one school, one row")

    def test_no_ssa_always_sorts_first(self):
        with_ssa = self._school("UA-S1")
        self._ssa(with_ssa)
        self._plan(with_ssa, day=5)
        without = self._school("UA-S2")
        self._plan(without, day=25)
        card = monthly_urgent_schools(self.cceo, fy=self.fy, month=7)
        self.assertEqual(card["rows"][0]["key"], "no_ssa")

    def test_count_is_unique_schools(self):
        school = self._school("UA-C1")
        self._plan(school, day=3)
        self._plan(school, activity_type="training", day=9)
        card = monthly_urgent_schools(self.cceo, fy=self.fy, month=7)
        self.assertEqual(card["total_schools"], 1)
