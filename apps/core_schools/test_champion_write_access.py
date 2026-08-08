"""§11: graduating a school is a write on that school's record.

Both champion actions took a school reference straight from the URL and acted
on it. The review drawer beside them scoped its lookup with
`get_scoped_object_or_404`, so the UI only ever *offered* the buttons for
schools you could see — but the POST behind them checked nothing at all, and
four roles hold the `core_schools` page permission. Any of them could graduate,
or reject, any of the ~17,000 schools in the country by posting a school_id.

These tests are written against the service, not the view, because that is
where the rule now lives: a fix that only removed the button would leave the
endpoint exactly as open as it was.
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
from apps.core_schools.champion_services import ChampionEligibilityService
from apps.core_schools.models import CorePlan, CoreSchoolProfile
from apps.geography.models import District, Region
from apps.schools.models import School


class ChampionGraduationFollowsOwnershipTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Champ Access Region")
        self.district = District.objects.create(
            name="Champ Access District", region=self.region
        )

        self.owner, self.owner_profile = self._staff("owner@champ.test", EdifyRole.CCEO)
        self.peer, self.peer_profile = self._staff("peer@champ.test", EdifyRole.CCEO)
        self.lead, self.lead_profile = self._staff(
            "lead@champ.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.owner_profile, supervisor=self.lead_profile
        )
        self.ia, _ = self._staff("ia@champ.test", EdifyRole.IMPACT_ASSESSMENT)
        self.accountant, _ = self._staff(
            "acct@champ.test", EdifyRole.PROGRAM_ACCOUNTANT
        )
        self.cd, _ = self._staff("cd@champ.test", EdifyRole.COUNTRY_DIRECTOR)

        self.school = School.objects.create(
            school_id="SCH-CHAMP-ACCESS",
            name="Champ Access Academy",
            region=self.region,
            district=self.district,
            school_type="potential_champion",
            account_owner_id=self.owner_profile.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.owner_profile, school_id=self.school.id
        )
        self.plan = CorePlan.objects.create(
            id=f"cplan-{self.school.school_id}",
            school_id=self.school.school_id,
            fy="2026",
            status="Active",
        )
        self.profile = CoreSchoolProfile.objects.create(
            school_id=self.school.school_id,
            core_plan=self.plan,
            champion_status="Potential Champion",
        )

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

    def _status(self):
        self.profile.refresh_from_db()
        self.school.refresh_from_db()
        return self.profile.champion_status, self.school.school_type

    def test_the_owner_may_graduate_their_own_school(self):
        self.assertTrue(
            ChampionEligibilityService.approve(self.school.school_id, self.owner)
        )
        self.assertEqual(self._status(), ("Champion", "champion"))

    def test_a_country_role_may_graduate_any_school(self):
        self.assertTrue(
            ChampionEligibilityService.approve(self.school.school_id, self.cd)
        )
        self.assertEqual(self._status(), ("Champion", "champion"))

    def test_another_cceo_may_not_graduate_it(self):
        """The hole: the school reference came from the URL and was trusted."""
        with self.assertRaises(Forbidden):
            ChampionEligibilityService.approve(self.school.school_id, self.peer)
        self.assertEqual(self._status(), ("Potential Champion", "potential_champion"))

    def test_the_supervising_lead_may_not_graduate_it(self):
        """Supervision is not ownership — the PL reviews and asks."""
        with self.assertRaises(Forbidden):
            ChampionEligibilityService.approve(self.school.school_id, self.lead)
        self.assertEqual(self._status(), ("Potential Champion", "potential_champion"))

    def test_a_country_wide_verifier_may_not_graduate_it(self):
        """Seeing the whole country is not running it.

        Impact Assessment and the Programme Accountant are in COUNTRY_ROLES so
        they can verify completed work and pay accountabilities across every
        district. A guard written against `country_scope` would read that
        visibility as authority and hand both of them the Country Director's
        programme decisions — which is why the rule reads COUNTRY_WRITE_ROLES.
        """
        for verifier in (self.ia, self.accountant):
            with self.subTest(role=verifier.active_role):
                with self.assertRaises(Forbidden):
                    ChampionEligibilityService.approve(self.school.school_id, verifier)
                self.assertEqual(
                    self._status(), ("Potential Champion", "potential_champion")
                )

    def test_rejection_is_guarded_too(self):
        """Rejecting somebody's candidate costs them the graduation; it is as
        much a write into their portfolio as approving it."""
        with self.assertRaises(Forbidden):
            ChampionEligibilityService.reject(self.school.school_id, self.peer)
        self.assertEqual(self._status()[0], "Potential Champion")

        self.assertTrue(
            ChampionEligibilityService.reject(self.school.school_id, self.owner)
        )
        self.assertEqual(self._status()[0], "Not Eligible")

    def test_a_missing_school_is_still_not_found_rather_than_forbidden(self):
        """Order matters: the guard must not turn an unknown id into a 403 that
        tells the caller which school references exist."""
        self.assertFalse(ChampionEligibilityService.approve("SCH-NOPE", self.peer))
