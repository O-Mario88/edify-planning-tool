"""Deployment-hardening gates (2026-07-17): speed, concurrency, boundaries,
failure isolation, consistency.

- Query budgets are SCALING assertions: a page's query count must stay
  ~constant when the dataset doubles (catches every O(n) N+1 without
  hardcoding brittle absolute numbers).
- Concurrency tests use real threads against real Postgres transactions
  (TransactionTestCase) — not mocked "concurrency".
- Failure injection proves secondary effects (notifications, chain audit)
  can fail without rolling back or corrupting the primary write.
"""

from __future__ import annotations

import threading
from datetime import datetime as _dt
from datetime import timedelta
from datetime import timezone as _dt_tz

from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
        status="active",
    )


def _confirmed_ssa(school, fy, avg=5.0):
    record = SsaRecord.objects.create(
        school=school,
        fy=fy,
        quarter="Q1",
        date_of_ssa=timezone.now(),
        average_score=avg,
        verification_status="confirmed",
    )
    SsaScore.objects.bulk_create(
        [
            SsaScore(ssa_record=record, intervention=i, score=avg)
            for i in (
                "christlike_behaviour",
                "exposure_to_word_of_god",
                "financial_health",
                "leadership",
                "government_requirement",
                "learning_environment",
                "teaching_environment",
                "enrolment",
            )
        ]
    )
    return record


class QueryBudgetScalingTest(TestCase):
    """Critical pages must not add queries as the dataset grows (H01)."""

    # Allow a small constant slack for caching warm-up differences, never
    # anything proportional to the increment size.
    TOLERANCE = 4
    INCREMENT = 25  # schools added between measurements

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(name="Perf Region")
        cls.district = District.objects.create(name="Perf District", region=cls.region)
        cls.cd = _user("perf-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cceo = _user("perf-cceo@edify.test", EdifyRole.CCEO.value)
        cls.cceo_staff = StaffProfile.objects.create(user=cls.cceo, title="CCEO")
        cls._grow(0, cls.INCREMENT)

    @classmethod
    def _grow(cls, start, count):
        fy = cls.fy
        for i in range(start, start + count):
            school = School.objects.create(
                school_id=f"PERF-{i}",
                name=f"Perf School {i}",
                region=cls.region,
                district=cls.district,
            )
            StaffSchoolAssignment.objects.create(
                staff=cls.cceo_staff, school_id=school.id
            )
            _confirmed_ssa(school, fy)
            activity = Activity.objects.create(
                school=school,
                activity_type="school_visit",
                status="scheduled",
                fy=fy,
                quarter="Q1",
                responsible_staff_id=cls.cceo_staff.id,
                scheduled_date=timezone.now(),
                planned_date=timezone.now().date(),
                focus_intervention="leadership",
            )
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                school=school,
                cost_setting_key="transport",
                label="Transport",
                line_item_type="transport",
                unit_cost=10_000,
                quantity=1,
                amount=10_000,
                responsible_user=cls.cceo.id,
                planned_date=timezone.now().date(),
            )

    def _measure(self, client, url):
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
        self.assertLess(response.status_code, 500, url)
        return len(ctx.captured_queries)

    def assert_scales(self, url, principal):
        client = Client()
        client.force_login(principal)
        client.get(url)  # warm caches (permissions, sessions)
        before = self._measure(client, url)
        self._grow(self.INCREMENT, self.INCREMENT)
        after = self._measure(client, url)
        self.assertLessEqual(
            after,
            before + self.TOLERANCE,
            f"{url}: query count grew {before} → {after} when schools doubled "
            f"({self.INCREMENT} → {self.INCREMENT * 2}) — O(n) query pattern.",
        )

    def test_school_directory_scales(self):
        self.assert_scales("/schools", self.cd)

    def test_planning_scales(self):
        self.assert_scales("/planning", self.cd)

    def test_ssa_performance_scales(self):
        self.assert_scales("/ssa", self.cd)

    def test_dashboard_scales(self):
        self.assert_scales("/dashboard", self.cd)

    def test_my_plan_scales(self):
        self.assert_scales("/my-plan", self.cceo)

    def test_todos_scales(self):
        self.assert_scales("/todos", self.cceo)

    def test_impact_scales(self):
        self.assert_scales("/impact", self.cd)


