"""Read the existing notification centre's HTML as a person sees it.

Run inside the existing application (development or a shadow copy only):

    ACCTS=accounts.txt OUT=django.json python manage.py shell < django_reader.py

For every account (`email|Role` lines) and every question below it renders
/notifications with the existing view and template, unmodified, and reads
the page that comes back into the words, figures and choices it shows. A
role the page refuses is not rendered (the refusal writes an audit row);
it is recorded as refused from the exported rules, which the drift test
holds to the page's own gate. cmd/notificationparity compares these pages
with Go's answers.

The view is called directly (the feed's own _page_get request), so no
sign-in, session or middleware writes anything.
"""

import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.auth import get_user_model

from apps.frontend.views.staff_views import notifications_page_view
from apps.mobile_feed.views import _page_get

RULES = json.loads(
    Path("platform/backend/internal/notificationcenter/rules.json").read_text()
)

#: The questions every account is asked (a list of query pairs).
QUESTIONS = [
    [],
    [["status", "unread"]],
    [["status", "read"]],
    [["status", "archived"]],
    [["status", "all"]],
    [["status", "nonsense"]],
    [["status", ""]],
    [["priority", "low"]],
    [["priority", "normal"]],
    [["priority", "high"]],
    [["priority", "urgent"]],
    [["priority", "nonsense"]],
    [["category", "availability"]],
    [["category", "hr"]],
    [["category", "partner"]],
    [["category", "nonsense"]],
    [["action_required", "true"]],
    [["action_required", "yes"]],
    [["q", "planning"]],
    [["q", "inc-0000"]],
    [["q", "%"]],
    [["q", "_"]],
    [["q", "zzz-nothing"]],
    [["page", "2"]],
    [["page", "999"]],
    [["page", "0"]],
    [["page", "-1"]],
    [["page", "abc"]],
    [["page", "1_0"]],
    [["settings", "saved"]],
    [["status", "unread"], ["priority", "high"], ["page", "2"]],
    [["status", "all"], ["action_required", "true"], ["q", "slo"]],
]

#: More questions for a copy whose rows were made for the comparison, as a
#: JSON list in the same shape (EXTRA_QUESTIONS).
QUESTIONS += json.loads(os.environ.get("EXTRA_QUESTIONS") or "[]")

SPACE = re.compile(r"\s+")


def clean(text: str) -> str:
    return SPACE.sub(" ", unescape(text)).strip()


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        parts = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif "sr-only" not in child.classes and child.tag not in ("svg", "script"):
                parts.append(" " + child.text() + " ")
        return clean("".join(parts))

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, pred):
        return [n for n in self.walk() if pred(n)]

    def find(self, pred):
        return next(iter(self.find_all(pred)), None)


VOID = {"input", "br", "img", "meta", "link", "hr", "source", "path", "circle"}


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = Node("root", [], None)
        self.at = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.at)
        self.at.children.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        self.at.children.append(Node(tag, attrs, self.at))

    def handle_endtag(self, tag):
        node = self.at
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.at = node.parent

    def handle_data(self, data):
        self.at.children.append(data)

    def handle_entityref(self, name):
        self.at.children.append(f"&{name};")

    def handle_charref(self, name):
        self.at.children.append(f"&#{name};")


def has_class(*names):
    return lambda n: all(name in n.classes for name in names)


def selected(select):
    for option in select.find_all(lambda n: n.tag == "option"):
        if "selected" in option.attrs:
            return unescape(option.attrs.get("value", ""))
    return ""


def tone(icon):
    classes = icon.classes
    if "bg-rose-50" in classes:
        return "critical"
    if "bg-amber-50" in classes:
        return "high"
    if "edify-primary-soft" in classes:
        return "normal"
    return "other"


def notification(row):
    out = {"unread": "edify-primary-soft-alpha-15" in row.classes}
    icon = next(c for c in row.children if isinstance(c, Node))
    out["tone"] = tone(icon)
    content = row.find(has_class("flex-1", "min-w-0", "space-y-1"))
    out["title"] = content.find(lambda n: n.tag == "h4").text()
    line = content.find(has_class("flex", "items-center", "gap-2.5", "flex-wrap"))
    pills = [c for c in line.children if isinstance(c, Node) and c.tag == "span"]
    out["categoryLabel"] = pills[0].text()
    out["priorityLabel"] = pills[1].text()
    out["actionRequired"] = any(p.text() == "Action Required" for p in pills[2:])
    body = content.find(lambda n: n.tag == "p")
    out["body"] = body.text() if body else ""
    meta = content.find(has_class("edify-text-caption", "text-slate-400", "pt-1"))
    spans = [c for c in meta.children if isinstance(c, Node) and c.tag == "span"]
    out["createdLabel"] = spans[0].text()
    out["senderName"] = ""
    out["link"] = ""
    for span in spans[1:]:
        words = span.text()
        if words.startswith("From "):
            out["senderName"] = words[len("From ") :]
        elif words.startswith("Link: "):
            out["link"] = words[len("Link: ") :]
    actions = row.find(has_class("w-full", "sm:w-auto", "shrink-0"))
    button = actions.find(has_class("edify-primary-solid"))
    out["targetRoute"] = unescape(button.attrs["href"]) if button else ""
    out["actionLabel"] = button.text() if button else ""
    mark = actions.find(lambda n: n.tag == "a" and n.text() == "Mark read")
    out["canMarkRead"] = mark is not None
    archive = actions.find(
        lambda n: n.tag == "input" and n.attrs.get("name") == "notification_id"
    )
    out["canArchive"] = archive is not None
    ids = set()
    if mark is not None:
        ids.add(mark.attrs["href"].split("/")[2])
    if archive is not None:
        ids.add(archive.attrs["value"])
    if button is not None and "data-notification-read" in button.attrs:
        ids.add(button.attrs["data-notification-read"])
    # A row that is neither unread nor archivable shows no id at all.
    out["id"] = ids.pop() if len(ids) == 1 else (sorted(ids) or None)
    return out


