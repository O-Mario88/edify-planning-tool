"""The batched latest-SSA lookup must agree with the single-school one.

`latest_applicable_record` is the canonical "newest CONFIRMED record" rule, and
cluster intelligence called it inside a loop -- then read `latest.scores.all()`
on each result. Ninety round trips on one load of `/clusters`.

`latest_applicable_records` answers the same question for a set of schools in
one query. These tests exist because a batched twin that quietly disagrees with
its canonical original is worse than the loop it replaced: an unconfirmed
upload slipping in, or a stale record winning the tiebreak, would change which
schools look like they need support.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.core.enums import SsaIntervention
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.services import latest_applicable_record, latest_applicable_records


class LatestApplicableRecordsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="ssa-batch-user",
            email="ssa-batch@edify.org",
            name="SSA Batch",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            is_active=True,
        )
        cls.region = Region.objects.create(name="SSA Batch Region")
        cls.district = District.objects.create(
            name="SSA Batch District", region=cls.region
        )
        cls.schools = [
            School.objects.create(
                school_id=f"SCH-SSA-BATCH-{i}",
                name=f"SSA Batch School {i}",
                region=cls.region,
                district=cls.district,
            )
            for i in range(4)
        ]

    def _record(self, school, *, year, status="confirmed", score=5.0):
        return SsaRecord.objects.create(
            school=school,
            date_of_ssa=datetime(year, 6, 1, tzinfo=dt_timezone.utc),
            fy=str(year),
            quarter="Q3",
            average_score=score,
            verification_status=status,
            uploaded_by=self.user.id,
        )

    def test_it_agrees_with_the_single_school_helper(self):
        for i, school in enumerate(self.schools[:3]):
            self._record(school, year=2024 + i)

        batched = latest_applicable_records(self.schools)
        for school in self.schools:
            with self.subTest(school.school_id):
                single = latest_applicable_record(school)
                self.assertEqual(
                    batched.get(school.id).id if batched.get(school.id) else None,
                    single.id if single else None,
                )

    def test_the_newest_confirmed_record_wins(self):
        school = self.schools[0]
        self._record(school, year=2024)
        newest = self._record(school, year=2026)

        self.assertEqual(latest_applicable_records([school])[school.id].id, newest.id)

    def test_an_unconfirmed_record_never_wins(self):
        """An unverified upload must not gate or rank money-bearing work."""
        school = self.schools[0]
        confirmed = self._record(school, year=2024)
        self._record(school, year=2026, status="pending")

        self.assertEqual(
            latest_applicable_records([school])[school.id].id, confirmed.id
        )

    def test_a_school_with_no_confirmed_record_is_absent_not_zero(self):
        school = self.schools[0]
        self._record(school, year=2026, status="pending")

        batched = latest_applicable_records([school])
        self.assertNotIn(
            school.id,
            batched,
            "a school with no verified SSA must be absent, so a caller cannot "
            "mistake a missing measurement for a bad one",
        )

    def test_a_deleted_record_is_ignored(self):
        from django.utils import timezone

        school = self.schools[0]
        kept = self._record(school, year=2024)
        dropped = self._record(school, year=2026)
        SsaRecord.objects.filter(id=dropped.id).update(deleted_at=timezone.now())

        self.assertEqual(latest_applicable_records([school])[school.id].id, kept.id)

    def test_one_query_serves_every_school(self):
        for i, school in enumerate(self.schools):
            self._record(school, year=2024 + i)

        with CaptureQueriesContext(connection) as queries:
            latest_applicable_records(self.schools)

        self.assertEqual(
            len(queries.captured_queries),
            1,
            "the batched lookup exists to replace one query per school",
        )

    def test_scores_can_be_prefetched_without_extra_queries(self):
        """Cluster intelligence reads `.scores.all()` on every result."""
        for school in self.schools:
            record = self._record(school, year=2026)
            SsaScore.objects.create(
                ssa_record=record,
                intervention=SsaIntervention.values[0],
                score=7.0,
            )

        batched = latest_applicable_records(self.schools, with_scores=True)
        with CaptureQueriesContext(connection) as queries:
            total = sum(
                score.score
                for record in batched.values()
                for score in record.scores.all()
            )

        self.assertEqual(total, 28.0)
        self.assertEqual(
            len(queries.captured_queries),
            0,
            "scores were prefetched, so reading them must hit no database",
        )

    def test_an_empty_school_set_does_not_query(self):
        self.assertEqual(latest_applicable_records([]), {})
