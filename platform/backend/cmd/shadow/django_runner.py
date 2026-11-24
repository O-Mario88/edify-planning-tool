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
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in
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
        # A browser sends no control inside a disabled fieldset (the
        # Complete drawer's sections for the purposes not chosen).
        self._fieldsets = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "template":
            self._template += 1
            return
        if tag == "fieldset":
            self._fieldsets.append("disabled" in a)
            return
        if any(self._fieldsets) and tag in ("input", "select", "textarea"):
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
        if tag == "fieldset":
            if self._fieldsets:
                self._fieldsets.pop()
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


def message(html: str, limit: int | None = 1000) -> str:
    """What the answer said, as text: the toast, error or panel words."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())[:limit]


def script_values(html: str, wanted: dict) -> dict:
    """Fields the drawer's script fills: each from its starting value in the
    page (`key: 'value'` in the drawer's x-data), as the script binds it."""
    out = {}
    for field, key in wanted.items():
        m = re.search(r"\b" + re.escape(key) + r"\s*:\s*'((?:[^'\\]|\\.)*)'", html)
        out[field] = m.group(1) if m else ""
    return out


def resolve(path: str) -> str:
    """A step may name an activity an earlier step made by its purpose text
    (`{activity:[shadow-r] A}`): each copy makes its own ids, so the step
    finds the activity on the copy it plays on."""
    from apps.activities.models import Activity

    def one(m):
        found = (
            Activity.objects.filter(activity_purpose_text=m.group(1))
            .order_by("-created_at")
            .values_list("id", flat=True)
            .first()
        )
        return found or "missing"

    return re.sub(r"\{activity:([^}]*)\}", one, path)


def confirm_advances(step: dict) -> dict:
    """A step that is not a drawer: the person confirms the advance of one of
    their visits (advance_service.confirm_advance, the money page's door), so
    a later step meets a day whose money has moved. Played by the existing
    application on every copy alike."""
    from apps.fund_requests import advance_service
    from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

    user = get_user_model().objects.get(email=step["who"])
    activity_id = resolve(step["confirm_advance"])
    pending = AdvanceRequest.objects.filter(
        budget_line__activity_id=activity_id,
        status=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
    ).values_list("id", flat=True)
    confirmed = [advance_service.confirm_advance(i, user)["status"] for i in pending]
    return {
        "ok": bool(confirmed),
        "status": 200,
        "message": f"{len(confirmed)} confirmed",
    }


def post_form(client: Client, step: dict) -> dict:
    """A step whose form sits on a page rather than in a drawer: Today's
    Snooze menu (partials/today/queue_row.html) is a form of three hidden
    fields (todo, choice, title) per choice, so the step names them in "data"
    and posts them to "post" with the page's htmx headers (docs/migration/50)."""
    headers = {"HTTP_HX_REQUEST": "true", "HTTP_HOST": "localhost"}
    data = {k: (v if isinstance(v, list) else [v]) for k, v in step["data"].items()}
    # "follow": a view that answers with a redirect and a flash message is
    # read on the page it leads to, where the message is shown.
    answer = client.post(step["post"], data, follow=bool(step.get("follow")), **headers)
    return {
        "ok": answer.status_code < 400,
        "status": answer.status_code,
        "action": step["post"],
        "retarget": answer.headers.get("HX-Retarget", ""),
        # A whole page's words, when it was followed: its message sits
        # below the page's chrome.
        "message": message(
            answer.content.decode(), limit=None if step.get("follow") else 1000
        ),
        "posted": data,
    }


def read_page(client: Client, step: dict) -> dict:
    """A step that only reads a page with the page's htmx headers: what the
    existing application draws after a Go save whose answer is a redraw
    (undoing a snooze answers with the Today panel, docs/migration/63).
    "background": the gateway's own read, marked as one nobody made
    (X-Edify-Background), so the person's presence is the save's stamp, not
    the redraw's (docs/migration/65)."""
    headers = {"HTTP_HX_REQUEST": "true", "HTTP_HOST": "localhost"}
    if step.get("background"):
        headers["HTTP_X_EDIFY_BACKGROUND"] = "1"
    answer = client.get(step["get"], **headers)
    return {
        "ok": answer.status_code < 400,
        "status": answer.status_code,
        "action": step["get"],
        "retarget": answer.headers.get("HX-Retarget", ""),
        "message": message(answer.content.decode()),
    }


def play(client: Client, step: dict) -> dict:
    if "confirm_advance" in step:
        return confirm_advances(step)
    if "post" in step:
        return post_form(client, step)
    if "get" in step:
        return read_page(client, step)
    headers = {"HTTP_HX_REQUEST": "true", "HTTP_HOST": "localhost"}
    step = {**step, "open": resolve(step["open"]), "form": resolve(step["form"])}
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
        # A list in "set" ticks several boxes of one name (a checklist).
        for item in v if isinstance(v, list) else [v]:
            data.setdefault(k, []).append(item)
    answer = client.post(form["action"], data, **headers)
    # The pricing that follows a save runs in a thread of its own once the
    # save commits (apps.daily_visit_batches.costs_follow); let it finish
    # before the next step, as a person's next request waits for it.
    from apps.daily_visit_batches.costs_follow import wait
    from apps.routes import after_save

    wait()
    # And the route check that follows the pricing (apps.routes.after_save).
    for thread in list(after_save._running):
        thread.join(30)
    trigger = answer.headers.get("HX-Trigger", "")
    outcome = {
        "ok": answer.status_code < 400,
        "status": answer.status_code,
        "action": form["action"],
        "trigger": trigger,
        "message": message(answer.content.decode()),
        # What the drawer posted, so another runner (cmd/shadow/goplay) can
        # make the same save with the same fields.
        "posted": data,
    }
    # A save that reloads the page says what it did in a flash message
    # (the group actions' "3 activities moved to …"), not in its answer.
    flash = [str(m) for m in getattr(answer.wsgi_request, "_messages", [])]
    if flash:
        outcome["flash"] = flash
    if "activity_ids" in data:
        # The ticked activities by their purpose text, so another copy finds
        # its own ids for them (each copy makes its own).
        from apps.activities.models import Activity

        texts = dict(
            Activity.objects.filter(id__in=data["activity_ids"]).values_list(
                "id", "activity_purpose_text"
            )
        )
        outcome["posted_texts"] = [texts.get(i) or "" for i in data["activity_ids"]]
    return outcome


def main():
    steps = json.load(open(os.environ["SCENARIO"]))
    User = get_user_model()
    # Each step stands for a request in the session the person already has:
    # the runner's force_login is a stand-in for that session, not a sign-in,
    # so it must not write the sign-in's last_login (django.contrib.auth's
    # update_last_login). A Go save makes no sign-in either, so a person whose
    # steps were all Go's read differently on that column alone
    # (docs/migration/65).
    user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
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
