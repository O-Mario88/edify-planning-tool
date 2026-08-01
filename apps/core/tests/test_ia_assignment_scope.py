from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
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

    def test_ia_with_direct_portfolio_is_assignment_scoped(self):
        user, staff = self._ia("assistant@edify.test")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.assigned.id)

        scope = resolve_user_scope(user)

        self.assertFalse(scope.country_scope)
        self.assertEqual(scope.own_school_ids, [self.assigned.id])
        self.assertEqual(list(school_queryset(scope)), [self.assigned])

    def test_ia_without_direct_portfolio_retains_country_oversight(self):
        user, _ = self._ia("officer@edify.test")

        scope = resolve_user_scope(user)

        self.assertTrue(scope.country_scope)
        self.assertEqual(set(school_queryset(scope)), {self.assigned, self.other})