def read(html: str) -> dict:
    tree = Tree()
    tree.feed(html)
    root = tree.root
    out = {}
    kpis = {}
    for label in root.find_all(has_class("context-metrics__label")):
        value = label.parent.find(has_class("context-metrics__value"))
        kpis[label.text()] = int(value.text().replace(",", ""))
    out["kpis"] = {
        "actionRequired": kpis["Action required"],
        "critical": kpis["Critical tasks"],
    }
    form = root.find(
        lambda n: n.tag == "form" and n.attrs.get("id") == "notifications-filters"
    )
    selects = {s.attrs["name"]: s for s in form.find_all(lambda n: n.tag == "select")}
    box = form.find(
        lambda n: n.tag == "input" and n.attrs.get("name") == "action_required"
    )
    search = root.find(
        lambda n: n.tag == "input"
        and n.attrs.get("name") == "q"
        and n.attrs.get("form") == "notifications-filters"
    )
    out["filters"] = {
        "status": selected(selects["status"]),
        "priority": selected(selects["priority"]),
        "category": selected(selects["category"]),
        "actionRequired": "checked" in box.attrs,
        "q": unescape(search.attrs.get("value", "")) if search else None,
        "categories": [
            {"value": unescape(o.attrs.get("value", "")), "label": o.text()}
            for o in selects["category"].find_all(lambda n: n.tag == "option")
        ][1:],
    }
    listing = root.find(has_class("divide-y", "divide-slate-100"))
    rows = (
        [c for c in listing.children if isinstance(c, Node) and c.tag == "div"]
        if listing
        else []
    )
    out["notifications"] = [notification(r) for r in rows]
    out["empty"] = (
        root.find(lambda n: n.tag == "h2" and n.text() == "All caught up!") is not None
    )
    pager = root.find(has_class("edify-pagination"))
    out["pager"] = None
    if pager is not None:
        out["pager"] = {
            "summary": pager.find(has_class("edify-pagination__summary")).text(),
            "pages": [
                n.text()
                for n in pager.find_all(
                    lambda n: "edify-pagination__control" in n.classes
                    and "edify-pagination__control--direction" not in n.classes
                    or "edify-pagination__ellipsis" in n.classes
                )
            ],
            "current": pager.find(
                lambda n: n.attrs.get("aria-current") == "page"
            ).text(),
            "previous": pager.find(lambda n: n.attrs.get("rel") == "prev") is not None,
            "next": pager.find(lambda n: n.attrs.get("rel") == "next") is not None,
        }
    section = root.find(lambda n: n.attrs.get("id") == "delivery-settings")
    settings_form = section.find(lambda n: n.tag == "form")

    def checkbox(name):
        node = settings_form.find(
            lambda n: n.tag == "input" and n.attrs.get("name") == name
        )
        return "checked" in node.attrs

    heading = next(
        h.text()
        for h in settings_form.find_all(lambda n: n.tag == "h3")
        if h.text().startswith("Email to ")
    )
    out["delivery"] = {
        "pushEnabled": checkbox("push_enabled"),
        "emailEnabled": checkbox("email_enabled"),
        "address": heading[len("Email to ") :],
        "emailConfigured": settings_form.find(has_class("text-amber-700")) is None,
        "categories": [
            {
                "value": unescape(n.attrs["value"]),
                "label": n.parent.text(),
                "muted": "checked" in n.attrs,
            }
            for n in settings_form.find_all(
                lambda n: n.tag == "input" and n.attrs.get("name") == "muted"
            )
        ],
        "saved": settings_form.find(lambda n: n.attrs.get("role") == "status")
        is not None,
    }
    return out


def main():
    users = get_user_model().objects
    answers = []
    for line in Path(os.environ["ACCTS"]).read_text().splitlines():
        if not line.strip():
            continue
        email = line.split("|")[0].strip()
        user = users.get(email=email)
        if not RULES["roles"].get(user.active_role, {}).get("page"):
            answers.append({"email": email, "refused": True})
            continue
        for question in QUESTIONS:
            request = _page_get(user, "/notifications", {})
            request.GET = request.GET.copy()
            for key, value in question:
                request.GET.appendlist(key, value)
            response = notifications_page_view(request)
            if hasattr(response, "render") and not getattr(
                response, "is_rendered", True
            ):
                response.render()
            entry = {"email": email, "query": question, "status": response.status_code}
            if response.status_code == 200:
                entry["page"] = read(response.content.decode())
            answers.append(entry)
    Path(os.environ["OUT"]).write_text(
        json.dumps(answers, indent=1, ensure_ascii=False)
    )
    print(f"read {len(answers)} pages")


main()
