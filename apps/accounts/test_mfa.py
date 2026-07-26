"""The second factor has to be a factor.

A code prompt that can be walked around is worse than no code prompt, because
it is read as protection. So these tests are written from the attacker's side
wherever they can be: not "does the happy path work" but "with a stolen
password and a browser, what can be reached".

The one that matters most is StolenPasswordTest — everything else is detail if
a correct password alone still opens the product.
"""

from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts import mfa_service
from apps.accounts.models import MfaChallenge
from apps.core.rbac import EdifyRole
from apps.core.sms import SmsService

PASSWORD = "correct-horse-battery-1"


def _user(email="mfa@edify.test", *, enabled=True, channel="email", phone=None):
    user = get_user_model().objects.create_user(
        email=email,
        password=PASSWORD,
        name="MFA Tester",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        is_active=True,
    )
    user.mfa_enabled = enabled
    user.mfa_channel = channel
    user.phone = phone
    user.save(update_fields=["mfa_enabled", "mfa_channel", "phone"])
    return user


class Captured:
    """The code as the person would receive it, read back out of whatever the
    provider was handed. Tests must not reach into the hash."""

    def __init__(self):
        self.messages = []

    @property
    def code(self) -> str:
        found = re.findall(r"\b(\d{6})\b", "\n".join(self.messages))
        return found[-1] if found else ""


def capture_codes():
    """Patch both senders and collect the bodies."""
    captured = Captured()

    def take_mail(msg):
        captured.messages.append(msg.text)
        return {"delivered": True}

    def take_sms(msg):
        captured.messages.append(msg.text)
        return {"delivered": True}

    return captured, (
        mock.patch("apps.accounts.mfa_service.mailer.send", side_effect=take_mail),
        mock.patch("apps.accounts.mfa_service.sms.send", side_effect=take_sms),
    )


def _form_error(response) -> str:
    """The message the login page actually shows."""
    match = re.search(
        r'data-form-status-message[^>]*>(.*?)</span>',
        response.content.decode(),
        re.S,
    )
    return (match.group(1) if match else "").strip()


class MfaTestCase(TestCase):
    def setUp(self):
        self.captured, patches = capture_codes()
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def sign_in(self, client, user, password=PASSWORD):
        return client.post(
            "/login", {"email": user.email, "password": password}, follow=False
        )


class StolenPasswordTest(MfaTestCase):
    """The whole point: a correct password, and nothing else, reaches nothing."""

    def setUp(self):
        super().setUp()
        self.user = _user()
        self.client = Client()

    def test_the_password_alone_does_not_sign_anyone_in(self):
        self.sign_in(self.client, self.user)
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
            "a correct password created a logged-in session and the second "
            "factor is decorative",
        )

    def test_the_password_alone_reaches_no_page(self):
        self.sign_in(self.client, self.user)
        for url in ("/dashboard", "/settings", "/my-plan"):
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertIn(
                    "/login",
                    response.redirect_chain[-1][0] if response.redirect_chain else "",
                    f"{url} was served to someone who only had the password",
                )

    def test_the_password_sends_the_browser_to_the_code_prompt(self):
        response = self.sign_in(self.client, self.user)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/verify")

    def test_the_code_finishes_the_job(self):
        self.sign_in(self.client, self.user)
        response = self.client.post("/login/verify", {"code": self.captured.code})
        self.assertEqual(response["Location"], "/dashboard")
        self.assertIn("_auth_user_id", self.client.session)

    def test_a_wrong_password_never_sends_a_code(self):
        self.sign_in(self.client, self.user, password="not-the-password")
        self.assertEqual(self.captured.messages, [])
        self.assertEqual(MfaChallenge.objects.count(), 0)


