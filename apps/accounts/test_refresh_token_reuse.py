"""SEC-03 — refresh-token family/lineage tracking + reuse detection.

Every token minted from one login shares a family_id. A refresh token is
single-use; presenting an already-consumed (or already-revoked) token again
is treated as reuse — the family is revoked and the user must authenticate
again. See apps.accounts.auth_services.refresh / apps.accounts.jwt.
"""

from __future__ import annotations

import threading

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts import auth_services
from apps.accounts.models import RefreshToken, User
from apps.core.exceptions import Unauthorized
from apps.core.rbac import EdifyRole
from apps.core.security import hash_token


def _user(email="reuse@edify.test", password="CorrectPassword1!"):
    return User.objects.create_user(
        email=email,
        name="Reuse Target",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        password=password,
        is_active=True,
        status="active",
    )


class RefreshTokenFamilyTest(APITestCase):
    def test_login_starts_a_family_and_refresh_rotates_within_it(self):
        user = _user()
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        first = RefreshToken.objects.get(token_hash=hash_token(tokens["refreshToken"]))
        family_id = first.family_id
        self.assertTrue(family_id)

        rotated = auth_services.refresh(tokens["refreshToken"])
        second = RefreshToken.objects.exclude(id=first.id).get(user=user)
        self.assertEqual(second.family_id, family_id)
        self.assertEqual(second.parent_id, first.id)
        self.assertNotEqual(rotated["refreshToken"], tokens["refreshToken"])

        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNotNone(first.consumed_at)

    def test_refresh_token_is_single_use(self):
        user = _user()
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        auth_services.refresh(tokens["refreshToken"])  # consumes it
        with self.assertRaises(Unauthorized):
            auth_services.refresh(tokens["refreshToken"])  # reuse

    def test_reuse_revokes_the_entire_family(self):
        user = _user()
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        rotated_once = auth_services.refresh(tokens["refreshToken"])
        rotated_twice = auth_services.refresh(rotated_once["refreshToken"])

        # Replay the FIRST (already-consumed) token — reuse detected.
        with self.assertRaises(Unauthorized):
            auth_services.refresh(tokens["refreshToken"])

        # The most recent, otherwise-still-live descendant must now be dead too.
        with self.assertRaises(Unauthorized):
            auth_services.refresh(rotated_twice["refreshToken"])

    def test_reuse_is_audited(self):
        from apps.audit.models import AuditLog

        user = _user()
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        auth_services.refresh(tokens["refreshToken"])
        with self.assertRaises(Unauthorized):
            auth_services.refresh(tokens["refreshToken"])

        self.assertTrue(
            AuditLog.objects.filter(
                action="auth.refresh_token_reuse_detected", subject_id=user.id
            ).exists()
        )

    def test_raw_refresh_token_is_never_stored(self):
        user = _user()
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        raw = tokens["refreshToken"]
        for record in RefreshToken.objects.filter(user=user):
            self.assertNotEqual(record.token_hash, raw)
            self.assertNotIn(raw, record.token_hash)

    def test_independent_logins_get_independent_families(self):
        user = _user()
        first_login = auth_services.login(user.email, "CorrectPassword1!")
        second_login = auth_services.login(user.email, "CorrectPassword1!")
        families = set(
            RefreshToken.objects.filter(user=user).values_list("family_id", flat=True)
        )
        self.assertEqual(len(families), 2)
        # Reusing a consumed token from family A must not touch family B.
        auth_services.refresh(first_login["refreshToken"])
        with self.assertRaises(Unauthorized):
            auth_services.refresh(first_login["refreshToken"])
        # The second login's still-fresh (never-rotated) token remains valid.
        auth_services.refresh(second_login["refreshToken"])

    def test_disabling_user_revokes_live_refresh_tokens(self):
        user = _user("disable-me@edify.test")
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        user.status = "disabled"
        user.is_active = False
        user.save(update_fields=["status", "is_active"])
        RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        with self.assertRaises(Unauthorized):
            auth_services.refresh(tokens["refreshToken"])


class RefreshTokenConcurrencyTest(TransactionTestCase):
    """Two simultaneous refresh attempts against the SAME raw token must
    never both succeed — real threads, real DB row locking."""

    def test_concurrent_refresh_of_same_token_yields_exactly_one_winner(self):
        user = User.objects.create_user(
            email="concurrent-refresh@edify.test",
            name="Concurrent Refresh",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="CorrectPassword1!",
            is_active=True,
            status="active",
        )
        tokens = auth_services.login(user.email, "CorrectPassword1!")
        raw = tokens["refreshToken"]

        results = [None, None]
        barrier = threading.Barrier(2)

        def attempt(idx):
            try:
                barrier.wait(timeout=10)
                results[idx] = (True, auth_services.refresh(raw))
            except Exception as exc:  # noqa: BLE001
                results[idx] = (False, exc)

        t1 = threading.Thread(target=attempt, args=(0,))
        t2 = threading.Thread(target=attempt, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        winners = [r for ok, r in results if ok]
        self.assertEqual(len(winners), 1, f"expected exactly one winner: {results}")

        # The winner's own freshly-issued child must also be dead — reuse
        # detection revokes the whole family, including tokens issued after
        # the replayed one (never two valid descendants).
        winner_refresh = winners[0]["refreshToken"]
        with self.assertRaises(Unauthorized):
            auth_services.refresh(winner_refresh)
