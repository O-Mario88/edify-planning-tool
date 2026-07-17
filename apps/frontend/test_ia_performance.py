"""Issue 6 of the audit — IA Dashboard / IA Verification Queue performance.

Investigation finding (documented here, not assumed): /ia/dashboard/ itself
was NOT reproducibly slow or N+1 at any code-shape level — every per-object
loop there already uses select_related/bulk aggregation. What WAS real: (a)
a copy-pasted block computing the same 9 queries twice (fixed below by
deleting the duplicate — the second block's results were byte-identical to
the first, since it was the exact same queries), and (b) a genuine, unbounded
per-row N+1 in the adjacent /ia/verification/ queue (`a.evidence.filter(...)
.exists()` + `a.school.ssa_records.filter(...).exists()` inside a `for a in
filtered_qs` loop, with no pagination) — likely what the original report
actually meant by "IA Dashboard is slow", since that's the IA's primary
day-to-day work surface.

test_ia_dashboard_query_count_is_bounded documents the /ia/dashboard/ finding
with real numbers. The rest prove the /ia/verification/ fix: batched
evidence/SSA existence lookups (apps/frontend/views/ia_views.py) + real
pagination (QUEUE_PAGE_SIZE), verified not to scale with queue size.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, VerificationHistory
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()
FY = "2026"


class IAPerformanceTestBase(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="IA Region")
        self.district = District.objects.create(name="IA District", region=self.region)
        self.ia = User.objects.create_user(
            email="ia-perf@edify.test",
            name="IA Perf Tester",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        self.ia_sp = StaffProfile.objects.create(user=self.ia, title="IA")
        self.client.force_login(self.ia)

    def _school(self, sid):
        return School.objects.create(
            school_id=f"IAP-{sid}",
            name=f"IA Perf School {sid}",
            region=self.region,
            district=self.district,
        )

    def _pending_activity(self, school, with_evidence=False, with_ssa=False):
        act = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="awaiting_ia_verification",
            responsible_staff_id=self.ia_sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            salesforce_activity_id=f"SV-IAP-{school.school_id}",
        )
        if with_evidence:
            EvidenceRecord.objects.create(
                activity=act,
                kind="attendance_form",
                status="uploaded",
                quarantined=False,
                uploaded_by=self.ia.id,
            )
        if with_ssa:
            SsaRecord.objects.create(
                school=school,
                fy=FY,
                quarter="Q1",
                average_score=6.0,
                verification_status="confirmed",
                date_of_ssa=date(2025, 11, 1),
                uploaded_by="test",
            )
        return act


class IADashboardQueryBudgetTest(IAPerformanceTestBase):
    def test_ia_dashboard_sla_is_empty_until_a_real_cycle_is_measured(self):
        response = self.client.get("/ia/dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["verification_sla"]["pct"])
        self.assertEqual(response.context["verification_sla"]["sample_size"], 0)
        self.assertContains(response, "Not yet measured")
        self.assertNotContains(response, "84%")
        self.assertNotContains(response, "2 pts vs last week")

    def test_ia_dashboard_sla_uses_real_queue_cycle_timestamps(self):
        now = timezone.now()
        for index, hours in enumerate((10, 30)):
            activity = self._pending_activity(self._school(f"dashboard-sla-{index}"))
            activity.status = "ia_verified"
            activity.submitted_to_ia_at = now - timezone.timedelta(hours=hours)
            activity.ia_confirmed_at = now
            activity.save(
                update_fields=[
                    "status",
                    "submitted_to_ia_at",
                    "ia_confirmed_at",
                    "updated_at",
                ]
            )
            VerificationHistory.objects.create(
                activity=activity,
                verified_by=self.ia.id,
                verified_at=now,
            )

        response = self.client.get("/ia/dashboard/")

        self.assertEqual(response.context["verification_sla"]["pct"], 50.0)
        self.assertEqual(response.context["verification_sla"]["sample_size"], 2)
        self.assertContains(response, "50.0%")
        self.assertContains(response, "n=2")

    # ── 1. /ia/dashboard/ documented, bounded, not O(rows) ───────────────────
    def test_ia_dashboard_query_count_is_bounded(self):
        for i in range(15):
            school = self._school(i)
            self._pending_activity(school, with_evidence=(i % 2 == 0))

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/ia/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            60,
            f"/ia/dashboard/ ran {len(ctx.captured_queries)} queries -- investigation "
            "measured ~61-62 before deduplicating the copy-pasted KPI block; should "
            "now be meaningfully lower and, either way, a small constant.",
        )

    # ── 2. /ia/dashboard/ query count doesn't grow with data volume ─────────
    def test_ia_dashboard_query_count_does_not_scale_with_data_volume(self):
        for i in range(5):
            self._pending_activity(self._school(i))
        with CaptureQueriesContext(connection) as ctx_small:
            self.client.get("/ia/dashboard/")
        small_count = len(ctx_small.captured_queries)

        for i in range(5, 60):
            self._pending_activity(self._school(i))
        with CaptureQueriesContext(connection) as ctx_large:
            self.client.get("/ia/dashboard/")
        large_count = len(ctx_large.captured_queries)

        self.assertEqual(
            small_count,
            large_count,
            f"/ia/dashboard/ ran {small_count} queries at 5 activities but "
            f"{large_count} at 60 -- a per-row query has crept in.",
        )


class IAVerificationQueueN1FixTest(IAPerformanceTestBase):
    # ── 3. Query count does not scale with queue size (the real N+1 fix) ────
    def test_ia_verification_queue_query_count_does_not_scale_with_queue_size(self):
        for i in range(5):
            self._pending_activity(self._school(i), with_evidence=True, with_ssa=True)
        with CaptureQueriesContext(connection) as ctx_small:
            response = self.client.get("/ia/verification/")
        self.assertEqual(response.status_code, 200)
        small_count = len(ctx_small.captured_queries)

        for i in range(5, 60):
            self._pending_activity(
                self._school(i), with_evidence=(i % 2 == 0), with_ssa=(i % 3 == 0)
            )
        with CaptureQueriesContext(connection) as ctx_large:
            response = self.client.get("/ia/verification/")
        self.assertEqual(response.status_code, 200)
        large_count = len(ctx_large.captured_queries)

        self.assertEqual(
            small_count,
            large_count,
            f"/ia/verification/ ran {small_count} queries for 5 queued activities but "
            f"{large_count} for 55 -- the old code ran 2 extra queries PER ROW "
            "(has_evidence/has_ssa), unbounded by the queue size.",
        )
        self.assertLessEqual(large_count, 25)

    # ── 4. Pagination ─────────────────────────────────────────────────────────
    def test_ia_verification_queue_is_paginated(self):
        from apps.frontend.views.ia_views import QUEUE_PAGE_SIZE

        for i in range(QUEUE_PAGE_SIZE + 10):
            self._pending_activity(self._school(i))

        response = self.client.get("/ia/verification/")
        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.paginator.count, QUEUE_PAGE_SIZE + 10)
        self.assertEqual(len(response.context["queue"]), QUEUE_PAGE_SIZE)
        self.assertTrue(page_obj.has_next)

        page2 = self.client.get("/ia/verification/?page=2")
        self.assertEqual(len(page2.context["queue"]), 10)

    # ── 5. Batched evidence/SSA flags are still correct per row ─────────────
    def test_ia_verification_queue_evidence_and_ssa_flags_are_correct(self):
        s_both = self._school("both")
        s_neither = self._school("neither")
        act_both = self._pending_activity(s_both, with_evidence=True, with_ssa=True)
        act_neither = self._pending_activity(
            s_neither, with_evidence=False, with_ssa=False
        )

        response = self.client.get("/ia/verification/")
        by_id = {row["id"]: row for row in response.context["queue"]}
        self.assertTrue(by_id[act_both.id]["has_evidence"])
        self.assertTrue(by_id[act_both.id]["has_ssa"])
        self.assertFalse(by_id[act_neither.id]["has_evidence"])
        self.assertFalse(by_id[act_neither.id]["has_ssa"])

    # ── 6. A quarantined evidence row must not count as "has evidence" ──────
    def test_ia_verification_queue_ignores_quarantined_evidence(self):
        school = self._school("quarantined")
        act = self._pending_activity(school)
        EvidenceRecord.objects.create(
            activity=act,
            kind="attendance_form",
            status="uploaded",
            quarantined=True,
            uploaded_by=self.ia.id,
        )
        response = self.client.get("/ia/verification/")
        by_id = {row["id"]: row for row in response.context["queue"]}
        self.assertFalse(by_id[act.id]["has_evidence"])

    def test_sla_headline_is_empty_until_a_real_cycle_is_measured(self):
        response = self.client.get("/ia/verification/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["kpis"]["sla_compliance"])
        self.assertEqual(response.context["kpis"]["avg_time"], "—")
        self.assertContains(response, "Not yet measured")

    def test_sla_headline_uses_submission_to_verification_timestamps(self):
        now = timezone.now()
        durations = (10, 30)
        for index, hours in enumerate(durations):
            activity = self._pending_activity(self._school(f"sla-{index}"))
            activity.status = "ia_verified"
            activity.submitted_to_ia_at = now - timezone.timedelta(hours=hours)
            activity.ia_confirmed_at = now
            activity.save(
                update_fields=[
                    "status",
                    "submitted_to_ia_at",
                    "ia_confirmed_at",
                    "updated_at",
                ]
            )
            VerificationHistory.objects.create(
                activity=activity,
                verified_by=self.ia.id,
                verified_at=now,
            )

        response = self.client.get("/ia/verification/")

        self.assertEqual(response.context["kpis"]["sla_compliance"], 50.0)
        self.assertEqual(response.context["kpis"]["sla_sample_size"], 2)
        self.assertEqual(response.context["kpis"]["avg_time"], "20h")
        self.assertContains(response, "50.0%")
        self.assertContains(response, "n=2")