class CodePromptIsNotAnOpenDoorTest(MfaTestCase):
    """Reaching /login/verify without having passed the password check."""

    def setUp(self):
        super().setUp()
        self.user = _user("stranger@edify.test")

    def test_a_stranger_cannot_open_the_prompt(self):
        response = Client().get("/login/verify", follow=True)
        self.assertIn("/login", response.redirect_chain[-1][0])

    def test_a_stranger_cannot_post_a_code_to_it(self):
        """Even with the right code — which is the case that matters, because
        a code sent to a phone can be read off a lock screen."""
        mfa_service.start_challenge(self.user)
        stranger = Client()
        stranger.post("/login/verify", {"code": self.captured.code}, follow=True)
        self.assertNotIn("_auth_user_id", stranger.session)

    def test_a_challenge_cannot_be_answered_on_behalf_of_another_user(self):
        """The challenge id and the user id come out of the same session, and
        the pairing is what stops one being swapped for the other."""
        victim = _user("victim@edify.test")
        challenge, _ = mfa_service.start_challenge(victim)

        attacker = _user("attacker@edify.test")
        client = Client()
        self.sign_in(client, attacker)
        session = client.session
        session["mfa_pending_challenge_id"] = str(challenge.id)
        session.save()

        client.post("/login/verify", {"code": self.captured.code})
        self.assertNotIn("_auth_user_id", client.session)


