"""Write the Settings page's golden: what the existing page shows each
account, from the view's own context (apps.frontend.views.extended_views.
settings_view), under each SMS and two-step policy setting.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/settings_golden.json \\
    python manage.py shell < platform/backend/internal/settingspage/testdata/golden.py

Only against a database whose name ends in "_test". It files accounts, every
id starting "gset", covering each thing the page reads: no phone, a phone,
a short number, enrolled on email, on text messages and on the app with and
without the app set up, a channel the page does not know, required roles
held and active, a refused role, an account owing a new password, and a
name in letters beyond ASCII; asks the view for each under SMS on and off,
no policy, a required role and the estate-wide switch, and a session
setting; writes the rows and the answers to GOLDEN_OUT; and rolls the
accounts back.
"""

import json
import os
from unittest import mock

from django.conf import settings
from django.db import connection, transaction
from django.test import override_settings

from apps.accounts.models import User
from apps.frontend.views import extended_views
from apps.mobile_feed.views import _page_get

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

P = "gset"
ACCOUNTS = (
    # id, email, phone, roles, active, enrolled, channel, secret, owes password
    ("01", "ann@settings.test", "", ["CCEO"], "CCEO", False, "email", "", False),
    (
        "02",
        "bob@settings.test",
        "+256 700 000 002",
        ["CCEO"],
        "CCEO",
        True,
        "sms",
        "",
        False,
    ),
    (
        "03",
        "cat@settings.test",
        "+256700000003",
        ["Admin"],
        "Admin",
        True,
        "app",
        "SECRETSEED",
        False,
    ),
    (
        "04",
        "dan@settings.test",
        "",
        ["Program Lead"],
        "Program Lead",
        True,
        "app",
        "",
        False,
    ),
    (
        "05",
        "eve@settings.test",
        "123",
        ["Accountant", "Admin"],
        "Accountant",
        False,
        "sms",
        "",
        False,
    ),
    (
        "06",
        "fay@settings.test",
        "",
        ["ClusterLeader"],
        "ClusterLeader",
        False,
        "email",
        "",
        False,
    ),
    (
        "07",
        "élise.n@settings.test",
        "0772 123 456",
        ["CountryDirector"],
        "CountryDirector",
        False,
        "pigeon",
        "",
        False,
    ),
    ("08", "gus@settings.test", "", ["CCEO"], "CCEO", False, "email", "", True),
)
SMS_ON = {"SMS_PROVIDER": "africastalking", "SMS_API_KEY": "k", "SMS_USERNAME": "u"}
SMS_OFF = {"SMS_PROVIDER": "", "SMS_API_KEY": "", "SMS_USERNAME": ""}
POLICIES = (
    {"for_all": False, "roles": []},
    {"for_all": False, "roles": ["Admin"]},
    {"for_all": True, "roles": []},
)
SESSIONS = ("", "3600")
KEYS = (
    "mfa_in_force",
    "mfa_required_by_policy",
    "mfa_channel",
    "mfa_app_available",
    "mfa_sms_available",
    "mfa_sms_blocked_reason",
    "mfa_email_hint",
    "mfa_phone_hint",
    "session_idle_minutes",
)


def file_accounts():
    for (
        suffix,
        email,
        phone,
        roles,
        active,
        enrolled,
        channel,
        secret,
        owes,
    ) in ACCOUNTS:
        User.objects.create(
            id=P + suffix,
            email=email,
            name=email.split("@")[0],
            phone=phone,
            roles=roles,
            active_role=active,
            is_active=True,
            mfa_enabled=enrolled,
            mfa_channel=channel,
            mfa_secret=secret,
            must_change_password=owes,
        )


def ask(user):
    """The page's context for user, or how it refuses them."""
    if user.must_change_password:
        # ForcePasswordChangeMiddleware sends them to /change-password before
        # any view runs.
        return {"refused": "password_owed"}
    seen = {}

    def capture(request, template, context):
        seen.update(context)
        from django.http import HttpResponse

        return HttpResponse("")

    with mock.patch.object(extended_views, "render", side_effect=capture):
        response = extended_views.settings_view(_page_get(user, "/settings", {}, None))
    if not seen:
        return {"refused": str(response.status_code)}
    answer = {key: seen[key] for key in KEYS}
    answer["email"] = seen["user"].email
    answer["must_change_password"] = bool(seen["user"].must_change_password)
    return answer


rows, answers = [], []
with transaction.atomic():
    file_accounts()
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT row_to_json(t)::text FROM "user" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        rows = [row[0] for row in cursor.fetchall()]
    for sms in (SMS_ON, SMS_OFF):
        for policy in POLICIES:
            for session in SESSIONS:
                age = int(session) if session else 30 * 60
                with (
                    mock.patch.dict(os.environ, sms),
                    override_settings(
                        MFA_REQUIRED_FOR_ALL=policy["for_all"],
                        MFA_REQUIRED_ROLES=frozenset(policy["roles"]),
                        SESSION_COOKIE_AGE=age,
                    ),
                ):
                    for user in User.objects.filter(id__startswith=P).order_by("id"):
                        answers.append(
                            {
                                "user_id": user.id,
                                "active_role": user.active_role,
                                "env": {**sms, "SESSION_IDLE_TIMEOUT_SECONDS": session},
                                "policy": policy,
                                "answer": ask(user),
                            }
                        )
    transaction.set_rollback(True)

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"rows": {"user": [json.loads(r) for r in rows]}, "answers": answers},
        out,
        ensure_ascii=False,
        indent=1,
    )
print(f"wrote {len(answers)} answers")
