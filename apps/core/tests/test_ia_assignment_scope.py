"""An Impact Assessment assistant is narrowed; an account owner is not.

The distinction is real — an IA assistant does field work inside one officer's
remit and their portfolio is the access boundary — but it used to be read off
``StaffSchoolAssignment``. That table is account ownership, and the school
upload writes a row into it for every uploaded school whose account-owner cell
matches a staff profile by name, so the country officer who ran the upload was
demoted by their own file. An IA officer's supervisor link over another — the
assurance oversight `StaffSupervisorAssignment` documents, not the reporting
line, which runs to the Country Director for every IA officer — is what an
administrator sets deliberately, and it is what this reads now.
"""

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.geography.models import District, Region
from apps.schools.models import School


class ImpactAssessmentAssignmentScopeTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="East")
        district = District.objects.create(name="Mbale", region=region)
        self.assigned = School.objects.create(
            school_id="IA-1", name="Assigned", region=region, district=district
        )
        self.other = School.objects.create(
            school_id="IA-2", name="Other", region=region, district=district
        )

    def _ia(self, email):
        user = User.objects.create_user(
            email=email,
            name=email,
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="strong-test-pass",
            status="active",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user)

    def test_an_assistant_under_an_ia_officer_is_assignment_scoped(self):
        officer_user, officer = self._ia("officer-with-team@edify.test")
        user, staff = self._ia("assistant@edify.test")
        StaffSupervisorAssignment.objects.create(supervisor=officer, supervisee=staff)
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.assigned.id)

        scope = resolve_user_scope(user)

        self.assertFalse(scope.country_scope)
        self.assertEqual(scope.own_school_ids, [self.assigned.id])
        self.assertEqual(list(school_queryset(scope)), [self.assigned])
        # The officer overseeing them keeps the country, portfolio or not.
        self.assertTrue(resolve_user_scope(officer_user).country_scope)

    def test_ia_without_direct_portfolio_retains_country_oversight(self):
        user, _ = self._ia("officer@edify.test")

        scope = resolve_user_scope(user)

        self.assertTrue(scope.country_scope)
        self.assertEqual(set(school_queryset(scope)), {self.assigned, self.other})

    def test_owning_a_school_does_not_narrow_the_officer_who_uploaded_it(self):
        """The row `apps/schools/upload_service.py` writes for a matched owner.

        One such row out of sixteen thousand used to collapse the officer's lens
        to that row — no directory, no SSA, no country oversight, and nothing
        said about why.
        """
        user, staff = self._ia("uploader@edify.test")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.assigned.id)

        scope = resolve_user_scope(user)

        self.assertTrue(scope.country_scope)
        self.assertEqual(set(school_queryset(scope)), {self.assigned, self.other})

    def test_a_country_director_link_is_not_ia_oversight(self):
        cd = User.objects.create_user(
            email="cd@edify.test",
            name="Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="strong-test-pass",
            status="active",
            is_active=True,
        )
        cd_staff = StaffProfile.objects.create(user=cd)
        user, staff = self._ia("reports-to-cd@edify.test")
        StaffSupervisorAssignment.objects.create(supervisor=cd_staff, supervisee=staff)
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.assigned.id)

        self.assertTrue(resolve_user_scope(user).country_scope)