class GuessingTest(MfaTestCase):
    def setUp(self):
        super().setUp()
        self.user = _user("guess@edify.test")
        self.client = Client()
        self.sign_in(self.client, self.user)

    def test_a_wrong_code_does_not_sign_anyone_in(self):
        self.client.post("/login/verify", {"code": "000000"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_guessing_runs_out(self):
        wrong = "111111" if self.captured.code != "111111" else "222222"
        for _ in range(mfa_service.MAX_ATTEMPTS):
            self.client.post("/login/verify", {"code": wrong})

        # Even the real code no longer works — the challenge is dead, not
        # merely rate-limited.
        self.client.post("/login/verify", {"code": self.captured.code})
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
            "the correct code still worked after the attempt limit",
        )

    def test_an_empty_code_is_not_a_match(self):
        """A blank submission must not compare equal to anything."""
        challenge = MfaChallenge.objects.get(user=self.user)
        self.assertFalse(mfa_service.verify(challenge, "").ok)


class SingleUseTest(MfaTestCase):
    def setUp(self):
        super().setUp()
        self.user = _user("reuse@edify.test")

    def test_a_code_cannot_be_used_twice(self):
        first = Client()
        self.sign_in(first, self.user)
        code = self.captured.code
        first.post("/login/verify", {"code": code})
        self.assertIn("_auth_user_id", first.session)

        # Someone who read the code off a lock screen tries it afterwards.
        second = Client()
        self.sign_in(second, self.user)
        second.post("/login/verify", {"code": code})
        self.assertNotIn("_auth_user_id", second.session)

    def test_starting_again_kills_the_previous_code(self):
        client = Client()
        self.sign_in(client, self.user)
        stale = self.captured.code

        self.sign_in(Client(), self.user)
        self.assertNotEqual(stale, self.captured.code)

        client.post("/login/verify", {"code": stale})
        self.assertNotIn("_auth_user_id", client.session)


class ExpiryTest(MfaTestCase):
    def setUp(self):
        super().setUp()
        self.user = _user("expiry@edify.test")

    def test_a_stale_code_is_refused(self):
        client = Client()
        self.sign_in(client, self.user)
        MfaChallenge.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        client.post("/login/verify", {"code": self.captured.code})
        self.assertNotIn("_auth_user_id", client.session)

    def test_the_waiting_room_itself_expires(self):
        """The attempt is bounded even while the challenge row is still live,
        so an abandoned half-login does not sit open for whoever walks up to
        the browser next."""
        client = Client()
        self.sign_in(client, self.user)
        session = client.session
        session["mfa_pending_started_at"] = (
            timezone.now() - timedelta(hours=1)
        ).isoformat()
        session.save()

        response = client.post(
            "/login/verify", {"code": self.captured.code}, follow=True
        )
        self.assertIn("/login", response.redirect_chain[-1][0])
        self.assertNotIn("_auth_user_id", client.session)


class SessionFixationTest(MfaTestCase):
    """The session key must not survive from before the password check to
    after the sign-in — otherwise a planted cookie becomes a live session."""

    def test_the_key_changes_across_the_whole_flow(self):
        user = _user("fixation@edify.test")
        client = Client()
        client.get("/login")
        planted = client.session.session_key

        self.sign_in(client, user)
        waiting = client.session.session_key

        client.post("/login/verify", {"code": self.captured.code})
        signed_in = client.session.session_key

        self.assertIn("_auth_user_id", client.session)
        self.assertNotEqual(planted, waiting)
        self.assertNotEqual(waiting, signed_in)


class ResendTest(MfaTestCase):
    def setUp(self):
        super().setUp()
        self.user = _user("resend@edify.test")
        self.client = Client()
        self.sign_in(self.client, self.user)

    def _age_last_send(self):
        MfaChallenge.objects.filter(user=self.user).update(
            last_sent_at=timezone.now() - mfa_service.RESEND_INTERVAL * 2
        )

    def test_a_resend_delivers_a_new_code_and_retires_the_old_one(self):
        old = self.captured.code
        self._age_last_send()
        self.client.post("/login/resend-code")
        self.assertNotEqual(old, self.captured.code)

        self.client.post("/login/verify", {"code": old})
        self.assertNotIn("_auth_user_id", self.client.session)

        self.client.post("/login/verify", {"code": self.captured.code})
        self.assertIn("_auth_user_id", self.client.session)

    def test_resending_immediately_sends_nothing(self):
        before = len(self.captured.messages)
        self.client.post("/login/resend-code")
        self.assertEqual(
            len(self.captured.messages),
            before,
            "the form can be held down to pump messages at a phone number",
        )

    def test_there_is_a_ceiling_on_messages_per_attempt(self):
        for _ in range(mfa_service.MAX_DELIVERIES + 3):
            self._age_last_send()
            self.client.post("/login/resend-code")
        self.assertLessEqual(
            len(self.captured.messages),
            mfa_service.MAX_DELIVERIES,
            "one sign-in attempt sent more messages than its ceiling allows",
        )

    def test_resending_does_not_extend_the_deadline(self):
        challenge = MfaChallenge.objects.get(user=self.user)
        deadline = challenge.expires_at
        self._age_last_send()
        self.client.post("/login/resend-code")
        challenge.refresh_from_db()
        self.assertEqual(
            challenge.expires_at,
            deadline,
            "a challenge could be held open forever by resending",
        )

    def test_a_stranger_cannot_make_us_send_messages(self):
        before = len(self.captured.messages)
        Client().post("/login/resend-code")
        self.assertEqual(len(self.captured.messages), before)


class StorageTest(MfaTestCase):
    def test_the_raw_code_is_never_stored(self):
        user = _user("storage@edify.test")
        challenge, _ = mfa_service.start_challenge(user)
        code = self.captured.code

        self.assertTrue(code)
        self.assertNotIn(code, challenge.code_hash)
        row = MfaChallenge.objects.filter(id=challenge.id).values().first()
        for field, value in row.items():
            self.assertNotIn(
                code,
                str(value),
                f"the code is recoverable from MfaChallenge.{field}",
            )

    def test_the_hint_is_a_hint_and_not_the_address(self):
        user = _user("storage2@edify.test", channel="email")
        challenge, _ = mfa_service.start_challenge(user)
        self.assertNotEqual(challenge.destination_hint, user.email)
        self.assertIn("•", challenge.destination_hint)


class ChannelTest(MfaTestCase):
    def test_email_is_always_available(self):
        self.assertIn("email", mfa_service.available_channels(_user("c1@edify.test")))

    def test_sms_needs_both_a_number_and_a_provider(self):
        no_number = _user("c2@edify.test", channel="sms")
        with mock.patch.object(SmsService, "is_configured", True):
            self.assertNotIn("sms", mfa_service.available_channels(no_number))

        with_number = _user("c3@edify.test", channel="sms", phone="+256700123456")
        with mock.patch.object(SmsService, "is_configured", False):
            self.assertNotIn("sms", mfa_service.available_channels(with_number))
        with mock.patch.object(SmsService, "is_configured", True):
            self.assertIn("sms", mfa_service.available_channels(with_number))

    def test_an_unreachable_channel_falls_back_rather_than_stranding_anyone(self):
        """Someone enrolled on SMS whose number was later removed must still be
        able to sign in."""
        user = _user("c4@edify.test", channel="sms", phone=None)
        self.assertEqual(mfa_service.resolve_channel(user), "email")

        client = Client()
        self.sign_in(client, user)
        client.post("/login/verify", {"code": self.captured.code})
        self.assertIn("_auth_user_id", client.session)

    def test_a_code_goes_by_text_when_that_is_the_choice(self):
        user = _user("c5@edify.test", channel="sms", phone="+256700123456")
        with mock.patch.object(SmsService, "is_configured", True):
            challenge, delivery = mfa_service.start_challenge(user)
        self.assertEqual(challenge.channel, "sms")
        self.assertTrue(delivery.ok)
        self.assertIn(self.captured.code, self.captured.messages[-1])


class WhoIsAskedTest(MfaTestCase):
    def test_someone_not_enrolled_signs_in_as_before(self):
        user = _user("plain@edify.test", enabled=False)
        client = Client()
        response = self.sign_in(client, user)
        self.assertEqual(response["Location"], "/dashboard")
        self.assertIn("_auth_user_id", client.session)
        self.assertEqual(self.captured.messages, [])

    @override_settings(MFA_REQUIRED_FOR_ALL=True)
    def test_the_org_wide_switch_covers_accounts_that_never_enrolled(self):
        user = _user("policy@edify.test", enabled=False)
        client = Client()
        response = self.sign_in(client, user)
        self.assertEqual(response["Location"], "/login/verify")
        self.assertNotIn("_auth_user_id", client.session)


class EnrolmentTest(MfaTestCase):
    def setUp(self):
        super().setUp()
        self.user = _user("enrol@edify.test", enabled=False)
        self.client = Client()
        self.client.force_login(self.user)

    def test_a_person_can_turn_it_on_for_themselves(self):
        self.client.post(
            "/settings/two-step", {"mfa_enabled": "on", "mfa_channel": "email"}
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)

    def test_and_off_again(self):
        self.user.mfa_enabled = True
        self.user.save(update_fields=["mfa_enabled"])
        self.client.post("/settings/two-step", {})
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)

    def test_nobody_can_enrol_onto_a_channel_that_cannot_deliver(self):
        """Choosing SMS with no number would be a lockout wearing the costume
        of a security control."""
        self.client.post(
            "/settings/two-step", {"mfa_enabled": "on", "mfa_channel": "sms"}
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.mfa_channel, "email")

    @override_settings(MFA_REQUIRED_FOR_ALL=True)
    def test_it_cannot_be_switched_off_when_the_organisation_requires_it(self):
        self.user.mfa_enabled = True
        self.user.save(update_fields=["mfa_enabled"])
        self.client.post("/settings/two-step", {})
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)

    def test_a_stranger_cannot_change_anyone_s_enrolment(self):
        self.user.mfa_enabled = True
        self.user.save(update_fields=["mfa_enabled"])
        Client().post("/settings/two-step", {})
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)

    def test_the_settings_page_shows_the_state(self):
        body = self.client.get("/settings").content.decode()
        self.assertIn("Two-step verification", body)
        self.assertIn("enrol@edify.test"[0], body)


