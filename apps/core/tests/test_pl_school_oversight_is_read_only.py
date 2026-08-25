"""Supervision is not ownership.

A Program Lead sees two portfolios: schools assigned to them, and schools
assigned to the CCEOs they supervise. The first is theirs to work. The second
is theirs to watch.

`can_update` ended with `return can_view_record(user, obj)` — edit permission
was view permission. Every school a PL could see, a PL could edit, which for a
Program Lead means every school belonging to every CCEO on their team. Nothing
in the interface offered those controls, so the hole was invisible until
someone reached the endpoint directly; template hiding is not authorization,
and the API, the HTMX endpoints and the bulk actions all resolve through this
one function.

The distinction these tests hold: a PL keeps every authorized action on their
own schools, and loses only mutation on their team's.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.core.permissions import RolePermissionService
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class ProgramLeadSchoolAccessTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Scope Region")
        self.district = District.objects.create(
            name="Scope District", region=self.region
        )

        self.pl, self.pl_profile = self._staff("pl", "Program Lead")
        self.cceo, self.cceo_profile = self._staff("cceo", "CCEO")
        self.other_cceo, self.other_cceo_profile = self._staff("other", "CCEO")

        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_profile, supervisee=self.cceo_profile
        )

        self.own_school = self._school("PL-OWN", self.pl_profile)
        self.team_school = self._school("TEAM-1", self.cceo_profile)
        self.other_school = self._school("OTHER-1", self.other_cceo_profile)

    def _staff(self, key, role):
        user = User.objects.create(
            id=f"sc-{key}",
            email=f"sc-{key}@edify.org",
            name=f"SC {key}",
            roles=[role],
            active_role=role,
            is_active=True,
        )
        profile = StaffProfile.objects.create(id=f"scp-{key}", user=user, title=role)
        return user, profile

    def _school(self, ref, owner_profile):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=owner_profile.id,
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=owner_profile, school_id=school.id
        )
        return school

    # ── the hole ─────────────────────────────────────────────────────────────

    def test_a_program_lead_cannot_edit_a_supervised_cceos_school(self):
        """The defect. Supervision granted mutation because can_update
        delegated to can_view_record, and a PL can view their team's schools
        by design."""
        self.assertFalse(
            RolePermissionService.can_update(self.pl, self.team_school),
            "read-only oversight: a school on the team is not the PL's to edit",
        )

    def test_a_program_lead_cannot_delete_a_supervised_cceos_school(self):
        self.assertFalse(RolePermissionService.can_delete(self.pl, self.team_school))

    def test_the_edit_drawer_refuses_a_supervisors_write(self):
        """The same rule, asked of the endpoint instead of the helper.

        `can_update` above has no production caller — every school-row write
        reaches its own guard — so the two tests before this one held while the
        edit drawer stayed open. It gated on `get_scoped_object_or_404`, which
        answers the READ question a PL is meant to pass for a team school, and
        then wrote `account_owner_id` and rebuilt `StaffSchoolAssignment`: the
        row `resolve_user_scope` reads to decide planning, targets and budget
        scope. A supervisor could move a supervised school onto themselves.

        `apps/frontend/test_bulk_school_actions_scope.py` calls that outcome
        "the worst one to lose" while its docstring records the single-school
        paths as never affected. This is the test that would have disagreed.
        """
        self.client.force_login(self.pl)
        response = self.client.post(
            f"/schools/{self.team_school.id}/edit-drawer",
            {
                "school_id": "TEAM-1",
                "name": "TAKEN BY THE SUPERVISOR",
                "school_type": "client",
                "district_id": str(self.district.id),
                "account_owner_id": self.pl_profile.id,
            },
        )
        self.assertEqual(
            response.status_code,
            403,
            "a Programme Lead reached the write path on a supervised school",
        )
        self.team_school.refresh_from_db()
        self.assertEqual(
            self.team_school.name,
            "School TEAM-1",
            "the supervised school was renamed by its supervisor",
        )
        self.assertEqual(
            self.team_school.account_owner_id,
            self.cceo_profile.id,
            "ownership moved off the CCEO — this is the root of the scoping "
            "chain, so the school's planning, targets and budget moved with it",
        )
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                school_id=self.team_school.id, staff=self.cceo_profile
            ).exists(),
            "the CCEO's own assignment row was deleted by their supervisor",
        )

    def test_the_edit_drawer_still_accepts_the_owners_write(self):
        """A fix that refused everyone would pass the test above."""
        self.client.force_login(self.pl)
        response = self.client.post(
            f"/schools/{self.own_school.id}/edit-drawer",
            {
                "school_id": "PL-OWN",
                "name": "Renamed By Its Owner",
                "school_type": "client",
                "district_id": str(self.district.id),
                "account_owner_id": self.pl_profile.id,
            },
        )
        self.assertNotEqual(
            response.status_code,
            403,
            "the PL was refused a write on a school in their own portfolio",
        )
        self.own_school.refresh_from_db()
        self.assertEqual(self.own_school.name, "Renamed By Its Owner")

    # ── what must NOT regress ────────────────────────────────────────────────

    def test_a_program_lead_still_sees_the_team_school(self):
        """Oversight is the point. Losing visibility would trade one defect
        for a worse one."""
        self.assertTrue(
            RolePermissionService.can_view_record(self.pl, self.team_school)
        )

    def test_a_program_lead_keeps_full_access_to_their_own_school(self):
        self.assertTrue(RolePermissionService.can_view_record(self.pl, self.own_school))
        self.assertTrue(
            RolePermissionService.can_update(self.pl, self.own_school),
            "a directly assigned school is the PL's to work",
        )

    def test_another_teams_school_is_neither_visible_nor_editable(self):
        self.assertFalse(RolePermissionService.can_update(self.pl, self.other_school))

    # ── the owning CCEO is unaffected ────────────────────────────────────────

    def test_the_owning_cceo_can_still_edit_their_own_school(self):
        """A fix that locked the owner out would be the real outage."""
        self.assertTrue(RolePermissionService.can_update(self.cceo, self.team_school))
