"""What an acting leader reaches, and what they never do.

An Acting Programme Lead reads the whole team of the Lead who appointed them,
that Lead included, and nothing of any other team or country. An Acting
Country Director reads the appointing Director's country and no other. Every
check here is made against the platform's own scope resolver and permission
gates, which is what every page and service asks.
"""

from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffSupervisorAssignment, User
from apps.acting import services
from apps.core import acting as acting_api
from apps.core.permissions import RolePermissionService, has_permission
from apps.core.rbac import Permission as P
from apps.core.scoping import (
    resolve_user_scope,
    school_queryset,
    scope_cache_fingerprint,
)
from apps.hr.team_roster import team_members
from apps.planning.monitor_roster import monitor_roster
from apps.planning.oversight_service import resolve_oversight_scope

from .fixtures import (
    NOVEMBER_1,
    OCTOBER_1,
    OCTOBER_31,
    SEPTEMBER_30,
    ActingFixture,
    fresh,
    on_day,
)


class ActingProgramLeadScopeTests(ActingFixture):
    def setUp(self):
        self.appointment = self.appoint_sarah()

    def test_the_capacity_is_the_month_and_nothing_else(self):
        self.assertEqual(self.acting(self.sarah, SEPTEMBER_30).active_role, "CCEO")
        self.assertEqual(self.acting(self.sarah, OCTOBER_1).active_role, "Program Lead")
        self.assertEqual(
            self.acting(self.sarah, OCTOBER_31).active_role, "Program Lead"
        )
        self.assertEqual(self.acting(self.sarah, NOVEMBER_1).active_role, "CCEO")
        # The account itself never moved.
        stored = User.objects.get(id=self.sarah.id)
        self.assertEqual((stored.roles, stored.active_role), (["CCEO"], "CCEO"))

    def test_the_context_says_who_whose_seat_and_why(self):
        sarah = self.acting(self.sarah)
        context = acting_api.acting_context(sarah)
        self.assertEqual(context.assignment_id, self.appointment.id)
        self.assertEqual(context.substantive_role, "CCEO")
        self.assertEqual(context.acting_role, "Program Lead")
        self.assertEqual(context.seat_staff_id, self.john_sp.id)
        self.assertEqual(context.appointed_by_name, "John Lead")
        self.assertEqual(acting_api.capacity_label(sarah), "CCEO · Acting PL")
        self.assertEqual(acting_api.substantive_role(sarah), "CCEO")
        self.assertEqual(context.period_label, "October 2026")

    def test_the_scope_is_the_whole_team_with_the_lead(self):
        scope = resolve_user_scope(self.acting(self.sarah))
        self.assertEqual(scope.active_role, "Program Lead")
        self.assertEqual(
            set(scope.supervised_staff_ids),
            {self.david_sp.id, self.michael_sp.id, self.john_sp.id},
        )
        # Her own work stays her own; nobody oversees themselves.
        self.assertNotIn(self.sarah_sp.id, scope.supervised_staff_ids)
        self.assertEqual(scope.own_school_ids, [self.schools["sarah"].id])
        self.assertEqual(
            set(scope.team_school_ids),
            {self.schools[k].id for k in ("david", "michael", "john")},
        )
        self.assertEqual(scope.acting_assignment_id, self.appointment.id)
        self.assertEqual(scope.acting_seat_staff_id, self.john_sp.id)

    def test_it_matches_the_leads_own_reach_and_goes_no_further(self):
        acting = resolve_user_scope(self.acting(self.sarah))
        john = resolve_user_scope(fresh(self.john))
        self.assertEqual(set(acting.school_ids), set(john.school_ids))
        for outside in ("peter", "agnes", "otieno", "achieng"):
            self.assertNotIn(self.schools[outside].id, acting.school_ids)
        rows = set(school_queryset(acting).values_list("id", flat=True))
        self.assertEqual(
            rows, {self.schools[k].id for k in ("john", "sarah", "david", "michael")}
        )

    def test_records_of_another_team_or_country_are_refused(self):
        sarah = self.acting(self.sarah)
        can = RolePermissionService.can_view_record
        for inside in ("john", "david", "michael", "sarah"):
            self.assertTrue(can(sarah, self.schools[inside]), inside)
        for outside in ("agnes", "peter", "otieno", "achieng"):
            self.assertFalse(can(sarah, self.schools[outside]), outside)

    def test_the_team_roster_is_the_leads_officers(self):
        sarah = self.acting(self.sarah)
        self.assertEqual(
            {m.id for m in team_members(sarah)}, {self.david_sp.id, self.michael_sp.id}
        )
        # In her own role she leads nobody.
        self.assertEqual(team_members(fresh(self.sarah)), [])

    def test_the_monitors_follow_the_leads_team_with_the_lead_first(self):
        sarah = self.acting(self.sarah)
        oversight = resolve_oversight_scope(sarah)
        self.assertEqual(oversight.kind, "pl")
        self.assertIn(self.john_sp.id, oversight.lead_ids)
        self.assertIn(self.john.id, oversight.lead_ids)
        teams = monitor_roster(sarah)
        self.assertEqual(len(teams), 1)
        people = teams[0].people
        self.assertEqual(people[0].name, "John Lead")
        self.assertEqual(people[0].visits_target, 280)
        officers = {p.name: p.visits_target for p in people[1:]}
        # Everyone at their own permanent target, the acting leader included.
        self.assertEqual(
            officers,
            {"Sarah Officer": 560, "David Officer": 560, "Michael Officer": 560},
        )

    def test_the_calendar_offers_the_teams_calendars_with_the_leads_first(self):
        from apps.activities.calendar_people import find, teams_for

        teams = teams_for(self.acting(self.sarah))
        self.assertEqual(
            [p.name for p in teams[0].people],
            ["John Lead", "David Officer", "Michael Officer"],
        )
        self.assertEqual(
            teams[0].people[0].ids, frozenset({self.john_sp.id, self.john.id})
        )
        # Another team's officer is on nobody's strip but their own Lead's.
        self.assertEqual(find(teams, self.agnes_sp.id), (None, None))
        self.assertIsNotNone(find(teams, self.john_sp.id)[1])
        # In her own role her calendar is the personal page it always was,
        # and John's strip is his officers, himself not among them.
        self.assertEqual(teams_for(fresh(self.sarah)), [])
        self.assertEqual(
            [p.name for p in teams_for(fresh(self.john))[0].people],
            ["David Officer", "Michael Officer", "Sarah Officer"],
        )

    def test_the_team_is_read_as_it_stands_today(self):
        """Someone who joins or leaves the team mid-month joins or leaves the
        acting leader's reach with them."""
        StaffSupervisorAssignment.objects.filter(supervisee=self.michael_sp).delete()
        StaffSupervisorAssignment.objects.create(
            supervisor=self.john_sp, supervisee=self.agnes_sp
        )
        scope = resolve_user_scope(self.acting(self.sarah))
        self.assertIn(self.agnes_sp.id, scope.supervised_staff_ids)
        self.assertNotIn(self.michael_sp.id, scope.supervised_staff_ids)
        self.assertNotIn(self.schools["michael"].id, scope.school_ids)

    def test_permissions_are_the_leads_less_what_is_withheld(self):
        sarah = self.acting(self.sarah)
        for held in (P.EXPORT, P.STAFF_PERFORMANCE_VIEW, P.PARTNER_WITHDRAWAL_REVIEW):
            self.assertTrue(has_permission(sarah, held.value), held)
        for withheld in (P.MILESTONES_ALLOCATE, P.SCHOOL_EDIT, P.PARTNER_HOLD):
            self.assertFalse(has_permission(sarah, withheld.value), withheld)
            self.assertTrue(has_permission(fresh(self.john), withheld.value), withheld)
        # As herself she has neither.
        self.assertFalse(has_permission(fresh(self.sarah), P.EXPORT.value))

    def test_the_substantive_lead_is_untouched(self):
        before = resolve_user_scope(fresh(self.john))
        john = self.acting(self.john)
        self.assertIsNone(acting_api.acting_context(john))
        self.assertEqual(john.active_role, "Program Lead")
        after = resolve_user_scope(john)
        self.assertEqual(
            scope_cache_fingerprint(before), scope_cache_fingerprint(after)
        )
        self.assertEqual(
            set(after.supervised_staff_ids),
            {self.sarah_sp.id, self.david_sp.id, self.michael_sp.id},
        )
        self.assertEqual(
            {m.id for m in team_members(john)},
            {self.sarah_sp.id, self.david_sp.id, self.michael_sp.id},
        )

    def test_a_snapshot_cached_for_the_acting_leader_is_never_the_leads(self):
        self.assertNotEqual(
            scope_cache_fingerprint(resolve_user_scope(self.acting(self.sarah))),
            scope_cache_fingerprint(resolve_user_scope(fresh(self.john))),
        )


