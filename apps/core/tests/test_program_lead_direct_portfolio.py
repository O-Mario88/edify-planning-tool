"""A Programme Lead plans only for what is theirs.

Supervision is not ownership; oversight is not planning authority; approval
authority is not school write access. The rule is one sentence and the ways it
leaks are many, so this file walks every door into a supervisee's portfolio —
page, selector, direct URL, API, HTMX, search, export and cache — and shuts
each one, then proves the read side is untouched: the supervisor still sees
the work, and can ask the person who owns it to act.

The fixture gives the Programme Lead a real portfolio of their own. A lead
with nothing directly assigned would pass most of these tests by having no
access to anything, which proves nothing at all — every assertion below has to
distinguish "mine" from "my team's", not "something" from "nothing".
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.clusters.models import Cluster
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.core.scoping import (
    OVERSIGHT_ONLY_MESSAGE,
    cluster_queryset,
    direct_portfolio_schools,
    may_plan_school,
    resolve_user_scope,
    scope_cache_fingerprint,
    school_queryset,
    team_oversight_schools,
)
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ProgramLeadDirectPortfolioBase(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="DP Region")
        self.mine_district = District.objects.create(
            name="DP Mine District", region=self.region
        )
        self.mine_sub = SubCounty.objects.create(
            name="DP Mine Sub", district=self.mine_district
        )
        self.team_district = District.objects.create(
            name="DP Team District", region=self.region
        )
        self.team_sub = SubCounty.objects.create(
            name="DP Team Sub", district=self.team_district
        )

        self.pl, self.pl_profile = self._staff(
            "dp-pl@edify.org", EdifyRole.COUNTRY_PROGRAM_LEAD, "Dana Lead"
        )
        self.cceo, self.cceo_profile = self._staff(
            "dp-cceo@edify.org", EdifyRole.CCEO, "James Field"
        )
        self.outsider, self.outsider_profile = self._staff(
            "dp-other-pl@edify.org", EdifyRole.COUNTRY_PROGRAM_LEAD, "Other Lead"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_profile, supervisor=self.pl_profile
        )

        self.my_cluster = self._cluster("DP Mine Cluster", self.mine_district)
        self.team_cluster = self._cluster("DP Team Cluster", self.team_district)

        self.my_school = self._school(
            "DP-MINE",
            self.pl_profile,
            self.mine_district,
            self.mine_sub,
            cluster=self.my_cluster,
        )
        self.my_core = self._school(
            "DP-MINE-CORE",
            self.pl_profile,
            self.mine_district,
            self.mine_sub,
            school_type="core",
            cluster=self.my_cluster,
        )
        self.team_school = self._school(
            "DP-THEIRS",
            self.cceo_profile,
            self.team_district,
            self.team_sub,
            cluster=self.team_cluster,
        )
        self.team_core = self._school(
            "DP-THEIRS-CORE",
            self.cceo_profile,
            self.team_district,
            self.team_sub,
            school_type="core",
            cluster=self.team_cluster,
        )

    def _staff(self, email, role, name):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
            status="active",
        )
        return user, StaffProfile.objects.create(user=user, title=role.value)

    def _cluster(self, name, district):
        return Cluster.objects.create(
            name=name,
            district=district,
            region=self.region,
            status="active",
            responsible_staff_id="",
        )

    def _school(
        self, ref, owner, district, sub_county, *, school_type="client", cluster=None
    ):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=district,
            sub_county=sub_county,
            school_type=school_type,
            cluster_status="clustered" if cluster else "unclustered",
            account_owner_id=owner.id,
            account_owner_name_raw=owner.user.name,
            account_owner_status="matched",
        )
        # School.save() nulls cluster_id on insert; re-apply it directly.
        if cluster is not None:
            School.objects.filter(pk=school.pk).update(cluster_id=cluster.id)
            school.refresh_from_db()
        StaffSchoolAssignment.objects.get_or_create(staff=owner, school_id=school.id)
        return school


class ScopeSplitTest(ProgramLeadDirectPortfolioBase):
    """The two scopes are separate, and stay separate."""

    def test_the_fixture_really_produces_a_supervised_portfolio(self):
        scope = resolve_user_scope(self.pl)
        self.assertIn(self.my_school.id, scope.own_school_ids)
        self.assertIn(self.team_school.id, scope.team_school_ids)
        self.assertNotIn(self.team_school.id, scope.own_school_ids)

    def test_direct_geography_excludes_the_teams(self):
        scope = resolve_user_scope(self.pl)
        self.assertIn(self.mine_district.id, scope.own_district_ids)
        self.assertNotIn(self.team_district.id, scope.own_district_ids)
        self.assertIn(self.my_cluster.id, scope.own_cluster_ids)
        self.assertNotIn(self.team_cluster.id, scope.own_cluster_ids)
        self.assertIn(self.my_core.id, scope.own_core_school_ids)
        self.assertNotIn(self.team_core.id, scope.own_core_school_ids)
        # The read scope still unions them, because oversight depends on it.
        self.assertIn(self.team_district.id, scope.district_ids)
        self.assertIn(self.team_core.id, scope.core_school_ids)

    def test_the_two_lenses_are_disjoint(self):
        scope = resolve_user_scope(self.pl)
        direct = set(direct_portfolio_schools(scope).values_list("id", flat=True))
        oversight = set(team_oversight_schools(scope).values_list("id", flat=True))
        self.assertEqual(direct, {self.my_school.id, self.my_core.id})
        self.assertEqual(oversight, {self.team_school.id, self.team_core.id})
        self.assertFalse(direct & oversight)

    def test_a_cceo_is_unaffected(self):
        scope = resolve_user_scope(self.cceo)
        self.assertEqual(
            set(direct_portfolio_schools(scope).values_list("id", flat=True)),
            set(school_queryset(scope).values_list("id", flat=True)),
        )

    def test_may_plan_school_answers_ownership_not_supervision(self):
        scope = resolve_user_scope(self.pl)
        self.assertTrue(may_plan_school(scope, self.my_school.id))
        self.assertFalse(may_plan_school(scope, self.team_school.id))


class ClusterPlanningScopeTest(ProgramLeadDirectPortfolioBase):
    def test_direct_cluster_set_excludes_the_teams(self):
        scope = resolve_user_scope(self.pl)
        writable = set(
            cluster_queryset(scope, direct_only=True).values_list("id", flat=True)
        )
        self.assertIn(self.my_cluster.id, writable)
        self.assertNotIn(self.team_cluster.id, writable)

    def test_read_cluster_set_still_shows_the_team(self):
        scope = resolve_user_scope(self.pl)
        readable = set(cluster_queryset(scope).values_list("id", flat=True))
        self.assertIn(self.team_cluster.id, readable)

    def test_an_unowned_cluster_in_a_supervisees_district_is_not_plannable(self):
        """The subtler half of the leak.

        Dropping the supervisees from `cluster_owner_ids` is not enough on its
        own: `district_ids` is derived from the own+team school union, so every
        not-yet-owned cluster across a supervisee's districts stayed reachable
        through the unassigned-cluster carve-out.
        """
        orphan = self._cluster("DP Orphan", self.team_district)
        scope = resolve_user_scope(self.pl)
        self.assertNotIn(
            orphan.id,
            set(cluster_queryset(scope, direct_only=True).values_list("id", flat=True)),
        )

    def test_planning_a_cluster_activity_for_the_team_is_refused(self):
        from apps.activities.services import _assert_target_in_scope

        _assert_target_in_scope(
            school=None, cluster_id=self.my_cluster.id, principal=self.pl
        )
        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            _assert_target_in_scope(
                school=None, cluster_id=self.team_cluster.id, principal=self.pl
            )

    def test_the_cceo_may_still_plan_their_own_cluster(self):
        from apps.activities.services import _assert_target_in_scope

        _assert_target_in_scope(
            school=None, cluster_id=self.team_cluster.id, principal=self.cceo
        )


class SchoolPlanningScopeTest(ProgramLeadDirectPortfolioBase):
    def test_planning_at_a_supervised_school_is_refused(self):
        from apps.activities.services import _assert_target_in_scope

        _assert_target_in_scope(
            school=self.my_school, cluster_id=None, principal=self.pl
        )
        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            _assert_target_in_scope(
                school=self.team_school, cluster_id=None, principal=self.pl
            )

    def test_a_school_belonging_to_nobody_in_the_chain_is_a_plain_refusal(self):
        """A different fact deserves a different sentence.

        "Ask the responsible CCEO" is only true when there *is* one under this
        supervisor. A school in another lead's team is simply out of scope.
        """
        from apps.activities.services import _assert_target_in_scope

        stranger = self._school(
            "DP-STRANGER", self.outsider_profile, self.mine_district, self.mine_sub
        )
        with self.assertRaisesMessage(Forbidden, "outside your scope"):
            _assert_target_in_scope(school=stranger, cluster_id=None, principal=self.pl)


class OperationalSurfacesTest(ProgramLeadDirectPortfolioBase):
    """The pages, selectors and endpoints, driven as the Programme Lead."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.pl)

    def test_school_directory_lists_only_the_direct_portfolio(self):
        body = self.client.get("/schools").content.decode()
        self.assertIn("School DP-MINE", body)
        self.assertNotIn("School DP-THEIRS", body)

    def test_core_schools_page_lists_only_the_direct_portfolio(self):
        response = self.client.get("/core-schools")
        self.assertEqual(response.status_code, 200)
        rows = {r["school_id"] for r in response.context["matrix_rows"]}
        self.assertEqual(rows, {"DP-MINE-CORE"})
        self.assertNotIn("DP-THEIRS-CORE", rows)

    def test_core_schools_oversight_lens_shows_the_team_read_only(self):
        response = self.client.get("/core-schools?lens=oversight")
        self.assertEqual(response.status_code, 200)
        rows = {r["school_id"] for r in response.context["oversight_rows"]}
        self.assertEqual(rows, {"DP-THEIRS-CORE"})
        body = response.content.decode()
        self.assertIn("Read-Only Team Oversight", body)
        # Not one operational control anywhere on the read-only lens.
        self.assertNotIn("/core-schools/schedule-", body)
        self.assertNotIn("/core-schools/assign-partner", body)
        self.assertIn("Send to James", body)

    def test_the_empty_operational_list_points_at_the_oversight_lens(self):
        StaffSchoolAssignment.objects.filter(staff=self.pl_profile).delete()
        body = self.client.get("/core-schools").content.decode()
        self.assertIn("No Core Schools in your portfolio", body)
        self.assertIn("lens=oversight", body)

    def test_core_drawers_refuse_a_supervised_school_by_direct_url(self):
        for path in (
            "/core-schools/schedule-visit",
            "/core-schools/schedule-training",
            "/core-schools/assign-partner",
            "/core-schools/assessment",
            "/core-schools/schedule-activity",
        ):
            with self.subTest(path=path):
                response = self.client.get(
                    f"{path}?school_id={self.team_school.school_id}",
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn(
                    "read-only supervisory oversight",
                    response.content.decode(),
                )

    def test_core_drawers_open_for_the_direct_portfolio(self):
        response = self.client.get(
            f"/core-schools/schedule-activity?school_id={self.my_core.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)

    def test_htmx_scheduling_post_is_refused(self):
        response = self.client.post(
            "/core-schools/schedule-visit/action",
            {
                "school_id": self.team_school.school_id,
                "visit_number": "1",
                "scheduled_date": "2026-08-20",
                "catalogue_item_id": "anything",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_planning_drawer_is_refused_for_school_and_cluster(self):
        for query in (
            f"school_id={self.team_school.school_id}",
            f"cluster_id={self.team_cluster.id}&action=training",
        ):
            with self.subTest(query=query):
                response = self.client.get(
                    f"/planning/schedule-modal?{query}", HTTP_HX_REQUEST="true"
                )
                self.assertEqual(response.status_code, 403)

    def test_partner_assignment_to_a_supervised_school_is_refused(self):
        response = self.client.get(
            f"/core-schools/assign-partner?school_id={self.team_school.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_bulk_actions_cannot_reach_a_supervised_school(self):
        self.client.post(
            "/schools/bulk-match-staff",
            {"school_ids": self.team_school.id, "staff_id": self.pl_profile.id},
        )
        self.team_school.refresh_from_db()
        self.assertEqual(self.team_school.account_owner_id, self.cceo_profile.id)

    def test_cluster_membership_write_is_refused(self):
        from apps.clusters.services import assign_school

        with self.assertRaises(Exception) as ctx:
            assign_school(
                self.team_school.school_id,
                {"clusterId": self.my_cluster.id},
                self.pl,
            )
        self.assertNotEqual(
            School.objects.get(pk=self.team_school.pk).cluster_id, self.my_cluster.id
        )
        self.assertTrue(ctx.exception)


class ExecutingSupervisedWorkTest(ProgramLeadDirectPortfolioBase):
    """Reaching an activity is not the same as being able to run it.

    Every mutation used to go through the read gate alone, and the read gate
    lets a supervisor through on any activity at a supervisee's school. So a
    Programme Lead could reschedule it, cancel it, record its attendance,
    complete it and stamp its Salesforce ID — the whole of §1B's "may not"
    list, reached by knowing an activity id.
    """

    def setUp(self):
        super().setUp()
        from apps.activities.models import Activity

        self.their_activity = Activity.objects.create(
            school=self.team_school,
            activity_type="school_visit",
            fy="2026",
            status="scheduled",
            responsible_staff_id=self.cceo_profile.id,
        )
        self.my_activity = Activity.objects.create(
            school=self.my_school,
            activity_type="school_visit",
            fy="2026",
            status="scheduled",
            responsible_staff_id=self.pl_profile.id,
        )

    def test_the_supervisor_may_still_read_the_activity(self):
        from apps.activities.services import get_activity

        self.assertEqual(
            get_activity(self.their_activity.id, self.pl)["id"], self.their_activity.id
        )

    def test_the_supervisor_cannot_execute_a_supervisees_activity(self):
        from apps.activities.services import _get_for_execution

        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            _get_for_execution(self.their_activity.id, self.pl)

    def test_the_supervisor_can_execute_their_own(self):
        from apps.activities.services import _get_for_execution

        self.assertEqual(
            _get_for_execution(self.my_activity.id, self.pl).id, self.my_activity.id
        )

    def test_the_owner_is_unaffected(self):
        from apps.activities.services import _get_for_execution

        self.assertEqual(
            _get_for_execution(self.their_activity.id, self.cceo).id,
            self.their_activity.id,
        )

    def test_reschedule_and_cancel_are_both_refused(self):
        from apps.activities.services import _cancel_or_defer, reschedule

        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            reschedule(
                self.their_activity.id,
                {"scheduledDate": "2026-09-01", "reason": "because"},
                self.pl,
            )
        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            _cancel_or_defer(
                self.their_activity.id, {"reason": "because"}, self.pl, "cancelled"
            )
        self.their_activity.refresh_from_db()
        self.assertEqual(self.their_activity.status, "scheduled")

    def test_entering_a_salesforce_id_follows_ownership_not_role(self):
        from apps.core.permissions import RolePermissionService

        self.assertFalse(
            RolePermissionService.can_enter_activity_sf_id(self.pl, self.their_activity)
        )
        self.assertTrue(
            RolePermissionService.can_enter_activity_sf_id(self.pl, self.my_activity)
        )
        self.assertTrue(
            RolePermissionService.can_enter_activity_sf_id(
                self.cceo, self.their_activity
            )
        )

    def test_uploading_evidence_follows_ownership(self):
        from apps.core.permissions import RolePermissionService

        self.assertFalse(
            RolePermissionService.can_upload_evidence(self.pl, self.their_activity)
        )
        self.assertTrue(
            RolePermissionService.can_upload_evidence(self.cceo, self.their_activity)
        )


class SearchAndExportTest(ProgramLeadDirectPortfolioBase):
    def test_search_returns_the_direct_portfolio_only(self):
        from apps.search.services import search

        results = search(self.pl, "School DP-")
        ids = {r["id"] for r in results["results"] if r["kind"] == "school"}
        self.assertIn(self.my_school.id, ids)
        self.assertNotIn(self.team_school.id, ids)

    def test_the_school_api_list_matches_the_directory(self):
        from apps.schools.services import list_schools

        ids = set(list_schools({}, self.pl).values_list("id", flat=True))
        self.assertEqual(ids, {self.my_school.id, self.my_core.id})

    def test_the_directory_export_carries_the_direct_portfolio_only(self):
        self.client.force_login(self.pl)
        response = self.client.get("/schools?export=csv")
        body = response.content.decode()
        self.assertIn("DP-MINE", body)
        self.assertNotIn("DP-THEIRS", body)


class ApiScopeTest(ProgramLeadDirectPortfolioBase):
    def test_cluster_api_returns_the_writable_set(self):
        from apps.clusters.services import cluster_planning, list_clusters

        listed = {c["id"] for c in list_clusters(self.pl)}
        self.assertIn(self.my_cluster.id, listed)
        self.assertNotIn(self.team_cluster.id, listed)

        planned = {c["id"] for c in cluster_planning(self.pl)}
        self.assertNotIn(self.team_cluster.id, planned)

    def test_the_activity_api_refuses_a_supervised_target(self):
        from apps.activities.services import _assert_target_in_scope

        with self.assertRaisesMessage(Forbidden, OVERSIGHT_ONLY_MESSAGE):
            _assert_target_in_scope(
                school=self.team_school, cluster_id=None, principal=self.pl
            )


class ApprovalAndOversightRemainTest(ProgramLeadDirectPortfolioBase):
    """What the Programme Lead must NOT lose."""

    def test_the_supervisor_can_still_read_a_supervised_record(self):
        from apps.core.permissions import RolePermissionService

        self.assertTrue(
            RolePermissionService.can_view_record(self.pl, self.team_school)
        )

    def test_team_planning_oversight_still_covers_the_team(self):
        self.client.force_login(self.pl)
        response = self.client.get("/team-planning-oversight/")
        self.assertEqual(response.status_code, 200)

    def test_the_supervisor_can_send_an_action_to_the_responsible_cceo(self):
        from apps.core_schools.models import CorePlan
        from apps.planning.action_models import ActionState, TeamAction

        CorePlan.objects.create(
            id=f"cplan-{self.team_core.school_id}",
            school_id=self.team_core.school_id,
            fy="2026",
            status="Active",
            assessment_completed=0,
        )
        self.client.force_login(self.pl)
        response = self.client.post(
            "/core-schools/oversight/send",
            {"school_id": self.team_core.school_id, "fy": "2026"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        action = TeamAction.objects.get(school_id=self.team_core.id)
        self.assertEqual(action.state, ActionState.OPEN)
        self.assertEqual(action.recipient_id, self.cceo.id)
        self.assertEqual(action.issue_type, "core_assessment_missing")
        self.assertIsNotNone(action.due_date)

    def test_sending_creates_no_activity_and_moves_no_work(self):
        from apps.activities.models import Activity
        from apps.core_schools.models import CorePlan

        CorePlan.objects.create(
            id=f"cplan-{self.team_core.school_id}",
            school_id=self.team_core.school_id,
            fy="2026",
            status="Active",
            assessment_completed=0,
        )
        self.client.force_login(self.pl)
        self.client.post(
            "/core-schools/oversight/send",
            {"school_id": self.team_core.school_id, "fy": "2026"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(Activity.objects.count(), 0)
        self.assertEqual(
            School.objects.get(pk=self.team_core.pk).account_owner_id,
            self.cceo_profile.id,
        )

    def test_a_supervisor_cannot_send_about_a_school_outside_their_team(self):
        stranger_core = self._school(
            "DP-STRANGER-CORE",
            self.outsider_profile,
            self.mine_district,
            self.mine_sub,
            school_type="core",
        )
        self.client.force_login(self.pl)
        response = self.client.post(
            "/core-schools/oversight/send",
            {"school_id": stranger_core.school_id, "fy": "2026"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)


class PortfolioChangePropagationTest(ProgramLeadDirectPortfolioBase):
    def test_reassigning_a_school_moves_it_between_the_two_lenses(self):
        StaffSchoolAssignment.objects.filter(
            staff=self.cceo_profile, school_id=self.team_school.id
        ).delete()
        StaffSchoolAssignment.objects.create(
            staff=self.pl_profile, school_id=self.team_school.id
        )
        scope = resolve_user_scope(self.pl)
        self.assertIn(self.team_school.id, scope.own_school_ids)
        self.assertNotIn(self.team_school.id, scope.team_school_ids)
        self.assertTrue(may_plan_school(scope, self.team_school.id))

    def test_removing_the_supervision_link_removes_the_oversight(self):
        StaffSupervisorAssignment.objects.filter(supervisor=self.pl_profile).delete()
        scope = resolve_user_scope(self.pl)
        self.assertEqual(scope.team_school_ids, [])
        self.assertEqual(
            set(team_oversight_schools(scope).values_list("id", flat=True)), set()
        )

    def test_the_cache_fingerprint_changes_when_the_portfolio_changes(self):
        """A cached portfolio snapshot must not survive a reassignment.

        Keys built from user id and role alone did survive it, which is how a
        Programme Lead kept being served a supervisee's numbers — or their own
        old ones — for the life of the TTL.
        """
        before = scope_cache_fingerprint(resolve_user_scope(self.pl))

        StaffSchoolAssignment.objects.create(
            staff=self.pl_profile, school_id=self.team_school.id
        )
        after_assignment = scope_cache_fingerprint(resolve_user_scope(self.pl))
        self.assertNotEqual(before, after_assignment)

        StaffSupervisorAssignment.objects.filter(supervisor=self.pl_profile).delete()
        after_supervision = scope_cache_fingerprint(resolve_user_scope(self.pl))
        self.assertNotEqual(after_assignment, after_supervision)

    def test_the_fingerprint_separates_direct_from_oversight(self):
        """Moving a school from the team into the lead's own portfolio changes
        the fingerprint even though the union is identical."""
        before = scope_cache_fingerprint(resolve_user_scope(self.pl))
        StaffSchoolAssignment.objects.filter(
            staff=self.cceo_profile, school_id=self.team_school.id
        ).delete()
        StaffSchoolAssignment.objects.create(
            staff=self.pl_profile, school_id=self.team_school.id
        )
        scope = resolve_user_scope(self.pl)
        self.assertNotEqual(before, scope_cache_fingerprint(scope))


class HealthCheckTest(ProgramLeadDirectPortfolioBase):
    def test_the_portfolio_boundary_checks_are_clean_on_a_correct_system(self):
        from apps.system_health.portfolio_access_health import report

        result = report()
        self.assertTrue(result["clean"], result["checks"])

    def test_the_directory_check_goes_red_when_the_boundary_is_re_widened(self):
        """The probe has to be able to fail, or it is decoration."""
        from apps.system_health import portfolio_access_health as health
        import apps.core.scoping as scoping

        original = scoping.direct_portfolio_schools
        scoping.direct_portfolio_schools = lambda scope, base=None: school_queryset(
            scope
        )
        try:
            finding = health._directory_contains_supervised_schools()
        finally:
            scoping.direct_portfolio_schools = original

        self.assertFalse(finding["clean"])
        self.assertGreater(finding["count"], 0)


class HistoricalAuditCommandTest(ProgramLeadDirectPortfolioBase):
    def test_the_audit_classifies_a_draft_created_outside_the_portfolio(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.activities.models import Activity

        Activity.objects.create(
            school=self.team_school,
            activity_type="school_visit",
            fy="2026",
            status="planned",
            responsible_staff_id=self.pl_profile.id,
        )
        out = StringIO()
        call_command("audit_portfolio_access", stdout=out)
        report = out.getvalue()
        self.assertIn("unauthorized_draft     1", report)
        self.assertIn("Re-run with --repair", report)

    def test_repair_reassigns_the_draft_to_the_responsible_cceo(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.activities.models import Activity

        activity = Activity.objects.create(
            school=self.team_school,
            activity_type="school_visit",
            fy="2026",
            status="planned",
            responsible_staff_id=self.pl_profile.id,
        )
        call_command("audit_portfolio_access", "--repair", stdout=StringIO())
        activity.refresh_from_db()
        self.assertEqual(activity.responsible_staff_id, self.cceo_profile.id)

    def test_live_and_completed_work_is_never_touched(self):
        from io import StringIO

        from django.core.management import call_command

        from apps.activities.models import Activity

        live = Activity.objects.create(
            school=self.team_school,
            activity_type="school_visit",
            fy="2026",
            status="scheduled",
            responsible_staff_id=self.pl_profile.id,
        )
        done = Activity.objects.create(
            school=self.team_school,
            activity_type="school_visit",
            fy="2026",
            status="ia_verified",
            responsible_staff_id=self.pl_profile.id,
        )
        call_command("audit_portfolio_access", "--repair", stdout=StringIO())
        live.refresh_from_db()
        done.refresh_from_db()
        self.assertEqual(live.responsible_staff_id, self.pl_profile.id)
        self.assertEqual(done.responsible_staff_id, self.pl_profile.id)
