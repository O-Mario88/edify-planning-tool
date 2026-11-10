"""Record cards that open in place (partials/clusters/cluster_card.html,
schools/directory_row.html, core_schools/school_row.html,
projects/project_card.html): the record's name, its status pills, its Actions
menu and its "Label: value" facts — and what opening the card shows, with the
list it loads once opened (a cluster's schools) named by its web path.
"""

from __future__ import annotations

from apps.mobile_feed.page_blocks import Node

SUMMARY = "data-row-disclosure-summary"
FACTS = "school-record-row__metadata"
#: The pill tones the web's status badge carries (edify-status-badge <tone>).
BADGE_TONES = {
    "danger": "alert",
    "warning": "caution",
    "success": "good",
    "info": "info",
}
#: A fact's colour, by the words in its holder's classes.
FACT_TONES = (
    ("danger", "alert"),
    ("critical", "alert"),
    ("warning", "caution"),
    ("needs_attention", "caution"),
    ("success", "good"),
    ("healthy", "good"),
    # core_schools/school_row.html (owner 2026-09-27: done green, planned blue,
    # nothing planned amber).
    ("is-positive", "good"),
    ("is-planned", "info"),
    ("is-attention", "caution"),
)
#: Slot marks after a count (V1..V4): the count already says it in words.
SLOT_MARKS = "core-seq"
#: A part the card loads on opening is fetched on an event the card raises,
#: not as the page loads.
LOADS_ON_EVENT = ("load", "intersect", "revealed")


#: The classes core_schools/school_row.html marks its summary and details
#: with: it opens by a class on the row rather than the disclosure marker.
SUMMARY_CLASS = "school-record-row__summary"
DETAILS_CLASS = "school-record-row__details"


def _is_summary(node: Node) -> bool:
    return SUMMARY in node.attrs or node.has(SUMMARY_CLASS)


def is_record(node: Node) -> bool:
    """A card whose own summary opens it."""
    return any(
        isinstance(child, Node) and _is_summary(child) for child in node.children
    )


def read(node: Node) -> dict:
    from apps.mobile_feed import page_blocks

    summary = next(
        child
        for child in node.children
        if isinstance(child, Node) and _is_summary(child)
    )
    title = _title(summary)
    details = next(
        (
            child
            for child in node.children
            if isinstance(child, Node)
            and child is not summary
            and (child.get("x-show") or child.has(DETAILS_CLASS))
        ),
        None,
    )
    href = _href(title, details)
    later = _opened_part(details)
    blocks: list[dict] = []
    if details is not None:
        skipped = {
            id(n) for n in (later, _profile_link(details, href)) if n is not None
        }
        for child in details.children:
            if isinstance(child, Node) and id(child) not in skipped:
                page_blocks._blocks(_wrapped(child), blocks)
    return {
        "title": title.text() if title is not None else "",
        "href": href,
        "subtitle": "",
        "badges": [_badge(pill) for pill in summary.find_all(_is_badge)],
        "actions": _actions(summary, title),
        "facts": [
            fact
            for holder in summary.find_all(lambda n: n.tag == "dl" and n.has(FACTS))
            for fact in facts(holder)
        ],
        "details": blocks,
        "detailsPath": later.get("hx-get") if later is not None else "",
        **_pick(summary),
    }


def _pick(summary: Node) -> dict:
    """The card's tick box for the page's bar (core_schools/school_row.html:
    ``<input type="checkbox" x-model="selectedSchools" value="1693">``)."""
    box = summary.find(
        lambda n: n.tag == "input"
        and n.get("type") == "checkbox"
        and bool(n.get("x-model"))
        and bool(n.get("value"))
    )
    if box is None:
        return {"pickId": "", "pickLabel": ""}
    holder = box.parent
    caption = holder.find(lambda n: n.has("sr-only")) if holder is not None else None
    return {
        "pickId": box.get("value"),
        "pickLabel": box.get("aria-label") or (caption.text() if caption else ""),
    }


def _wrapped(child: Node) -> Node:
    """``child`` alone under a parent, so it is read as one of a page's parts."""
    holder = Node("div", {}, None)
    holder.children.append(child)
    return holder