class ActingCountryDirectorScopeTests(ActingFixture):
    def setUp(self):
        self.appointment = self.appoint_peter()

    def test_the_capacity_is_the_month_and_nothing_else(self):
        self.assertEqual(
            self.acting(self.peter, SEPTEMBER_30).active_role, "Program Lead"
        )
        self.assertEqual(
            self.acting(self.peter, OCTOBER_1).active_role, "CountryDirector"
        )
        self.assertEqual(
            self.acting(self.peter, NOVEMBER_1).active_role, "Program Lead"
        )
        stored = User.objects.get(id=self.peter.id)
        self.assertEqual(
            (stored.roles, stored.active_role), (["Program Lead"], "Program Lead")
        )

    def test_the_scope_is_the_appointing_directors_country(self):
        scope = resolve_user_scope(self.acting(self.peter))
        self.assertTrue(scope.country_scope)
        self.assertEqual(scope.country, "Uganda")
        rows = set(school_queryset(scope).values_list("id", flat=True))
        uganda = {
            self.schools[k].id
            for k in ("john", "sarah", "david", "michael", "peter", "agnes")
        }
        self.assertLessEqual(uganda, rows)
        for kenya in ("otieno", "achieng"):
            self.assertNotIn(self.schools[kenya].id, rows)

    def test_the_country_is_the_seats_even_if_the_appointee_moves(self):
        self.peter_sp.country = "Kenya"
        self.peter_sp.save(update_fields=["country"])
        scope = resolve_user_scope(self.acting(self.peter))
        self.assertEqual(scope.country, "Uganda")

    def test_the_people_overseen_are_the_countrys(self):
        scope = resolve_user_scope(self.acting(self.peter))
        managed = set(scope.managed_staff_ids)
        self.assertLessEqual(
            {self.john_sp.id, self.sarah_sp.id, self.agnes_sp.id}, managed
        )
        self.assertFalse(managed & {self.otieno_sp.id, self.achieng_sp.id})
        self.assertNotIn(self.peter_sp.id, managed)

    def test_administration_money_and_governance_are_not_held(self):
        peter = self.acting(self.peter)
        mary = fresh(self.mary)
        for withheld in (
            P.USER_MANAGE,
            P.STAFF_MANAGE,
            P.COST_SETTINGS_MANAGE,
            P.COUNTRY_BUDGET_SUBMIT,
            P.FUND_REQUEST_APPROVE_ESCALATED,
            P.PLANNING_POLICY_MANAGE,
            P.STRATEGIC_PRIORITIES_APPROVE,
            P.MILESTONES_DEFINE,
            P.PARTNER_USER_MANAGE,
            P.DOCUMENTS_PUBLISH,
            P.PARTNER_HOLD,
            P.PARTNER_ASSIGNMENT_WITHDRAW,
            P.SCHOOL_EDIT,
            P.SCHOOL_CLOSE,
        ):
            self.assertTrue(has_permission(mary, withheld.value), withheld)
            self.assertFalse(has_permission(peter, withheld.value), withheld)
        for held in (P.ANALYTICS_VIEW, P.PLANNING_VIEW, P.PARTNER_MONITORING_COUNTRY):
            self.assertTrue(has_permission(peter, held.value), held)
        self.assertFalse(RolePermissionService.can_manage_cost_catalogue(peter))
        self.assertTrue(RolePermissionService.can_manage_cost_catalogue(mary))

    def test_withheld_pages_are_refused_and_delegated_ones_open(self):
        peter = self.acting(self.peter)
        can = RolePermissionService.can_view_page
        for page in (
            "users",
            "cost_settings",
            "country_budget",
            "fund_approvals",
            "leave_approvals",
            "performance_reviews",
            "staff_setup_queue",
        ):
            self.assertFalse(can(peter, page), page)
            self.assertTrue(can(fresh(self.mary), page), page)
        for page in (
            "country_planning_oversight",
            "cd_analytics",
            "calendar",
            "staff_activity",
            "partner_oversight",
            "project_monitoring",
            "priorities_master",
            "coverage",
        ):
            self.assertTrue(can(peter, page), page)

    def test_the_director_is_untouched_and_caches_are_apart(self):
        mary = self.acting(self.mary)
        self.assertIsNone(acting_api.acting_context(mary))
        self.assertNotEqual(
            scope_cache_fingerprint(resolve_user_scope(self.acting(self.peter))),
            scope_cache_fingerprint(resolve_user_scope(mary)),
        )

    def test_another_countrys_acting_director_reads_only_theirs(self):
        with on_day(SEPTEMBER_30):
            services.appoint(
                self.wanjiru, appointee_staff_id=self.otieno_sp.id, month="2026-10"
            )
        scope = resolve_user_scope(self.acting(self.otieno))
        self.assertEqual(scope.country, "Kenya")
        rows = set(school_queryset(scope).values_list("id", flat=True))
        self.assertIn(self.schools["achieng"].id, rows)
        self.assertNotIn(self.schools["sarah"].id, rows)