class CodeQualityTest(TestCase):
    def test_codes_are_the_advertised_length(self):
        for _ in range(50):
            self.assertEqual(len(mfa_service._generate_code()), mfa_service.CODE_DIGITS)

    def test_codes_are_not_predictable(self):
        """Not a randomness test — a smoke alarm for someone swapping
        `secrets` for `random` seeded from the clock, or for a constant."""
        codes = {mfa_service._generate_code() for _ in range(200)}
        self.assertGreater(len(codes), 150)


class ForcedPasswordChangeTest(MfaTestCase):
    def test_the_code_still_comes_first(self):
        """Someone with a temporary password set by an administrator must not
        skip the factor on their way to the change-password screen."""
        user = _user("temp@edify.test")
        user.must_change_password = True
        user.save(update_fields=["must_change_password"])

        client = Client()
        response = self.sign_in(client, user)
        self.assertEqual(response["Location"], "/login/verify")

        response = client.post("/login/verify", {"code": self.captured.code})
        self.assertEqual(response["Location"], "/change-password")
        self.assertIn("_auth_user_id", client.session)


class TokenApiTest(MfaTestCase):
    """The token API issues a full credential, so the factor holds there too.

    Enforcing it only on the web sign-in would have left a stolen password
    worth exactly what it was worth before: the code prompt would be a door
    beside an open window.
    """

    def setUp(self):
        super().setUp()
        self.user = _user("api@edify.test")
        self.client = Client()

    def _login(self, password=PASSWORD):
        return self.client.post(
            "/api/auth/login",
            {"email": self.user.email, "password": password},
            content_type="application/json",
        )

    def test_a_password_alone_does_not_get_tokens(self):
        body = self._login().json()
        self.assertNotIn(
            "accessToken",
            body,
            "the token API handed out a credential for a password alone, so "
            "the second factor can be walked around entirely",
        )
        self.assertTrue(body.get("mfaRequired"))

    def test_the_code_completes_it(self):
        token = self._login().json()["mfaToken"]
        response = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": token, "code": self.captured.code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("accessToken", response.json())

    def test_a_wrong_code_gets_nothing(self):
        token = self._login().json()["mfaToken"]
        response = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": token, "code": "000000"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("accessToken", response.json())

    def test_an_invented_token_gets_nothing(self):
        self._login()
        response = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": "made-up", "code": self.captured.code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_the_right_code_with_the_wrong_token_gets_nothing(self):
        """The token is what binds the code to this sign-in attempt."""
        other = _user("api-other@edify.test")
        _, other_token, _ = mfa_service.start_api_challenge(other)
        self._login()

        response = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": other_token, "code": self.captured.code},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_the_token_is_not_stored_in_the_clear(self):
        challenge, token, _ = mfa_service.start_api_challenge(self.user)
        row = MfaChallenge.objects.filter(id=challenge.id).values().first()
        for field, value in row.items():
            self.assertNotIn(token, str(value), f"the token is readable from {field}")

    def test_the_token_is_long_enough_not_to_be_guessed(self):
        """Unlike the six-digit code it has no attempt counter behind it."""
        _, token, _ = mfa_service.start_api_challenge(self.user)
        self.assertGreaterEqual(len(token), 32)

    def test_a_token_cannot_be_spent_twice(self):
        token = self._login().json()["mfaToken"]
        code = self.captured.code
        payload = {"mfaToken": token, "code": code}
        self.assertEqual(
            self.client.post(
                "/api/auth/login/verify", payload, content_type="application/json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/login/verify", payload, content_type="application/json"
            ).status_code,
            401,
        )

    def test_an_account_without_the_factor_is_unaffected(self):
        plain = _user("api-plain@edify.test", enabled=False)
        response = self.client.post(
            "/api/auth/login",
            {"email": plain.email, "password": PASSWORD},
            content_type="application/json",
        )
        self.assertIn("accessToken", response.json())

    def test_every_rejection_reads_the_same(self):
        """An expired challenge, an unknown token and a wrong code must be
        indistinguishable to whoever is holding a stolen password."""
        token = self._login().json()["mfaToken"]
        wrong_code = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": token, "code": "000000"},
            content_type="application/json",
        )
        unknown_token = self.client.post(
            "/api/auth/login/verify",
            {"mfaToken": "nope", "code": "000000"},
            content_type="application/json",
        )
        self.assertEqual(wrong_code.status_code, unknown_token.status_code)
        # correlationId is per-request by design; what must not differ is
        # anything that describes the cause.
        self.assertEqual(
            wrong_code.json()["message"], unknown_token.json()["message"]
        )


