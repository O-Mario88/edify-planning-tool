"""My Plan reads each activity's weekly requests and advances in bulk (owner,
2026-10-26: "export takes too long to be exported to the computer").

My Plan's rows, and every export built from them, used to prefetch cost line
-> weekly request line -> weekly request and cost line -> advance requests.
Django builds one query object per cost line for each nested relation: for a
country's 45,000 cost lines that was 90,000 of them, about half of the
export's time, and the Planning Oversight export timed out on production.
These tests hold both halves of the fix: the rows say the same thing, and the
work no longer grows with the number of cost lines.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.db.models.query import QuerySet
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan.services import compute_next_action, get_frontend_context
from apps.schools.models import School


class MoneyChainFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Chain Region")
        district = District.objects.create(name="Chain District", region=region)
        cls.school = School.objects.create(
            name="Chain Primary",
            school_id="CH-1",
            region_id=region.id,
            district_id=district.id,
        )
        cls.user = User.objects.create_user(
            email="chain-cceo@edify.test",
            name="Chain Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="pw12345678",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.get_or_create(user=cls.user)[0]

    def _activity(self, **kw):
        values = dict(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=self.fy,
            planned_date=timezone.localdate() + timedelta(days=3),
            responsible_staff_id=self.staff.id,
            evidence_status="none",
        )
        values.update(kw)
        return Activity.objects.create(**values)

    def _line(self, activity, label="Transport"):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=label.lower().replace(" ", "_"),
            label=label,
            unit_cost=50_000,
            amount=50_000,
        )

    def _weekly(self, line, status, week=0):
        from apps.fund_requests.models import WeeklyFundRequest, WeeklyFundRequestLine

        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        start = monday + timedelta(weeks=week)
        request = WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date=start,
            week_end_date=start + timedelta(days=6),
            responsible_user=self.user.id,
            total_amount=line.amount,
            status=status,
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=request,
            activity_budget_line=line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=line.amount,
            total_cost=line.amount,
        )
        return request

    def _advance(self, line, status, **kw):
        from apps.fund_requests.models import AdvanceRequest

        return AdvanceRequest.objects.create(
            activity=line.activity,
            budget_line=line,
            fy=self.fy,
            quarter="Q1",
            planned_date=timezone.now(),
            amount=line.amount,
            status=status,
            **kw,
        )

    def _rows(self, activities):
        context = get_frontend_context(
            self.user,
            {"fy": str(self.fy), "period": "fy"},
            with_readiness=False,
            activities=Activity.objects.filter(id__in=[a.id for a in activities]),
        )
        return {row["id"]: row for row in context["school_visits"]}


class RowsSayTheSameTests(MoneyChainFixture):
    def test_budget_status_reads_the_first_lines_weekly_request(self):
        visit = self._activity()
        self._weekly(self._line(visit), "submitted_to_pl")

        row = self._rows([visit])[visit.id]

        self.assertEqual(row["budget_status"], "Awaiting PL Approval")

    def test_next_action_finds_money_on_a_later_cost_line(self):
        visit = self._activity(status="ia_verified", evidence_status="accepted")
        settled = self._line(visit, "Lunch")
        self._advance(settled, "accounted")
        owed = self._line(visit, "Transport")
        self._advance(owed, "disbursed", disbursed_amount=50_000)
        prefetched = Activity.objects.prefetch_related(
            "schedule_cost_lines__advance_requests"
        ).get(id=visit.id)

        row = self._rows([visit])[visit.id]

        self.assertEqual(
            row["next_action"]["action"],
            compute_next_action(prefetched, date.today())["action"],
        )
        self.assertNotEqual(row["next_action"]["action"], "view_status")


class WorkDoesNotGrowWithCostLinesTests(MoneyChainFixture):
    def _query_objects_built(self, lines_each: int) -> int:
        visits = [self._activity() for _ in range(2)]
        for v, visit in enumerate(visits):
            for n in range(lines_each):
                line = self._line(visit, f"Line {n}")
                self._weekly(line, "submitted_to_pl", week=v * lines_each + n)
                self._advance(line, "confirmed_for_advance")
        built = 0
        original = QuerySet.__init__

        def counting(queryset, *args, **kwargs):
            nonlocal built
            built += 1
            original(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "__init__", counting):
            self._rows(visits)
        from apps.fund_requests.models import WeeklyFundRequest

        Activity.objects.filter(id__in=[v.id for v in visits]).delete()
        WeeklyFundRequest.objects.filter(responsible_user=self.user.id).delete()
        return built

    def test_eight_cost_lines_cost_what_one_does(self):
        one = self._query_objects_built(1)
        eight = self._query_objects_built(8)

        self.assertEqual(eight, one)
