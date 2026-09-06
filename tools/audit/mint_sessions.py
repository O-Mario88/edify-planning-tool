"""Mint browser sessions for the audit roles and record their sidebar pages.

Writes out/sessions.json ({role: sessionid}) and out/role_urls.json
({email: [sidebar urls]}) for the browser-side audits. Sessions are minted
server-side, so no password is ever typed; run against a LOCAL database.

    .venv/bin/python tools/audit/mint_sessions.py cd@edify.org pl1@edify.org
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from apps.core.navigation import build_sidebar_for_user  # noqa: E402

DEFAULT_ROLES = {
    "superuser": "edwin.omario@gmail.com",
    "cd": "cd@edify.org",
    "pl": "pl1@edify.org",
    "ia": "ia@edify.org",
    "accountant": "accountant@edify.org",
}


def main():
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    User = get_user_model()
    roles = dict(DEFAULT_ROLES)
    for arg in sys.argv[1:]:
        role, _, email = arg.partition("=")
        roles[role if email else role.split("@")[0]] = email or role
    sessions, urls = {}, {}
    for role, email in roles.items():
        user = User.objects.filter(email=email).first()
        if user is None:
            print("no such user:", email)
            continue
        store = SessionStore()
        store["_auth_user_id"] = str(user.pk)
        store["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
        store["_auth_user_hash"] = user.get_session_auth_hash()
        store.create()
        sessions[role] = store.session_key
        seen = []
        for section in build_sidebar_for_user(user, "/dashboard"):
            for item in section["items"]:
                if item["url"] not in seen:
                    seen.append(item["url"])
        urls[email] = seen
    (out / "sessions.json").write_text(json.dumps(sessions, indent=1))
    (out / "role_urls.json").write_text(json.dumps(urls, indent=1))
    print("minted", list(sessions), "->", out)


if __name__ == "__main__":
    main()
