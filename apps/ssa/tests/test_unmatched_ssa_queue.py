"""Issue 5 of the audit — /ssa/unmatched pagination, filters, and the
narrowed-candidate fuzzy-match rewrite.

Before this fix: the view loaded EVERY pending/hold UnmatchedSSARecord with
no pagination, then looped over all of them running one
`School.objects.filter(name__icontains=...).first()` query per record — an
unbounded full-table ILIKE scan per unmatched row, on every page load. It
also silently discarded the "School Name"/"District" columns from the
upload file, so that loop never actually fired on real data.

Now: suggested_school/match_confidence are computed ONCE at upload time
(apps.ssa.unmatched_service.compute_suggested_match, called from
apps.ssa.upload_service.import_ssa_batch), narrowed by district first, then
ranked by pg_trgm trigram similarity. The queue view is real pagination +
filters (status/upload batch/district/suspected School ID/confidence/
uploaded date) reading the pre-computed columns — zero extra queries per
row at view time.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.geography.models import District, Region
from apps.schools.models import SSAImportBatch, School, UnmatchedSSARecord
from apps.ssa import unmatched_service
from apps.ssa.upload_service import import_ssa_batch

User = get_user_model()


class UnmatchedSSAQueueTestBase(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.d1 = District.objects.create(name="Kampala", region=self.region)
        self.d2 = District.objects.create(name="Wakiso", region=self.region)

        self.ia = User.objects.create_user(
            email="ia@edify.test",
            name="IA Tester",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        self.client.force_login(self.ia)

        self.sch_1 = School.objects.create(
            school_id="S-1",
            name="Kampala Hill Primary School",
            region=self.region,
            district=self.d1,
        )
        self.sch_2 = School.objects.create(
            school_id="S-2",
            name="Wakiso Valley Primary School",
            region=self.region,
            district=self.d2,
        )

    def _unmatched(
        self,
        school_id,
        name_raw=None,
        district_raw=None,
        status="pending",
        batch=None,
        suggested=None,
        confidence=None,
        days_ago=0,
    ):
        rec = UnmatchedSSARecord.objects.create(
            batch=batch,
            school_id=school_id,
            school_name_raw=name_raw,
            district_raw=district_raw,
            date_of_ssa="2026-07-01",
            scores={"leadership": 6.0},
            reason="not in directory",
            status=status,
            suggested_school=suggested,
            match_confidence=confidence,
        )
        if days_ago:
            UnmatchedSSARecord.objects.filter(id=rec.id).update(
                created_at=timezone.now() - timedelta(days=days_ago),
            )
        return rec


class UnmatchedSSAQueueFilterTest(UnmatchedSSAQueueTestBase):
    # ── 1. Pagination ────────────────────────────────────────────────────────
    def test_unmatched_queue_is_paginated(self):
        for i in range(30):
            self._unmatched(f"NR-{i}")
        page1 = unmatched_service.get_unmatched_queue(page=1, page_size=10)
        self.assertEqual(len(page1.object_list), 10)
        self.assertEqual(page1.paginator.num_pages, 3)
        self.assertEqual(page1.paginator.count, 30)
        page3 = unmatched_service.get_unmatched_queue(page=3, page_size=10)
        self.assertEqual(len(page3.object_list), 10)

        response = self.client.get("/ssa/unmatched?page=2")
        self.assertEqual(response.status_code, 200)

    # ── 2. Filter by status ──────────────────────────────────────────────────
    def test_unmatched_queue_filters_by_status(self):
        self._unmatched("NR-1", status="pending")
        self._unmatched("NR-2", status="hold")
        self._unmatched("NR-3", status="ignored")

        default_page = unmatched_service.get_unmatched_queue()
        self.assertEqual(
            {r.school_id for r in default_page.object_list}, {"NR-1", "NR-2"}
        )

        hold_page = unmatched_service.get_unmatched_queue(filters={"status": "hold"})
        self.assertEqual({r.school_id for r in hold_page.object_list}, {"NR-2"})

        ignored_page = unmatched_service.get_unmatched_queue(
            filters={"status": "ignored"}
        )
        self.assertEqual({r.school_id for r in ignored_page.object_list}, {"NR-3"})

    # ── 3. Filter by upload batch ────────────────────────────────────────────
    def test_unmatched_queue_filters_by_upload_batch(self):
        batch_a = SSAImportBatch.objects.create(
            file_name="a.xlsx", uploaded_by="u1", status="imported"
        )
        batch_b = SSAImportBatch.objects.create(
            file_name="b.xlsx", uploaded_by="u1", status="imported"
        )
        self._unmatched("NR-A", batch=batch_a)
        self._unmatched("NR-B", batch=batch_b)

        page = unmatched_service.get_unmatched_queue(filters={"batch": batch_a.id})
        self.assertEqual({r.school_id for r in page.object_list}, {"NR-A"})

        options = dict(unmatched_service.batch_options())
        self.assertEqual(options, {batch_a.id: "a.xlsx", batch_b.id: "b.xlsx"})

    # ── 4. Filter by district ────────────────────────────────────────────────
    def test_unmatched_queue_filters_by_district(self):
        self._unmatched("NR-KLA", district_raw="Kampala Metro")
        self._unmatched("NR-WKS", district_raw="Wakiso District")

        page = unmatched_service.get_unmatched_queue(filters={"district": "kampala"})
        self.assertEqual({r.school_id for r in page.object_list}, {"NR-KLA"})

    # ── 5. Filter by suspected School ID ─────────────────────────────────────
    def test_unmatched_queue_filters_by_suspected_school_id(self):
        self._unmatched("SCH-1001")
        self._unmatched("SCH-2002")

        page = unmatched_service.get_unmatched_queue(filters={"school_id": "1001"})
        self.assertEqual({r.school_id for r in page.object_list}, {"SCH-1001"})

    # ── 6. Filter by minimum confidence ──────────────────────────────────────
    def test_unmatched_queue_filters_by_min_confidence(self):
        self._unmatched("NR-HIGH", suggested=self.sch_1, confidence=0.9)
        self._unmatched("NR-LOW", suggested=self.sch_2, confidence=0.3)
        self._unmatched("NR-NONE")  # no suggestion at all -- NULL confidence

        page = unmatched_service.get_unmatched_queue(filters={"min_confidence": "0.5"})
        self.assertEqual({r.school_id for r in page.object_list}, {"NR-HIGH"})

    # ── 7. Filter by uploaded date range ─────────────────────────────────────
    def test_unmatched_queue_filters_by_uploaded_date_range(self):
        self._unmatched("NR-OLD", days_ago=40)
        self._unmatched("NR-RECENT", days_ago=1)

        cutoff = (timezone.now() - timedelta(days=10)).date().isoformat()
        page = unmatched_service.get_unmatched_queue(filters={"date_from": cutoff})
        self.assertEqual({r.school_id for r in page.object_list}, {"NR-RECENT"})

        page2 = unmatched_service.get_unmatched_queue(filters={"date_to": cutoff})
        self.assertEqual({r.school_id for r in page2.object_list}, {"NR-OLD"})


class SuggestedMatchTest(UnmatchedSSAQueueTestBase):
    # ── 8. Narrows candidates by district first ──────────────────────────────
    def test_suggested_match_narrows_candidates_by_district(self):
        # A same-named school in the OTHER district must not be suggested
        # once a district hint narrows the candidate pool.
        School.objects.create(
            school_id="S-3",
            name="Kampala Hill Primary School",
            region=self.region,
            district=self.d2,
        )
        school_id, confidence = unmatched_service.compute_suggested_match(
            "Kampala Hill Primary Schol",
            "Wakiso",
        )
        self.assertIsNotNone(school_id)
        matched = School.objects.get(id=school_id)
        self.assertEqual(matched.district_id, self.d2.id)

    # ── 9. Trigram similarity ranks a real fuzzy match ───────────────────────
    def test_suggested_match_uses_trigram_similarity(self):
        school_id, confidence = unmatched_service.compute_suggested_match(
            "Kampala Hil Primary Schol",
            None,  # two typos, no district hint
        )
        self.assertEqual(school_id, self.sch_1.id)
        self.assertGreater(confidence, 0.5)

    def test_suggested_match_returns_none_below_threshold(self):
        school_id, confidence = unmatched_service.compute_suggested_match(
            "Totally Unrelated Institution Name",
            None,
        )
        self.assertIsNone(school_id)
        self.assertIsNone(confidence)

    def test_suggested_match_returns_none_for_empty_name(self):
        school_id, confidence = unmatched_service.compute_suggested_match("", None)
        self.assertEqual((school_id, confidence), (None, None))

    # ── 10. Computed once at upload time, not view time ──────────────────────
    def test_suggested_match_computed_once_at_upload_not_view_time(self):
        batch = SSAImportBatch.objects.create(
            file_name="up.xlsx", uploaded_by=self.ia.id, status="staged"
        )
        row = batch.rows.create(
            row_number=1,
            school_id="NR-UPLOAD",
            scores={
                "leadership": 6.0,
                "_school_name_raw": "Kampala Hil Primary Schol",
            },
            status="ready",
        )
        import_ssa_batch(batch, self.ia)

        rec = UnmatchedSSARecord.objects.get(school_id="NR-UPLOAD")
        self.assertEqual(rec.suggested_school_id, self.sch_1.id)
        self.assertIsNotNone(rec.match_confidence)
        self.assertEqual(rec.batch_id, batch.id)

        # Viewing the queue must NOT re-run the match — it just reads the
        # stored columns (select_related, zero extra per-row queries).
        with CaptureQueriesContext(connection) as ctx:
            page = unmatched_service.get_unmatched_queue()
            for r in page.object_list:
                _ = r.suggested_school  # forces access; must be pre-fetched
        self.assertLessEqual(len(ctx.captured_queries), 3)

    # ── 11. View-level query count is bounded regardless of row count ────────
    def test_unmatched_queue_view_query_count_is_bounded(self):
        for i in range(40):
            self._unmatched(
                f"NR-{i}",
                name_raw="Kampala Hil Primary Schol",
                suggested=self.sch_1,
                confidence=0.7,
            )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/ssa/unmatched")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            20,
            f"/ssa/unmatched ran {len(ctx.captured_queries)} queries for 40 unmatched rows -- "
            "should be a small constant, not O(rows) (the old per-row icontains loop).",
        )

    # ── 12. Legacy backfill command ──────────────────────────────────────────
    def test_recompute_management_command_backfills_legacy_records(self):
        from io import StringIO

        from django.core.management import call_command

        legacy = self._unmatched("NR-LEGACY", name_raw="Kampala Hil Primary Schol")
        self.assertIsNone(legacy.match_confidence)

        out = StringIO()
        call_command("recompute_unmatched_ssa_suggestions", stdout=out)
        legacy.refresh_from_db()
        self.assertEqual(legacy.suggested_school_id, self.sch_1.id)
        self.assertIsNotNone(legacy.match_confidence)

        # Idempotent — a second run with no --force finds nothing left to do.
        out2 = StringIO()
        call_command("recompute_unmatched_ssa_suggestions", stdout=out2)
        self.assertIn("Nothing to recompute", out2.getvalue())

    # ── 13. System Health check reflects real state ──────────────────────────
    def test_health_check_reflects_queue_state(self):
        from apps.ssa.health import unmatched_ssa_health

        clean = unmatched_ssa_health()
        size_check = next(
            c for c in clean["checks"] if c["key"] == "unmatched_queue_size"
        )
        self.assertEqual(size_check["severity"], "ok")

        self._unmatched("NR-STALE", days_ago=45)
        dirty = unmatched_ssa_health()
        stale_check = next(
            c for c in dirty["checks"] if c["key"] == "unmatched_stale_records"
        )
        self.assertEqual(stale_check["severity"], "warning")


class UnmatchedSSAQueueScopeTest(UnmatchedSSAQueueTestBase):
    def test_unmatched_queue_scope_narrowing_combines_filters(self):
        """Filters must AND together, not silently override each other."""
        self._unmatched("NR-A", district_raw="Kampala", status="hold")
        self._unmatched("NR-B", district_raw="Kampala", status="pending")
        self._unmatched("NR-C", district_raw="Wakiso", status="hold")

        page = unmatched_service.get_unmatched_queue(
            filters={"district": "kampala", "status": "hold"},
        )
        self.assertEqual({r.school_id for r in page.object_list}, {"NR-A"})


class UnmatchedSSAQueuePerformanceTest(TransactionTestCase):
    """10k schools / 5k unmatched-record scale — proves the fix is O(1)
    queries at write time (bulk) and read time (bounded by page size), not
    O(schools) or O(unmatched records).

    Deliberately NOT using serialized_rollback=True — see
    DisbursementDoubleClickRaceTest / ConcurrentLockoutTest for why: Django
    would insert the ORIGINAL serialized snapshot's rows on top of what
    _post_teardown's reseed_migration_data() already restored, causing a
    duplicate-key IntegrityError. reseed_migration_data() alone is the
    single source of truth for leaving the kept database in a good state."""

    def _post_teardown(self):
        super()._post_teardown()
        from apps.core.test_seed_utils import reseed_migration_data

        reseed_migration_data()

    def test_unmatched_queue_performance_at_scale(self):
        region = Region.objects.create(name="Perf Region")
        districts = [
            District.objects.create(name=f"District {i}", region=region)
            for i in range(20)
        ]

        School.objects.bulk_create(
            [
                School(
                    school_id=f"PS-{i}",
                    name=f"Performance School {i}",
                    region=region,
                    district=districts[i % len(districts)],
                )
                for i in range(10_000)
            ],
            batch_size=1000,
        )

        UnmatchedSSARecord.objects.bulk_create(
            [
                UnmatchedSSARecord(
                    school_id=f"UNMATCHED-{i}",
                    school_name_raw=f"Performance Schol {i}",  # typo, real trigram candidate
                    district_raw=f"District {i % len(districts)}",
                    date_of_ssa="2026-07-01",
                    scores={"leadership": 6.0},
                    reason="not in directory",
                    status="pending",
                )
                for i in range(5_000)
            ],
            batch_size=1000,
        )

        # Read path: paginated, must stay fast and bounded regardless of the
        # 5,000-row backlog.
        with CaptureQueriesContext(connection) as ctx:
            page = unmatched_service.get_unmatched_queue(page=1, page_size=25)
            rows = list(page.object_list)
        self.assertEqual(len(rows), 25)
        self.assertEqual(page.paginator.count, 5000)
        self.assertLessEqual(len(ctx.captured_queries), 5)

        # Write-path candidate matching: must narrow by district BEFORE
        # ranking, never scan all 10,000 schools per suggestion.
        with CaptureQueriesContext(connection) as ctx2:
            school_id, confidence = unmatched_service.compute_suggested_match(
                "Performance Schol 42",
                "District 2",
            )
        self.assertIsNotNone(school_id)
        self.assertLessEqual(len(ctx2.captured_queries), 5)
