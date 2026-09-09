"""The distributed priority contract: recipient UI, contributions and rollups."""

from datetime import date
from decimal import Decimal

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.services import apply_catalogue_snapshot
from apps.hr.accountability import allocation_priorities
from apps.hr import target_distribution as distribution
from apps.hr.milestone_progress import (
    record_activity_progress,
    reverse_activity_progress,
)
from apps.hr.models import MilestoneActivityRule
from apps.hr.test_target_distribution import DistributionFixture, FY


class AccountabilityContractTests(DistributionFixture):
    def distribute(self):
        milestone = self._milestone("CONTRACT", target="10")
        milestone.weight = 100
        milestone.save()
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="ACTIVITIES_COMPLETED",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        team = self._team_allocation(milestone, self.pl_sp, 10)
        distribution.approve_team_distribution(milestone, principal=self.ia)
        team.refresh_from_db()
        self._employee_allocation(milestone, self.pl_sp, 2, parent=team)
        self._employee_allocation(milestone, self.cceo_a_sp, 8, parent=team)
        distribution.approve_employee_distribution(team, principal=self.pl)
        return milestone, item

    def activity(self, item, staff, *, partner=False, status="ia_verified"):
        activity = Activity.objects.create(
            activity_type=item.workflow_kind,
            status=status,
            salesforce_activity_id="audit-" + str(Activity.objects.count()),
            planned_date=date(2026, 10, 5),
            fy=FY,
            responsible_staff_id=None if partner else staff.id,
            monitored_by_staff_id=staff.id if partner else None,
            delivery_type="partner" if partner else "staff",
            focus_intervention="christlike_behaviour",
        )
        apply_catalogue_snapshot(
            activity, item=item, requested_intervention="christlike_behaviour"
        )
        if status == "ia_verified":
            record_activity_progress(activity)
        return activity

    def test_approved_allocation_is_default_priority_without_an_agreement_copy(self):
        milestone, _ = self.distribute()
        self.client.force_login(self.cceo_a)
        response = self.client.get("/priorities", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'data-distributed-priority="' + milestone.id + '"'
        )
        self.assertContains(response, "Distributed Priorities")
        self.assertContains(response, "Core Values")
        self.assertContains(response, "Spiritual Formation")
        self.assertContains(response, "Professional Development")
        self.assertEqual(response.context["tab"], "distributed")
        self.assertEqual(
            response.context["distributed"]["rows"][0]["target"], Decimal(8)
        )
        self.assertNotContains(response, "Distribute to my team")
        other = self.client.get("/priorities", {"fy": "2026"})
        self.assertNotContains(
            other, 'data-distributed-priority="' + milestone.id + '"'
        )

    def test_scope_completion_verification_and_reversal(self):
        _, item = self.distribute()
        own = self.activity(item, self.pl_sp)
        direct = self.activity(item, self.cceo_a_sp)
        partner = self.activity(item, self.cceo_a_sp, partner=True)
        pending = self.activity(item, self.cceo_a_sp, status="completed")
        cceo = allocation_priorities(self.cceo_a, FY)["rows"][0]
        self.assertEqual(cceo["actual"], 2)
        self.assertEqual(cceo["progress"]["completed"], 3)
        self.assertEqual(allocation_priorities(self.pl, FY)["rows"][0]["actual"], 3)
        self.assertEqual(allocation_priorities(self.cd, FY)["rows"][0]["actual"], 3)
        reverse_activity_progress(partner, reason="returned")
        self.assertEqual(allocation_priorities(self.pl, FY)["rows"][0]["actual"], 2)
        self.assertEqual(allocation_priorities(self.cd, FY)["rows"][0]["actual"], 2)

    def test_analytics_reads_the_same_contract_and_withholds_unmatched_filter_target(
        self,
    ):
        from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService

        _, item = self.distribute()
        self.activity(item, self.pl_sp)
        self.activity(item, self.cceo_a_sp, partner=True)
        for user, expected in ((self.cceo_a, 12.5), (self.pl, 20), (self.cd, 20)):
            data = AnalyticsDashboardService.get_analytics_data(user, {"fy": FY})
            headline = next(
                x
                for x in data["kpi_strip_items"]
                if x["label"] == "Overall Target Achievement"
            )
            self.assertEqual(headline["raw_value"], expected)
        data = AnalyticsDashboardService.get_analytics_data(
            self.cd, {"fy": FY, "activity_type": item.workflow_kind}
        )
        self.assertEqual(
            data["kpis"]["target_achievement"]["value"], "Scope target unavailable"
        )

    def test_quarter_uses_approved_phasing_and_future_period_does_not_count_delivery(
        self,
    ):
        _, item = self.distribute()
        self.activity(item, self.cceo_a_sp)
        from apps.hr.models import MilestoneAllocation

        allocation = MilestoneAllocation.objects.get(
            employee=self.cceo_a_sp, status="approved"
        )
        expected = sum(
            p.planned_value
            for p in allocation.period_targets.filter(
                period_type="month", period_start__month__in=[10, 11, 12]
            )
        )
        q1 = allocation_priorities(self.cceo_a, FY, quarter="Q1")["rows"][0]
        self.assertEqual(q1["target"], expected)
        self.assertEqual(q1["actual"], 1)
        self.assertEqual(
            allocation_priorities(self.cceo_a, FY, quarter="Q2")["rows"][0]["actual"], 0
        )

    def test_missing_weight_withholds_the_overall_score(self):
        milestone, item = self.distribute()
        self.activity(item, self.cceo_a_sp)
        milestone.weight = 0
        milestone.save(update_fields=["weight"])
        result = allocation_priorities(self.cceo_a, FY)
        self.assertIsNone(result["pct"])
        self.assertEqual(result["rows"][0]["pct"], 12.5)

    def test_partner_event_is_counted_once_when_owner_and_monitor_share_a_team(self):
        _, item = self.distribute()
        activity = self.activity(item, self.cceo_a_sp, partner=True)
        activity.responsible_staff_id = self.pl_sp.id
        activity.save(update_fields=["responsible_staff_id"])
        self.assertEqual(allocation_priorities(self.pl, FY)["rows"][0]["actual"], 1)
        self.assertEqual(allocation_priorities(self.cd, FY)["rows"][0]["actual"], 1)
        from apps.hr.performance_scores import country_performance

        self.assertEqual(country_performance("Uganda", FY)["pct"], 10)

    def test_rvp_reads_same_country_delivery_as_cd(self):
        from apps.hr.test_target_distribution import _user

        rvp, _ = _user("RegionalVicePresident", "contract-rvp@edify.org", "RVP")
        _, item = self.distribute()
        self.activity(item, self.pl_sp)
        self.assertEqual(
            allocation_priorities(rvp, FY)["pct"],
            allocation_priorities(self.cd, FY)["pct"],
        )

    def test_analytics_revision_changes_only_after_commit(self):
        from apps.hr.accountability_cache import revision

        from django.db import transaction

        # TestCase's class-level fixture transaction never commits. Isolate
        # its pending callback so this assertion models a new real request.
        connection = transaction.get_connection()
        fixture_callbacks = connection.run_on_commit
        connection.run_on_commit = []
        try:
            before = revision()
            with self.captureOnCommitCallbacks(execute=True):
                self.distribute()
                self.assertEqual(revision(), before)
            self.assertNotEqual(revision(), before)
        finally:
            connection.run_on_commit = fixture_callbacks

    def test_country_export_uses_the_same_approved_milestone_values(self):
        from apps.analytics.cd_export_service import country_export

        _, item = self.distribute()
        self.activity(item, self.cceo_a_sp, partner=True)
        slug, header, rows = country_export(self.cd, "delivery", fy=FY)
        self.assertEqual(slug, "distributed-delivery")
        self.assertIn("Approved Target", header)
        pl_row = next(row for row in rows if row[1] == "Program Lead")
        self.assertEqual(pl_row[4], 10)
        self.assertEqual(pl_row[6], 1)
        self.assertEqual(pl_row[7], 10)

    def test_target_pages_use_approved_contract_and_keep_pl_team_scope(self):
        from apps.targets.my_targets import MyTargetQueryService
        from apps.targets.team_targets import PLTeamTargetsService

        _, item = self.distribute()
        self.activity(item, self.cceo_a_sp, partner=True)
        personal = MyTargetQueryService.get_page(self.cceo_a, FY, 1)
        self.assertEqual(personal["distributed"]["pct"], 12.5)
        self.assertEqual(personal["contract_matrix"]["rows"][0]["cells"][-1]["t"], 8)
        team = PLTeamTargetsService.get_page(self.pl, FY, 1)
        self.assertEqual(team["distributed"]["pct"], 10)
        own_row = next(
            r for r in team["contract_members"] if r["role"] == "Program Lead"
        )
        self.assertEqual(own_row["matrix"]["annual"]["pct"], 10)

    def test_snapshot_projection_never_substitutes_later_live_delivery(self):
        from apps.hr.accountability import snapshot_contract
        from apps.hr.models import PerformanceCycle
        from apps.hr.performance_engine import (
            build_draft_agreement,
            take_snapshot,
            conversation_document,
        )

        _, item = self.distribute()
        self.activity(item, self.cceo_a_sp)
        cycle = PerformanceCycle.objects.create(fy=FY)
        review = build_draft_agreement(self.cceo_a_sp, cycle, self.ia)
        snapshot = take_snapshot(review, "q1")
        self.activity(item, self.cceo_a_sp, partner=True)
        snapshot.refresh_from_db()
        frozen = snapshot_contract(snapshot.data)
        self.assertEqual(frozen["pct"], 12.5)
        self.assertEqual(allocation_priorities(self.cceo_a, FY)["pct"], 25)
        self.assertEqual(
            conversation_document(review, "q1", self.ia)["distributed"], frozen
        )
        self.assertEqual(snapshot_contract({})["rows"], [])

    def test_rate_rollup_keeps_the_rate_instead_of_adding_percentages(self):
        from apps.hr.models import MilestoneAllocation

        milestone, item = self.distribute()
        milestone.measurement_type = "percentage"
        milestone.target_value = 90
        milestone.save()
        MilestoneAllocation.objects.filter(milestone=milestone).update(
            allocated_target=90
        )
        MilestoneAllocation.objects.filter(
            milestone=milestone, allocated_to_type="team"
        ).update(denominator=10)
        MilestoneAllocation.objects.filter(
            milestone=milestone, employee=self.pl_sp
        ).update(denominator=2)
        MilestoneAllocation.objects.filter(
            milestone=milestone, employee=self.cceo_a_sp
        ).update(denominator=8)
        self.activity(item, self.cceo_a_sp)
        self.activity(item, self.pl_sp)
        for user in [self.pl, self.cd]:
            contract = allocation_priorities(user, FY)
            self.assertEqual(contract["rows"][0]["target"], 90)
            self.assertEqual(contract["rows"][0]["actual"], 20)
            self.assertEqual(contract["pct"], 22.22)

    def test_drilldown_and_rvp_read_the_country_contract(self):
        from apps.analytics.cd_analytics_service import (
            CDAnalyticsService,
            resolve_cd_scope,
            _country_activities,
        )
        from apps.analytics.rvp_dashboard_service import RVPDashboardService

        milestone, item = self.distribute()
        self.activity(item, self.cceo_a_sp, partner=True)
        cd = resolve_cd_scope(FY, country="Uganda")
        rows = CDAnalyticsService._area_achievement_rows(cd, [self.cceo_a.id])
        self.assertEqual(rows[0]["key"], milestone.id)
        self.assertEqual(rows[0]["pct"], 12.5)
        directors = RVPDashboardService.cd_performance(cd, _country_activities(cd), FY)
        self.assertTrue(directors)
        self.assertEqual(directors[0]["target_pct"], 10)

    def test_country_counts_a_shared_school_once_across_staff_and_partners(self):
        milestone, item = self.distribute()
        milestone.activity_rules.update(counting_basis="UNIQUE_SCHOOLS_SUPPORTED")
        school = self.schools_by_staff[self.cceo_a_sp.id][0]
        for staff, partner in [(self.cceo_a_sp, False), (self.pl_sp, True)]:
            activity = self.activity(item, staff, partner=partner)
            activity.school_id = school.id
            activity.save()
        self.assertEqual(allocation_priorities(self.cd, FY)["rows"][0]["actual"], 1)
        self.assertEqual(allocation_priorities(self.pl, FY)["rows"][0]["actual"], 1)

    def test_monitor_reassignment_updates_staff_scopes_without_changing_country(self):
        _, item = self.distribute()
        activity = self.activity(item, self.cceo_a_sp, partner=True)
        self.assertEqual(allocation_priorities(self.pl, FY)["pct"], 10)
        activity.monitored_by_staff_id = self.cceo_c_sp.id
        activity.save()
        self.assertEqual(allocation_priorities(self.cceo_a, FY)["pct"], 0)
        self.assertEqual(allocation_priorities(self.pl, FY)["pct"], 0)
        self.assertEqual(allocation_priorities(self.cd, FY)["pct"], 10)

    def test_an_explicit_school_country_prevents_cross_country_credit(self):
        from apps.geography.models import Region

        _, item = self.distribute()
        activity = self.activity(item, self.cceo_a_sp)
        school = self.schools_by_staff[self.cceo_a_sp.id][0]
        school.region = Region.objects.create(name="Outside country", country="Kenya")
        school.save()
        activity.school = school
        activity.save()
        for user in [self.cceo_a, self.pl, self.cd]:
            self.assertEqual(allocation_priorities(user, FY)["pct"], 0)
