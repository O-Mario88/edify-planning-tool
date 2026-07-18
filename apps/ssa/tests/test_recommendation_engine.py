"""Unit tests for the analytics-backed SSA recommendation engine.

Covers the guarantees the engine exists to provide: verified-only input,
min-N honesty (components drop out rather than fabricate), deterministic
ordering, and the analytics signals (severity anchor, trend, peer gap,
persistence) each changing the ranking in the intended direction.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.test import TestCase

from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.recommendation_engine import (
    prioritized_interventions,
    school_recommendation,
)

ALL = [c[0] for c in SsaIntervention.choices]


class RecommendationEngineTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Rec Region")
        self.district = District.objects.create(name="Rec District", region=self.region)
        self.school = School.objects.create(
            school_id="REC-1",
            name="Rec Primary",
            region=self.region,
            district=self.district,
        )

    def _record(self, when, scores, *, status="confirmed", school=None):
        """scores: dict intervention -> value; missing interventions omitted."""
        school = school or self.school
        avg = round(sum(scores.values()) / len(scores), 1) if scores else None
        rec = SsaRecord.objects.create(
            school=school,
            date_of_ssa=when,
            fy="2026",
            quarter="Q3",
            average_score=avg,
            uploaded_by="u1",
            verification_status=status,
        )
        for interv, val in scores.items():
            SsaScore.objects.create(ssa_record=rec, intervention=interv, score=val)
        return rec

    def _all(self, **overrides):
        base = {c: 6.0 for c in ALL}
        base.update(overrides)
        return base

    # ── Empty / honesty ──────────────────────────────────────────────────
    def test_no_confirmed_ssa_yields_empty_ranking_never_fabricated(self):
        self.assertEqual(prioritized_interventions(self.school), [])
        rec = school_recommendation(self.school)
        self.assertFalse(rec["hasSsa"])
        self.assertEqual(rec["weakest"], [])
        self.assertEqual(rec["prioritized"], [])

    def test_unverified_ssa_is_ignored(self):
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=1.0),
            status="pending",
        )
        # A pending record must not drive any ranking.
        self.assertEqual(prioritized_interventions(self.school), [])

    # ── Single record → reduces to ascending score + alpha tiebreak ──────
    def test_single_record_reduces_to_ascending_score_ordering(self):
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=2.0, financial_health=3.0, enrolment=9.0),
        )
        ranked = prioritized_interventions(self.school)
        self.assertEqual(ranked[0]["intervention"], "leadership")  # lowest score
        self.assertEqual(ranked[1]["intervention"], "financial_health")
        self.assertEqual(ranked[-1]["intervention"], "enrolment")  # highest score
        # Only severity is measurable with one record.
        self.assertTrue(ranked[0]["components"]["severity"]["measurable"])
        self.assertFalse(ranked[0]["components"]["trend"]["measurable"])
        self.assertFalse(ranked[0]["components"]["persistence"]["measurable"])

    def test_tied_scores_break_alphabetically_deterministically(self):
        # leadership and financial_health both 3.0 → alphabetical: financial_health first.
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=3.0, financial_health=3.0),
        )
        ranked = prioritized_interventions(self.school)
        idx = {r["intervention"]: i for i, r in enumerate(ranked)}
        self.assertLess(idx["financial_health"], idx["leadership"])
        # Stable across repeated calls.
        again = prioritized_interventions(self.school)
        self.assertEqual(
            [r["intervention"] for r in ranked], [r["intervention"] for r in again]
        )

    # ── Trend ────────────────────────────────────────────────────────────
    def test_declining_intervention_outranks_stable_one_at_same_current_score(self):
        # leadership: 6 -> 4 -> 2 (declining). financial_health: flat 2.0.
        # Both end at 2.0, but leadership is on a downward trajectory.
        self._record(
            datetime(2026, 1, 1, tzinfo=dt_tz.utc),
            self._all(leadership=6.0, financial_health=2.0),
        )
        self._record(
            datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            self._all(leadership=4.0, financial_health=2.0),
        )
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=2.0, financial_health=2.0),
        )
        ranked = prioritized_interventions(self.school)
        idx = {r["intervention"]: i for i, r in enumerate(ranked)}
        self.assertLess(idx["leadership"], idx["financial_health"])
        lead = next(r for r in ranked if r["intervention"] == "leadership")
        self.assertTrue(lead["components"]["trend"]["measurable"])
        self.assertEqual(lead["components"]["trend"]["direction"], "declining")

    def test_improving_intervention_deprioritized_vs_stagnant_same_score(self):
        # leadership improving 2->4->6, financial_health stuck at 6.
        self._record(
            datetime(2026, 1, 1, tzinfo=dt_tz.utc),
            self._all(leadership=2.0, financial_health=6.0),
        )
        self._record(
            datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            self._all(leadership=4.0, financial_health=6.0),
        )
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=6.0, financial_health=6.0),
        )
        ranked = prioritized_interventions(self.school)
        idx = {r["intervention"]: i for i, r in enumerate(ranked)}
        # Both currently 6.0, but leadership is on the mend → ranks lower (less urgent).
        self.assertLess(idx["financial_health"], idx["leadership"])

    # ── Persistence ──────────────────────────────────────────────────────
    def test_persistence_signal_reflects_chronic_weakness(self):
        for m in (1, 3, 6):
            self._record(
                datetime(2026, m, 1, tzinfo=dt_tz.utc), self._all(leadership=3.0)
            )
        ranked = prioritized_interventions(self.school)
        lead = next(r for r in ranked if r["intervention"] == "leadership")
        pers = lead["components"]["persistence"]
        self.assertTrue(pers["measurable"])
        self.assertEqual(pers["below_count"], 3)
        self.assertEqual(pers["considered"], 3)

    # ── Peer gap ─────────────────────────────────────────────────────────
    def test_peer_gap_flags_a_school_far_below_its_cluster(self):
        cluster = Cluster.objects.create(
            name="Peer Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        # School.save() recomputes cluster membership from geography, so a
        # cluster_id passed to create() gets nulled (a known codebase gotcha).
        # Set the canonical pointer directly via .update(), matching how the
        # engine reads School.cluster_id.
        School.objects.filter(id=self.school.id).update(cluster_id=cluster.id)
        self.school.refresh_from_db()
        # Five peers strong on leadership with realistic spread (a real z-score
        # needs non-zero peer variance); target school weak (3.0), far below.
        peer_scores = [7.0, 8.0, 8.5, 9.0, 7.5]
        for i, ps in enumerate(peer_scores):
            peer = School.objects.create(
                school_id=f"PEER-{i}",
                name=f"Peer {i}",
                region=self.region,
                district=self.district,
            )
            School.objects.filter(id=peer.id).update(cluster_id=cluster.id)
            self._record(
                datetime(2026, 6, 1, tzinfo=dt_tz.utc),
                self._all(leadership=ps),
                school=peer,
            )
        self._record(datetime(2026, 6, 1, tzinfo=dt_tz.utc), self._all(leadership=3.0))
        ranked = prioritized_interventions(self.school)
        lead = next(r for r in ranked if r["intervention"] == "leadership")
        gap = lead["components"]["peer_gap"]
        self.assertTrue(gap["measurable"])
        self.assertLess(gap["z_score"], 0)  # below peers
        self.assertGreaterEqual(gap["peer_count"], 4)

    def test_peer_gap_not_measurable_when_unclustered(self):
        self._record(datetime(2026, 6, 1, tzinfo=dt_tz.utc), self._all(leadership=3.0))
        ranked = prioritized_interventions(self.school)
        lead = next(r for r in ranked if r["intervention"] == "leadership")
        self.assertFalse(lead["components"]["peer_gap"]["measurable"])

    # ── Recommendation wrapper ───────────────────────────────────────────
    def test_school_recommendation_uses_canonical_band_and_top_n(self):
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=2.0, financial_health=3.0),
        )
        rec = school_recommendation(self.school, n=2)
        self.assertTrue(rec["hasSsa"])
        self.assertEqual(len(rec["weakest"]), 2)
        self.assertEqual(rec["weakest"][0]["intervention"], "leadership")
        # average = (2+3+6*6)/8 = 5.125 → Warning band from canonical ssa_score_band.
        self.assertEqual(rec["severity"], "Warning")
        self.assertTrue(rec["engine"]["confirmed_only"])
        self.assertEqual(rec["engine"]["record_count"], 1)

    def test_priority_is_bounded_0_100(self):
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=0.0, enrolment=10.0),
        )
        ranked = prioritized_interventions(self.school)
        for r in ranked:
            self.assertGreaterEqual(r["priority"], 0.0)
            self.assertLessEqual(r["priority"], 100.0)

    def test_realistic_multi_year_scenario_prioritises_chronic_decline(self):
        """End-to-end: a chronically-declining intervention should out-rank a
        flat-low one at a HIGHER current score, and a fast-improving low one
        should rank below both — the whole point of the analytics upgrade over
        'two lowest scores on the newest assessment'."""
        # leadership: 6 -> 4 -> 2 (declining, ends 2.0)
        # financial_health: flat 3.0 (weak but stable, better current score)
        # enrolment: 2 -> 4 -> 6 (improving, ends 6.0)
        self._record(
            datetime(2025, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=6.0, financial_health=3.0, enrolment=2.0),
        )
        self._record(
            datetime(2025, 12, 1, tzinfo=dt_tz.utc),
            self._all(leadership=4.0, financial_health=3.0, enrolment=4.0),
        )
        self._record(
            datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            self._all(leadership=2.0, financial_health=3.0, enrolment=6.0),
        )
        ranked = prioritized_interventions(self.school)
        idx = {r["intervention"]: i for i, r in enumerate(ranked)}
        # Declining leadership (2.0) is the top priority.
        self.assertEqual(ranked[0]["intervention"], "leadership")
        # Flat-low financial_health (3.0) outranks improving enrolment (6.0)…
        self.assertLess(idx["financial_health"], idx["enrolment"])
        # …and a naive "lowest two scores" rule would have picked leadership +
        # financial_health, never surfacing the trend signal — confirm the
        # engine's leadership priority reflects its declining trend.
        self.assertEqual(ranked[0]["components"]["trend"]["direction"], "declining")
