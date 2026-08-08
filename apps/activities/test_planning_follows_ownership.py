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

    def _plan(self, actor, school, owner=None):
        from apps.activities.services import _assert_target_in_scope

        _assert_target_in_scope(
            school=school,
            cluster_id=None,
            principal=actor,
            owner_id=owner.id if owner else None,
        )

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


class AssigningWorkToTheOwnerIsNotReachingPastThemTest(
    PlanningFollowsDirectOwnershipTest
):
    """The one case where actor and owner legitimately differ.

    A supervisor accepting a Field Debrief recommendation creates an activity
    the *submitter* owns, at the submitter's own school. The write lands inside
    the submitter's portfolio at their own request, so it is their ownership
    that decides the target — not the supervisor's, which would refuse it, and
    not supervision-as-ownership, which would permit far too much.
    """

    def test_a_lead_may_assign_work_to_the_cceo_who_owns_the_school(self):
        self._plan(self.pl, self.cceo_school, owner=self.cceo_profile)

    def test_a_lead_still_may_not_take_the_work_themselves(self):
        """Naming nobody means naming yourself, and the PL owns no such school."""
        with self.assertRaises(Forbidden):
            self._plan(self.pl, self.cceo_school)

    def test_a_lead_may_not_assign_a_school_the_named_owner_does_not_own(self):
        """The supervisee is not a pass-through to schools nobody owns."""
        unowned = School.objects.create(
            school_id="OWN-NONE",
            name="School OWN-NONE",
            region=self.region,
            district=self.district,
            school_type="client",
        )

        with self.assertRaises(Forbidden):
            self._plan(self.pl, unowned, owner=self.cceo_profile)

    def test_a_peer_may_not_plant_work_by_naming_the_owner(self):
        """Without the supervision test, naming the owner would be a bypass:
        anyone could write into anyone else's portfolio uninvited."""
        peer, peer_profile = self._staff("peer@own.test", EdifyRole.CCEO)

        with self.assertRaises(Forbidden):
            self._plan(peer, self.cceo_school, owner=self.cceo_profile)

    def test_naming_an_unrelated_owner_does_not_widen_the_lead(self):
        """A CCEO who does not report to this PL is not theirs to assign."""
        stranger, stranger_profile = self._staff("stranger@own.test", EdifyRole.CCEO)
        theirs = self._school("OWN-STRANGER", stranger_profile)

        with self.assertRaises(Forbidden):
            self._plan(self.pl, theirs, owner=stranger_profile)


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


class ASummaryOnlyRoleHasNoPortfolioToWriteIntoTest(PlanningFollowsDirectOwnershipTest):
    """§12: the RVP reads the country in aggregate and owns none of it.

    The school branch already refused them — an RVP has no `own_school_ids`.
    The cluster branch did not: `cluster_in_scope` answers True for every
    cluster when a scope is summary-only, because that is the right answer for
    a *reader*, and the guard was spending a read rule as a write rule.
    """

    def _rvp(self):
        rvp, _ = self._staff("rvp@own.test", EdifyRole.REGIONAL_VICE_PRESIDENT)
        return rvp

    def test_an_rvp_may_not_plan_at_a_school(self):
        with self.assertRaises(Forbidden):
            self._plan(self._rvp(), self.cceo_school)

    def test_an_rvp_may_not_plan_at_a_cluster_either(self):
        from apps.activities.services import _assert_target_in_scope
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Summary Only Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )

        with self.assertRaises(Forbidden):
            _assert_target_in_scope(
                school=None, cluster_id=cluster.id, principal=self._rvp()
            )

    def test_the_cceo_can_still_plan_at_that_cluster(self):
        """The narrowing must land on the summary-only role and nobody else."""
        from apps.activities.services import _assert_target_in_scope
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Owned Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=self.cceo_profile.id,
        )

        _assert_target_in_scope(
            school=None, cluster_id=cluster.id, principal=self.cceo
        )  # does not raise


