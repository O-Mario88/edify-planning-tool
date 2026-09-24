"""The SSA workspace reads each record and score once per build.

A Country Director's page read the latest confirmed records five times (the
selection, the previous period, the seven-year trend and both years of the
improvement monitor) and their scores four times — ~1.1 million score rows at
50,000 schools, most of them the same rows again. `_SsaReads` reads every
year the build needs in one records query and each record's scores once;
these tests pin that, and that the export's lighter build yields exactly the
page's rows. Equivalence of the whole view model with the previous
implementation was checked on the realistic 50,000-school estate for eight
roles and seven filter sets (2026-09-24 audit).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.analytics.ssa_performance_service import build_dashboard
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SsaWorkspaceReadsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        previous = str(int(cls.fy) - 1)
        region = Region.objects.create(name="Reads Region")
        districts = [
            District.objects.create(name=f"Reads District {n}", region=region)
            for n in range(3)
        ]
        cls.director = User.objects.create(
            email="reads-cd@edify.test",
            name="Reads Director",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.director, title="CD", country="Uganda")
        now = timezone.now()
        for n in range(12):
            school = School.objects.create(
                school_id=f"READS-{n:02d}",
                name=f"Reads Primary {n:02d}",
                region=region,
                district=districts[n % 3],
            )
            # Two confirmed records this year (the later one counts), one
            # last year, and one this year that is not confirmed.
            for fy, days_ago, status, average in (
                (cls.fy, 30, "confirmed", 5.0 + n / 10),
                (cls.fy, 5, "confirmed", 6.0 + n / 10),
                (previous, 400, "confirmed", 4.0 + n / 10),
                (cls.fy, 1, "pending", 9.9),
            ):
                record = SsaRecord.objects.create(
                    school=school,
                    fy=fy,
                    quarter="Q1",
                    date_of_ssa=now - timedelta(days=days_ago),
                    # Every third school's latest record carries no average,
                    # so its scores are read to resolve one.
                    average_score=None if n % 3 == 0 and days_ago == 5 else average,
                    verification_status=status,
                )
                SsaScore.objects.bulk_create(
                    SsaScore(
                        ssa_record=record,
                        intervention=item.value,
                        score=average - (1.5 if i == n % 8 else 0),
                    )
                    for i, item in enumerate(SsaIntervention)
                )

    def _table_reads(self, queries, table):
        return [
            q["sql"]
            for q in queries
            if f'FROM "{table}"' in q["sql"] and q["sql"].lstrip().startswith("SELECT")
        ]

    def test_records_are_read_once_and_scores_once_per_record(self):
        with CaptureQueriesContext(connection) as ctx:
            dashboard = build_dashboard(self.director, {})
        self.assertEqual(dashboard["kpis"]["assessed"], 12)
        record_reads = self._table_reads(ctx.captured_queries, "ssa_record")
        score_reads = self._table_reads(ctx.captured_queries, "ssa_score")
        self.assertEqual(
            len(record_reads), 1, "every year's records come from one query"
        )
        # The selection's scores, then the trend's missing averages and the
        # remaining years: each record's scores are read once, never again.
        self.assertLessEqual(len(score_reads), 3, score_reads)

    def test_the_export_reads_only_the_selected_year_and_matches_the_page(self):
        for query in ({}, {"quarter": "Q1"}, {"fy": str(int(self.fy) - 1)}):
            page = build_dashboard(self.director, dict(query))
            with CaptureQueriesContext(connection) as ctx:
                export = build_dashboard(self.director, dict(query), export_only=True)
            self.assertEqual(export["export_rows"], page["export_rows"], query)
            self.assertEqual(export["scope"]["can_export"], page["scope"]["can_export"])
            for key in ("fy", "quarter", "is_full_year"):
                self.assertEqual(export["filters"][key], page["filters"][key])
            self.assertNotIn("trend", export)
            self.assertEqual(
                len(self._table_reads(ctx.captured_queries, "ssa_record")), 1
            )

    def test_a_record_with_no_average_is_resolved_from_its_scores(self):
        dashboard = build_dashboard(self.director, {})
        rows = {row["school_id"]: row for row in dashboard["export_rows"]}
        # School 00: latest record has no average; its scores are 6.0 with
        # one intervention 1.5 lower, so the mean is 6.0 - 1.5 / 8.
        self.assertEqual(rows["READS-00"]["average"], round(6.0 - 1.5 / 8, 2))
        self.assertEqual(rows["READS-00"]["lowest_score"], 4.5)
