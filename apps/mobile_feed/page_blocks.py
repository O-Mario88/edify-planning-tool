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


def _header(main: Node) -> dict:
    back = main.find(lambda n: n.has("edify-back-link"))
    title = main.find(lambda n: n.tag == "h1")
    description = main.find(lambda n: n.has("edify-page-header__description"))
    controls = main.find(lambda n: n.has("edify-page-header__controls"))
    badges, actions = [], []
    for node in controls.nodes() if controls else ():
        if node.tag == "span" and node.has("rounded-pill"):
            badges.append(
                {
                    "text": node.text(),
                    "tone": _badge_tone(node),
                    "title": node.get("title"),
                }
            )
        elif node.tag == "button" or (node.tag == "a" and node.has("btn")):
            label = node.text()
            enabled = "disabled" not in node.attrs
            actions.append(
                {
                    "key": _slug(label),
                    "label": label,
                    "primary": node.has("edify-primary-solid"),
                    "enabled": enabled,
                    "reason": "" if enabled else node.get("title"),
                    "href": node.get("hx-get") or node.get("href"),
                }
            )
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


def _filters(form: Node) -> dict:
    filters = []
    for select in form.find_all(lambda n: n.tag == "select"):
        holder = select.parent
        label = holder.find(lambda n: n.has("edify-filter-label")) if holder else None
        options = select.find_all(lambda n: n.tag == "option")
        chosen = next(
            (option.get("value") for option in options if "selected" in option.attrs),
            options[0].get("value") if options else "",
        )
        filters.append(
            {
                "name": select.get("name"),
                "label": label.text() if label else select.get("aria-label"),
                "value": chosen,
                "options": [
                    {"value": option.get("value"), "label": option.text()}
                    for option in options
                ],
            }
        )
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
            }
        )
    return actions


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
    return {
        "text": text,
        "href": _href(cell),
        "tone": badge_tone
        if is_badge
        else (tone.get("data-edify-tone") if tone else ""),
        "strong": bool(strong and strong.text() == text),
        "badge": is_badge,
    }


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
    rows = [
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
        for row in body.find_all(lambda n: n.tag == "tr")
        if not (head and _inside(row, head))
    ]
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


def _panel_items(node: Node, skip: set[int], out: list[dict]) -> list[dict]:
    children = [c for c in node.children if isinstance(c, Node)]
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
        else:
            _panel_items(child, skip, out)
    return out


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
        "items": _panel_items(node, skip, []),
    }


def _switch_parts(node: Node) -> tuple[Node, list[tuple[Node, Node]]] | None:
    """The tab list inside ``node`` and its (button, part) pairs."""
    tablist = node.find(lambda n: "data-edify-tablist" in n.attrs)
    if tablist is None:
        return None
    pairs = []
    for button in tablist.find_all(lambda n: "data-edify-tab" in n.attrs):
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
                "active": button.get("aria-pressed") == "true",
                "blocks": _blocks(part, []),
            }
        )
    return {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else "",
        "caption": caption.text() if caption else "",
        "segments": segments,
    }


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


def _block(node: Node) -> dict | None:
    """The block ``node`` is, or None to look inside it."""
    if node.tag == "nav" and (tabs := _link_tabs(node)) is not None:
        return {"linkTabs": tabs}
    if node.tag == "form" and node.get("data-component") == "filter-toolbar":
        return {"filters": _filters(node)}
    if node.tag == "p" and "data-profile-scope" in node.attrs:
        return {"scopeLine": node.text()}
    if "data-profile-identity" in node.attrs:
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
    if switch is not None and not any(
        isinstance(child, Node) and _holds_switch(child) for child in node.children
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
    if (
        node.has("edify-surface")
        and node.has("rounded-surface")
        and not _holds_blocks(node)
    ):
        return {"panel": _panel(node)}
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
            or "data-insight-rail" in n.attrs
            or (n.has("edify-surface") and n.has("rounded-surface"))
        )
        is not None
    )


def _blocks(node: Node, out: list[dict], later=None) -> list[dict]:
    for child in node.children:
        if not isinstance(child, Node) or child.tag in SILENT:
            continue
        if (
            later is not None
            and child.get("hx-trigger") == "load"
            and child.get("hx-get")
        ):
            # A part the page loads once it is open (My Plan's readiness):
            # read what that request answers, in its place.
            part = later(child.get("hx-get"))
            if part is not None:
                _blocks(parse(part), out, later)
                continue
        block = _block(child)
        if block is None:
            _blocks(child, out, later)
        else:
            out.append(block)
    return out


def read(html: str, later=None) -> dict:
    """The page's header, tabs and blocks, in the order the page draws them.
    ``later(path)`` answers a part the page loads after it opens, or None to
    leave it out."""
    root = parse(html)
    main = root.find(lambda n: n.tag == "main") or root
    return {
        "header": _header(main),
        "tabs": _tabs(main),
        "blocks": _blocks(main, [], later),
    }