class ChallengePurgeTest(MfaTestCase):
    """A row is written for every sign-in, so something has to remove them."""

    def setUp(self):
        super().setUp()
        self.user = _user("purge@edify.test")

    def _aged_challenge(self, age, *, consumed=False):
        challenge, _ = mfa_service.start_challenge(self.user)
        when = timezone.now() - age
        MfaChallenge.objects.filter(id=challenge.id).update(
            created_at=when,
            expires_at=when,
            consumed_at=when if consumed else None,
        )
        return challenge

    def test_dead_challenges_past_the_window_are_deleted(self):
        from apps.realtime.jobs import MFA_CHALLENGE_RETENTION, _do_mfa_challenge_purge

        old = self._aged_challenge(MFA_CHALLENGE_RETENTION + timedelta(days=1))
        _do_mfa_challenge_purge()
        self.assertFalse(MfaChallenge.objects.filter(id=old.id).exists())

    def test_recent_ones_are_left_alone(self):
        """An incident review the next morning still has something to read."""
        from apps.realtime.jobs import _do_mfa_challenge_purge

        recent = self._aged_challenge(timedelta(hours=2), consumed=True)
        _do_mfa_challenge_purge()
        self.assertTrue(MfaChallenge.objects.filter(id=recent.id).exists())

    def test_a_challenge_someone_is_answering_is_never_touched(self):
        from apps.realtime.jobs import _do_mfa_challenge_purge

        client = Client()
        self.sign_in(client, self.user)
        _do_mfa_challenge_purge()

        client.post("/login/verify", {"code": self.captured.code})
        self.assertIn(
            "_auth_user_id",
            client.session,
            "the purge deleted a challenge that was mid-flight",
        )

    def test_the_job_is_registered_and_wired(self):
        """A job function with no registry entry never runs; a registry entry
        with no function fails the scheduler at start-up."""
        from apps.realtime.registry import JOB_NAMES

        self.assertIn("mfa_challenge_purge", JOB_NAMES)


