"""Reads a rendered web page's shared components into the native app's blocks.

The profile pages (school, cluster, district, partner, staff) draw everything
through shared components — the page header, the profile tabs, the identity
card, the filter bar, the figure strips (components/context_metrics.html),
record tables and the insight rail — and most of their wording lives in the
templates. Reading those components from the page the web itself renders keeps
every label, figure, helper line and link exactly the web's, and follows the
web when it changes. Only the components are read; anything else on the page
is left out, never guessed at.

Python's own HTML parser is used, so the production app gains no dependency.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

#: Elements that never have content or an end tag.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}  # fmt: skip
#: Never shown as text.
SILENT = {"script", "style", "svg", "noscript", "template"}
#: The pill colours the page header uses, as the app's tones.
BADGE_TONES = (
    ("bg-emerald", "good"),
    ("bg-amber", "caution"),
    ("bg-rose", "alert"),
    ("bg-red", "alert"),
    ("bg-sky", "info"),
    ("bg-blue", "info"),
)
#: The tick-box column of a table whose rows can be ticked together.
PICK_CELL = "school-plan-table__select"
METER_SHARE = re.compile(r"(?:inline-size|width)\s*:\s*([\d.]+)%")


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent: Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node | str] = []
        self.parent = parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def has(self, name: str) -> bool:
        return name in self.classes

    def get(self, name: str) -> str:
        return self.attrs.get(name) or ""

    def nodes(self):
        """Every element below this one, in page order."""
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.nodes()

    def find(self, test) -> Node | None:
        return next((node for node in self.nodes() if test(node)), None)

    def find_all(self, test) -> list[Node]:
        return [node for node in self.nodes() if test(node)]

    def text(self, *, shown: bool = True) -> str:
        """The element's text, whitespace collapsed. ``shown`` leaves out what
        only a screen reader hears (``sr-only``), as the page shows it."""
        parts: list[str] = []
        self._collect(parts, shown)
        return " ".join("".join(parts).split())

    def _collect(self, parts: list[str], shown: bool) -> None:
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in SILENT or (shown and child.has("sr-only")):
                continue
            else:
                child._collect(parts, shown)


def _attrs(pairs) -> dict:
    return {key: (value if value is not None else "") for key, value in pairs}


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.open = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, _attrs(attrs), self.open)
        self.open.children.append(node)
        if tag not in VOID:
            self.open = node

    def handle_startendtag(self, tag, attrs):
        self.open.children.append(Node(tag, _attrs(attrs), self.open))

    def handle_endtag(self, tag):
        node = self.open
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.open = node.parent

    def handle_data(self, data):
        self.open.children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def _opens_drawer(node: Node) -> bool:
    """Whether the web opens what ``node`` links to as a drawer."""
    return node.get("hx-target") == "#drawer-container"


def _href(node: Node | None) -> str:
    if node is None:
        return ""
    link = node if node.tag == "a" else node.find(lambda n: n.tag == "a")
    return link.get("href") if link else ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _badge_tone(node: Node) -> str:
    classes = node.get("class")
    return next((tone for marker, tone in BADGE_TONES if marker in classes), "plain")


#: The tone a list row's icon square carries, by its background class.
ICON_TONES = (
    ("edify-primary-soft", "info"),
    ("bg-emerald", "good"),
    ("bg-green", "good"),
    ("bg-amber", "caution"),
    ("bg-rose", "alert"),
    ("bg-red", "alert"),
    ("bg-violet", "brand"),
    ("bg-purple", "brand"),
    ("bg-teal", "good"),
)


def _role_home(home: Node) -> dict:
    """The phone's task-first page header (components/mobile_role_home.html):
    eyebrow, headline, line, the figure it counts and its primary action."""
    copy = home.find(lambda n: n.has("mobile-role-home__copy"))
    eyebrow = copy.find(lambda n: n.tag == "p") if copy else None
    title = home.find(lambda n: n.tag == "h1")
    line = copy.find(lambda n: n.tag == "span") if copy else None
    context = home.find(lambda n: n.has("mobile-role-home__context"))
    action = home.find(lambda n: n.has("mobile-role-home__action") and n.tag == "a")
    label = action.find(lambda n: n.tag == "span") if action else None
    return {
        "eyebrow": eyebrow.text() if eyebrow else "",
        "backLabel": "",
        "backHref": "",
        "title": title.text() if title else "",
        "description": line.text() if line else "",
        "badges": [
            {"text": part.text(), "tone": "plain", "title": ""}
            for part in (context.children if context else ())
            if isinstance(part, Node) and part.text()
        ],
        "actions": (
            [
                {
                    "key": "primary-action",
                    "label": label.text() if label else action.text(),
                    "primary": True,
                    "enabled": True,
                    "reason": "",
                    "href": action.get("href"),
                }
            ]
            if action
            else []
        ),
    }


#: The classes that draw a header control as a button (a link among them).
HEADER_BUTTON_CLASSES = ("btn", "edify-action-button")
#: A link whose path ends here downloads a file (Staff Activity's Export).
DOWNLOAD_PATH_END = "/export"


def _is_header_action(node: Node, in_controls: bool) -> bool:
    """A control of the header band the app offers as an action. In the
    controls slot every button is one; beside it (Planning's button row, a
    page header's aside) only what is drawn as an action button."""
    drawn = any(node.has(name) for name in HEADER_BUTTON_CLASSES)
    if node.tag == "button":
        return in_controls or drawn
    return node.tag == "a" and drawn


def _downloads(href: str) -> bool:
    """Whether a header link downloads a file (an export) rather than opening
    a page: its query names an export, which the feed never passes on."""
    from urllib.parse import parse_qsl, urlparse

    from apps.mobile_feed.views import NOT_PASSED

    url = urlparse(href)
    keys = {key for key, _ in parse_qsl(url.query, keep_blank_values=True)}
    return bool(keys & NOT_PASSED) or url.path.endswith(DOWNLOAD_PATH_END)


def _resolved(href: str, path: str) -> str:
    """A header link as the app is given it: one written as a query alone
    ({% querystring %}) resolved on the page's path, and its parameters in
    name order without the blank ones, so it reads the same whatever order
    the page was asked in (the gateway passes no blank parameter on)."""
    from urllib.parse import parse_qsl, urlencode

    if "?" not in href:
        return href
    base, _, query = href.partition("?")
    if not base:
        if not path:
            return href
        base = path
    pairs = sorted(parse_qsl(query), key=lambda pair: pair[0])
    return f"{base}?{urlencode(pairs)}" if pairs else base


def _header_action(node: Node, path: str) -> dict:
    from apps.mobile_feed import dialogs

    label = node.text()
    enabled = "disabled" not in node.attrs
    # A button that opens one of the page's own dialogs opens its sheet.
    opens = dialogs.opener_href(node)
    href = _resolved(node.get("hx-get") or node.get("href") or opens, path)
    return {
        "key": _slug(label),
        "label": label,
        "primary": node.has("edify-primary-solid")
        or (node.has("edify-action-button") and node.has("primary")),
        "enabled": enabled,
        "reason": "" if enabled else node.get("title"),
        "href": href,
        "drawer": _opens_drawer(node) or bool(opens),
        "download": node.tag == "a" and ("download" in node.attrs or _downloads(href)),
    }


def _header(main: Node, path: str = "") -> dict:
    home = main.find(lambda n: "data-mobile-role-home" in n.attrs)
    if home is not None:
        return _role_home(home)
    back = main.find(lambda n: n.has("edify-back-link"))
    title = main.find(lambda n: n.tag == "h1")
    description = main.find(lambda n: n.has("edify-page-header__description"))
    controls = main.find(lambda n: n.has("edify-page-header__controls"))
    band = main.find(lambda n: n.has("edify-page-header"))
    lead = band.find(lambda n: n.has("edify-page-header__lead")) if band else None
    # The band holds the controls slot; a page without the slot (Planning)
    # draws its buttons beside the lead.
    holder = (
        band
        if band is not None and (controls is None or _inside(controls, band))
        else controls
    )
    badges, actions = [], []
    for node in holder.nodes() if holder else ():
        if lead is not None and _inside(node, lead):
            continue
        in_controls = controls is not None and _inside(node, controls)
        if in_controls and node.tag == "span" and node.has("rounded-pill"):
            badge = {
                "text": node.text(),
                "tone": _badge_tone(node),
                "title": node.get("title"),
            }
            # The year's support visit is taken: the page draws a lock.
            if "data-visit-closed" in node.attrs:
                badge["icon"] = "lock"
            badges.append(badge)
        elif _is_header_action(node, in_controls):
            actions.append(_header_action(node, path))
    eyebrow = main.find(lambda n: n.has("edify-page-eyebrow"))
    return {
        "eyebrow": eyebrow.text() if eyebrow else "",
        "backLabel": back.text() if back else "",
        "backHref": back.get("href") if back else "",
        "title": title.text() if title else "",
        "description": description.text() if description else "",
        "badges": badges,
        "actions": actions,
    }


def _tabs(main: Node) -> list[dict]:
    nav = main.find(lambda n: "data-profile-tabs" in n.attrs)
    tabs = []
    for link in nav.find_all(lambda n: n.tag == "a") if nav else ():
        query = parse_qs(urlparse(link.get("href")).query)
        tabs.append(
            {
                "key": (query.get("tab") or [""])[0],
                "label": link.text(),
                "active": link.has("is-active") or bool(link.get("aria-current")),
            }
        )
    return tabs


def _facts(section: Node) -> dict:
    facts = []
    for term in section.find_all(lambda n: n.tag == "dt"):
        value = term.parent.find(lambda n: n.tag == "dd") if term.parent else None
        facts.append(
            {
                "label": term.text(),
                "value": value.text() if value else "",
                "href": _href(value),
            }
        )
    return {"facts": facts}


def _filter_label(form: Node, select: Node) -> str:
    """A filter's name: the page's filter label beside it, the label it sits
    in or the label that names it, else what it says to a screen reader."""
    holder = select.parent
    marked = holder.find(lambda n: n.has("edify-filter-label")) if holder else None
    if marked is not None:
        return marked.text()
    if holder is not None and holder.tag == "label":
        own = "".join(c for c in holder.children if isinstance(c, str))
        if own.strip():
            return " ".join(own.split())
    if select.get("id"):
        named = form.find(
            lambda n: n.tag == "label" and n.get("for") == select.get("id")
        )
        if named is not None:
            return named.text()
    return select.get("aria-label")


def _filter_caption(select: Node) -> str:
    """The short word the page draws beside a select, in the same holder and
    before it ("FY" beside the "Fiscal year" select), when the select is named
    for a screen reader by something longer."""
    holder = select.parent
    if holder is None:
        return ""
    for child in holder.children:
        if child is select:
            return ""
        if (
            isinstance(child, Node)
            and child.tag == "span"
            and not child.has("sr-only")
            and not child.has("edify-filter-label")
            and child.text()
        ):
            return child.text()
    return ""


def _filters(form: Node) -> dict:
    filters = []
    for select in form.find_all(lambda n: n.tag == "select"):
        options = select.find_all(lambda n: n.tag == "option")
        chosen = next(
            (option.get("value") for option in options if "selected" in option.attrs),
            options[0].get("value") if options else "",
        )
        label = _filter_label(form, select)
        entry = {
            "name": select.get("name"),
            "label": label,
            "value": chosen,
            "options": [
                {"value": option.get("value"), "label": option.text()}
                for option in options
            ],
        }
        caption = _filter_caption(select)
        if caption and caption != label:
            entry["caption"] = caption
        # The page folds it under its own More filters (clusters/filters.html).
        if _ancestor(select, lambda n: "data-edify-filter-more-panel" in n.attrs):
            entry["more"] = True
        filters.append(entry)
    hidden = {
        node.get("name"): node.get("value")
        for node in form.find_all(
            lambda n: n.tag == "input" and n.get("type").lower() == "hidden"
        )
        if node.get("name")
    }
    return {"filters": filters, "hidden": hidden} if hidden else {"filters": filters}


def _metric(fact: Node) -> dict:
    label = fact.find(lambda n: n.has("context-metrics__label"))
    value = fact.find(lambda n: n.has("context-metrics__value"))
    helper = fact.find(lambda n: n.has("context-metrics__helper"))
    note = fact.find(lambda n: "data-kpi-note" in n.attrs)
    link = fact.find(lambda n: n.has("context-metrics__link"))
    return {
        "label": label.text() if label else "",
        "value": value.text() if value else "",
        "helper": helper.text() if helper else "",
        "note": note.text(shown=False) if note else "",
        "href": (link.get("href") or link.get("hx-get")) if link else "",
        "tone": helper.get("data-tone") if helper else "",
    }


def _strip(section: Node) -> dict:
    title = section.find(lambda n: n.has("context-metrics__title"))
    return {
        "title": title.text() if title else section.get("aria-label"),
        "metrics": [
            _metric(fact)
            for fact in section.find_all(lambda n: n.has("context-metrics__fact"))
        ],
    }


def _badge(cell: Node) -> tuple[str, bool]:
    """A cell drawn as one pill: its tone ("green", "amber" … from
    ``mp-badge--<tone>``, "primary" for the plain pill)."""
    pill = cell.find(
        lambda n: n.has("mp-badge") or (n.tag == "span" and n.has("rounded-pill"))
    )
    if pill is None or pill.text() != cell.text():
        return "", False
    tone = next(
        (
            name.removeprefix("mp-badge--")
            for name in pill.classes
            if name.startswith("mp-badge--")
        ),
        "primary",
    )
    return tone, True


def _row_actions(cell: Node) -> list[dict]:
    """A row's own buttons and the items of its Actions menu, in order."""
    actions = []
    for button in cell.find_all(lambda n: n.tag in ("button", "a")):
        path = button.get("hx-get") or (button.get("href") if button.tag == "a" else "")
        if not path or button.has("row-menu__trigger"):
            continue
        in_menu = button.has("row-menu__item")
        actions.append(
            {
                "key": "danger"
                if button.has("row-menu__item--danger")
                else ("menu" if in_menu else "button"),
                "label": button.text(),
                "primary": not in_menu,
                "enabled": "disabled" not in button.attrs,
                "reason": button.get("title"),
                "href": path,
                "drawer": _opens_drawer(button),
            }
        )
    return actions


#: A school's plan-status and Visit Lock chips (components/
#: school_planning_badges.html, partials/planning/visit_lock_cell.html).
PLANNING_CHIP = "school-planning-badge"


def _planning_pills(cell: Node) -> list[dict]:
    """The chips a cell draws side by side, each with the page's own
    planning tone, the hover sentence and, on a Visit Lock chip, its padlock:
    shut where the visit is held, open where it is not."""
    pills = []
    for chip in cell.find_all(lambda n: n.has(PLANNING_CHIP)):
        pill = {
            "text": chip.text(),
            "tone": chip.get("data-planning-tone"),
            "title": chip.get("title"),
        }
        if "data-visit-closed" in chip.attrs or chip.get("data-visit-lock"):
            pill["icon"] = "unlock" if pill["tone"] == "open" else "lock"
        pills.append(pill)
    return pills


def _cell(cell: Node) -> dict:
    if "data-record-action" in cell.attrs or cell.find(lambda n: n.has("row-menu")):
        note = cell.find(lambda n: n.has("row-menu__note"))
        return {
            "text": note.text() if note else "",
            "href": "",
            "tone": "",
            "strong": False,
            "actions": _row_actions(cell),
        }
    tone = cell.find(lambda n: bool(n.get("data-edify-tone")))
    strong = cell.find(lambda n: n.tag in ("strong", "b"))
    text = cell.text()
    badge_tone, is_badge = _badge(cell)
    read = {
        "text": text,
        "href": _href(cell),
        "tone": badge_tone
        if is_badge
        else (tone.get("data-edify-tone") if tone else ""),
        "strong": bool(strong and strong.text() == text),
        "badge": is_badge,
    }
    pills = _planning_pills(cell)
    if pills:
        read["pills"] = pills
    return read


def _pick(row: Node) -> dict:
    """The row's tick box (partials/activities/pick_cell.html): the activity
    it ticks for the Reschedule / Cancel bar, and what it says."""
    cell = next(
        (c for c in row.children if isinstance(c, Node) and c.has(PICK_CELL)), None
    )
    box = cell.find(lambda n: n.tag == "input") if cell else None
    if box is None or not box.get("value"):
        return {}
    return {"pickId": box.get("value"), "pickLabel": box.get("aria-label")}


def _row_tone(row: Node) -> str:
    """The row's colour as My Plan draws it: done green, overdue red, and
    work on a holiday or leave day marked."""
    if "data-done" in row.attrs:
        return "done"
    if "data-overdue" in row.attrs:
        return "overdue"
    if row.has("mp-dayoff-row"):
        return "dayoff"
    return ""


def _pager(holder: Node) -> dict | None:
    """The shared table pager (components/table_pager.html), when a table has
    more than one page."""
    nav = holder.find(lambda n: n.tag == "nav" and n.has("edify-pagination"))
    if nav is None:
        return None
    summary = nav.find(lambda n: n.has("edify-pagination__summary"))
    pages = []
    for node in nav.find_all(
        lambda n: n.has("edify-pagination__control")
        or n.has("edify-pagination__ellipsis")
    ):
        direction = node.has("edify-pagination__control--direction")
        label = node.get("aria-label") if direction else node.text()
        pages.append(
            {
                "label": "Prev"
                if direction and node.get("rel") == "prev"
                else ("Next" if direction else label or "…"),
                "href": node.get("href") if node.tag == "a" else "",
                "current": node.get("aria-current") == "page",
            }
        )
    return {"summary": summary.text() if summary else "", "pages": pages}


#: A pager's arrow buttons, by what they say to a screen reader.
PAGER_ARROWS = {"previous page": "Prev", "next page": "Next"}


def _scoped_pager(scope: Node) -> dict:
    """A page's own pager (edify-pagination-scope): "Showing 1 to 5 of 15
    clusters" and its page buttons, each loading that page of the list."""
    summary = scope.find(lambda n: n.tag == "span" and n.text().startswith("Showing"))
    pages = []
    for node in scope.find_all(lambda n: n.tag in ("a", "button", "span")):
        if node is summary or (
            node.tag == "span" and node.find(lambda n: n.tag == "span")
        ):
            continue
        href = node.get("hx-get") or (node.get("href") if node.tag == "a" else "")
        arrow = PAGER_ARROWS.get(node.get("aria-label").lower())
        label = (
            arrow or node.text() or ("…" if node.get("aria-hidden") == "true" else "")
        )
        if not label or (
            node.tag == "span" and summary is not None and _inside(node, summary)
        ):
            continue
        pages.append(
            {
                "label": label,
                "href": href,
                "current": node.get("aria-current") == "page",
            }
        )
    pager = {"summary": summary.text() if summary else "", "pages": pages}
    size = scope.find(lambda n: n.tag == "select" and n.get("name") == "per_page")
    if size is not None:
        # The chooser read as a filter form of its own.
        holder = Node("form", {}, None)
        holder.children = [size]
        pager["size"] = _filters(holder)["filters"][0]
    return pager


def _ancestor(node: Node, test) -> Node | None:
    """The nearest element around ``node`` that passes ``test``."""
    holder = node.parent
    while holder is not None:
        if test(holder):
            return holder
        holder = holder.parent
    return None


def _inside(node: Node | None, ancestor: Node) -> bool:
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _footnote(holder: Node, table: Node) -> str:
    """The note a table card prints under its table."""
    seen = False
    for node in holder.nodes():
        if node is table:
            seen = True
        elif seen and node.tag == "p" and not _inside(node, table):
            return node.text()
    return ""


def _card_head(
    holder: Node, table: Node | None
) -> tuple[Node | None, Node | None, str]:
    """A plain card's heading row, drawn above its table (My Plan's cards):
    the title on the left and, on the right, its count pill or a summary
    line ("15 clusters · 15 without a meeting")."""
    heading = holder.find(
        lambda n: n.tag in ("h2", "h3") and (table is None or not _inside(n, table))
    )
    if heading is None:
        return None, None, ""
    head = heading
    while head.parent is not None and head.parent is not holder:
        head = head.parent
    parts = (
        [c for c in head.children if isinstance(c, Node)] if head is not heading else []
    )
    aside = parts[-1] if len(parts) > 1 and not _inside(heading, parts[-1]) else None
    if aside is None:
        return heading, None, ""
    count = aside.find(
        lambda n: n.tag == "span" and n.has("rounded-pill") and n.text().isdigit()
    )
    if count is not None and count.text() == aside.text():
        return heading, count, ""
    return heading, None, aside.text()


def _empty_action(holder: Node) -> dict | None:
    empty = holder.find(lambda n: n.has("edify-empty-state"))
    link = empty.find(lambda n: n.tag == "a") if empty else None
    if link is None:
        return None
    label = (
        " ".join("".join(c for c in link.children if isinstance(c, str)).split())
        or link.text()
    )
    return {
        "key": "empty",
        "label": label,
        "primary": False,
        "enabled": True,
        "reason": "",
        "href": link.get("href"),
    }


def _table(holder: Node, table: Node) -> dict:
    titlebar = holder.find(lambda n: n.has("edify-table-titlebar"))
    title = titlebar.find(lambda n: n.tag in ("h2", "h3")) if titlebar else None
    subtitle = (
        titlebar.find(lambda n: n.tag == "span" and n.parent is titlebar)
        if titlebar
        else None
    )
    count, summary = None, ""
    if titlebar is None and holder.has("card"):
        title, count, summary = _card_head(holder, None if holder is table else table)
    head = table.find(lambda n: n.tag == "thead")
    columns = [
        {"label": th.text(), "numeric": th.has("text-right")}
        for th in (head.find_all(lambda n: n.tag == "th") if head else ())
        if not th.has(PICK_CELL)
    ]
    body = table.find(lambda n: n.tag == "tbody") or table
    if head is None and len(table.find_all(lambda n: n.tag == "tbody")) > 1:
        # A table without a head whose groups are its bodies (the budget
        # ledger: one body an activity group, then the grand total) is read
        # whole; the first body alone hid every group after the first.
        body = table
    rows: list[dict] = []
    for row in body.find_all(lambda n: n.tag == "tr"):
        if head and _inside(row, head):
            continue
        if _is_detail_row(row):
            # What opening the row above shows: under that row, not a row.
            if rows:
                rows[-1] = {**rows[-1], **_row_details(row)}
            continue
        rows.append(
            {
                "cells": [
                    _cell(cell)
                    for cell in row.children
                    if isinstance(cell, Node)
                    and cell.tag in ("td", "th")
                    and not cell.has(PICK_CELL)
                ],
                "tone": _row_tone(row),
                **_pick(row),
            }
        )
    result = {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else summary,
        "columns": columns,
        "rows": rows,
        "footnote": _footnote(holder, table) if holder is not table else "",
    }
    if count is not None:
        result["count"] = count.text()
    if table is holder or not rows:
        message = _empty_message(holder)
        if message:
            result["emptyMessage"] = message
        action = _empty_action(holder)
        if action:
            result["emptyAction"] = action
    pager = _pager(holder) if holder is not table else None
    if pager:
        result["pager"] = pager
    return result


def _is_detail_row(row: Node) -> bool:
    """A row the web opens under the row above it (the school's details)."""
    if row.has("school-plan-table__details"):
        return True
    cells = [c for c in row.children if isinstance(c, Node) and c.tag == "td"]
    return bool(row.get("x-show")) and len(cells) == 1 and bool(cells[0].get("colspan"))


def _row_details(row: Node) -> dict:
    """An opened row's facts and the link to the record's own page."""
    from apps.mobile_feed import records

    facts = [
        fact
        for holder in row.find_all(lambda n: n.tag == "dl")
        for fact in records.facts(holder)
    ]
    link = row.find(lambda n: n.tag == "a" and bool(n.get("href")))
    # What else the open row shows (the school's SSA scores), as page blocks.
    rest = Node("div", {}, None)
    for cell in row.children:
        if not isinstance(cell, Node):
            continue
        rest.children += [
            child
            for child in cell.children
            if isinstance(child, Node) and child is not link and child.tag != "dl"
        ]
    return {
        "details": facts,
        "detailsHref": link.get("href") if link else "",
        "detailBlocks": _blocks(rest, []),
    }


def _meter(item: Node) -> dict:
    name = item.find(lambda n: n.has("edify-rail__name"))
    value = item.find(lambda n: n.has("edify-rail__value"))
    fill = item.find(lambda n: bool(METER_SHARE.search(n.get("style"))))
    share = METER_SHARE.search(fill.get("style")) if fill else None
    return {
        "label": name.text() if name else "",
        "value": value.text() if value else "",
        "fraction": round(float(share.group(1)) / 100, 4) if share else 0.0,
        "href": _href(name),
    }


def _rail_part(part: Node) -> dict:
    heading = part.find(lambda n: n.tag in ("h3", "h4"))
    figure = part.find(lambda n: n.has("edify-rail__figure"))
    figure_link = figure.find(lambda n: n.tag == "a") if figure else None
    small = figure.find(lambda n: n.tag == "small") if figure else None
    note = part.find(lambda n: n.has("edify-rail__note"))
    if figure_link is not None:
        shown = figure_link.text()
    elif figure is not None:
        shown = figure.text().removesuffix(small.text() if small else "").strip()
    else:
        shown = ""
    meters = [
        _meter(item)
        for meter_list in part.find_all(lambda n: n.has("edify-rail__meters"))
        for item in meter_list.children
        if isinstance(item, Node) and item.tag == "li"
    ]
    links = [
        {"text": link.text(), "href": link.get("href")}
        for link_list in part.find_all(lambda n: n.has("edify-rail__links"))
        for link in link_list.find_all(lambda n: n.tag == "a")
    ]
    return {
        "key": part.get("data-rail-part"),
        "title": heading.text() if heading else "",
        "figure": shown,
        "figureHref": _href(figure_link),
        "figureNote": small.text() if small else "",
        "meters": meters,
        "note": note.text() if note else "",
        "links": links,
    }


def _rail(aside: Node) -> dict:
    head = aside.find(lambda n: n.has("edify-rail__head"))
    title = head.find(lambda n: n.tag in ("h2", "h3")) if head else None
    subtitle = head.find(lambda n: n.tag == "p") if head else None
    return {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else "",
        "parts": [
            _rail_part(part)
            for part in aside.find_all(lambda n: n.has("edify-rail__part"))
        ],
    }


def _empty_message(node: Node) -> str:
    empty = (
        node
        if node.has("edify-empty-state")
        else node.find(lambda n: n.has("edify-empty-state"))
    )
    message = (
        empty.find(lambda n: n.has("edify-empty-state__message")) if empty else None
    )
    return (message or empty).text() if empty else ""


def _chart(section: Node) -> dict:
    """A bar chart, from the data the page hands its chart (a JSON script)."""
    title = section.find(lambda n: n.has("edify-data-chart__title"))
    subtitle = section.find(lambda n: n.has("edify-data-chart__subtitle"))
    script = section.find(
        lambda n: n.tag == "script" and n.get("type") == "application/json"
    )
    try:
        payload = (
            json.loads("".join(c for c in script.children if isinstance(c, str)))
            if script
            else {}
        )
    except ValueError:
        payload = {}
    yaxis = payload.get("yaxis") if isinstance(payload.get("yaxis"), dict) else {}
    axis_title = yaxis.get("title") if isinstance(yaxis.get("title"), dict) else {}
    return {
        "title": title.text() if title else section.get("aria-label"),
        "subtitle": subtitle.text() if subtitle else "",
        "horizontal": bool(
            ((payload.get("plotOptions") or {}).get("bar") or {}).get("horizontal")
        ),
        "categories": [
            str(category)
            for category in (payload.get("xaxis") or {}).get("categories") or []
        ],
        # A reading with no value draws no bar.
        "series": [
            {
                "name": str(series.get("name", "")),
                "values": [
                    float(v) if v is not None else 0.0 for v in series.get("data") or []
                ],
            }
            for series in payload.get("series") or []
        ],
        "min": float(yaxis.get("min") or 0),
        "max": float(yaxis.get("max") or 0),
        "axisTitle": str(axis_title.get("text", "")),
    }


def _field(holder: Node) -> dict | None:
    label = holder.find(lambda n: n.has("edify-profile-field__label"))
    value = holder.find(lambda n: n.has("edify-profile-field__value"))
    if label is None:
        return None
    return {
        "label": label.text(),
        "value": value.text() if value else "",
        "href": _href(value),
    }


def _data_row(row: Node) -> dict:
    label = row.find(lambda n: n.has("edify-data-row__label"))
    meta = row.find(lambda n: n.has("edify-data-row__meta"))
    value = row.find(lambda n: n.has("edify-data-row__value"))
    return {
        "label": label.text() if label else "",
        "meta": meta.text() if meta else "",
        "value": value.text() if value else "",
        "tone": (value.get("data-edify-tone") or value.get("data-tone"))
        if value
        else "",
    }


def _list_link(item: Node) -> dict:
    caption = item.find(lambda n: n.has("block") or n.has("edify-text-caption"))
    link = item.find(lambda n: n.tag == "a")
    if link is not None:
        text = link.text()
    else:
        text = item.text().removesuffix(caption.text() if caption else "").strip()
    return {
        "text": text,
        "href": link.get("href") if link else "",
        "caption": caption.text() if caption and caption is not link else "",
    }


def _tone_of(node: Node) -> str:
    toned = (
        node
        if node.get("data-tone") or node.get("data-edify-tone")
        else node.find(lambda n: bool(n.get("data-tone") or n.get("data-edify-tone")))
    )
    if toned is None:
        return ""
    return toned.get("data-edify-tone") or toned.get("data-tone")


HEADINGS = ("h2", "h3", "h4", "h5", "summary")


#: Elements a sentence runs through; anything else starts a part of its own.
INLINE = {
    "a", "abbr", "b", "br", "button", "code", "em", "i", "mark", "small",
    "span", "strong", "sub", "sup", "time", "u",
}  # fmt: skip


def _mixed(node: Node) -> bool:
    """Whether ``node`` holds words of its own beside its elements (a sentence
    around a link, a bold opening before the rest of the line)."""
    return any(isinstance(c, str) and c.strip() for c in node.children) and any(
        isinstance(c, Node) and c.tag not in SILENT and c.text() for c in node.children
    )


def _sentences(node: Node, skip: set[int], out: list[dict]) -> list[dict]:
    """A part whose own words run around its elements, read whole: each run of
    words and inline elements one text item (its bold opening as ``lead``, its
    links as ``textLinks`` at their words), each block inside it read in turn."""
    parts: list[str] = []
    links: list[dict] = []
    lead = ""

    def flush() -> None:
        nonlocal lead
        text = " ".join("".join(parts).split())
        if text:
            item = {"text": text}
            tone = node.get("data-edify-tone") or node.get("data-tone")
            if tone:
                item["tone"] = tone
            if lead:
                item["lead"] = lead
            if links:
                item["textLinks"] = list(links)
            out.append(item)
        parts.clear()
        links.clear()
        lead = ""

    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        if child.tag in SILENT or child.has("sr-only") or id(child) in skip:
            continue
        if child.tag not in INLINE:
            flush()
            _panel_parts([child], skip, out)
            continue
        if child.tag == "br":
            parts.append(" ")
            continue
        if child.tag in ("strong", "b") and not "".join(parts).strip():
            lead = child.text()
        if _is_link(child) and child.text():
            links.append(_link_item(child))
        child._collect(parts, True)
    flush()
    return out


def _panel_items(node: Node, skip: set[int], out: list[dict]) -> list[dict]:
    if _mixed(node):
        return _sentences(node, skip, out)
    return _panel_parts([c for c in node.children if isinstance(c, Node)], skip, out)


def _panel_parts(children: list[Node], skip: set[int], out: list[dict]) -> list[dict]:
    for index, child in enumerate(children):
        if id(child) in skip or child.tag in SILENT or child.has("sr-only"):
            continue
        if child.has("edify-field-grid"):
            fields = [
                field
                for holder in child.children
                if isinstance(holder, Node) and (field := _field(holder))
            ]
            out.append({"fields": {"facts": fields}})
        elif child.has("edify-data-list"):
            out.append(
                {
                    "rows": {
                        "rows": [
                            _data_row(row)
                            for row in child.find_all(lambda n: n.has("edify-data-row"))
                        ]
                    }
                }
            )
        elif child.tag in HEADINGS or child.has("edify-section__heading"):
            out.append({"heading": child.text()})
        elif child.has("edify-rail__figure"):
            small = child.find(lambda n: n.tag == "small")
            following = next(
                (c for c in children[index + 1 :] if c.has("edify-rail__meter")), None
            )
            if following is not None:
                skip.add(id(following))
            share = (
                METER_SHARE.search(fill.get("style"))
                if following is not None
                and (
                    fill := following.find(
                        lambda n: bool(METER_SHARE.search(n.get("style")))
                    )
                )
                else None
            )
            out.append(
                {
                    "meter": {
                        "label": small.text() if small else "",
                        "value": child.text()
                        .removesuffix(small.text() if small else "")
                        .strip(),
                        "fraction": round(float(share.group(1)) / 100, 4)
                        if share
                        else 0.0,
                        "href": _href(child),
                    }
                }
            )
        elif child.tag in ("ul", "ol"):
            out.append(
                {
                    "links": {
                        "links": [
                            _list_link(item)
                            for item in child.children
                            if isinstance(item, Node) and item.tag == "li"
                        ]
                    }
                }
            )
        elif child.has("edify-empty-state"):
            out.append({"text": _empty_message(child)})
        elif child.tag == "p" or (child.tag == "span" and _tone_of(child)):
            text = child.text()
            if text:
                item = {"text": text}
                tone = _tone_of(child)
                if tone:
                    item["tone"] = tone
                out.append(item)
        elif _is_link(child):
            link = _link_item(child)
            if link["text"]:
                if out and "links" in out[-1]:
                    out[-1]["links"]["links"].append(link)
                else:
                    out.append({"links": {"links": [link]}})
        elif child.tag in ("form", "select", "input", "textarea", "template"):
            continue
        elif not any(isinstance(c, Node) for c in child.children):
            text = child.text()
            if text:
                out.append({"text": text})
        else:
            _panel_items(child, skip, out)
    return out


def _is_link(node: Node) -> bool:
    """A link, or a button that opens something (a drawer, a page)."""
    if node.tag == "a":
        return bool(node.get("href") or node.get("hx-get"))
    return node.tag == "button" and bool(node.get("hx-get"))


def _link_item(node: Node) -> dict:
    """A link row: its first line, the lines under it as its caption."""
    lines = [
        c.text()
        for c in node.children
        if isinstance(c, Node) and c.text() and not c.has("sr-only")
    ]
    text = lines[0] if len(lines) > 1 else node.text()
    return {
        "text": text,
        "href": node.get("hx-get") or node.get("href"),
        "caption": " · ".join(lines[1:]) if len(lines) > 1 else "",
        "drawer": _opens_drawer(node),
    }


def _panel(node: Node) -> dict:
    """A titled card of record details."""
    title = node.find(lambda n: n.tag in ("h2", "h3"))
    header = title.parent if title is not None and title.parent is not node else title
    subtitle = (
        header.find(lambda n: n.tag == "p")
        if header is not None and header is not title
        else None
    )
    badges = [
        {"text": pill.text(), "tone": _badge_tone(pill), "title": pill.get("title")}
        for pill in (
            header.find_all(lambda n: n.tag == "span" and n.has("rounded-pill"))
            if header is not None and header is not title
            else ()
        )
    ]
    skip = {id(header)} if header is not None else set()
    return {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else "",
        "badges": badges,
        "items": _paired(_panel_items(node, skip, [])),
    }


#: A figure on its own: "0", "1,204", "68%", "5.8 / 10", "UGX 1.3M", "—".
FIGURE = re.compile(
    r"^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?"
    r"(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$"
)


PAGER_CAPTION = re.compile(r"^Showing\s+\d")


def _paired(items: list[dict]) -> list[dict]:
    """A label line followed by its figure ("Escalations to Review", "0"),
    as the panel's data rows rather than two loose lines; consecutive pairs
    share one list."""
    out: list[dict] = []
    index = 0
    while index < len(items):
        item = items[index]
        after = items[index + 1] if index + 1 < len(items) else None
        is_pair = (
            set(item) <= {"text", "tone"}
            # A pager's caption ("Showing 1–50 of 65") is not a label.
            and not PAGER_CAPTION.match(item["text"])
            and after is not None
            and set(after) <= {"text", "tone"}
            and any(c.isalpha() for c in item["text"])
            and FIGURE.match(after["text"].strip()) is not None
        )
        if not is_pair:
            out.append(item)
            index += 1
            continue
        row = {
            "label": item["text"],
            "meta": "",
            "value": after["text"].strip(),
            "tone": after.get("tone", ""),
        }
        if out and "rows" in out[-1]:
            out[-1]["rows"]["rows"].append(row)
        else:
            out.append({"rows": {"rows": [row]}})
        index += 2
    return out


def _switch_parts(node: Node) -> tuple[Node, list[tuple[Node, Node]]] | None:
    """The tab list inside ``node`` and its (button, part) pairs."""
    tablist = node.find(
        lambda n: "data-edify-tablist" in n.attrs or n.get("role") == "tablist"
    )
    if tablist is None:
        return None
    pairs = []
    for button in tablist.find_all(
        lambda n: "data-edify-tab" in n.attrs or n.get("role") == "tab"
    ):
        target = button.get("aria-controls")
        part = (
            node.find(lambda n, target=target: n.get("id") == target)
            if target
            else None
        )
        if part is None:
            return None
        pairs.append((button, part))
    return (tablist, pairs) if pairs else None


def _segments(node: Node, tablist: Node, pairs: list[tuple[Node, Node]]) -> dict:
    titlebar = node.find(lambda n: n.has("edify-table-titlebar"))
    title = titlebar.find(lambda n: n.tag in ("h2", "h3")) if titlebar else None
    subtitle = (
        titlebar.find(lambda n: n.tag == "span" and n.parent is titlebar)
        if titlebar
        else None
    )
    holder = tablist.parent
    caption = (
        holder.find(lambda n: n.tag == "p" and not _inside(n, tablist))
        if holder
        else None
    )
    segments = []
    for button, part in pairs:
        count = button.find(lambda n: "data-edify-tab-count" in n.attrs)
        label = button.text()
        if count is not None:
            label = label.removesuffix(count.text()).strip()
        segments.append(
            {
                "label": label,
                "count": count.text() if count else "",
                "active": button.get("aria-pressed") == "true"
                or button.get("aria-selected") == "true",
                "blocks": _blocks(part, []),
            }
        )
    return {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else "",
        "caption": caption.text() if caption else "",
        "segments": segments,
    }


def _beside_switch(
    node: Node, tablist: Node, pairs: list[tuple[Node, Node]]
) -> list[Node]:
    """What ``node`` holds besides its tab rail and the parts it switches
    (figures above the tabs): read on their own, not inside the switch."""
    parts = {id(part) for _, part in pairs}
    return [
        child
        for child in node.children
        if isinstance(child, Node)
        and child.tag not in SILENT
        and id(child) not in parts
        and child is not tablist
        and not _inside(tablist, child)
        and child.tag not in ("h2", "h3", "h4", "p", "header")
        and not child.has("edify-table-titlebar")
        and child.text()
    ]


#: The triggers that fetch a part of the page once it is open or in view.
LATER_TRIGGERS = re.compile(r"^\s*(load\b|intersect\b|revealed\b|load-[a-z-]+)")


#: The request headers a part's section sets (``hx-headers``) that the feed
#: sends on with the part: the dashboard's embed mark, without which the
#: Planning Monitor and Staff Activity answer a Programme Lead with a redirect.
FORWARDED_HEADERS = frozenset({"X-Edify-Embed"})


def _sent_headers(node: Node) -> dict[str, str]:
    """The headers htmx sends with ``node``'s request: the nearest
    ``hx-headers`` of each name, among those the feed forwards."""
    sent: dict[str, str] = {}
    holder: Node | None = node
    while holder is not None:
        try:
            declared = json.loads(holder.get("hx-headers") or "{}")
        except ValueError:
            declared = {}
        if isinstance(declared, dict):
            for name, value in declared.items():
                if name in FORWARDED_HEADERS and isinstance(value, str):
                    sent.setdefault(name, value)
        holder = holder.parent
    return sent


def _loads_later(node: Node) -> bool:
    """A part the page fetches once it is open or scrolled into view (never a
    drawer, which opens into the drawer container)."""
    return (
        bool(node.get("hx-get"))
        and bool(LATER_TRIGGERS.match(node.get("hx-trigger")))
        and node.get("hx-target") != "#drawer-container"
    )


def _section_nav(nav: Node) -> dict | None:
    """The strip of a workspace's sibling pages (partials/_section_nav.html):
    real links in the tab look, scrolling sideways on a phone."""
    if not nav.has("edify-section-nav"):
        return None
    links = nav.find_all(
        lambda n: n.tag == "a"
        and (n.has("edify-section-nav__link") or n.has("edify-section-nav__cluster"))
    )
    if not links:
        return None
    eyebrow = nav.find(lambda n: n.has("edify-section-nav__eyebrow"))
    return {
        "tabs": [
            {"label": a.text(), "href": a.get("href"), "active": a.has("is-active")}
            for a in links
        ],
        "label": eyebrow.text() if eyebrow else "",
        "scrolls": True,
    }


def _is_beside_link(node: Node) -> bool:
    """The link drawn beside a rail of link tabs (Open Calendar): the rail
    carries it, so it is not read again on its own."""
    if node.tag != "a" or node.parent is None:
        return False
    siblings = [c for c in node.parent.children if isinstance(c, Node)]
    before = siblings[: siblings.index(node)]
    return any(
        sibling.tag == "nav" and "data-edify-beside-link" in sibling.attrs
        for sibling in before
    )


def sibling_switch(node: Node) -> tuple[dict, set[int]] | None:
    """A tab rail whose parts sit beside it in a container that also holds
    other things: the switch as a block, and the parts it takes."""
    if node.parent is None or not (
        "data-edify-tablist" in node.attrs or node.get("role") == "tablist"
    ):
        return None
    holder = node.parent
    switch = _switch_parts(holder)
    if switch is None or switch[0] is not node or not _beside_switch(holder, *switch):
        return None
    return _segments(holder, *switch), {id(part) for _, part in switch[1]}


def _holds_switch(node: Node) -> bool:
    return _switch_parts(node) is not None


def _table_card(node: Node) -> Node | None:
    """The table a titled table card holds (or the card itself, when it shows
    an empty state instead), if ``node`` is one: a card with the shared
    titlebar, or a plain card whose heading sits above its table."""
    if not node.find(lambda n: n.has("edify-table-titlebar")):
        return _plain_table_card(node)
    if node.find(lambda n: n.has("context-metrics") or "data-insight-rail" in n.attrs):
        return None
    table = node.find(lambda n: n.tag == "table")
    if table is None and node.find(lambda n: n.has("edify-empty-state")):
        return node
    return table


def _plain_table_card(node: Node) -> Node | None:
    if not node.has("card"):
        return None
    tables = node.find_all(lambda n: n.tag == "table")
    heading = node.find(lambda n: n.tag in ("h2", "h3"))
    if heading is None or len(tables) > 1:
        return None
    if tables:
        return tables[0]
    return node if node.find(lambda n: n.has("edify-empty-state")) else None


def _tile_grid(node: Node) -> dict | None:
    """A card of figure tiles (My Plan's Plan Breakdown by Period): a heading,
    a line under it, and tiles of an uppercase label over a figure."""
    if not node.has("card") or node.find(lambda n: n.tag == "table"):
        return None
    grid = node.find(lambda n: n.has("grid"))
    heading = node.find(lambda n: n.tag in ("h2", "h3"))
    if grid is None or heading is None:
        return None
    metrics = []
    for tile in grid.children:
        if not isinstance(tile, Node):
            continue
        label = tile.find(lambda n: n.tag == "p" and n.has("uppercase"))
        figure = next(
            (p for p in tile.find_all(lambda n: n.tag == "p") if p is not label),
            None,
        )
        if label is None or figure is None:
            return None
        metrics.append(
            {
                "label": label.text(),
                "value": figure.text(),
                "helper": "",
                "note": "",
                "href": "",
                "tone": "",
            }
        )
    subtitle = heading.parent.find(lambda n: n.tag == "p") if heading.parent else None
    return {
        "title": heading.text(),
        "subtitle": subtitle.text() if subtitle else "",
        "metrics": metrics,
    }


#: A tab that sets a field of the page's filter form and sends it:
#: ``document.querySelector('#filters-form [name=tab]').value = 'core'``.
SETS_FORM_FIELD = re.compile(
    r"querySelector\(\s*'#([\w-]+)\s+\[name=(\w+)\]'\s*\)\.value\s*=\s*'([^']*)'"
)


def _form_tabs(nav: Node) -> dict | None:
    """Tabs that set a field of the page's filter form and send it
    (Planning's Client Schools … Scheduled): each a link to the form's
    values as they stand, that field changed."""
    from urllib.parse import urlencode

    tabs = [n for n in nav.find_all(lambda n: n.get("role") == "tab")]
    sets = [SETS_FORM_FIELD.search(tab.get("@click")) for tab in tabs]
    if not tabs or not all(sets):
        return None
    root = nav
    while root.parent is not None:
        root = root.parent
    form = root.find(lambda n: n.tag == "form" and n.get("id") == sets[0].group(1))
    if form is None:
        return None
    values = _form_state(form)
    return {
        "tabs": [
            {
                "label": tab.text(),
                "href": "?" + urlencode({**values, found.group(2): found.group(3)}),
                "active": tab.get("aria-selected") == "true",
            }
            for tab, found in zip(tabs, sets)
        ]
    }


def _form_state(form: Node) -> dict[str, str]:
    """What a GET form sends as it stands: each field's value, empty ones left out."""
    values: dict[str, str] = {}
    for node in form.find_all(
        lambda n: n.tag in ("input", "select") and bool(n.get("name"))
    ):
        if node.tag == "select":
            options = node.find_all(lambda n: n.tag == "option")
            chosen = next((o for o in options if "selected" in o.attrs), None)
            value = (
                chosen.get("value")
                if chosen
                else (options[0].get("value") if options else "")
            )
        elif node.get("type").lower() in ("checkbox", "radio"):
            value = node.get("value") if "checked" in node.attrs else ""
        else:
            value = node.get("value")
        if value:
            values[node.get("name")] = value
    return values


def _entity_tabs(nav: Node) -> dict | None:
    """An oversight page's section links (My Performance's Executive Summary
    … November Summary, Cluster Oversight's sections): link tabs."""
    if not nav.has("oversight-entity-tabs"):
        return None
    links = nav.find_all(
        lambda n: n.tag == "a" and n.has("oversight-entity-tabs__link")
    )
    if not links:
        return None
    return {
        "tabs": [
            {
                "label": a.text(),
                "href": a.get("href"),
                "active": a.has("is-active") or a.get("aria-current") == "page",
            }
            for a in links
        ],
        # Long section names: every link on one strip that scrolls sideways.
        "scrolls": True,
    }


def _link_tabs(nav: Node) -> dict | None:
    """Tabs that are links (My Plan's This Week … This FY), with the link set
    beside them (Open Calendar)."""
    if "data-profile-tabs" in nav.attrs or "data-edify-tablist" not in nav.attrs:
        return None
    links = [
        a for a in nav.find_all(lambda n: n.tag == "a" and "data-edify-tab" in n.attrs)
    ]
    if not links:
        return None
    beside = None
    if "data-edify-beside-link" in nav.attrs and nav.parent is not None:
        siblings = [c for c in nav.parent.children if isinstance(c, Node)]
        after = siblings[siblings.index(nav) + 1 :]
        link = next((c for c in after if c.tag == "a" and c.has("btn")), None)
        if link is not None:
            beside = {
                "key": "beside",
                "label": link.get("aria-label") or link.text(),
                "primary": link.has("btn-primary"),
                "enabled": True,
                "reason": "",
                "href": link.get("href"),
            }
    result = {
        "tabs": [
            {
                "label": a.text(),
                "href": a.get("href"),
                "active": a.get("aria-current") == "page",
            }
            for a in links
        ]
    }
    if beside:
        result["beside"] = beside
    return result


def _row_lines(row: Node) -> list[str]:
    """A row's lines of text, its pills and actions aside."""
    column = row.find(lambda n: n.has("flex-1") or n.has("min-w-0"))
    holder = column or row
    lines = [
        p.text()
        for p in holder.find_all(lambda n: n.tag in ("p", "h3", "h4"))
        if p.text()
    ]
    return lines or ([holder.text()] if holder.text() else [])


def _list_item(row: Node) -> dict:
    icon = row.find(
        lambda n: n.tag == "div"
        and any(marker in n.get("class") for marker, _ in ICON_TONES)
        and n.find(lambda m: m.tag == "svg") is not None
    )
    tone = (
        next((t for marker, t in ICON_TONES if marker in icon.get("class")), "")
        if icon
        else ""
    )
    actions = [
        {
            "key": "button",
            "label": link.text(),
            "primary": "edify-primary" in link.get("class"),
            "enabled": "disabled" not in link.attrs,
            "reason": link.get("title"),
            "href": link.get("hx-get") or link.get("href"),
            "drawer": _opens_drawer(link),
        }
        for link in row.find_all(_is_link)
        if link.text()
    ]
    badges = [
        {"text": pill.text(), "tone": _badge_tone(pill), "title": pill.get("title")}
        for pill in row.find_all(lambda n: n.tag == "span" and n.has("rounded-pill"))
        if pill.text()
    ]
    lines = _row_lines(row)
    return {
        "title": lines[0] if lines else "",
        "lines": lines[1:],
        "badges": badges,
        "actions": actions,
        "href": row.get("href") if row.tag == "a" else "",
        "tone": tone,
    }


#: `name === 'value'` in a row's x-show: the client-side filter it answers to.
SHOWN_FOR = re.compile(r"(\w+)\s*===\s*'([^']*)'")
#: `name='value'` in a chip's @click.
CHIP_SETS = re.compile(r"^\s*(\w+)\s*=\s*'([^']*)'\s*;?\s*$")


def _row_keys(row: Node) -> dict[str, str]:
    """What a row is filtered on in the browser (``x-show`` naming
    ``cat === 'Finance'``), the "all" alternatives aside."""
    holder = row if row.get("x-show") else row.find(lambda n: bool(n.get("x-show")))
    expression = holder.get("x-show") if holder is not None else ""
    return {
        name: value for name, value in SHOWN_FOR.findall(expression) if value != "all"
    }


def _group_item(details: Node) -> dict:
    """An entry that opens onto its records (identical To-Dos as one)."""
    summary = details.find(lambda n: n.tag == "summary")
    spans = (
        [
            s
            for s in summary.find_all(lambda n: n.tag == "span" and n.has("block"))
            if s.text()
        ]
        if summary
        else []
    )
    count = summary.find(lambda n: n.has("todo-group__count")) if summary else None
    rows_holder = next(
        (c for c in details.children if isinstance(c, Node) and c.tag != "summary"),
        None,
    )
    children = (
        [
            _list_item(r)
            for r in rows_holder.children
            if isinstance(r, Node) and r.text()
        ]
        if rows_holder is not None
        else []
    )
    return {
        "title": spans[0].text() if spans else (summary.text() if summary else ""),
        "lines": [s.text() for s in spans[1:]],
        "badges": [],
        "actions": [],
        "href": "",
        "tone": "",
        "children": children,
        "count": count.text() if count else str(len(children)),
        "keys": _row_keys(details),
    }


def _row_item(row: Node) -> dict:
    details = row if row.tag == "details" else None
    if details is not None:
        return _group_item(details)
    return {**_list_item(row), "keys": _row_keys(row)}


def _row_list(card: Node) -> dict | None:
    """A card of rows, one record each (a task, an activity, a request)."""
    if not (card.has("card") or card.has("edify-surface")) or not card.has("divide-y"):
        return None
    if card.find(lambda n: n.tag == "table"):
        return None
    rows = [c for c in card.children if isinstance(c, Node) and c.text()]
    if not rows:
        return None
    return {
        "title": "",
        "count": "",
        "subtitle": "",
        "items": [_row_item(row) for row in rows],
    }


def _chips(rail: Node) -> dict | None:
    """Buttons that filter the page in the browser (To-Do's categories): the
    value each sets, its label and count, and the value the page opens on."""
    if "data-edify-tablist" not in rail.attrs or rail.tag == "nav":
        return None
    chips, name = [], ""
    buttons = rail.find_all(lambda n: n.tag == "button" and "data-edify-tab" in n.attrs)
    if any(button.get("aria-controls") for button in buttons):
        return None  # a switch between parts of a card: _segments reads it
    for button in buttons:
        sets = CHIP_SETS.match(button.get("@click"))
        if sets is None:
            return None
        name = sets.group(1)
        count = button.find(lambda n: "data-edify-tab-count" in n.attrs)
        label = " ".join(
            "".join(c for c in button.children if isinstance(c, str)).split()
        )
        chips.append(
            {
                "value": sets.group(2),
                "label": label or button.text(),
                "count": count.text() if count else "",
            }
        )
    if not chips:
        return None
    return {
        "name": name,
        "label": rail.get("aria-label"),
        "value": _opening_value(rail, name),
        "chips": chips,
    }


def _opening_value(node: Node, name: str) -> str:
    """The value the page's script starts ``name`` on (x-data="{ cat: 'all' }")."""
    from apps.mobile_feed.planning_drawers import script_values

    holder = node
    while holder is not None:
        if holder.get("x-data"):
            value = script_values(holder.get("x-data")).get(name)
            if value is not None:
                return str(value)
        holder = holder.parent
    return ""


def _home_section(section: Node) -> dict | None:
    """A phone home's titled section of rows ("Do next  45 open")."""
    if not section.has("mobile-home-section"):
        return None
    head = section.find(lambda n: n.has("mobile-home-section__header"))
    title = head.find(lambda n: n.tag in ("h2", "h3")) if head else None
    count = head.find(lambda n: n.tag == "span") if head else None
    card = section.find(lambda n: _row_list(n) is not None)
    found = _row_list(card) if card is not None else None
    if found is None:
        return None
    return {
        **found,
        "title": title.text() if title else "",
        "count": count.text() if count else "",
    }


def _is_filter_form(node: Node) -> bool:
    """A form of selects that reloads the page it is on (method GET): the
    page's filters, in any of the web's shapes."""
    if node.tag != "form" or node.has("edify-filter-bar"):
        return False
    if (
        node.get("data-component") == "filter-toolbar"
        or "data-edify-filter-row" in node.attrs
    ):
        return True
    is_get = (node.get("method") or "get").lower() == "get" and not node.get("hx-post")
    return is_get and node.find(lambda n: n.tag == "select") is not None


def _block(node: Node) -> dict | None:
    """The block ``node`` is, or None to look inside it."""
    from apps.mobile_feed import css_charts, inline_charts, page_forms, records

    if records.is_record(node):
        return {"record": records.read(node)}
    if (form := page_forms.read(node)) is not None:
        return {"form": form}
    if node.has("edify-pagination-scope"):
        return {"pager": _scoped_pager(node)}
    if (section := _home_section(node)) is not None:
        return {"list": section}
    if (chips := _chips(node)) is not None:
        return {"chips": chips}
    if (rows := _row_list(node)) is not None:
        return {"list": rows}
    if (
        node.tag == "nav"
        and (tabs := _link_tabs(node) or _section_nav(node) or _entity_tabs(node))
        is not None
    ):
        return {"linkTabs": tabs}
    if node.get("role") == "tablist" and (tabs := _form_tabs(node)) is not None:
        return {"linkTabs": tabs}
    if _is_filter_form(node):
        return {"filters": _filters(node)}
    if node.tag == "p" and "data-profile-scope" in node.attrs:
        return {"scopeLine": node.text()}
    if "data-profile-identity" in node.attrs or (
        node.tag == "dl" and node.find(lambda n: n.tag == "dt")
    ):
        return {"facts": _facts(node)}
    if node.tag == "form" and node.has("edify-filter-bar"):
        return {"filters": _filters(node)}
    if node.tag == "section" and node.has("context-metrics"):
        return {"strip": _strip(node)}
    if "data-insight-rail" in node.attrs:
        return {"rail": _rail(node)}
    if node.tag == "section" and node.has("edify-data-chart"):
        return {"chart": _chart(node)}
    switch = _switch_parts(node)
    if (
        switch is not None
        and not any(
            isinstance(child, Node) and _holds_switch(child) for child in node.children
        )
        and not _beside_switch(node, *switch)
    ):
        return {"segments": _segments(node, *switch)}
    if switch is not None:
        return None
    if node.tag in ("section", "div") and (
        node.has("card") or node.has("edify-surface")
    ):
        table = _table_card(node)
        if table is not None:
            return {"table": _table(node, table)}
        tiles = _tile_grid(node)
        if tiles is not None:
            return {"strip": tiles}
    if (chart := inline_charts.read(node)) is not None:
        return {"chart": chart}
    if (bars := css_charts.bar_card(node)) is not None:
        return {"chart": bars}
    if (
        node.has("edify-surface")
        and node.has("rounded-surface")
        and not _holds_blocks(node)
        # A card around a part loaded later is read inside, so that part is
        # fetched (the PL dashboard's Planning Monitor), not left "Loading…".
        and node.find(_loads_later) is None
        and node.text()
    ):
        panel = _panel(node)
        if panel["items"] or panel["title"]:
            return {"panel": panel}
    if node.tag == "table":
        return {"table": _table(node, node)}
    if node.has("edify-empty-state"):
        return {"empty": _empty_message(node)}
    return None


def _holds_blocks(node: Node) -> bool:
    """Whether ``node`` holds blocks of its own (then it is read inside)."""
    return (
        node.find(
            lambda n: n.has("context-metrics")
            or n.has("edify-data-chart")
            or n.has("edify-table-titlebar")
            or n.tag == "table"
            or n.has("edify-pagination-scope")
            or "data-insight-rail" in n.attrs
            or (n.has("edify-surface") and n.has("rounded-surface"))
            # A chart the card sets up in its own script (inline_charts).
            or (n is not node and "cfg.series" in n.get("x-data"))
        )
        is not None
    )


#: The page header's parts, read by _header, never as blocks.
HEADER_PARTS = ("edify-page-header", "mobile-role-home", "edify-back-link")
#: Words a section needs before the fallback draws it as a panel.
MIN_FALLBACK_WORDS = 2
#: A heading on its own between a page's parts: a section title, not a card.
SECTION_HEADINGS = ("h2", "h3")


def _is_header(node: Node) -> bool:
    """The page header's parts and its tab rail: read by _header and _tabs."""
    return (
        any(node.has(name) for name in HEADER_PARTS)
        or "data-profile-tabs" in node.attrs
    )


def _fallback(node: Node) -> dict | None:
    """A section no component reader knows, drawn as a plain panel of its
    headings, text, rows and links rather than left out."""
    if node.tag in ("form", "dialog", "template") or _is_header(node):
        return None
    # A heading that is only a figure ("0") is a tile's number, not a title.
    if node.tag in SECTION_HEADINGS and any(c.isalpha() for c in node.text()):
        return {"section": node.text()}
    if len(node.text().split()) < MIN_FALLBACK_WORDS:
        return None
    panel = _panel(node)
    if not panel["items"] and not panel["title"]:
        panel["items"] = [{"text": node.text()}]
    return {"panel": panel}


#: ``x-show="selectedSchools.length > 0"``: shown once a list holds something.
SHOWN_WHEN_FILLED = re.compile(r"^\s*(\w+)\.length(\s*>\s*0)?\s*$")


def _hidden_on_opening(node: Node) -> bool:
    """A part the page shows only once a list fills (the selection bar, once a
    school is ticked) while that list starts empty: not drawn on opening."""
    from apps.mobile_feed import checklists, dialogs

    if dialogs.closed_flag(node):
        return True
    # Every part of an "a && b" must hold, so one empty list hides it.
    for part in node.get("x-show").split("&&"):
        shown = SHOWN_WHEN_FILLED.match(part)
        if shown is None:
            continue
        holder = node
        while holder is not None and not holder.get("x-data"):
            holder = holder.parent
        if holder is not None:
            value = checklists.data_value(holder.get("x-data"), shown.group(1))
            if value == []:
                return True
    return False


def _blocks(node: Node, out: list[dict], later=None) -> list[dict]:
    taken: set[int] = set()
    for child in node.children:
        if not isinstance(child, Node) or child.tag in SILENT or _is_header(child):
            continue
        if id(child) in taken or _is_beside_link(child):
            continue
        if (
            child.tag == "summary"
            and node.tag == "details"
            and node.find(
                lambda n: _is_filter_form(n)
                or (n.tag == "form" and n.has("edify-filter-bar"))
            )
        ):
            # The phone's fold around the filters: the filter bar folds itself.
            continue
        if (beside := sibling_switch(child)) is not None:
            out.append({"segments": beside[0]})
            taken |= beside[1]
            _calendar_after(child.parent, out)
            continue
        if later is not None and _loads_later(child):
            # A part the page loads once it is open (My Plan's readiness):
            # read what that request answers, in its place.
            part = later(child.get("hx-get"), _sent_headers(child))
            if part is not None:
                _blocks(_for_phone(parse(part)), out, later)
                continue
        if (several := _several_blocks(child)) is not None:
            out.extend(several)
            continue
        block = _block(child)
        if block is not None:
            out.append(block)
            if "segments" in block:
                _calendar_after(child, out)
        elif _holds_blocks(child) or _holds_known(child):
            _blocks(child, out, later)
        elif (fallback := _fallback(child)) is not None:
            out.append(fallback)
    return out


def _calendar_after(holder: Node, out: list[dict]) -> None:
    """The Calendar's month as a block of its own, right after the
    event-type tabs that draw it as text (calendar_block)."""
    from apps.mobile_feed import calendar_block

    if (month := calendar_block.read(holder)) is not None:
        out.append({"calendar": month})


def _several_blocks(node: Node) -> list[dict] | None:
    """A part that is several blocks at once: a grid of small cards (a record
    each), or an indicator card of My Performance (its chart and table)."""
    from apps.mobile_feed import card_grids, css_charts

    if card_grids.is_grid(node):
        return [{"record": record} for record in card_grids.read(node)]
    if card_grids.is_strip_row(node):
        return [{"record": record} for record in card_grids.read_strip_row(node)]
    if css_charts.is_area_card(node):
        return css_charts.read_area(node)
    return None


def _holds_known(node: Node) -> bool:
    """Whether a component reader knows something inside ``node`` that
    _holds_blocks does not look for (link tabs, filter toolbars, empty
    states, a part loaded later), so it is read inside, not as a panel."""
    return (
        node.find(
            lambda n: "data-edify-tablist" in n.attrs
            or "data-row-disclosure-summary" in n.attrs
            or n.has("school-record-row__summary")
            or (n.get("role") == "tablist" and _form_tabs(n) is not None)
            or _is_filter_form(n)
            or n.has("edify-filter-bar")
            or n.has("edify-empty-state")
            or "data-profile-tabs" in n.attrs
            or "data-profile-identity" in n.attrs
            or "data-profile-scope" in n.attrs
            or _loads_later(n)
            or n.has("edify-section-nav")
            or n.has("card")
            or n.has("divide-y")
            or _is_header(n)
            or _switch_parts(n) is not None
        )
        is not None
    )


#: Shown again on a phone by a max-width variant (Tailwind max-sm/md/lg).
PHONE_SHOWN = re.compile(
    r"^max-(?:sm|md|lg):(?:block|flex|grid|inline|inline-flex|inline-block|table|contents)$"
)
PHONE_HIDDEN = re.compile(r"^max-(?:sm|md|lg):hidden$")


def phone_hidden(node: Node) -> bool:
    """Whether a phone (below the 64rem breakpoint) draws ``node`` at all:
    the page's own classes decide, as the browser does at that width."""
    classes = node.classes
    if "mobile-home-hide" in classes or any(PHONE_HIDDEN.match(c) for c in classes):
        return True
    return "hidden" in classes and not any(PHONE_SHOWN.match(c) for c in classes)


def _is_tick_bar(node: Node) -> bool:
    """The bar a page shows once rows are ticked: the app draws its own."""
    from apps.mobile_feed import selection

    return selection.is_bar(node)


def _for_phone(node: Node) -> Node:
    """``node`` with what a phone does not draw left out, and what the page
    shows only once a list fills (its selection bar)."""
    node.children = [
        child
        for child in node.children
        if isinstance(child, str)
        or not (phone_hidden(child) or _hidden_on_opening(child) or _is_tick_bar(child))
    ]
    for child in node.children:
        if isinstance(child, Node):
            _for_phone(child)
    return node


def read(html: str, later=None, path: str = "") -> dict:
    """The page's header, tabs and blocks, in the order a phone draws them.
    ``later(path, headers)`` answers a part the page loads after it opens
    (with the headers its section sends), or None to leave it out."""
    from apps.mobile_feed import dialogs

    from apps.mobile_feed import selection

    root = parse(html)
    # The page's closed dialogs and its bar for ticked rows, read before they
    # are left out of its blocks.
    closed = dialogs.read_all(root)
    ticks = selection.read(root)
    root = _for_phone(root)
    main = root.find(lambda n: n.tag == "main") or root
    page = {
        "header": _header(main, path),
        "tabs": _tabs(main),
        "dialogs": closed,
        "blocks": _blocks(main, [], later),
    }
    if ticks is not None:
        page["selection"] = ticks
    return page
