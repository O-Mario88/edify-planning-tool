"""The Messages inbox, Go against the existing page's own HTML.

Run on a SHADOW copy only: the existing page marks the conversation it opens
read, so every question writes. For each reader and question, Go answers
first (MessagingService.ListThreads through a Go-only gateway on the same
copy), then the existing page is drawn by Django's test client and read back
from its HTML; the two must say the same. The badge count is compared too.

    DATABASE_URL=postgresql://localhost:5432/<shadow copy> \\
    GATEWAY=http://127.0.0.1:<port> PASSWORD=... USERS=a@x,b@y THREADS=id1,id2 \\
    OUT=proof.json python manage.py shell < proof.py
"""

import json
import os
import re
import time
import urllib.request
from html.parser import HTMLParser

from django.db import connection
from django.test import Client

from apps.accounts.models import User
from apps.messaging import services

if not connection.settings_dict["NAME"].startswith("edify_shadow_"):
    raise SystemExit("shadow copies only")

GATEWAY = os.environ["GATEWAY"]
PASSWORD = os.environ["PASSWORD"]
USERS = [u for u in os.environ["USERS"].split(",") if u]
THREADS = [t for t in os.environ.get("THREADS", "").split(",") if t]
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
    "path",
    "circle",
}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        if self.tag in ("svg", "script", "style") or "sr-only" in self.cls():
            return ""
        return " ".join(
            " ".join(c.split()) if isinstance(c, str) else c.text()
            for c in self.children
        ).strip()

    def cls(self):
        return (self.attrs.get("class") or "").split()

    def all(self, pred):
        for c in self.children:
            if isinstance(c, Node):
                if pred(c):
                    yield c
                yield from c.all(pred)

    def first(self, pred):
        return next(self.all(pred), None)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.at = node.parent

    def handle_data(self, data):
        if data.strip():
            self.at.children.append(data)


def norm(s):
    return " ".join((s or "").split())


def tone_of(classes):
    for key, tone in (
        ("bg-emerald-50", "finance"),
        ("bg-purple-50", "leave"),
        ("bg-cyan-50", "verification"),
        ("bg-teal-50", "evidence"),
        ("edify-primary-soft", "primary"),
    ):
        if key in classes:
            return tone
    return "?"