class WriteAccessDoesNotSurviveATransferTest(PlanningFollowsDirectOwnershipTest):
    """§23: nobody keeps write access to a school they no longer own.

    Today this holds for a structural reason rather than a deliberate one:
    `resolve_user_scope` memoizes into `apps.core.request_cache`, which exists
    only while a request is being handled, so the next request re-resolves from
    the assignment tree. There is no cross-request scope cache to invalidate,
    and therefore no invalidation hook that could be forgotten.

    That is worth pinning precisely *because* it is structural. Scope
    resolution walks the full assignment tree and is a natural candidate for
    somebody to move behind a TTL cache keyed on (user, role) — a change that
    looks like pure performance work and would silently hand a departing owner
    write access for the length of the timeout. These tests fail the moment
    that happens.
    """

    def _transfer(self, school, *, to):
        """The transfer as the system performs it today.

        §15's controlled Portfolio Transfer workflow is not built yet, so this
        moves the two records that ownership is actually read from. When that
        workflow lands it should replace the body of this helper and leave the
        assertions untouched.
        """
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.filter(school_id=school.id).delete()
        StaffSchoolAssignment.objects.create(staff=to, school_id=school.id)
        School.objects.filter(pk=school.pk).update(account_owner_id=to.id)

    def test_the_previous_owner_loses_write_access_immediately(self):
        from apps.core.scoping import resolve_user_scope

        # Resolve first, so a cache that outlived the transfer would be warm
        # and this test would be measuring the stale copy.
        self.assertIn(self.cceo_school.id, resolve_user_scope(self.cceo).own_school_ids)
        self._plan(self.cceo, self.cceo_school)  # does not raise, yet

        other, other_profile = self._staff("successor@own.test", EdifyRole.CCEO)
        self._transfer(self.cceo_school, to=other_profile)

        with self.assertRaises(Forbidden):
            self._plan(self.cceo, self.cceo_school)

    def test_the_new_owner_gains_it_in_the_same_breath(self):
        """Half a transfer is worse than none: the school would belong to
        nobody and no one could plan for it."""
        other, other_profile = self._staff("successor2@own.test", EdifyRole.CCEO)

        self._transfer(self.cceo_school, to=other_profile)

        self._plan(other, self.cceo_school)  # does not raise

    def test_scope_is_not_cached_beyond_the_request_that_resolved_it(self):
        """The structural reason the two tests above pass, stated directly."""
        from apps.core import request_cache

        self.assertIsNone(
            request_cache.store(),
            "a scope memo outside a request means scope can go stale between them",
        )


class SeeingTheCountryIsNotSchedulingInItTest(PlanningFollowsDirectOwnershipTest):
    """Impact Assessment schedules its own field work; the Accountant does not.

    Both roles are in COUNTRY_ROLES because both need country-wide visibility —
    IA verifies completed work, the Accountant confirms and pays
    accountabilities. Every scheduling guard tested that one flag, so it
    granted the union of two jobs: the Accountant could place and move field
    work anywhere in Uganda, which is not part of the role.

    IA must keep it. IA does school visits and assessment training, and a guard
    written against COUNTRY_WRITE_ROLES — the set that correctly withholds the
    Country Director's programme decisions from both — would have taken IA's
    own work away instead. Three different questions, three different sets.
    """

    def _country(self, role, email):
        user, _ = self._staff(email, role)
        return user

    def test_impact_assessment_may_schedule_anywhere(self):
        ia = self._country(EdifyRole.IMPACT_ASSESSMENT, "ia@sched.test")

        self._plan(ia, self.cceo_school)  # does not raise

    def test_the_accountant_may_not_schedule_at_all(self):
        accountant = self._country(EdifyRole.PROGRAM_ACCOUNTANT, "acct@sched.test")

        with self.assertRaises(Forbidden):
            self._plan(accountant, self.cceo_school)

    def test_the_accountant_may_not_schedule_at_their_own_cluster_either(self):
        """ "Anything" means anything: the cluster branch is a separate path
        into the same guard and would otherwise still be open."""
        from apps.activities.services import _assert_target_in_scope
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Accountant Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )
        accountant = self._country(EdifyRole.PROGRAM_ACCOUNTANT, "acct2@sched.test")

        with self.assertRaises(Forbidden):
            _assert_target_in_scope(
                school=None, cluster_id=cluster.id, principal=accountant
            )

    def test_the_accountant_may_not_move_an_existing_activity(self):
        """Rescheduling is scheduling. The read gate let them this far because
        reading every activity in the country is exactly their job."""
        from apps.activities.services import _assert_may_schedule
        from apps.activities.models import Activity

        activity = Activity.objects.create(
            activity_type="school_visit",
            school_id=self.cceo_school.id,
            responsible_staff_id=self.cceo_profile.id,
            fy="2026",
            status="planned",
        )
        accountant = self._country(EdifyRole.PROGRAM_ACCOUNTANT, "acct3@sched.test")

        with self.assertRaises(Forbidden):
            _assert_may_schedule(activity, accountant)

        _assert_may_schedule(activity, self.cceo)  # the owner still may
        _assert_may_schedule(
            activity, self._country(EdifyRole.IMPACT_ASSESSMENT, "ia2@sched.test")
        )

    def test_the_accountant_still_sees_everything(self):
        """The narrowing is on scheduling alone. If this fails, the change went
        too far and took the Accountant's actual job with it."""
        from apps.core.scoping import resolve_user_scope

        accountant = self._country(EdifyRole.PROGRAM_ACCOUNTANT, "acct4@sched.test")

        self.assertTrue(resolve_user_scope(accountant).country_scope)
