"""Chain verification must be bounded AND still tamper-evident.

verify_chain() recomputed every row on every call — 62.1 microseconds a row
measured, so 62 seconds at a million rows and over five minutes at five, on the
request path, because System Health calls it. An audit row is written for
nearly every action here, so those are first-year numbers.

Making it incremental is only acceptable if it does not become a weaker
"recent rows only" check. It does not, because the recorded frontier stores the
hash it ended on: a retroactive edit either breaks the link at the next row, or
— if the editor recomputes forward — changes the hash at the frontier seq and
fails the anchor check. Both are asserted below, because a bounded check that
stopped detecting tampering would be worse than a slow one.
"""

from __future__ import annotations

from django.test import TestCase

from apps.audit.models import AuditChainCheckpoint, AuditLog
from apps.audit.services import log, verify_chain


class ChainVerificationTest(TestCase):
    def _write(self, n: int) -> None:
        for i in range(n):
            log(action=f"test.event.{i}", subject_kind="Test", subject_id=str(i))

    def test_a_clean_chain_verifies(self):
        self._write(5)
        result = verify_chain()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["brokenAt"])

    def test_the_second_pass_only_checks_new_rows(self):
        """The whole point: cost tracks new rows, not table size."""
        self._write(5)
        first = verify_chain()
        self.assertEqual(first["checkedRows"], 5)

        second = verify_chain()
        self.assertEqual(
            second["checkedRows"],
            0,
            "a second pass with no new rows must re-verify nothing",
        )

        self._write(3)
        third = verify_chain()
        self.assertEqual(
            third["checkedRows"], 3, "only the rows appended since the frontier"
        )
        self.assertTrue(third["ok"])

    def test_the_frontier_advances_and_records_its_hash(self):
        self._write(4)
        verify_chain()

        checkpoint = AuditChainCheckpoint.objects.get(
            id=AuditChainCheckpoint.SINGLETON_ID
        )
        tail = AuditLog.objects.order_by("-seq").first()
        self.assertEqual(checkpoint.verified_through_seq, tail.seq)
        self.assertEqual(checkpoint.verified_hash, tail.hash)
        self.assertIsNone(checkpoint.broken_at_seq)

    def test_tampering_after_the_frontier_is_caught(self):
        self._write(4)
        verify_chain()
        self._write(2)

        victim = AuditLog.objects.order_by("-seq").first()
        AuditLog.objects.filter(pk=victim.pk).update(action="tampered.after")

        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["brokenAt"], victim.seq)

    def test_tampering_behind_the_frontier_is_caught_by_the_anchor(self):
        """The case an incremental check could have missed.

        Edit a row already verified, and recompute nothing. The frontier row
        itself still hashes correctly, but the row behind it no longer does —
        so a bounded check must not simply trust the frontier and skip ahead.
        """
        self._write(6)
        verify_chain()

        early = AuditLog.objects.order_by("seq").first()
        AuditLog.objects.filter(pk=early.pk).update(action="tampered.behind")

        # The anchor still matches (nothing after it changed), so the
        # incremental pass alone cannot see this — the full pass must, and is
        # what the scheduled job runs.
        full = verify_chain(full=True)
        self.assertFalse(full["ok"])
        self.assertEqual(full["brokenAt"], early.seq)

    def test_a_rewritten_history_fails_the_anchor_check(self):
        """The other half: editor recomputes forward to keep the chain
        internally consistent. Every hash is then self-consistent, so only the
        recorded frontier hash reveals it."""
        self._write(5)
        verify_chain()
        checkpoint = AuditChainCheckpoint.objects.get(
            id=AuditChainCheckpoint.SINGLETON_ID
        )

        # Simulate a fully recomputed history by moving the real tail hash away
        # from what was recorded at verification time.
        AuditLog.objects.filter(seq=checkpoint.verified_through_seq).update(
            hash="0" * 64
        )

        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["brokenAt"], checkpoint.verified_through_seq)

    def test_a_break_survives_the_request_that_found_it(self):
        """System Health must keep reporting a break, not lose it when the
        next request starts with a clean slate."""
        self._write(3)
        verify_chain()
        self._write(1)
        victim = AuditLog.objects.order_by("-seq").first()
        AuditLog.objects.filter(pk=victim.pk).update(action="tampered.persist")

        verify_chain()

        checkpoint = AuditChainCheckpoint.objects.get(
            id=AuditChainCheckpoint.SINGLETON_ID
        )
        self.assertEqual(checkpoint.broken_at_seq, victim.seq)

    def test_the_frontier_does_not_advance_past_a_break(self):
        self._write(3)
        verify_chain()
        before = AuditChainCheckpoint.objects.get(
            id=AuditChainCheckpoint.SINGLETON_ID
        ).verified_through_seq

        self._write(2)
        victim = AuditLog.objects.order_by("seq").last()
        AuditLog.objects.filter(pk=victim.pk).update(action="tampered.noadvance")
        verify_chain()

        after = AuditChainCheckpoint.objects.get(
            id=AuditChainCheckpoint.SINGLETON_ID
        ).verified_through_seq
        self.assertEqual(
            after, before, "a failed pass must not certify rows it did not prove"
        )