class ConcurrentMutationTest(TransactionTestCase):
    """Two real threads race the same mutation; exactly one wins (H02)."""

    reset_sequences = False

    def setUp(self):
        self.fy = get_operational_fy()
        region = Region.objects.create(name="Conc Region")
        district = District.objects.create(name="Conc District", region=region)
        self.school = School.objects.create(
            school_id="CONC-1",
            name="Concurrency P/S",
            region=region,
            district=district,
        )
        self.accountant = _user(
            "conc-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )

    def _race(self, fn):
        """Run fn twice concurrently; return list of (ok, result_or_exc)."""
        results = [None, None]
        barrier = threading.Barrier(2)

        def runner(idx):
            try:
                barrier.wait(timeout=10)
                results[idx] = (True, fn())
            except Exception as exc:  # noqa: BLE001
                results[idx] = (False, exc)
            finally:
                for conn in connections.all():
                    conn.close()

        threads = [threading.Thread(target=runner, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return results

    def _activity(self, **kwargs):
        defaults = dict(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=self.fy,
            quarter="Q1",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
        )
        defaults.update(kwargs)
        return Activity.objects.create(**defaults)

    def test_concurrent_salesforce_id_reserves_once(self):
        from apps.activities.salesforce import reserve_salesforce_id

        a1 = self._activity()
        a2 = self._activity(planned_date=timezone.now().date() + timedelta(days=1))
        ids = iter([a1.id, a2.id])
        lock = threading.Lock()

        principal_id = self.accountant.id

        def reserve():
            with lock:
                activity_id = next(ids)
            activity = Activity.objects.get(id=activity_id)
            principal = User.objects.get(id=principal_id)
            reserve_salesforce_id(
                activity=activity,
                raw_value="SVE-RACE-1",
                kind="visit",
                principal=principal,
                entry_source="staff",
            )
            return activity_id

        results = self._race(reserve)
        winners = [r for ok, r in results if ok]
        losers = [r for ok, r in results if not ok]
        self.assertEqual(len(winners), 1, f"expected one winner: {results}")
        self.assertEqual(len(losers), 1)
        from apps.activities.models import ActivitySalesforceReference

        self.assertEqual(
            ActivitySalesforceReference.objects.filter(
                normalized_value="SVE-RACE-1"
            ).count(),
            1,
        )

    def test_concurrent_weekly_disbursement_pays_once(self):
        from apps.fund_requests import weekly_service
        from apps.fund_requests.models import (
            AdvanceRequest,
            WeeklyFundRequest,
            WeeklyFundRequestLine,
        )

        activity = self._activity()
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="transport",
            label="Transport",
            line_item_type="transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            planned_date=timezone.now().date(),
        )
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy=self.fy,
            quarter="Q1",
            amount=50_000,
            status="confirmed_for_advance",
        )
        week_start = timezone.now().date() - timedelta(
            days=timezone.now().date().weekday()
        )
        wfr = WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user="conc-owner",
            total_amount=50_000,
            status="confirmed_for_advance",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=wfr,
            activity_budget_line=line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=50_000,
            total_cost=50_000,
        )
        accountant_id = self.accountant.id

        def disburse():
            principal = User.objects.get(id=accountant_id)
            return weekly_service.disburse(wfr.id, {"amount": 50_000}, principal)

        results = self._race(disburse)
        winners = [r for ok, r in results if ok]
        self.assertEqual(len(winners), 1, f"double disbursement: {results}")
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "disbursed")

    def test_concurrent_partner_payment_pays_once(self):
        from apps.evidence.models import EvidenceRecord
        from apps.fund_requests.finance_models import PartnerPayment
        from apps.fund_requests.finance_services import PartnerPaymentService

        activity = self._activity(
            delivery_type="partner",
            status="ia_verified",
            salesforce_activity_id="SVE-CONC-PAY",
            evidence_status="accepted",
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="partner",
            label="Partner",
            line_item_type="partner",
            unit_cost=80_000,
            quantity=1,
            amount=80_000,
        )
        EvidenceRecord.objects.create(
            activity=activity, kind="visit_form", uri="x.pdf", status="accepted"
        )
        accountant_id = self.accountant.id

        def pay():
            act = Activity.objects.get(id=activity.id)
            return PartnerPaymentService.pay_partner(
                act,
                "Conc Partner",
                80_000,
                "bank",
                "REF-CONC",
                accountant_id,
                netsuite_id="NS-CONC-1",
            )

        results = self._race(pay)
        winners = [r for ok, r in results if ok]
        self.assertEqual(len(winners), 1, f"double partner payment: {results}")
        self.assertEqual(PartnerPayment.objects.filter(activity=activity).count(), 1)

    def test_concurrent_identical_schedule_creates_one_activity(self):
        from apps.activities import services as activity_services

        cceo = _user("conc-cceo@edify.test", EdifyRole.CCEO.value)
        staff = StaffProfile.objects.create(user=cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.school.id)
        from apps.budget.models import CostCatalogue, CostSetting

        CostCatalogue.objects.get_or_create(
            fy=self.fy, version=1, defaults={"label": "Concurrency test catalogue"}
        )[0]
        for key, label in (
            ("staff_visit_transport_primary", "Transport (primary)"),
            ("lunch", "Lunch"),
        ):
            CostSetting.objects.get_or_create(
                key=key, defaults={"label": label, "unit_cost": 10_000, "version": 1}
            )[0]
        self.school.district.district_type = "primary"
        self.school.district.save(update_fields=["district_type"])
        _confirmed_ssa(self.school, self.fy, avg=4.0)
        target_date = (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        cceo_id = cceo.id

        def schedule():
            principal = User.objects.get(id=cceo_id)
            return activity_services.create(
                {
                    "activityType": "school_visit",
                    "schoolId": self.school.school_id,
                    "scheduledDate": target_date,
                    "focus": "leadership",
                },
                principal,
            )

        results = self._race(schedule)
        count = Activity.objects.filter(
            school=self.school,
            activity_type="school_visit",
            deleted_at__isnull=True,
        ).count()
        self.assertEqual(
            count,
            1,
            f"expected exactly one activity, got {count}; results={results}",
        )


class BoundaryTest(TestCase):
    """Fiscal-year and period boundaries (H03)."""

    def test_fy_boundary_days(self):
        from datetime import datetime, timezone as dt_tz

        from apps.core.fy import get_operational_fy, get_quarter_for_date

        sep30 = datetime(2026, 9, 30, 23, 59, tzinfo=dt_tz.utc)
        oct1 = datetime(2026, 10, 1, 0, 0, tzinfo=dt_tz.utc)
        self.assertEqual(get_operational_fy(sep30), "2026")
        self.assertEqual(get_operational_fy(oct1), "2027")
        self.assertEqual(get_quarter_for_date(sep30), "Q4")
        self.assertEqual(get_quarter_for_date(oct1), "Q1")

    def test_cross_fy_reschedule_moves_all_period_fields(self):
        from apps.activities import services as activity_services
        from apps.budget.models import CostCatalogue, CostSetting

        region = Region.objects.create(name="Bound Region")
        district = District.objects.create(
            name="Bound District", region=region, district_type="primary"
        )
        school = School.objects.create(
            school_id="BOUND-1", name="Boundary P/S", region=region, district=district
        )
        cceo = _user("bound-cceo@edify.test", EdifyRole.CCEO.value)
        staff = StaffProfile.objects.create(user=cceo, title="CCEO")
        catalogue = CostCatalogue.objects.get_or_create(
            fy="2027", version=1, defaults={"label": "FY 2027 boundary test catalogue"}
        )[0]
        for key, label in (
            ("primary_transport_per_day", "Primary transport"),
            ("primary_lunch_per_day", "Primary lunch"),
        ):
            CostSetting.objects.get_or_create(
                key=key,
                defaults={"label": label, "unit_cost": 10_000, "catalogue": catalogue},
            )[0]
        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=staff.id,
            scheduled_date=_dt(2026, 9, 15, 9, 0, tzinfo=_dt_tz.utc),
            planned_date=_dt(2026, 9, 15).date(),
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=school,
            cost_setting_key="transport",
            label="Transport",
            line_item_type="transport",
            unit_cost=10_000,
            quantity=1,
            amount=10_000,
            planned_date=activity.planned_date,
            fiscal_year="2026",
            quarter="Q4",
            month=9,
        )
        activity_services.reschedule(
            activity.id,
            {"scheduledDate": "2026-10-06", "reason": "FY-boundary hardening test"},
            cceo,
        )
        activity.refresh_from_db()
        self.assertEqual(activity.fy, "2027")
        self.assertEqual(activity.quarter, "Q1")
        line = activity.schedule_cost_lines.first()
        self.assertEqual(line.fiscal_year, "2027")
        self.assertEqual(line.quarter, "Q1")
        self.assertEqual(line.month, 10)


