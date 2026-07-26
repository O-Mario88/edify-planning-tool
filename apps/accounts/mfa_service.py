"""The second factor: issuing, delivering and checking a one-time code.

Every rule about how the second factor behaves lives here, so that the views
are about screens and this is about policy. The login view, the verification
view and the enrolment page all call in; none of them decides anything.

What the design is guarding against, and how:

  A stolen password.       The point of the whole thing. A correct password
                           leaves the person at a code prompt, not signed in.

  A guessed code.          Six digits is one in a million per attempt, which is
                           a wall only while attempts are few — MAX_ATTEMPTS
                           kills the challenge, and the code cannot be reused
                           afterwards even if it was right.

  A replayed code.         Single-use. A code read over a shoulder is spent the
                           moment its owner signs in with it.

  A leaked database.       Only the SHA-256 hash of the code is stored, so a
                           dump contains nothing presentable as a factor.

  A login form used as a   Resends are rate-limited per challenge and the
  way to bombard someone.  challenge itself expires, so the form cannot be
                           turned into an SMS pump aimed at a number.

  Enrolment as a lockout.  A channel that cannot deliver is not offered, and
                           the account falls back to email rather than
                           stranding somebody behind a factor they cannot
                           receive.

  Telling a stranger who   Starting a challenge for an unknown or non-enrolled
  banks here.              account is the caller's business, not this module's:
                           `required_for` answers only about a user the caller
                           has already authenticated.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.email import MailMessage, mailer
from apps.core.sms import SmsMessage, sms

from .models import MfaChallenge, User

logger = logging.getLogger("edify.mfa")

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_DELIVERIES = 4
RESEND_INTERVAL = timedelta(seconds=30)

# How many challenges one account may open in an hour. A person signing in
# needs one, or two if they mistyped and started over; anything approaching ten
# is somebody working through the six-digit space five guesses at a time.
MAX_CHALLENGES_PER_WINDOW = 10
CHALLENGE_WINDOW = timedelta(hours=1)

EMAIL_CHANNEL = "email"
SMS_CHANNEL = "sms"


# Outcome codes. Plain strings so a view can branch on them and a template can
# print one without importing anything.
CODE_INCORRECT = "code_incorrect"
CODE_EXPIRED = "code_expired"
TOO_MANY_ATTEMPTS = "too_many_attempts"
ALREADY_USED = "already_used"


@dataclass(frozen=True)
class Verification:
    ok: bool
    reason: str = ""
    attempts_left: int = 0


@dataclass(frozen=True)
class Delivery:
    ok: bool
    channel: str
    hint: str
    reason: str = ""


# ── Enrolment ────────────────────────────────────────────────────────────────


def available_channels(user: User) -> list[str]:
    """The channels this user could actually receive a code on, right now.

    Email is always there — it is how the account was created and how a
    password reset already reaches them. SMS needs both a number on the account
    and a provider that can send to it; offering it otherwise would enrol
    somebody onto a factor that silently never arrives, which is not a security
    control but a lockout.
    """
    channels = [EMAIL_CHANNEL]
    if user.phone and sms.is_configured:
        channels.append(SMS_CHANNEL)
    return channels


def enrolment_state(user: User) -> dict:
    """What the settings page needs to show, including why a channel is off.

    "SMS (unavailable)" with no reason is the kind of dead control that makes
    people mail an administrator. Each unavailable channel says what would make
    it available, and whether that is something the person can fix themselves.
    """
    channels = available_channels(user)
    return {
        "mfa_enabled": bool(user.mfa_enabled),
        # Whether the factor is actually in force, which is not the same as
        # whether this person enrolled: under the organisation-wide switch it
        # applies to accounts that never did. The page keys its state off this,
        # so someone covered by the policy still sees — and can change — the
        # channel their codes go to.
        "mfa_in_force": required_for(user),
        "mfa_channel": resolve_channel(user),
        "mfa_channels": channels,
        "mfa_sms_available": SMS_CHANNEL in channels,
        "mfa_sms_blocked_reason": (
            ""
            if SMS_CHANNEL in channels
            else (
                "Add a phone number to your profile to receive codes by text."
                if not user.phone
                else "Text messaging is not configured on this deployment. "
                "Your administrator can enable it."
            )
        ),
        "mfa_required_by_policy": bool(
            getattr(settings, "MFA_REQUIRED_FOR_ALL", False)
        ),
        "mfa_email_hint": _mask_email(user.email),
        "mfa_phone_hint": _mask_phone(user.phone) if user.phone else "",
    }


def required_for(user: User) -> bool:
    """Does this sign-in need a second factor?

    Per-user enrolment, plus an organisation-wide switch so the whole estate
    can be turned on without editing every row. The switch is read from
    settings on each call rather than cached, so turning it on takes effect for
    the next sign-in rather than the next deploy.
    """
    if getattr(settings, "MFA_REQUIRED_FOR_ALL", False):
        return True
    return bool(user.mfa_enabled)


def resolve_channel(user: User) -> str:
    """The channel to use, degraded to one that works.

    A user enrolled on SMS whose number was later removed — or whose provider
    was switched off — must not be stranded. Email is the floor.
    """
    preferred = user.mfa_channel or EMAIL_CHANNEL
    if preferred in available_channels(user):
        return preferred
    return EMAIL_CHANNEL


# ── Issuing ──────────────────────────────────────────────────────────────────


def _generate_code() -> str:
    """`secrets`, not `random`: this is a credential, and the Mersenne Twister
    is predictable from its output."""
    upper = 10**CODE_DIGITS
    return str(secrets.randbelow(upper)).zfill(CODE_DIGITS)


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _mask_email(address: str) -> str:
    name, _, domain = address.partition("@")
    if not domain:
        return "•••"
    head = name[0] if name else ""
    return f"{head}{'•' * max(3, len(name) - 1)}@{domain}"


def _mask_phone(number: str) -> str:
    digits = "".join(c for c in number if c.isdigit())
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"


def destination_for(user: User, channel: str) -> tuple[str, str]:
    """(where it goes, what we are willing to show)."""
    if channel == SMS_CHANNEL and user.phone:
        return user.phone, _mask_phone(user.phone)
    return user.email, _mask_email(user.email)


@transaction.atomic
def start_challenge(
    user: User, channel: str | None = None
) -> tuple[MfaChallenge | None, Delivery]:
    """Issue a code and send it, unless too many have been issued lately.

    Any challenge already open for this user is expired first. Two live codes
    would double an attacker's chances for no benefit to anybody, and it also
    means "resend" and "start again" cannot leave a stale code working.

    The window matters more than it looks. MAX_ATTEMPTS kills a challenge after
    five wrong codes, but on its own that only forces an attacker holding a
    stolen password to start a new one — five fresh guesses per round, for as
    many rounds as they care to run, each one mailing or texting the person
    they are trying to break in as. Capping how many challenges an account can
    open in an hour is what turns that from an unbounded grind into a wall.

    Returns (None, refusal) when the cap is hit. The caller shows the same
    unhelpful message it shows for a bad password: whoever is on the other end
    has already got past the password, and telling them precisely which limit
    they have run into is telling them how to pace the next attempt.
    """
    if _recent_challenge_count(user) >= MAX_CHALLENGES_PER_WINDOW:
        logger.warning(
            "MFA challenge rate limit reached for user %s — %s in the last %s",
            user.id,
            MAX_CHALLENGES_PER_WINDOW,
            CHALLENGE_WINDOW,
        )
        return None, Delivery(False, resolve_channel(user), "", "too_many_requests")

    _expire_open_challenges(user)

    channel = channel or resolve_channel(user)
    code = _generate_code()
    destination, hint = destination_for(user, channel)

    challenge = MfaChallenge.objects.create(
        user=user,
        channel=channel,
        destination_hint=hint,
        code_hash=_hash(code),
        expires_at=timezone.now() + CODE_TTL,
        last_sent_at=timezone.now(),
    )
    delivery = _deliver(user, challenge, code, destination)
    return challenge, delivery


def resend(challenge: MfaChallenge) -> Delivery:
    """Send a fresh code for an open challenge.

    A new code rather than the same one again: the old one has been in flight
    for a while and may have gone to a channel the person no longer controls.
    Bounded twice over — a minimum interval between sends, and a ceiling on how
    many a single challenge may ever trigger — because otherwise this endpoint
    is a way to bill the organisation for messages to a number of the
    attacker's choosing.
    """
    now = timezone.now()
    if challenge.consumed_at or challenge.expires_at <= now:
        return Delivery(
            False, challenge.channel, challenge.destination_hint, CODE_EXPIRED
        )
    if challenge.deliveries >= MAX_DELIVERIES:
        return Delivery(
            False, challenge.channel, challenge.destination_hint, "resend_limit"
        )
    if challenge.last_sent_at and now - challenge.last_sent_at < RESEND_INTERVAL:
        return Delivery(
            False, challenge.channel, challenge.destination_hint, "resend_too_soon"
        )

    code = _generate_code()
    destination, hint = destination_for(challenge.user, challenge.channel)
    challenge.code_hash = _hash(code)
    challenge.destination_hint = hint
    challenge.deliveries += 1
    challenge.last_sent_at = now
    # Deliberately NOT extending expires_at. The window belongs to the sign-in
    # attempt, not to the last message; refreshing it on every resend would let
    # anyone hold a challenge open indefinitely.
    challenge.save(
        update_fields=[
            "code_hash",
            "destination_hint",
            "deliveries",
            "last_sent_at",
            "updated_at",
        ]
    )
    return _deliver(challenge.user, challenge, code, destination)


def _recent_challenge_count(user: User) -> int:
    return MfaChallenge.objects.filter(
        user=user, created_at__gte=timezone.now() - CHALLENGE_WINDOW
    ).count()


def _expire_open_challenges(user: User) -> None:
    MfaChallenge.objects.filter(
        user=user, consumed_at__isnull=True, expires_at__gt=timezone.now()
    ).update(expires_at=timezone.now())


def _deliver(
    user: User, challenge: MfaChallenge, code: str, destination: str
) -> Delivery:
    minutes = int(CODE_TTL.total_seconds() // 60)
    if challenge.channel == SMS_CHANNEL:
        result = sms.send(
            SmsMessage(
                to=destination,
                text=(
                    f"{code} is your Edify sign-in code. "
                    f"It expires in {minutes} minutes. "
                    "If this was not you, change your password."
                ),
            )
        )
    else:
        result = mailer.send(
            MailMessage(
                to=destination,
                subject="Your Edify sign-in code",
                text="\n".join(
                    [
                        f"Hello {user.name},",
                        "",
                        "Your sign-in code is:",
                        "",
                        f"    {code}",
                        "",
                        f"It expires in {minutes} minutes and can be used once.",
                        "",
                        "If you did not try to sign in, someone else may know "
                        "your password — change it as soon as you can.",
                        "",
                        "— Edify Planning and Monitoring Tool",
                    ]
                ),
            )
        )

    # In dev both providers report delivered=False by design and hand the body
    # back instead, so "the provider took it" is the honest question here.
    accepted = bool(result.get("delivered")) or "devPreview" in result
    if not accepted:
        logger.error(
            "MFA code could not be sent over %s for user %s",
            challenge.channel,
            user.id,
        )
    return Delivery(
        ok=accepted,
        channel=challenge.channel,
        hint=challenge.destination_hint,
        reason="" if accepted else "delivery_failed",
    )


# ── Checking ─────────────────────────────────────────────────────────────────


def verify(challenge: MfaChallenge, code: str) -> Verification:
    """Check a submitted code and, if it is right, spend it."""
    now = timezone.now()

    if challenge.consumed_at:
        return Verification(False, ALREADY_USED)
    if challenge.expires_at <= now:
        return Verification(False, CODE_EXPIRED)
    if challenge.attempts >= MAX_ATTEMPTS:
        return Verification(False, TOO_MANY_ATTEMPTS)

    submitted = "".join(c for c in (code or "") if c.isdigit())

    # compare_digest, not ==. Comparing hex digests of equal length leaks
    # little, but the habit is what keeps the one comparison that would matter
    # from being written the other way.
    if hmac.compare_digest(_hash(submitted), challenge.code_hash) and submitted:
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at", "updated_at"])
        return Verification(True)

    challenge.attempts += 1
    challenge.save(update_fields=["attempts", "updated_at"])
    remaining = max(0, MAX_ATTEMPTS - challenge.attempts)
    if remaining == 0:
        return Verification(False, TOO_MANY_ATTEMPTS)
    return Verification(False, CODE_INCORRECT, attempts_left=remaining)


# ── The token API ────────────────────────────────────────────────────────────
#
# The web flow keeps its pending state in the session. The token API has no
# session, so the client is handed an opaque token to present back with the
# code. It is generated the same way the code is and stored the same way — the
# difference is that it is long enough not to be guessed, because unlike the
# code it is not protected by an attempt counter on a six-digit space.
API_TOKEN_BYTES = 32


def start_api_challenge(
    user: User, channel: str | None = None
) -> tuple[MfaChallenge | None, str, Delivery]:
    challenge, delivery = start_challenge(user, channel)
    if challenge is None:
        return None, "", delivery
    token = secrets.token_urlsafe(API_TOKEN_BYTES)
    challenge.client_token_hash = _hash(token)
    challenge.save(update_fields=["client_token_hash", "updated_at"])
    return challenge, token, delivery


def open_api_challenge(token: str) -> MfaChallenge | None:
    if not token:
        return None
    return (
        MfaChallenge.objects.filter(
            client_token_hash=_hash(token), consumed_at__isnull=True
        )
        .select_related("user")
        .first()
    )


def open_challenge(challenge_id: str, user_id: str) -> MfaChallenge | None:
    """Load a challenge, but only for the user it was issued to.

    The pending user id and the challenge id both come out of the same session,
    so this pairing is what stops a tampered-with challenge id from being
    answered on somebody else's behalf.
    """
    return (
        MfaChallenge.objects.filter(
            id=challenge_id, user_id=user_id, consumed_at__isnull=True
        )
        .select_related("user")
        .first()
    )
