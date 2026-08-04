"""A Program Lead's School Directory lists the schools they own, not the team's.

`resolve_user_scope` builds `school_ids` as the union of `own_school_ids` and
the schools of every supervised staff member. The School Directory read that
union, so a supervising PL saw their CCEOs' schools listed as their own — on
production, 1030 of the 2171 rows in one PL's directory (47.4%) belonged to two
supervised CCEOs, each carrying the same edit, cluster, project and staff-match
controls as a school the PL actually owned.

Supervision is not ownership. The directory and its bulk actions now narrow to
`own_school_ids` via `school_queryset(scope, direct_only=True)`.

Only the directory narrows. The flat own+team scope is correct for team
targets, PL analytics and the review queue, and roughly fifteen services read
it, so `school_ids` keeps its meaning — which is what the last test here pins
down. Without that, a later "tidy-up" that pushed `direct_only` down into
`resolve_user_scope` would silently blank every team surface.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


class ProgramLeadDirectoryIsDirectOnlyTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="PLD Region")
        self.district = District.objects.create(name="PLD District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="PLD Sub", district=self.district
        )

        self.pl = self._user("pld-pl", "pld-pl@edify.org", "PLD Lead", "Program Lead")
        self.pl_sp = StaffProfile.objects.create(
            id="pld-pl-sp", user=self.pl, title="PL"
        )

        self.cceo = self._user("pld-cceo", "pld-cceo@edify.org", "PLD Field", "CCEO")
        self.cceo_sp = StaffProfile.objects.create(
            id="pld-cceo-sp", user=self.cceo, title="CCEO"
        )
        # The supervision link that produces the union.
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )

        self.mine = self._school("PLD-MINE", "PLD Mine", self.pl_sp)
        self.theirs = self._school("PLD-THEIRS", "PLD Theirs", self.cceo_sp)

    def _user(self, uid, email, name, role):
        return User.objects.create(
            id=uid,
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            is_active=True,
        )

    def _school(self, school_id, name, owner):
        school = School.objects.create(
            school_id=school_id,
            name=name,
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_name_raw=owner.user.name,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.get_or_create(staff=owner, school_id=school.id)
        return school

    def test_the_fixture_actually_produces_a_supervised_school(self):
        # If this fails the rest of the file proves nothing: the union has to
        # exist before narrowing it can mean anything.
        scope = resolve_user_scope(self.pl)
        self.assertIn(self.theirs.id, scope.school_ids)
        self.assertIn(self.theirs.id, scope.team_school_ids)
        self.assertNotIn(self.theirs.id, scope.own_school_ids)

    def test_directory_lists_only_directly_assigned_schools(self):
        self.client.force_login(self.pl)
        body = self.client.get("/schools").content.decode()
        self.assertIn("PLD Mine", body)
        self.assertNotIn(
            "PLD Theirs",
            body,
            "a supervised CCEO's school must not appear in the PL's directory",
        )

    def test_bulk_match_staff_cannot_reach_a_supervised_schools_ownership(self):
        self.client.force_login(self.pl)
        self.client.post(
            "/schools/bulk-match-staff",
            {"school_ids": self.theirs.id, "staff_id": self.pl_sp.id},
        )
        self.theirs.refresh_from_db()
        self.assertEqual(
            self.theirs.account_owner_id,
            self.cceo_sp.id,
            "supervision must not become ownership through the bulk action",
        )

    def test_direct_only_is_opt_in_and_leaves_the_team_scope_intact(self):
        scope = resolve_user_scope(self.pl)
        direct = set(
            school_queryset(scope, direct_only=True).values_list("id", flat=True)
        )
        full = set(school_queryset(scope).values_list("id", flat=True))

        self.assertEqual(direct, {self.mine.id})
        self.assertEqual(
            full,
            {self.mine.id, self.theirs.id},
            "team targets, PL analytics and the review queue still read the "
            "union — narrowing is the directory's choice, not the scope's",
        )

    def test_a_cceo_sees_no_change(self):
        # A CCEO supervises nobody, so own == union and the narrowing is a no-op.
        scope = resolve_user_scope(self.cceo)
        self.assertEqual(
            set(school_queryset(scope, direct_only=True).values_list("id", flat=True)),
            set(school_queryset(scope).values_list("id", flat=True)),
        )
