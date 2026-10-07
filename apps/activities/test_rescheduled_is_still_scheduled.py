"""A rescheduled activity is a scheduled activity that has been moved.

Found by the 2026-10-07 calculation check (owner: "do a final logic,
computation and calculation check ... accurate and not missleading").

Moving a staff activity writes the status `rescheduled`. Some forty readers
named `scheduled` by hand and forgot it, so on its new day the activity lost
its Start button, sat under "Upcoming" instead of "Due today", was counted by
Today as already done, never became overdue, and left the Planning page's
"In My Plan" count. Every reader now names both, and the last test here keeps
it that way.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.closure_services import NOT_EXECUTED_STATUSES
from apps.activities.models import Activity
from apps.activities.services import STARTABLE_STATUSES
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.my_plan.services import compute_next_action, get_frontend_context
from apps.planning.planning_service import PlanningDashboardService
from apps.schools.models import School


class MovedWork(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(name="Moved Region")
        cls.district = District.objects.create(name="Moved District", region=cls.region)
        cls.user = User.objects.create(
            email="moved@edify.org",
            name="Moved Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")
        cls.admin = User.objects.create(
            email="moved-admin@edify.org",
            name="Moved Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )
        cls.cluster = Cluster.objects.create(
            name="Moved Cluster", region=cls.region, district=cls.district
        )
        cls.school = School.objects.create(
            school_id="MOVED-1",
            name="Moved School",
            region=cls.region,
            district=cls.district,
            school_type="core",
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
            account_owner_id=cls.user.id,
        )

    def activity(self, status, *, days=0, **more):
        when = date.today() + timedelta(days=days)
        fields = {
            "activity_type": "school_visit",
            "school": self.school,
            "fy": self.fy,
            "quarter": "Q1",
            "planned_date": when,
            "planned_month": when.month,
            "status": status,
            "delivery_type": "staff",
            "responsible_staff_id": self.staff.id,
            **more,
        }
        return Activity.objects.create(**fields)

    def kpis(self):
        return PlanningDashboardService.get_dashboard_data(self.admin, {})["kpis"]


class OnItsNewDayTest(MovedWork):
    def test_it_can_be_started(self):
        self.assertIn("rescheduled", STARTABLE_STATUSES)
        for status in ("scheduled", "rescheduled"):
            with self.subTest(status=status):
                action = compute_next_action(self.activity(status), date.today())
                self.assertEqual(action["action"], "start")

    def test_my_plan_lists_it_as_due_today(self):
        moved = self.activity("rescheduled")
        later = self.activity("rescheduled", days=3)
        context = get_frontend_context(self.user, {})
        self.assertEqual([row["id"] for row in context["due_today"]], [moved.id])
        self.assertEqual([row["id"] for row in context["this_week"]], [later.id])

    def test_today_offers_it_next_and_does_not_call_it_done(self):
        self.activity("rescheduled")
        self.client.force_login(self.user)
        response = self.client.get("/today/panel")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["next_activity"])
        self.assertEqual(response.context["done_count"], 0)

    def test_it_has_not_been_executed(self):
        self.assertIn("rescheduled", NOT_EXECUTED_STATUSES)


class PlanningTilesTest(MovedWork):
    def test_in_my_plan_counts_an_activity_at_every_stage(self):
        for status in ("scheduled", "rescheduled", "evidence_uploaded", "closed"):
            self.activity(status)
        for status in ("cancelled", "deferred", "awaiting_owner_approval"):
            self.activity(status)
        self.assertEqual(self.kpis()["scheduled_this_week"], 4)

    def test_a_cluster_with_only_cancelled_work_still_needs_action(self):
        self.assertEqual(self.kpis()["cluster_activities_needed"], 1)
        called_off = self.activity(
            "cancelled",
            school=None,
            cluster=self.cluster,
            activity_type="cluster_meeting",
        )
        self.assertEqual(self.kpis()["cluster_activities_needed"], 1)
        Activity.objects.filter(id=called_off.id).update(status="scheduled")
        self.assertEqual(self.kpis()["cluster_activities_needed"], 0)

    def test_core_gap_reads_this_years_finished_work_on_one_activity(self):
        self.assertEqual(self.kpis()["core_pending"], 1)
        # Finished last year, and something merely planned this year: the
        # status and the year used to be tested on different activities.
        self.activity("ia_verified", fy="FY1999")
        self.activity("scheduled")
        self.assertEqual(self.kpis()["core_pending"], 1)
        # Closed work is finished work.
        self.activity("closed")
        self.assertEqual(self.kpis()["core_pending"], 0)


#: Files that name "scheduled" in some other vocabulary, and how many times:
#: enum declarations, a school's SSA status, a hand-over's or a catch-up
#: plan's own status, tab and filter keys. Adding an activity-status list to
#: one of them raises its count and fails the test below; say `rescheduled`
#: in the new list rather than raise the number.
_OTHER_VOCABULARIES = {
    "apps/activities/schedule_models.py": 1,
    "apps/admin_ops/models.py": 1,
    "apps/analytics/analytics_dashboard_service.py": 1,
    "apps/analytics/decision_engine.py": 1,
    "apps/analytics/pl_week_service.py": 1,
    "apps/analytics/services.py": 1,
    "apps/business_transformation/models.py": 1,
    "apps/business_transformation/services.py": 2,
    "apps/command_center/todo_service.py": 1,
    "apps/core/enums.py": 3,
    "apps/frontend/views/analytics_views.py": 1,
    "apps/frontend/views/extended_views.py": 1,
    "apps/frontend/views/ia_views.py": 1,
    "apps/frontend/views/oversight_views.py": 2,
    "apps/frontend/views/partner_views.py": 1,
    "apps/frontend/views/planning_views.py": 1,
    "apps/messaging/services.py": 1,
    "apps/partners/models.py": 2,
    "apps/planning/country_execution/stages.py": 1,
    "apps/planning/partner_oversight_service.py": 1,
    "apps/planning/planning_service.py": 1,
    "apps/projects/dashboard_service.py": 1,
    "apps/projects/planning_service.py": 3,
    "apps/realtime/health.py": 1,
    "apps/realtime/registry.py": 1,
    "apps/system_health/planning_oversight_health.py": 2,
    "apps/system_health/services.py": 1,
    "apps/targets/models.py": 1,
    "apps/targets/team_targets.py": 2,
}


def _names_scheduled_alone(tree) -> int:
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            named = {
                item.value
                for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            found += "scheduled" in named and "rescheduled" not in named
        elif isinstance(node, ast.Compare):
            found += sum(
                isinstance(side, ast.Constant) and side.value == "scheduled"
                for side in node.comparators
            )
        elif isinstance(node, ast.keyword) and node.arg in (
            "status",
            "activity__status",
        ):
            found += (
                isinstance(node.value, ast.Constant) and node.value.value == "scheduled"
            )
    return found


class NobodyForgetsItAgainTest(TestCase):
    def test_no_new_reader_names_scheduled_without_rescheduled(self):
        root = Path(settings.BASE_DIR)
        found = Counter()
        for path in sorted((root / "apps").rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if (
                "/migrations/" in relative
                or "/tests/" in relative
                or "/management/" in relative
                or path.name.startswith("test")
            ):
                continue
            count = _names_scheduled_alone(ast.parse(path.read_text()))
            if count:
                found[relative] = count
        over = {
            name: (count, _OTHER_VOCABULARIES.get(name, 0))
            for name, count in found.items()
            if count > _OTHER_VOCABULARIES.get(name, 0)
        }
        self.assertEqual(
            over,
            {},
            'These files test an activity for "scheduled" and not "rescheduled" '
            "(found, allowed). A moved activity is still a scheduled one: name "
            "both, or use apps.core.activity_types.NOT_STARTED_ACTIVITY_STATUSES.",
        )