def django_page(html):
    tree = Tree()
    tree.feed(html)
    root = tree.root
    out = {"tabs": [], "threads": []}
    header = root.first(lambda n: "edify-page-header__lead" in n.cls())
    out["eyebrow"] = header.first(lambda n: "edify-page-eyebrow" in n.cls()).text()
    out["title"] = header.first(lambda n: n.tag == "h1").text()
    out["description"] = header.first(
        lambda n: "edify-page-header__description" in n.cls()
    ).text()
    for tab in root.all(
        lambda n: n.tag == "button"
        and n.attrs.get("id", "").startswith("messages-tab-")
    ):
        count = tab.first(lambda n: "messages-inbox-tab__count" in n.cls())
        label = norm(" ".join(c for c in tab.children if isinstance(c, str)))
        out["tabs"].append(
            [
                tab.attrs["id"][len("messages-tab-") :],
                label,
                count.text() if count else None,
            ]
        )
    select = root.first(lambda n: n.attrs.get("id") == "messages-sort")
    out["sorts"] = [
        [o.attrs.get("value"), o.text(), "selected" in o.attrs]
        for o in select.all(lambda n: n.tag == "option")
    ]
    listing = root.first(lambda n: n.attrs.get("id") == "thread-list")
    for b in listing.all(
        lambda n: n.tag == "button"
        and n.attrs.get("id", "").startswith("message-thread-")
    ):
        avatar = b.first(lambda n: "h-8" in n.cls())
        name = b.first(lambda n: n.tag == "span" and "truncate" in n.cls())
        when = b.first(lambda n: n.tag == "span" and "text-slate-400" in n.cls())
        paras = list(b.all(lambda n: n.tag == "p"))
        pills = list(
            b.all(
                lambda n: n.tag == "span"
                and "rounded-pill" in n.cls()
                and "px-1.5" in n.cls()
            )
        )
        badge, tone, prio, ptone = "", "", "", ""
        for pill in pills:
            if "bg-rose-50" in pill.cls():
                prio, ptone = pill.text(), "alert"
            elif "bg-slate-50" in pill.cls():
                prio, ptone = pill.text(), "plain"
            else:
                badge, tone = pill.text(), tone_of(pill.cls())
        out["threads"].append(
            {
                "id": b.attrs["id"][len("message-thread-") :],
                "avatar": "gear"
                if avatar.first(lambda n: n.tag == "svg")
                else avatar.text(),
                "sender": name.text(),
                "when": when.text(),
                "unread": b.first(lambda n: "data-unread-indicator" in n.attrs)
                is not None,
                "subject": paras[0].text(),
                "snippet": paras[1].text(),
                "badge": badge,
                "tone": tone,
                "priority": prio,
                "priority_tone": ptone,
                "starred": b.first(lambda n: "text-amber-400" in n.cls()) is not None,
                "selected": "edify-primary-soft-alpha-60" in b.cls(),
            }
        )
    empty = listing.first(lambda n: "edify-empty-state__title" in n.cls())
    out["empty"] = (
        [
            empty.text(),
            listing.first(lambda n: "edify-empty-state__message" in n.cls()).text(),
        ]
        if empty
        else None
    )
    summary = listing.first(
        lambda n: n.tag == "span" and (n.text() or "").startswith("Showing ")
    )
    if summary:
        bar = summary.parent
        links = []
        for item in bar.all(lambda n: n.tag in ("span", "button") and n is not summary):
            if item.tag == "button" and item.attrs.get("aria-label") == "Next page":
                continue
            text = item.text()
            if not text:
                continue
            page = re.search(r"[?&]page=(\d+)", item.attrs.get("hx-get", ""))
            links.append(
                [
                    text,
                    item.tag == "span" and text != "…",
                    text == "…",
                    page.group(1) if page else None,
                ]
            )
        nxt = bar.first(lambda n: n.attrs.get("aria-label") == "Next page")
        nxt_page = (
            re.search(r"[?&]page=(\d+)", nxt.attrs.get("hx-get", "")) if nxt else None
        )
        out["pager"] = {
            "summary": summary.text(),
            "links": links,
            "next": nxt_page.group(1) if nxt_page else None,
        }
    else:
        out["pager"] = None
    star = re.search(r'hx-post="/messages/thread/([^/"]+)/star"', html)
    out["selected"] = star.group(1) if star else ""
    rules = root.first(lambda n: n.tag == "h3" and n.text() == "Message Rules")
    out["rules"] = [
        s.text()
        for s in rules.parent.parent.all(
            lambda n: n.tag == "span" and "leading-snug" in n.cls()
        )
    ]
    return out


def go_page(answer):
    out = {
        "eyebrow": answer.get("eyebrow", ""),
        "title": answer.get("title", ""),
        "description": answer.get("description", ""),
        "tabs": [],
        "threads": [],
    }
    for t in answer.get("tabs", []):
        out["tabs"].append(
            [
                t["key"],
                t["label"],
                str(t.get("count", 0)) if t.get("hasCount") else None,
            ]
        )
    out["sorts"] = [
        [s["value"], s["label"], bool(s.get("selected"))]
        for s in answer.get("sorts", [])
    ]
    for r in answer.get("threads", []):
        out["threads"].append(
            {
                "id": r["id"],
                "avatar": "gear" if r.get("isSystem") else r.get("initials", ""),
                "sender": r.get("senderName", ""),
                "when": r.get("lastAtLabel", ""),
                "unread": bool(r.get("unread")),
                "subject": norm(r.get("subject")),
                "snippet": norm(r.get("snippet")),
                "badge": r.get("contextBadge", ""),
                "tone": r.get("contextTone", ""),
                "priority": r.get("priorityBadge", ""),
                "priority_tone": r.get("priorityTone", ""),
                "starred": bool(r.get("starred")),
                "selected": bool(r.get("selected")),
            }
        )
    out["empty"] = (
        [answer.get("emptyTitle", ""), answer.get("emptyMessage", "")]
        if not out["threads"]
        else None
    )
    pager = answer.get("pager", {})
    if pager.get("shown"):
        nxt = re.search(r"[?&]page=(\d+)", pager.get("nextHref", ""))
        out["pager"] = {
            "summary": pager.get("summary", ""),
            "links": [
                [
                    link["label"],
                    bool(link.get("current")),
                    bool(link.get("gap")),
                    None
                    if link.get("current") or link.get("gap")
                    else str(link.get("page")),
                ]
                for link in pager.get("links", [])
            ],
            "next": nxt.group(1) if nxt else None,
        }
    else:
        out["pager"] = None
    out["selected"] = answer.get("selectedThreadId", "")
    out["rules"] = answer.get("messageRules", [])
    return out


