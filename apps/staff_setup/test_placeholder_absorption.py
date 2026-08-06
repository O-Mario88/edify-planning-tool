"""Resolving a placeholder must carry its work, not just its schools.

A school import that names an owner with no account invents a placeholder and
assigns the school to it. Work is then planned against those schools and
recorded against the placeholder. When an admin finally matches that name to
the real person, the schools moved and the work did not — so the real person
inherited their own schools with none of their own history, and the
activities were stranded permanently, because a candidate is only resolved
once.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSetupCandidate,
    StaffSetupCandidateStatus,
    User,
    UserStatus,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.action_models import TeamAction
from apps.schools.models import School
from apps.staff_setup import services


class AbsorbFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="s1",
            name="Alpha Primary",
            district=cls.district,
            region=cls.region,
            account_owner_name_raw="James Okello",
        )
        cls.admin = cls._user("admin@a.test", "Admin", EdifyRole.ADMIN, "active")

        # What the school import leaves behind.
        cls.placeholder = cls._user(
            "pending.james.okello@edify.org",
            "James Okello",
            EdifyRole.CCEO,
            UserStatus.PENDING_INVITED.value,
            is_active=False,
        )
        cls.placeholder_profile = StaffProfile.objects.create(
            user=cls.placeholder, title="CCEO"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.placeholder_profile, school_id=cls.school.id
        )
        cls.candidate = StaffSetupCandidate.objects.create(
            full_name="James Okello",
            normalized_name="james okello",
            status=StaffSetupCandidateStatus.PENDING_PROFILE,
            matched_user_id=cls.placeholder.id,
            email=cls.placeholder.email,
        )

        # The real person, already on the system.
        cls.real = cls._user("james@edify.org", "James Okello", EdifyRole.CCEO, "active")
        cls.real_profile = StaffProfile.objects.create(user=cls.real, title="CCEO")

    @classmethod
    def _user(cls, email, name, role, status, *, is_active=True):
        return User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            status=status,
            is_active=is_active,
        )

    def _activity(self, *, owner_id, monitored_by=None):
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today(),
            planned_month=date.today().month,
            status="completed",
            responsible_staff_id=owner_id,
            monitored_by_staff_id=monitored_by,
        )

    def _match(self):
        return services.match_existing(
            self.candidate.id, {"userId": self.real.id}, self.admin
        )


class WorkMovesWithTheNameTest(AbsorbFixture):
    def test_activities_held_in_the_user_id_space_move(self):
        activity = self._activity(owner_id=self.placeholder.id)

        self._match()

        activity.refresh_from_db()
        self.assertEqual(activity.responsible_staff_id, self.real.id)

    def test_activities_held_in_the_profile_id_space_also_move(self):
        """Both spaces are live; rewriting one would disown the other half."""
        activity = self._activity(owner_id=self.placeholder_profile.id)

        self._match()

        activity.refresh_from_db()
        self.assertEqual(activity.responsible_staff_id, self.real_profile.id)

    def test_the_monitoring_seat_moves_too(self):
        activity = self._activity(
            owner_id=self.real.id, monitored_by=self.placeholder.id
        )

        self._match()

        activity.refresh_from_db()
        self.assertEqual(activity.monitored_by_staff_id, self.real.id)

    def test_partner_handovers_move(self):
        partner = Partner.objects.create(name="Partner X", active_status=True)
        assignment = PartnerAssignment.objects.create(
            school=self.school,
            partner=partner,
            assigning_staff_id=self.placeholder.id,
            monitoring_staff_id=self.placeholder.id,
            expected_activity_type="school_visit",
            focus_intervention="financial_health",
            status="assigned",
        )

        self._match()

        assignment.refresh_from_db()
        self.assertEqual(assignment.monitoring_staff_id, self.real.id)
        self.assertEqual(assignment.assigning_staff_id, self.real.id)

    def test_an_open_action_follows_the_person_it_was_meant_for(self):
        action = TeamAction.objects.create(
            condition_key="no_ssa|s1",
            issue_type="no_ssa",
            severity="critical",
            school_id=self.school.id,
            fy=self.fy,
            sender_id=self.admin.id,
            recipient_id=self.placeholder.id,
            requested_action="Complete a School Self-Assessment",
            workflow_route="/planning",
            state="open",
            detected_at=timezone.now(),
        )

        self._match()

        action.refresh_from_db()
        self.assertEqual(action.recipient_id, self.real.id)


class ThePlaceholderIsRetiredTest(AbsorbFixture):
    def test_it_stops_being_an_account_anybody_could_own_work_as(self):
        self._match()

        self.placeholder.refresh_from_db()
        self.assertEqual(self.placeholder.status, UserStatus.DISABLED.value)
        self.assertFalse(self.placeholder.is_active)

    def test_its_stale_school_assignment_is_removed(self):
        """Otherwise the school has two owners, one of whom cannot sign in."""
        self._match()

        self.assertFalse(
            StaffSchoolAssignment.objects.filter(
                staff_id=self.placeholder_profile.id
            ).exists()
        )
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff_id=self.real_profile.id, school_id=self.school.id
            ).exists()
        )

    def test_the_school_now_points_at_the_real_person(self):
        self._match()

        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.real_profile.id)


class OnlyImportArtefactsAreAbsorbedTest(AbsorbFixture):
    def test_a_real_account_is_never_merged_away(self):
        """An account somebody has actually used is somebody's.

        `pending_invited` alone is the normal state of every genuine
        invitation awaiting its first sign-in, so absorbing on that would
        destroy real access rather than tidy an import artefact.
        """
        genuine = self._user(
            "new.hire@edify.org",
            "New Hire",
            EdifyRole.CCEO,
            UserStatus.PENDING_INVITED.value,
            is_active=False,
        )
        StaffProfile.objects.create(user=genuine, title="CCEO")
        self.candidate.matched_user_id = genuine.id
        self.candidate.save(update_fields=["matched_user_id"])
        activity = self._activity(owner_id=genuine.id)

        self._match()

        genuine.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(genuine.status, UserStatus.PENDING_INVITED.value)
        self.assertEqual(activity.responsible_staff_id, genuine.id)

    def test_matching_a_candidate_to_itself_changes_nothing(self):
        self.candidate.matched_user_id = self.real.id
        self.candidate.save(update_fields=["matched_user_id"])
        activity = self._activity(owner_id=self.real.id)

        self._match()

        self.real.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(self.real.status, "active")
        self.assertEqual(activity.responsible_staff_id, self.real.id)

    def test_the_candidate_is_marked_merged(self):
        result = self._match()

        self.assertEqual(result["status"], StaffSetupCandidateStatus.MERGED.value)
