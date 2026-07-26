"""The approval-shaped races the hardening gates did not yet cover.

test_hardening_gates.py already races the money paths — disbursement, partner
payment, SF ID reservation, closure, reopen, the scheduler lock. What it never
raced is the approvals that FEED those paths: two approvers on one fund
request, two IA staffers certifying one activity, and two ledger rebuilds for
one person.

The shape of every test here is the same: two real threads, two separate
connections, both loading the row the way two request handlers would — which
means the guard each handler runs sees its own stale copy. A status check
before `transaction.atomic()` is a comment, not a guard; only a re-check under
the lock decides anything.

Required duplicates, per the brief: 0. And for certification specifically,
`ia_confirmed_by` must be the person who actually won — a second certify that
overwrites the verifier's identity corrupts the audit trail even when the
status transition itself is idempotent.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, role):
    return User.objects.create_user(
        email=email,
        password="password123",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )


class RaceTestCase(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        self.fy = get_operational_fy()
        region = Region.objects.create(name="Race Region")
        district = District.objects.create(name="Race District", region=region)
        self.school = School.objects.create(
            school_id="RACE-1",
            name="Race P/S",
            region=region,
            district=district,
        )

    def _race(self, first, second):
        """Run two callables at the same instant on their own connections."""
        results = [None, None]
        barrier = threading.Barrier(2)

        def runner(idx, fn):
            try:
                barrier.wait(timeout=10)
                results[idx] = (True, fn())
            except Exception as exc:  # noqa: BLE001
                results[idx] = (False, exc)
            finally:
                for conn in connections.all():
                    conn.close()

        threads = [
            threading.Thread(target=runner, args=(0, first)),
            threading.Thread(target=runner, args=(1, second)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        # A thread still alive here is holding a database connection — and
        # possibly row locks — that the teardown flush will then deadlock
        # against, taking the rest of the suite down with it. Fail loudly now
        # rather than mysteriously three files later.
        alive = [t.name for t in threads if t.is_alive()]
        if alive:
            raise AssertionError(f"race threads never finished: {alive}")
        return results

    def tearDown(self):
        """No backend but ours may be inside a transaction when the flush runs.

        The teardown flush TRUNCATEs every table under AccessExclusive locks.
        Any other backend still holding so much as a row lock deadlocks it —
        and a deadlocked teardown does not stay local: it aborts mid-flush,
        skips the class's clock cleanup, and the cumulative run then fails in
        files that have nothing to do with this one. Twice, before this
        existed, with nothing in either failure pointing here.

        So the flush gets a clean room. Anything else found mid-transaction is
        terminated and NAMED, with the query it was stuck on — turning the
        next occurrence from thirty minutes of forensics into one line.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, state, COALESCE(query, '')
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state LIKE '%transaction%'
                """
            )
            stragglers = cursor.fetchall()
            for pid, _state, _query in stragglers:
                cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
        super().tearDown()
        if stragglers:
            detail = "; ".join(
                f"pid={pid} state={state} query={query[:120]!r}"
                for pid, state, query in stragglers
            )
            raise AssertionError(
                f"a race left {len(stragglers)} backend(s) mid-transaction at "
                f"teardown — the flush would have deadlocked on them: {detail}"
            )

    def _awaiting_activity(self):
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="awaiting_ia_verification",
            ia_verification_status="pending",
            fy=self.fy,
            quarter="Q1",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
        )


class ConcurrentCertificationTest(RaceTestCase):
    """Two IA staffers, one queue, one activity."""

    CHECKLIST = {
        "evidence_exists": True,
        "attendance_valid": True,
        "ssa_uploaded": True,
        "correct_school": True,
        "correct_cluster": True,
        "correct_intervention": True,
        "sf_id_entered": True,
        "duplicate_check_passed": True,
        "analytics_ready": True,
    }

    def test_exactly_one_certification_wins(self):
        from apps.activities.ia_services import ActivityCertificationService

        activity = self._awaiting_activity()
        ia_one = _user("ia-one@edify.test", EdifyRole.IMPACT_ASSESSMENT.value)
        ia_two = _user("ia-two@edify.test", EdifyRole.IMPACT_ASSESSMENT.value)
        activity_id, checklist = activity.id, self.CHECKLIST

        def certify_as(actor_id):
            def run():
                # Each handler loads its OWN copy, as two requests would.
                instance = Activity.objects.get(id=activity_id)
                ActivityCertificationService.certify_activity(
                    instance, checklist, actor_id
                )
                return actor_id

            return run

        results = self._race(certify_as(ia_one.id), certify_as(ia_two.id))
        winners = [r for ok, r in results if ok]
        self.assertEqual(
            len(winners),
            1,
            "both IA staffers were told their certification succeeded — the "
            f"status guard runs before the lock, so it guards nothing: {results}",
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(
            activity.ia_confirmed_by,
            winners[0],
            "the recorded verifier is not the person whose certification won — "
            "the loser's write overwrote the audit identity",
        )

    def test_exactly_one_return_wins(self):
        from apps.activities.ia_services import ActivityReturnService

        activity = self._awaiting_activity()
        activity_id = activity.id

        def return_it(actor):
            def run():
                instance = Activity.objects.get(id=activity_id)
                ActivityReturnService.return_activity(
                    instance, ["evidence_missing"], "insufficient", actor
                )
                return actor

            return run

        results = self._race(return_it("ia-a"), return_it("ia-b"))
        winners = [r for ok, r in results if ok]
        self.assertEqual(len(winners), 1, f"both returns succeeded: {results}")

    def test_certify_and_return_cannot_both_win(self):
        """The nastiest interleaving: one certifies while the other returns.
        Whichever loses must be refused — an activity that is simultaneously
        verified and returned is two contradictory instructions to the CCEO."""
        from apps.activities.ia_services import (
            ActivityCertificationService,
            ActivityReturnService,
        )

        activity = self._awaiting_activity()
        ia = _user("ia-three@edify.test", EdifyRole.IMPACT_ASSESSMENT.value)
        activity_id, checklist = activity.id, self.CHECKLIST

        def certify():
            instance = Activity.objects.get(id=activity_id)
            ActivityCertificationService.certify_activity(instance, checklist, ia.id)
            return "certified"

        def send_back():
            instance = Activity.objects.get(id=activity_id)
            ActivityReturnService.return_activity(
                instance, ["evidence_missing"], "no", ia.id
            )
            return "returned"

        results = self._race(certify, send_back)
        winners = [r for ok, r in results if ok]
        self.assertEqual(
            len(winners), 1, f"certify and return both succeeded: {results}"
        )
        activity.refresh_from_db()
        expected = "ia_verified" if winners[0] == "certified" else "returned_by_ia"
        self.assertEqual(activity.status, expected)


class ConcurrentWeeklyApprovalTest(RaceTestCase):
    """Two approvers act on the same weekly fund request at the same moment."""

    def test_the_second_approver_is_refused(self):
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.fund_requests.weekly_service import approve_weekly_request

        cd_one = _user("race-cd1@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        cd_two = _user("race-cd2@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        owner = _user("race-owner@edify.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value)

        week_start = timezone.now().date()
        wfr = WeeklyFundRequest.objects.create(
            responsible_user=owner.id,
            responsible_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            fy=self.fy,
            status="submitted_to_cd",
            total_amount=0,
        )
        request_id = str(wfr.id)

        results = self._race(
            lambda: approve_weekly_request(request_id, cd_one),
            lambda: approve_weekly_request(request_id, cd_two),
        )
        winners = [r for ok, r in results if ok]
        losers = [r for ok, r in results if not ok]
        self.assertEqual(
            len(winners),
            1,
            "both Country Directors were told their approval went through — "
            f"downstream sync and notifications both fired twice: {results}",
        )
        self.assertIn("not awaiting approval", str(losers[0]))

        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")


class ConcurrentLedgerRebuildTest(RaceTestCase):
    """Two page loads rebuild the same person's target ledger at once.

    This happens constantly in normal use — a CCEO opens My Targets while
    their PL opens Team Targets — so it is not an edge case, it is Tuesday.
    The ledger's UniqueConstraint plus bulk_create(ignore_conflicts=True) is
    the claimed protection; this is the claim being cashed.
    """

    def test_no_duplicate_credit_rows(self):
        from apps.targets.models import TargetAchievementLedger
        from apps.targets.my_targets import TargetAchievementService

        cceo = _user("race-cceo@edify.test", EdifyRole.CCEO.value)
        # A completed, credit-bearing activity for them.
        Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="ia_verified",
            fy=self.fy,
            quarter="Q1",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
            responsible_staff_id=cceo.id,
        )

        fy = self.fy
        results = self._race(
            lambda: TargetAchievementService.rebuild(User.objects.get(id=cceo.id), fy),
            lambda: TargetAchievementService.rebuild(User.objects.get(id=cceo.id), fy),
        )
        failures = [r for ok, r in results if not ok]
        self.assertEqual(failures, [], f"a rebuild crashed: {failures}")

        rows = TargetAchievementLedger.objects.filter(user_id=cceo.id, fy=fy)
        seen = {}
        for row in rows:
            key = (row.source_type, row.source_id)
            seen.setdefault(key, 0)
            seen[key] += 1
        duplicates = {k: n for k, n in seen.items() if n > 1}
        self.assertEqual(
            duplicates,
            {},
            f"the same source earned credit more than once: {duplicates}",
        )
