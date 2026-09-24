"""Cluster peer scores are read for a page of clusters at once, unchanged.

`_cluster_latest_scores` answered one cluster per three queries, and a field
officer's Planning page asked it for fifteen clusters (2026-09-24 A+ audit:
45 of the page's 86 queries). `prime_recommendation_inputs` now reads every
cluster on the page together. These tests hold that the batched read gives
each cluster exactly what the one-cluster definition gave, and that the page's
cost no longer grows with the number of clusters.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.clusters.models import Cluster
from apps.core import request_cache
from apps.core.enums import SsaIntervention
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa import recommendation_engine as engine
from apps.ssa.models import SsaRecord, SsaScore

ALL = [c[0] for c in SsaIntervention.choices]


def _unbatched(cluster_id):
    """The one-cluster read as it stood before batching, frozen as the oracle."""
    school_ids = list(
        School.objects.filter(
            cluster_id=cluster_id, deleted_at__isnull=True
        ).values_list("id", flat=True)
    )
    if not school_ids:
        return {}
    latest_by_school: dict[str, str] = {}
    for row in (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        .order_by("school_id", "-date_of_ssa", "-created_at")
        .values("id", "school_id")
    ):
        latest_by_school.setdefault(row["school_id"], row["id"])
    school_by_record = {rid: sid for sid, rid in latest_by_school.items()}
    scores: dict[str, dict[str, float]] = {sid: {} for sid in latest_by_school}
    for row in SsaScore.objects.filter(
        ssa_record_id__in=list(latest_by_school.values())
    ).values("ssa_record_id", "intervention", "score"):
        if row["score"] is not None and row["intervention"] in ALL:
            scores[school_by_record[row["ssa_record_id"]]][row["intervention"]] = float(
                row["score"]
            )
    return scores


class ClusterLatestScoresBatchTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Batch Region")
        cls.district = District.objects.create(name="Batch District", region=cls.region)
        cls.clusters = [
            Cluster.objects.create(
                name=f"Batch Cluster {n}",
                region=cls.region,
                district=cls.district,
                status="active",
            )
            for n in range(4)
        ]
        cls.schools = []
        for c, cluster in enumerate(cls.clusters[:3]):
            for s in range(3):
                cls.schools.append(
                    School.objects.create(
                        school_id=f"BATCH-{c}-{s}",
                        name=f"Batch School {c}-{s}",
                        region=cls.region,
                        district=cls.district,
                        cluster_id=cluster.id,
                    )
                )
        # A deleted school's records never count toward its cluster.
        gone = School.objects.create(
            school_id="BATCH-GONE",
            name="Batch Gone",
            region=cls.region,
            district=cls.district,
            cluster_id=cls.clusters[0].id,
        )
        cls._record(gone, datetime(2026, 7, 1, tzinfo=dt_tz.utc), 1.0)
        School.objects.filter(pk=gone.pk).update(deleted_at=timezone.now())

        june = datetime(2026, 6, 1, tzinfo=dt_tz.utc)
        may = datetime(2026, 5, 1, tzinfo=dt_tz.utc)
        a, b, c = cls.schools[0], cls.schools[1], cls.schools[3]
        cls._record(a, may, 3.0)
        cls._record(a, june, 5.5, extra={"not_an_intervention": 2.0})
        # Same day twice: the later upload is the latest.
        cls._record(b, june, 4.0)
        cls._record(b, june, 7.25, missing=ALL[0])
        # A pending record and a deleted record are not scores.
        cls._record(c, june, 2.0, status="pending")
        deleted = cls._record(c, may, 8.0)
        SsaRecord.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())
        cls._record(cls.schools[4], may, 6.0, missing=ALL[1])
        cls._record(cls.schools[7], june, 9.0)
        # schools[2], [5], [6], [8] have no record; clusters[3] has no school.

    @staticmethod
    def _record(
        school,
        when,
        value,
        *,
        status="confirmed",
        extra=None,
        missing=None,
        none_for=None,
    ):
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=when,
            fy="2026",
            quarter="Q3",
            average_score=value,
            uploaded_by="u1",
            verification_status=status,
        )
        scores = {i: value for i in ALL if i != missing}
        scores.update(extra or {})
        for intervention, score in scores.items():
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=score,
            )
        return record

    def _ids(self):
        return [c.id for c in self.clusters]

    def test_batched_read_gives_each_cluster_its_own_answer(self):
        expected = {cid: _unbatched(cid) for cid in self._ids()}
        self.assertTrue(any(expected.values()), "fixture must carry scores")
        batched = engine._latest_scores_by_cluster([*self._ids(), None, self._ids()[0]])
        self.assertEqual(batched, expected)
        # Order is part of the answer: the peer statistics iterate these dicts.
        for cid in self._ids():
            self.assertEqual(list(batched[cid]), list(expected[cid]))
            self.assertEqual(engine._cluster_latest_scores(cid), expected[cid])

    def test_priming_fills_every_cluster_with_the_same_answer(self):
        with request_cache.scoped():
            engine.prime_recommendation_inputs(self.schools)
            with CaptureQueriesContext(connection) as ctx:
                primed = {
                    cid: engine._cluster_latest_scores(cid) for cid in self._ids()[:3]
                }
            self.assertEqual(len(ctx.captured_queries), 0)
        self.assertEqual(primed, {cid: _unbatched(cid) for cid in self._ids()[:3]})

    def test_priming_cost_does_not_grow_with_the_clusters(self):
        def cost(schools):
            with request_cache.scoped(), CaptureQueriesContext(connection) as ctx:
                engine.prime_recommendation_inputs(schools)
            return len(ctx.captured_queries)

        one_cluster = cost(self.schools[:3])
        three_clusters = cost(self.schools)
        self.assertEqual(three_clusters, one_cluster)

    def test_recommendations_are_unchanged_by_priming(self):
        unprimed = [engine.school_recommendation(s) for s in self.schools]
        with request_cache.scoped():
            engine.prime_recommendation_inputs(self.schools)
            primed = [engine.school_recommendation(s) for s in self.schools]
        self.assertEqual(primed, unprimed)