class FailureIsolationTest(TestCase):
    """Secondary-effect failures must not corrupt primary writes (H04)."""

    def setUp(self):
        region = Region.objects.create(name="Iso Region")
        district = District.objects.create(name="Iso District", region=region)
        self.school = School.objects.create(
            school_id="ISO-1", name="Isolation P/S", region=region, district=district
        )
        self.accountant = _user(
            "iso-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )

    def test_notification_failure_does_not_roll_back_closure(self):
        from unittest.mock import patch

        from apps.activities.closure_services import ActivityClosureService
        from apps.evidence.models import EvidenceRecord

        activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="ia_verified",
            ia_verification_status="confirmed",
            evidence_status="accepted",
            salesforce_activity_id="SVE-ISO-1",
            fy=get_operational_fy(),
            quarter="Q1",
        )
        EvidenceRecord.objects.create(
            activity=activity, kind="visit_form", uri="x.pdf", status="accepted"
        )
        with patch(
            "apps.notifications.services.WorkflowNotificationService.trigger",
            side_effect=RuntimeError("notification service down"),
        ):
            ActivityClosureService.close(
                activity, closed_by="system", bypass_checks=True
            )
        activity.refresh_from_db()
        self.assertEqual(activity.status, "closed")

    def test_audit_chain_failure_does_not_block_disbursement(self):
        from unittest.mock import patch

        from apps.fund_requests import advance_service
        from apps.fund_requests.models import AdvanceRequest

        activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            quarter="Q1",
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="transport",
            label="Transport",
            line_item_type="transport",
            unit_cost=30_000,
            quantity=1,
            amount=30_000,
        )
        adv = AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy=get_operational_fy(),
            quarter="Q1",
            amount=30_000,
            status="confirmed_for_advance",
        )
        with patch(
            "apps.audit.services.log", side_effect=RuntimeError("audit store down")
        ):
            advance_service.disburse(
                adv.id,
                {"amount": 30_000, "method": "bank", "reference": "R-ISO"},
                self.accountant,
            )
        adv.refresh_from_db()
        self.assertEqual(adv.status, "disbursed")
        self.assertEqual(adv.disbursed_amount, 30_000)


