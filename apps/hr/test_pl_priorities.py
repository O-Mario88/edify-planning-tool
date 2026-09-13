"""The Programme Lead's strategic direction on the Priorities page (owner, 2026-09-13).

The role description: "lead priority setting, planning, and communication for
CCE initiatives at the country level". The priorities are SET above the lead
(the RVP and the Country Director) and distributed by Impact Assessment; the
lead distributes what their team received and communicates it. These tests
hold that split:

* Priority Setting is read-only for a Program Lead — the allocation form and
  its POST need the distribution authority (strategicPriorities.allocate), and
  create_allocation refuses country and project targets from a lead whatever
  door the request came through; the header says who sets it.
* The Target Distribution tab shows the lead what the team received beside
  their own share.
* The To-Do queue reminds the lead to distribute each received team target
  and to approve each holder's quarterly spread, derived and bulk.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.exceptions import BadRequest

from .distribution_todos import distribution_todos
from .milestone_allocations import create_allocation
from .models import MilestoneAllocation, StrategicPriorityCycle
from .test_target_distribution import FY, DistributionFixture

TODAY = timezone.localdate()
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-priorities-tests",
    }
}


def _allocation(milestone, *, team=None, employee=None, parent=None, **extra):
    fields = {
        "milestone": milestone,
        "allocated_to_type": "team" if team is not None else "employee",
        "team_id": team.id if team is not None else None,
        "employee": employee,
        "parent": parent,
        "allocated_target": Decimal("10"),
        "allocation_reason": "test",
        "allocated_by": "test",
        "effective_date": date(2026, 10, 1),
        "status": "approved",
    }
    fields.update(extra)
    return MilestoneAllocation.objects.create(**fields)


class PrioritySettingReadOnlyTest(DistributionFixture):
    def test_the_lead_reads_the_setting_view_without_the_allocation_form(self):
        self._milestone("RO_SETTING")
        self.client.force_login(self.pl)
        response = self.client.get("/strategic-priorities", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_allocate"])
        self.assertContains(response, "Set by the RVP and Country Director · read-only")
        self.assertNotContains(response, "Strategy · RVP decision workspace")
        self.assertNotContains(response, "Allocate approved target")
        self.assertNotContains(response, "/allocate")

    def test_the_authors_keep_their_workspace_and_the_distributors_their_form(self):
        self._milestone("RO_AUTHOR")
        self.client.force_login(self.cd)
        response = self.client.get("/strategic-priorities", {"fy": FY})
        self.assertTrue(response.context["can_allocate"])
        self.assertContains(response, "Strategy · RVP decision workspace")
        # Impact Assessment is not an author but acts here, so it is told who
        # sets the priorities without being told it is read-only.
        self.client.force_login(self.ia)
        response = self.client.get("/strategic-priorities", {"fy": FY})
        self.assertTrue(response.context["can_allocate"])
        self.assertContains(response, "Set by the RVP and Country Director")
        self.assertNotContains(response, "· read-only")

    def test_the_allocation_door_refuses_the_lead(self):
        milestone = self._milestone("RO_DOOR")
        self.client.force_login(self.pl)
        before = MilestoneAllocation.objects.count()
        for scope, extra in (
            ("employee", {"employeeId": self.cceo_a_sp.id}),
            ("team", {"teamId": self.pl_sp.id}),
            ("country", {"countryId": "Uganda"}),
        ):
            with self.subTest(scope=scope):
                response = self.client.post(
                    f"/strategic-priorities/milestones/{milestone.id}/allocate",
                    {
                        "allocatedToType": scope,
                        "allocatedTarget": "5",
                        "effectiveDate": "2026-10-01",
                        "allocationReason": "should be refused",
                        "approve": "yes",
                        **extra,
                    },
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(MilestoneAllocation.objects.count(), before)

    def test_create_allocation_refuses_country_and_project_targets_from_a_lead(self):
        milestone = self._milestone("RO_SERVICE")
        for scope, extra in (
            ("country", {"countryId": "Uganda"}),
            ("project", {"projectId": "any-project"}),
        ):
            with self.subTest(scope=scope):
                with self.assertRaisesMessage(
                    BadRequest, "Program Leads distribute only the team target"
                ):
                    create_allocation(
                        milestone=milestone,
                        data={
                            "allocatedToType": scope,
                            "allocatedTarget": "5",
                            "effectiveDate": "2026-10-01",
                            "allocationReason": "refused",
                            **extra,
                        },
                        principal=self.pl,
                    )
        # The distributors are unaffected.
        allocation = create_allocation(
            milestone=milestone,
            data={
                "allocatedToType": "country",
                "countryId": "Uganda",
                "allocatedTarget": "5",
                "effectiveDate": "2026-10-01",
                "allocationReason": "country target",
            },
            principal=self.ia,
        )
        self.assertEqual(allocation.allocated_to_type, "country")

    def test_the_lead_still_divides_their_own_team_target(self):
        milestone = self._milestone("RO_TEAM")
        team = self._team_allocation(milestone, self.pl_sp, 10)
        team.status = "approved"
        team.save(update_fields=["status"])
        child = self._employee_allocation(milestone, self.cceo_a_sp, 4, parent=team)
        self.assertEqual(child.parent_id, team.id)


class TargetDistributionTabForTheLeadTest(DistributionFixture):
    def test_team_received_and_my_share_sit_side_by_side(self):
        milestone = self._milestone("TAB_SHARE", target="100")
        team = _allocation(milestone, team=self.pl_sp, allocated_target=Decimal("40"))
        _allocation(
            milestone,
            employee=self.pl_sp,
            parent=team,
            allocated_target=Decimal("15"),
            status="draft",
        )
        _allocation(
            milestone,
            employee=self.cceo_a_sp,
            parent=team,
            allocated_target=Decimal("25"),
            status="draft",
        )
        self.client.force_login(self.pl)
        response = self.client.get("/priorities/master", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_team_lead_viewer"])
        self.assertContains(response, "Team received")
        self.assertContains(response, "My share")
        self.assertNotContains(response, ">My Target<")
        row = next(
            row
            for group in response.context["groups"]
            for row in group["rows"]
            if row["milestone"].id == milestone.id
        )
        self.assertEqual(row["team_value"], "40 units")
        self.assertEqual(row["share_value"], "15 units")
        self.assertTrue(row["share_is_draft"])
        self.assertFalse(row["team_is_draft"])

    def test_the_officer_view_is_unchanged(self):
        milestone = self._milestone("TAB_CCEO", target="100")
        team = _allocation(milestone, team=self.pl_sp, allocated_target=Decimal("40"))
        _allocation(
            milestone,
            employee=self.cceo_a_sp,
            parent=team,
            allocated_target=Decimal("25"),
        )
        self.client.force_login(self.cceo_a)
        response = self.client.get("/priorities/master", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_team_lead_viewer"])
        self.assertContains(response, "My Target")
        self.assertNotContains(response, "Team received")
        row = next(
            row
            for group in response.context["groups"]
            for row in group["rows"]
            if row["milestone"].id == milestone.id
        )
        self.assertEqual(row["my_value"], "25 units")


class DistributionTodoTest(DistributionFixture):
    def _rows(self, principal=None, role="Program Lead"):
        return distribution_todos(principal or self.pl, role, TODAY)

    def test_a_received_target_asks_to_be_distributed_until_it_is_approved(self):
        milestone = self._milestone("TODO_DIST")
        team = _allocation(milestone, team=self.pl_sp)
        rows = self._rows()
        self.assertEqual(
            [row["title"] for row in rows],
            [f"Distribute your FY{FY} team target — {milestone.title}"],
        )
        row = rows[0]
        self.assertEqual(row["action_url"], f"/target-distribution/team?fy={FY}")
        self.assertEqual(row["category"], "Strategic Direction")
        self.assertEqual(row["action_label"], "Distribute")
        for key in (
            "id",
            "description",
            "priority",
            "status_key",
            "status_label",
            "status_tone",
            "due_label",
            "due_tone",
            "linked",
            "actionable",
            "source",
            "_due_sort",
        ):
            self.assertIn(key, row)

        child = _allocation(
            milestone, employee=self.cceo_a_sp, parent=team, status="draft"
        )
        self.assertEqual(self._rows()[0]["action_label"], "Continue distribution")

        child.status = "approved"
        child.quarter_status = "approved"
        child.save(update_fields=["status", "quarter_status"])
        self.assertEqual(self._rows(), [])

    def test_a_spread_waiting_on_the_lead_names_the_holder(self):
        first = self._milestone("TODO_SPREAD_1")
        second = self._milestone("TODO_SPREAD_2")
        for milestone in (first, second):
            team = _allocation(milestone, team=self.pl_sp)
            _allocation(milestone, employee=self.cceo_a_sp, parent=team)
            _allocation(
                milestone, employee=self.pl_sp, parent=team, quarter_status="approved"
            )
        rows = self._rows()
        self.assertEqual(
            [row["title"] for row in rows],
            ["Approve CCEO Alpha's quarterly spread"],
        )
        self.assertIn("2 approved targets", rows[0]["description"])
        self.assertEqual(rows[0]["id"], f"distribution-spread-{self.cceo_a_sp.id}")
        MilestoneAllocation.objects.filter(employee=self.cceo_a_sp).update(
            quarter_status="approved"
        )
        self.assertEqual(self._rows(), [])

    def test_the_lead_approves_their_own_spread_under_their_own_wording(self):
        milestone = self._milestone("TODO_SELF")
        team = _allocation(milestone, team=self.pl_sp)
        _allocation(milestone, employee=self.pl_sp, parent=team)
        self.assertEqual(
            [row["title"] for row in self._rows()],
            ["Approve your own quarterly spread"],
        )

    def test_only_the_leads_own_team_and_current_cycles_count(self):
        milestone = self._milestone("TODO_SCOPE")
        _allocation(milestone, team=self.pl2_sp)
        self.assertEqual(self._rows(), [])
        self.assertEqual(self._rows(self.pl2)[0]["action_label"], "Distribute")
        # Nobody else receives these rows.
        for principal, role in (
            (self.cceo_c, "CCEO"),
            (self.ia, "ImpactAssessment"),
            (self.cd, "CountryDirector"),
        ):
            with self.subTest(role=role):
                self.assertEqual(self._rows(principal, role), [])
        # An archived cycle is history, not work.
        StrategicPriorityCycle.objects.filter(financial_year=FY).update(
            status="archived"
        )
        self.assertEqual(self._rows(self.pl2), [])

    def test_many_targets_fold_into_one_row(self):
        for index in range(7):
            _allocation(self._milestone(f"TODO_FOLD_{index}"), team=self.pl_sp)
        rows = self._rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-1]["title"], "Distribute 2 more team targets")

    def test_the_builder_is_registered_and_never_raises(self):
        from unittest.mock import patch

        from apps.command_center.todo_service import MODULE_TODO_BUILDERS

        self.assertIn(
            "apps.hr.distribution_todos:distribution_todos", MODULE_TODO_BUILDERS
        )
        with patch(
            "apps.hr.distribution_todos._team_target_rows",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(self._rows(), [])


@override_settings(CACHES=LOCMEM)
class DistributionTodoQueryBudgetTest(DistributionFixture):
    """Two queries whatever the number of received targets or holders."""

    def _grow(self, start, count):
        for index in range(start, start + count):
            milestone = self._milestone(f"BUDGET_{index}")
            team = _allocation(milestone, team=self.pl_sp)
            _allocation(milestone, employee=self.cceo_a_sp, parent=team)
            _allocation(milestone, employee=self.cceo_b_sp, parent=team, status="draft")

    def _count(self):
        with CaptureQueriesContext(connection) as ctx:
            rows = distribution_todos(self.pl, "Program Lead", TODAY)
        return len(ctx.captured_queries), rows

    def test_the_cost_does_not_grow_with_the_team_or_the_targets(self):
        self._grow(0, 2)
        small, rows = self._count()
        self.assertTrue(rows)
        self._grow(2, 8)
        large, rows = self._count()
        self.assertLessEqual(small, 2)
        self.assertEqual(small, large)
