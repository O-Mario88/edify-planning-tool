"""Supervision is not ownership.

§10: planning authority follows the school's direct owner. A Programme Lead
supervising a CCEO may see that CCEO's work and ask about it; they may not
schedule it. The create-time guard read `school_ids`, which unions the
supervised team's schools into the supervisor's own, so a PL could plan across
every school of every CCEO reporting to them.

The read side is deliberately untouched: the PL still sees the work on Team
Planning Oversight, because the response to a problem there is to ask the
person who owns it rather than to reach past them.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


class PlanningFollowsDirectOwnershipTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Own Region")
        self.district = District.objects.create(name="Own District", region=self.region)

        self.pl, self.pl_profile = self._staff(
            "pl@own.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        self.cceo, self.cceo_profile = self._staff("cceo@own.test", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_profile, supervisor=self.pl_profile
        )

        self.cceo_school = self._school("OWN-CCEO", self.cceo_profile)
        self.pl_school = self._school("OWN-PL", self.pl_profile)

    def _staff(self, email, role):
        user = User.objects.create(
            email=email,
            name=email.split("@")[0],
            roles=[role.value],
            active_role=role.value,
            is_active=True,
            status="active",
        )
        return user, StaffProfile.objects.create(user=user, title=role.value)

    def _school(self, ref, owner):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def _plan(self, actor, school):
        from apps.activities.services import _assert_target_in_scope

        _assert_target_in_scope(school=school, cluster_id=None, principal=actor)

    def test_a_cceo_may_plan_for_their_own_school(self):
        self._plan(self.cceo, self.cceo_school)  # does not raise

    def test_a_programme_lead_may_plan_for_their_own_school(self):
        self._plan(self.pl, self.pl_school)  # does not raise

    def test_a_programme_lead_may_not_plan_for_a_supervised_cceos_school(self):
        """The rule. Reporting to somebody does not hand them your schools."""
        with self.assertRaises(Forbidden):
            self._plan(self.pl, self.cceo_school)

    def test_a_cceo_may_not_plan_for_another_cceos_school(self):
        other, other_profile = self._staff("other@own.test", EdifyRole.CCEO)
        theirs = self._school("OWN-OTHER", other_profile)

        with self.assertRaises(Forbidden):
            self._plan(self.cceo, theirs)

    def test_the_supervised_school_is_still_visible_to_the_lead(self):
        """Read is untouched: the PL sees the work, and asks rather than acts.

        If this ever fails, the change went too far — oversight would have
        been removed along with the write."""
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(self.pl)

        self.assertIn(self.cceo_school.id, scope.school_ids)
        self.assertNotIn(self.cceo_school.id, scope.own_school_ids)

    def test_a_country_role_is_unaffected(self):
        cd, _ = self._staff("cd@own.test", EdifyRole.COUNTRY_DIRECTOR)

        self._plan(cd, self.cceo_school)  # does not raise


class ThePlanningFormOffersOnlyWhatItWillAcceptTest(TestCase):
    """A dropdown listing a school the save refuses is the same fault as a
    cluster picker offering another owner's cluster."""

    def setUp(self):
        self.region = Region.objects.create(name="Form Region")
        self.district = District.objects.create(
            name="Form District", region=self.region
        )
        self.pl, self.pl_profile = self._staff(
            "pl2@own.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        self.cceo, self.cceo_profile = self._staff("cceo2@own.test", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_profile, supervisor=self.pl_profile
        )
        self.cceo_school = self._school("FORM-CCEO", self.cceo_profile)
        self.pl_school = self._school("FORM-PL", self.pl_profile)

    _staff = PlanningFollowsDirectOwnershipTest._staff
    _school = PlanningFollowsDirectOwnershipTest._school

    def test_the_planning_scope_lists_only_the_leads_own_schools(self):
        from apps.core.scoping import resolve_user_scope, school_queryset

        scope = resolve_user_scope(self.pl)
        refs = set(
            school_queryset(scope, direct_only=True).values_list("school_id", flat=True)
        )

        self.assertEqual(refs, {"FORM-PL"})