class ConsistencyReconciliationTest(TestCase):
    """Financial identities and cross-surface parity (H05)."""

    def test_weekly_request_total_equals_source_lines(self):
        from apps.fund_requests import weekly_service

        region = Region.objects.create(name="Recon Region")
        district = District.objects.create(name="Recon District", region=region)
        school = School.objects.create(
            school_id="RECON-1", name="Recon P/S", region=region, district=district
        )
        cceo = _user("recon-cceo@edify.test", EdifyRole.CCEO.value)
        week_start = timezone.now().date() - timedelta(
            days=timezone.now().date().weekday()
        )
        total = 0
        for i, amount in enumerate((13_333, 26_667, 40_001)):
            activity = Activity.objects.create(
                school=school,
                activity_type="school_visit",
                status="scheduled",
                fy=get_operational_fy(),
                quarter="Q1",
                scheduled_date=timezone.now(),
                planned_date=week_start + timedelta(days=i),
            )
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                school=school,
                cost_setting_key="transport",
                label="Transport",
                line_item_type="transport",
                unit_cost=amount,
                quantity=1,
                amount=amount,
                responsible_user=cceo.id,
                planned_date=week_start + timedelta(days=i),
            )
            total += amount
        wfr = weekly_service.generate_weekly_fund_request(
            cceo.id, week_start.isoformat()
        )
        self.assertIsNotNone(wfr)
        self.assertEqual(wfr.total_amount, total)
        self.assertEqual(sum(line.total_cost for line in wfr.lines.all()), total)

    def test_activity_status_matches_across_surfaces(self):
        region = Region.objects.create(name="Parity Region")
        district = District.objects.create(name="Parity District", region=region)
        school = School.objects.create(
            school_id="PARITY-1", name="Parity P/S", region=region, district=district
        )
        cceo = _user("parity-cceo@edify.test", EdifyRole.CCEO.value)
        staff = StaffProfile.objects.create(user=cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            quarter="Q1",
            responsible_staff_id=staff.id,
            scheduled_date=timezone.now() + timedelta(days=3),
            planned_date=(timezone.now() + timedelta(days=3)).date(),
        )
        from apps.my_plan.services import get as get_my_plan

        plan = get_my_plan(cceo, {})

        def _find(node):
            if isinstance(node, dict):
                if node.get("id") == activity.id:
                    yield node
                for value in node.values():
                    yield from _find(value)
            elif isinstance(node, list):
                for value in node:
                    yield from _find(value)

        plan_rows = list(_find(plan))
        self.assertTrue(plan_rows, "activity missing from My Plan feed")
        from apps.activities.services import get_activity

        detail = get_activity(activity.id, cceo)
        self.assertEqual(detail["status"], "scheduled")
        self.assertEqual(plan_rows[0].get("status"), "scheduled")