def rpc(method, body, token=None, service="edify.messaging.v1.MessagingService"):
    request = urllib.request.Request(
        f"{GATEWAY}/{service}/{method}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - a local gateway
            return 200, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


QUESTIONS = (
    [{}]
    + [
        {"tab": t}
        for t, _ in __import__(
            "apps.frontend.views.message_views", fromlist=["TABS"]
        ).TABS
    ]
    + [
        {"tab": "bogus"},
        {"q": "Cluster"},
        {"q": "  record  "},
        {"q": "zzz-none"},
        {"q": "ÜNÏ"},
        {"sort": "oldest"},
        {"sort": "oldest", "tab": "unread"},
        {"sort": "sideways"},
        {"page": "2"},
        {"page": "3"},
        {"page": "7"},
        {"page": "99"},
        {"page": "abc"},
        {"page": "0"},
        {"page": "-1"},
        {"page": " 2 "},
        {"tab": "all", "page": "2", "sort": "oldest"},
        {"thread": "nosuch-thread"},
    ]
    + [{"thread": t} for t in THREADS]
)

results = {"users": {}, "differing": 0, "equal": 0, "refused_both": 0}
PAUSE = float(os.environ.get("PAUSE", "0"))
for index, email in enumerate(USERS):
    if index and PAUSE:
        time.sleep(PAUSE)  # under the gateway's sign-in limit
    user = User.objects.get(email=email)
    status, signed = rpc(
        "SignIn",
        {"email": email, "password": PASSWORD},
        service="edify.identity.v1.SignInService",
    )
    token = signed.get("session", {}).get("accessToken")
    if not token:
        results["users"][email] = {"error": f"sign-in {status}"}
        results["differing"] += 1
        continue
    client = Client()
    client.force_login(user)
    diffs = []
    _, count = rpc("GetUnreadCount", {}, token)
    if count.get("unread", 0) != services.unread_thread_count(user):
        diffs.append(
            {
                "q": "unread-count",
                "go": count,
                "django": services.unread_thread_count(user),
            }
        )
    for q in QUESTIONS:
        go_status, answer = rpc("ListThreads", q, token)
        response = client.get("/messages", q)
        if response.status_code != 200 or go_status != 200:
            same = response.status_code == 404 and go_status == 404
            results["refused_both" if same else "differing"] += 1
            if not same:
                diffs.append(
                    {"q": q, "go": [go_status, answer], "django": response.status_code}
                )
            continue
        a, b = go_page(answer), django_page(response.content.decode())
        if os.environ.get("SAMPLE") and q == {}:
            results.setdefault("samples", {})[email] = {"go": a, "django": b}
        if a == b:
            results["equal"] += 1
        else:
            results["differing"] += 1
            diffs.append({"q": q, "go": a, "django": b})
    results["users"][email] = {
        "diffs": diffs,
        "threads_all": len(services.threads_for_user(user)),
    }
    print(email, "differing", len(diffs))
json.dump(
    results, open(os.environ["OUT"], "w"), indent=1, ensure_ascii=False, default=str
)
print(
    "questions",
    len(QUESTIONS),
    "users",
    len(USERS),
    "equal",
    results["equal"],
    "refused_both",
    results["refused_both"],
    "differing",
    results["differing"],
)
