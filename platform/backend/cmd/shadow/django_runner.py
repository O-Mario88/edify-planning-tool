"""Play a scenario of saves through the existing application, as people make them.

The shadow comparison's first half (cmd/shadow, docs/migration/26-shadow-writes.md).
Each step is one account opening a drawer and saving it:

    {"who": "cceo@edify.org", "open": "/planning/schedule?action=visit&school=<id>",
     "form": "/planning/schedule-action",
     "from_script": {"catalogue_item_id": "defaultCatalogueItemId", "delivery_type": "delivery"},
     "set": {"purpose_of_visit": "ssa_support", "scheduled_date": "2026-11-20"}}

The runner signs in as the account (no password: Django's test client),
renders the drawer exactly as the web does, takes its form posting to
"form", keeps every field the drawer
fills in itself, applies "set", and posts the form to its own action with
the drawer's htmx headers. Nothing below the view is stood in for. Each
step's outcome (its status, and the toast or error it answered with) is
written beside the scenario, so Go's outcomes are compared as well as the
rows it writes.

Run ONLY against a shadow copy (a database named edify_shadow_*):

    DATABASE_URL=postgresql://localhost:5432/edify_shadow_a SCENARIO=s.json OUT=o.json \\
        python manage.py shell < platform/backend/cmd/shadow/django_runner.py
"""

import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

NAME = settings.DATABASES["default"]["NAME"]
if not NAME.startswith("edify_shadow_"):
    # Not an assert: python -O would drop it, and this is what keeps the
    # runner off every database people use.
    raise SystemExit(f"refusing {NAME}: not a shadow copy")


class Forms(HTMLParser):
    """Every form's action and the values a browser would submit from it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._form = self._select = self._textarea = None
        self._picked = False
        # Inputs inside <template> exist only when the drawer's script shows
        # them (x-if), so a browser does not post them unless shown.
        self._template = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "template":
            self._template += 1
            return
        if tag == "form" and self._form is None:
            self._form = {
                "action": a.get("hx-post") or a.get("action") or "",
                "fields": [],
            }
            return
        if self._form is None or self._template:
            return
        name = a.get("name")
        if tag == "input" and name and "disabled" not in a:
            kind = (a.get("type") or "text").lower()
            if kind in ("checkbox", "radio") and "checked" not in a:
                return
            if kind in ("submit", "button", "file"):
                return
            on = kind in ("checkbox", "radio")
            self._form["fields"].append([name, a.get("value", "on" if on else "")])
        elif tag == "select" and name and "disabled" not in a:
            self._select, self._picked = [name, None], False
        elif tag == "option" and self._select is not None:
            if "selected" in a and not self._picked:
                self._select[1], self._picked = a.get("value", ""), True
            elif self._select[1] is None:
                self._select[1] = a.get("value", "")
        elif tag == "textarea" and name:
            self._textarea = [name, ""]

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "template":
            self._template = max(0, self._template - 1)
            return
        if self._form is None:
            return
        if tag == "select" and self._select is not None:
            self._form["fields"].append([self._select[0], self._select[1] or ""])
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self._form["fields"].append(self._textarea)
            self._textarea = None
        elif tag == "form":
            self.forms.append(self._form)
            self._form = None


def message(html: str) -> str:
    """What the answer said, as text: the toast, error or panel words."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())[:400]


def script_values(html: str, wanted: dict) -> dict:
    """Fields the drawer's script fills: each from its starting value in the
    page (`key: 'value'` in the drawer's x-data), as the script binds it."""
    out = {}
    for field, key in wanted.items():
        m = re.search(r"\b" + re.escape(key) + r"\s*:\s*'((?:[^'\\]|\\.)*)'", html)
        out[field] = m.group(1) if m else ""
    return out


def play(client: Client, step: dict) -> dict:
    headers = {"HTTP_HX_REQUEST": "true", "HTTP_HOST": "localhost"}
    drawer = client.get(step["open"], **headers)
    if drawer.status_code != 200:
        return {
            "ok": False,
            "opened": drawer.status_code,
            "message": message(drawer.content.decode()),
        }
    forms = Forms()
    forms.feed(drawer.content.decode())
    form = next((f for f in forms.forms if step["form"] in f["action"]), None)
    if form is None:
        return {
            "ok": False,
            "message": "the drawer has no form posting to " + step["form"],
        }
    chosen = {
        **script_values(drawer.content.decode(), step.get("from_script", {})),
        **step.get("set", {}),
    }
    fields = [f for f in form["fields"] if f[0] not in chosen]
    fields += [[k, v] for k, v in chosen.items()]
    data = {}
    for k, v in fields:
        data.setdefault(k, []).append(v)
    answer = client.post(form["action"], data, **headers)
    trigger = answer.headers.get("HX-Trigger", "")
    return {
        "ok": answer.status_code < 400,
        "status": answer.status_code,
        "action": form["action"],
        "trigger": trigger,
        "message": message(answer.content.decode()),
    }


def main():
    steps = json.load(open(os.environ["SCENARIO"]))
    User = get_user_model()
    started = datetime.now(timezone.utc).isoformat()
    outcomes = []
    for step in steps:
        client = Client(enforce_csrf_checks=False)
        client.force_login(User.objects.get(email=step["who"]))
        outcomes.append(play(client, step))
    json.dump(
        {
            "database": NAME,
            "from": started,
            "to": datetime.now(timezone.utc).isoformat(),
            "outcomes": outcomes,
        },
        open(os.environ["OUT"], "w"),
        indent=2,
    )
    saved = sum(o["ok"] for o in outcomes)
    print(
        f"{len(steps)} steps on {NAME}: {saved} answered ok, {len(steps) - saved} refused"
    )


main()