class StandingTests(ActingFixture):
    """An appointment stands only while the people it names still do."""

    def test_cancelled_upcoming_and_ended_appointments_grant_nothing(self):
        appointment = self.appoint_sarah()
        self.assertIsNone(
            acting_api.acting_context(self.acting(self.sarah, SEPTEMBER_30))
        )
        self.assertIsNone(
            acting_api.acting_context(self.acting(self.sarah, NOVEMBER_1))
        )
        with on_day(OCTOBER_1):
            services.cancel(self.john, appointment.id)
        self.assertIsNone(acting_api.acting_context(self.acting(self.sarah)))

    def test_it_lapses_when_the_appointee_or_the_lead_no_longer_stands(self):
        self.appoint_sarah()
        self.assertIsNotNone(acting_api.acting_context(self.acting(self.sarah)))
        # The Lead leaves: the delegation of their seat leaves with them.
        self.john.is_active = False
        self.john.save(update_fields=["is_active"])
        self.assertIsNone(acting_api.acting_context(self.acting(self.sarah)))
        self.john.is_active = True
        self.john.save(update_fields=["is_active"])
        # The appointee is no longer a CCEO.
        self.sarah.roles = ["ProjectCoordinator"]
        self.sarah.active_role = "ProjectCoordinator"
        self.sarah.save(update_fields=["roles", "active_role"])
        self.assertIsNone(acting_api.acting_context(self.acting(self.sarah)))

    def test_working_in_another_role_they_hold_is_not_acting(self):
        self.appoint_sarah()
        self.sarah.roles = ["CCEO", "ProjectCoordinator"]
        self.sarah.active_role = "ProjectCoordinator"
        self.sarah.save(update_fields=["roles", "active_role"])
        sarah = self.acting(self.sarah)
        self.assertIsNone(acting_api.acting_context(sarah))
        self.assertEqual(sarah.active_role, "ProjectCoordinator")

    def test_saving_the_account_while_acting_writes_the_permanent_role(self):
        self.appoint_sarah()
        sarah = self.acting(self.sarah)
        sarah.phone = "0700000000"
        sarah.save()
        self.assertEqual(sarah.active_role, "Program Lead")  # still presented
        stored = User.objects.get(id=self.sarah.id)
        self.assertEqual(stored.active_role, "CCEO")
        self.assertEqual(stored.roles, ["CCEO"])
        self.assertEqual(stored.phone, "0700000000")

    def test_a_person_never_appointed_costs_no_query(self):
        david = fresh(self.david)
        with on_day(OCTOBER_1), CaptureQueriesContext(connection) as queries:
            self.assertIsNone(services.attach(david))
        self.assertEqual(len(queries), 0)

    def test_an_appointee_costs_one_query_and_none_once_it_has_ended(self):
        self.appoint_sarah()
        sarah = fresh(self.sarah)
        with on_day(OCTOBER_1), CaptureQueriesContext(connection) as queries:
            self.assertIsNotNone(services.attach(sarah))
        self.assertEqual(len(queries), 1)
        sarah = fresh(self.sarah)
        with on_day(NOVEMBER_1), CaptureQueriesContext(connection) as queries:
            self.assertIsNone(services.attach(sarah))
        self.assertEqual(len(queries), 0)

    def test_the_lookup_is_answered_from_an_index_on_the_appointee(self):
        """The per-request lookup never reads the table through. Either
        index on the appointee serves it; which one the planner takes for a
        handful of rows is its own business."""
        self.appoint_sarah()
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(
                "EXPLAIN SELECT id FROM acting_assignment WHERE appointee_id = %s "
                "AND cancelled_at IS NULL AND start_date <= %s AND end_date >= %s",
                [self.sarah.id, OCTOBER_1, OCTOBER_1],
            )
            plan = " ".join(row[0] for row in cursor.fetchall())
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'acting_assignment'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
        self.assertNotIn("Seq Scan", plan)
        self.assertIn("appointee", plan)
        self.assertLessEqual(
            {
                "uniq_standing_acting_per_person_month",
                "uniq_standing_acting_per_seat_month",
                "acting_country_month_idx",
                "acting_end_date_idx",
            },
            indexes,
        )
