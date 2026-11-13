"""The Calendar page's month as one block (``PageCalendar``): each day of the
month with entries and each entry's kind, colour family, words, link, tick
box, multi-day run and day-off mark, read from pages/calendar/index.html
(the phone's month and agenda, ``section.calendar-mobile``) and its event
chips (partials/calendar/event.html).

The page's event-type tabs still read as text segments
(page_blocks._segments); this block sits right after them, so a client can
colour, filter and tick the entries without reading those words back.
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import Node

#: ``@click="setEventFilter('activity')"`` on an event-type tab.
SETS_KIND = re.compile(r"setEventFilter\('([^']*)'\)")
#: ``eventFilter: 'all',`` in the page's x-data.
OPEN_KIND = re.compile(r"eventFilter:\s*'([^']*)'")
#: ``@click="selectDate('2026-11-01')"`` on a day of the phone's month.
SELECTS_DAY = re.compile(r"selectDate\('(\d{4})-(\d{2})-(\d{2})'\)")

EVENT = "calendar-event"
MODIFIER = "calendar-event--"
#: The chip's marks that are not its kind or family.
FLAGS = frozenset({"continued", "dayoff", "pick"})


def read(holder: Node) -> dict | None:
    """The month block of the calendar inside ``holder``, or None."""
    phone = holder.find(lambda n: n.tag == "section" and n.has("calendar-mobile"))
    if phone is None:
        return None
    year, month, today = _month(phone)
    days = [
        _day(day)
        for day in phone.find_all(
            lambda n: n.tag == "li" and n.has("calendar-agenda__day")
        )
    ]
    opened = OPEN_KIND.search(_x_data(holder))
    return {
        "year": year,
        "month": month,
        "today": today,
        "kinds": _kinds(holder),
        "kind": opened.group(1) if opened else "",
        "days": days,
    }


def _x_data(node: Node | None) -> str:
    while node is not None:
        if node.get("x-data"):
            return node.get("x-data")
        node = node.parent
    return ""


def _month(phone: Node) -> tuple[int, int, str]:
    year = month = 0
    today = ""
    for button in phone.find_all(lambda n: n.has("calendar-mobile__day")):
        picked = SELECTS_DAY.search(button.get("@click"))
        if picked is None:
            continue
        if not year:
            year, month = int(picked.group(1)), int(picked.group(2))
        if button.has("calendar-mobile__day--today"):
            today = "-".join(picked.groups())
    return year, month, today


def _kinds(holder: Node) -> list[dict]:
    out = []
    for tab in holder.find_all(lambda n: n.get("role") == "tab"):
        key = SETS_KIND.search(tab.get("@click"))
        if key is None:
            continue
        name = tab.find(lambda n: n.has("calendar-workspace__filter-name"))
        count = tab.find(lambda n: n.has("calendar-workspace__filter-count"))
        out.append(
            {
                "value": key.group(1),
                "label": name.text() if name else "",
                "count": count.text() if count else "",
            }
        )
    return out


def _day(day: Node) -> dict:
    when = day.find(lambda n: n.tag == "time")
    events = [_event(chip) for chip in day.find_all(lambda n: n.has(EVENT))]
    return {
        "date": when.get("datetime") if when else "",
        "today": day.has("calendar-agenda__day--today"),
        "dayOff": any(event["dayOff"] for event in events),
        "events": events,
    }


def _event(chip: Node) -> dict:
    # The class list in its written order: the kind first, then the family
    # (an activity's family may repeat its kind, "activity").
    marks = [
        name.removeprefix(MODIFIER)
        for name in chip.get("class").split()
        if name.startswith(MODIFIER)
    ]
    kind = marks[0] if marks else ""
    family = marks[1] if len(marks) > 1 and marks[1] not in FLAGS else ""
    title = chip.find(lambda n: n.tag == "strong")
    meta = chip.find(lambda n: n.tag == "small")
    link = chip if chip.tag == "a" else chip.find(lambda n: n.tag == "a")
    pick = chip.find(lambda n: "data-activity-pick" in n.attrs)
    return {
        "kind": kind,
        "family": family,
        "title": title.text() if title else "",
        "meta": meta.text() if meta else "",
        "href": link.get("href") if link else "",
        "pickId": pick.get("value") if pick else "",
        "continued": "continued" in marks,
        "dayOff": "dayoff" in marks,
    }