class ChallengeRateLimitTest(MfaTestCase):
    """MAX_ATTEMPTS kills one challenge. Without a cap on how many challenges
    an account can open, that only forces an attacker holding a stolen password
    to start another — five fresh guesses per round, for as many rounds as they
    like, each one mailing the person they are trying to break in as.
    """

    def setUp(self):
        super().setUp()
        self.user = _user("ratelimit@edify.test")

    def _exhaust(self):
        for _ in range(mfa_service.MAX_CHALLENGES_PER_WINDOW):
            mfa_service.start_challenge(self.user)

    def test_the_grind_hits_a_wall(self):
        self._exhaust()
        challenge, delivery = mfa_service.start_challenge(self.user)
        self.assertIsNone(challenge)
        self.assertFalse(delivery.ok)

    def test_no_further_messages_are_sent(self):
        self._exhaust()
        before = len(self.captured.messages)
        mfa_service.start_challenge(self.user)
        self.assertEqual(len(self.captured.messages), before)

    def test_the_login_form_says_nothing_useful_about_it(self):
        """The person here already has the password. Naming the limit would
        only tell them how to pace the next run."""
        self._exhaust()
        client = Client()
        limited = self.sign_in(client, self.user)
        wrong_password = self.sign_in(Client(), self.user, password="wrong")

        self.assertEqual(limited.status_code, 200)
        self.assertNotIn("_auth_user_id", client.session)

        shown = _form_error(limited)
        # Scoped to the message the form shows, not the whole page: the page
        # carries a random CSRF token, and a keyword scan over it would fail
        # whenever the token happened to contain the word.
        for term in ("limit", "too many", "rate", "code"):
            self.assertNotIn(term, shown.lower())
        self.assertEqual(
            shown,
            _form_error(wrong_password),
            "a rate-limited sign-in is distinguishable from a bad password",
        )

    def test_the_token_api_refuses_it_the_same_way(self):
        self._exhaust()
        response = self.client.post(
            "/api/auth/login",
            {"email": self.user.email, "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("mfaToken", response.json())

    def test_ordinary_use_never_reaches_it(self):
        """Signing in, mistyping, and starting over must stay well clear."""
        for _ in range(3):
            challenge, _ = mfa_service.start_challenge(self.user)
            self.assertIsNotNone(challenge)

    def test_old_attempts_stop_counting(self):
        """The cap is a window, not a lifetime ban — someone locked out by a
        burst can sign in again once it has passed."""
        self._exhaust()
        MfaChallenge.objects.filter(user=self.user).update(
            created_at=timezone.now() - mfa_service.CHALLENGE_WINDOW * 2
        )
        challenge, _ = mfa_service.start_challenge(self.user)
        self.assertIsNotNone(challenge)
