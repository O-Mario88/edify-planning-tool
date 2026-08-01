"""A pending invite is still a member of staff.

`is_active` answers "may this account sign in?". Every list in this file asks a
different question — who owns these schools, whose targets are these, who may
be assigned this work — and the two answers diverge sharply for real data.

A school upload auto-creates the owners named in its "Staff Name" column as
`is_active=False`, `pending_invited`: the person exists and already holds every
school the upload attributed to them, but has not accepted their invite yet.
Filtering those lists on `is_active` therefore hid real staff behind real
portfolios. One CCEO holding 512 schools was absent from the CCEO lists
entirely, so no Program Lead could be given her as a supervisee — and because a
PL's planning scope is built from their supervisees' schools, none of those 512
schools could be planned by anyone but her, on an account that could not yet
log in.

Suspended and disabled staff are deliberate removals and stay excluded; so do
soft-deleted profiles. These tests pin that boundary in both directions.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.accounts.staff_matching import match, on_staff
from apps.core.scoping import resolve_user_scope
from apps.geography.models import District, Region
from apps.schools.models import School


def _staff(key, name, role, status, is_active):
    user = User.objects.create(
        id=f"pi-{key}"[:30],
        email=f"pi-{key}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        status=status,
        is_active=is_active,
    )
    return StaffProfile.objects.create(user=user, country="Uganda")


class PendingInviteStaffVisibilityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Invite Region")
        cls.district = District.objects.create(name="Invite District", region=region)

        # The shape a school upload produces: real portfolio, unaccepted invite.
        cls.pending = _staff(
            "pending", "Nancy Akello", "CCEO", "pending_invited", False
        )
        cls.active = _staff("active", "Active Cceo", "CCEO", "active", True)
        cls.suspended = _staff("susp", "Suspended Cceo", "CCEO", "suspended", False)
        cls.disabled = _staff("disabled", "Disabled Cceo", "CCEO", "disabled", False)

        cls.school = School.objects.create(
            school_id="INVITE-1",
            name="Pending Owner School",
            region=region,
            district=cls.district,
            account_owner_id=cls.pending.id,
        )
        StaffSchoolAssignment.objects.create(
            staff_id=cls.pending.id, school_id=cls.school.id
        )

    def test_a_pending_invite_counts_as_on_staff(self):
        names = set(on_staff(StaffProfile.objects).values_list("user__name", flat=True))
        self.assertIn("Nancy Akello", names)
        self.assertIn("Active Cceo", names)

    def test_deliberate_removals_stay_excluded(self):
        """The point is not "show everyone" — suspended and disabled are
        decisions somebody made and must keep their effect."""
        names = set(on_staff(StaffProfile.objects).values_list("user__name", flat=True))
        self.assertNotIn("Suspended Cceo", names)
        self.assertNotIn("Disabled Cceo", names)

    def test_a_soft_deleted_profile_is_gone(self):
        from django.utils import timezone

        StaffProfile.objects.filter(id=self.active.id).update(deleted_at=timezone.now())
        names = set(on_staff(StaffProfile.objects).values_list("user__name", flat=True))
        self.assertNotIn("Active Cceo", names)

    def test_the_school_owner_picker_offers_a_pending_invite(self):
        from apps.frontend.views.school_views import _school_owner_queryset

        names = set(_school_owner_queryset().values_list("user__name", flat=True))
        self.assertIn(
            "Nancy Akello",
            names,
            "a CCEO who already owns schools must be selectable as their owner",
        )

    def test_re_upload_matches_the_pending_profile_instead_of_duplicating_it(self):
        """The matcher created these rows; excluding them made a second upload
        fail to recognise its own work and split one portfolio in two."""
        staff_id, status = match("Nancy Akello")
        self.assertEqual(status, "matched")
        self.assertEqual(staff_id, self.pending.id)

    def test_a_program_lead_gets_the_schools_of_a_pending_invite_supervisee(self):
        """The end of the chain, and the reason this mattered: a PL's planning
        scope is built from their supervisees' schools."""
        lead = _staff("lead", "Invite Lead", "Program Lead", "active", True)
        StaffSupervisorAssignment.objects.create(
            supervisor_id=lead.id, supervisee_id=self.pending.id
        )

        scope = resolve_user_scope(lead.user)

        self.assertIn(
            str(self.pending.id), [str(i) for i in scope.supervised_staff_ids]
        )
        self.assertIn(
            self.school.id,
            scope.school_ids,
            "the supervisee's school must enter the lead's planning scope",
        )