def _title(summary: Node) -> Node | None:
    return (
        summary.find(lambda n: "data-list-title" in n.attrs)
        or summary.find(lambda n: n.has("school-record-row__title"))
        or summary.find(lambda n: n.has("school-record-row__link"))
        or summary.find(lambda n: n.tag in ("h2", "h3", "h4"))
    )


def _href(title: Node | None, details: Node | None) -> str:
    """The record's own page: its name's link, or the open card's link to it."""
    if title is not None:
        link = title if title.tag == "a" else title.find(lambda n: n.tag == "a")
        if link is not None and link.get("href"):
            return link.get("href")
    link = _profile_link(details, "", title.text() if title is not None else "")
    return link.get("href") if link is not None else ""


def _profile_link(details: Node | None, href: str, name: str = "") -> Node | None:
    """The open card's "Open Cluster A cluster profile" link."""
    if details is None:
        return None
    for child in details.children:
        if not isinstance(child, Node) or child.tag != "a" or not child.get("href"):
            continue
        if child.get("href") == href or (name and name in child.text()):
            return child
    return None


def _opened_part(details: Node | None) -> Node | None:
    """The list the card loads on opening (its schools), fetched on an event
    the card raises."""
    if details is None:
        return None
    for part in details.find_all(lambda n: bool(n.get("hx-get"))):
        trigger = part.get("hx-trigger").strip()
        first = trigger.split(",")[0].split()[0] if trigger else ""
        if (
            first
            and first not in LOADS_ON_EVENT
            and part.get("hx-target") != ("#drawer-container")
        ):
            return part
    return None


def _is_badge(node: Node) -> bool:
    return (
        node.has("edify-status-badge")
        and node.parent is not None
        and not any(holder.tag == "dl" for holder in _holders(node))
    )


def _holders(node: Node):
    holder = node.parent
    while holder is not None:
        yield holder
        holder = holder.parent


def _badge(pill: Node) -> dict:
    tone = next((tone for name, tone in BADGE_TONES.items() if pill.has(name)), "plain")
    return {"text": pill.text(), "tone": tone, "title": pill.get("title")}


def _actions(summary: Node, title: Node | None) -> list[dict]:
    """The card's Actions menu, and any button of its own beside it."""
    from apps.mobile_feed import page_blocks

    menus = summary.find_all(lambda n: n.has("row-menu"))
    taken = {id(n) for menu in menus for n in menu.nodes()}
    if title is not None:
        taken |= {id(title)} | {id(n) for n in title.nodes()}
    actions = [action for menu in menus for action in page_blocks._row_actions(menu)]
    for button in summary.find_all(
        lambda n: n.tag == "button" and bool(n.get("hx-get"))
    ):
        if id(button) not in taken:
            actions += page_blocks._row_actions(_wrapped(button))
    return actions


def _value_text(value: Node) -> str:
    """A fact's value as words, its slot marks left out."""
    parts: list[str] = []

    def walk(node: Node) -> None:
        for child in node.children:
            if isinstance(child, str):
                parts.append(child)
            elif not child.has(SLOT_MARKS):
                walk(child)

    walk(value)
    return " ".join("".join(parts).split())


def facts(listing: Node) -> list[dict]:
    """A list's "Label: value" pairs, each in the colour its holder gives it."""
    from apps.mobile_feed import page_blocks

    read = []
    for term in listing.find_all(lambda n: n.tag == "dt"):
        holder = term.parent
        value = holder.find(lambda n: n.tag == "dd") if holder is not None else None
        classes = " ".join(
            (
                holder.get("class")
                if holder is not None and holder is not listing
                else "",
                value.get("class") if value is not None else "",
                value.get("data-edify-tone") if value is not None else "",
            )
        )
        read.append(
            {
                "label": term.text().rstrip(":").strip(),
                "value": _value_text(value) if value is not None else "",
                "href": page_blocks._href(value),
                "tone": next(
                    (tone for word, tone in FACT_TONES if word in classes), ""
                ),
            }
        )
    return read
