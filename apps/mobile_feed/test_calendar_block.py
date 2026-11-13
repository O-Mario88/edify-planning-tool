"""The Calendar's month block, read from the page's own event chips."""

from datetime import date

from django.template import engines
from django.test import SimpleTestCase

from apps.mobile_feed import page_blocks

#: The page's tab rail and phone month around the real agenda partial
#: (partials/calendar/agenda.html and event.html), as index.html nests them.
PAGE = """
<main>
<section id="calendar-workspace" x-data="{ eventFilter: 'activity', selectedDate: '' }">
  <p>Operations calendar</p>
  <div class="calendar-workspace__filters" role="tablist">
    <button type="button" role="tab" aria-controls="surfaces" @click="setEventFilter('all')"><span class="calendar-workspace__filter-name">All events</span><span class="calendar-workspace__filter-count">4</span></button>
    <button type="button" role="tab" aria-controls="surfaces" @click="setEventFilter('activity')"><span class="calendar-workspace__filter-name">Activities</span><span class="calendar-workspace__filter-count">1</span></button>
  </div>
  <div id="surfaces" role="tabpanel">
    <section class="calendar-mobile">
      <div class="calendar-mobile__month-grid" role="grid">
        <span class="calendar-mobile__day calendar-mobile__day--outside" role="gridcell"></span>
        <button type="button" class="calendar-mobile__day" @click="selectDate('2026-11-01')" role="gridcell"><span>1</span></button>
        <button type="button" class="calendar-mobile__day calendar-mobile__day--today" @click="selectDate('2026-11-02')" role="gridcell"><span>2</span></button>
      </div>
      <div class="calendar-agenda calendar-agenda--mobile">
      {% include "partials/calendar/agenda.html" with mobile_calendar=True %}
      </div>
    </section>
  </div>
</section>
</main>
"""

VISIT = {
    "kind": "activity",
    "family": "activity",
    "title": "Coaching Visit",
    "meta": "Reschedule: public holiday · Kimenyedde · 1–2 November 2026",
    "href": "/my-plan/a1",
    "pick_id": "a1",
    "continued": False,
    "day_off": True,
}


def _agenda_day(day: int, events: list[dict], today: bool = False) -> dict:
    counts = {k: 0 for k in ("pick", "all", "activity", "leave", "holiday", "event")}
    return {
        "date": date(2026, 11, day),
        "events": events,
        "kind_counts": counts,
        "is_today": today,
    }


def _read(agenda_days: list[dict]) -> dict:
    html = engines["django"].from_string(PAGE).render({"agenda_days": agenda_days})
    blocks = page_blocks.read(html)["blocks"]
    months = [block["calendar"] for block in blocks if "calendar" in block]
    assert len(months) == 1, [list(block) for block in blocks]
    return months[0]


class CalendarBlockTests(SimpleTestCase):
    def test_the_month_tabs_and_open_tab_are_read(self):
        month = _read([])
        self.assertEqual((month["year"], month["month"]), (2026, 11))
        self.assertEqual(month["today"], "2026-11-02")
        self.assertEqual(month["kind"], "activity")
        self.assertEqual(
            month["kinds"],
            [
                {"value": "all", "label": "All events", "count": "4"},
                {"value": "activity", "label": "Activities", "count": "1"},
            ],
        )
        self.assertEqual(month["days"], [])

    def test_each_chip_carries_its_kind_family_tick_run_and_day_off(self):
        continued = {**VISIT, "continued": True, "meta": "Kimenyedde · Day 2 of 2"}
        leave = {
            "kind": "leave",
            "title": "Your leave",
            "meta": "Annual · Awaiting approval",
            "href": "/personal-time-off",
        }
        holiday = {"kind": "holiday", "title": "All Saints", "meta": "Observance"}
        month = _read(
            [
                _agenda_day(1, [holiday, VISIT]),
                _agenda_day(2, [leave, continued], today=True),
            ]
        )
        first, second = month["days"]
        self.assertEqual(first["date"], "2026-11-01")
        self.assertFalse(first["today"])
        self.assertTrue(first["dayOff"])
        self.assertEqual(
            first["events"],
            [
                {
                    "kind": "holiday",
                    "family": "",
                    "title": "All Saints",
                    "meta": "Observance",
                    "href": "",
                    "pickId": "",
                    "continued": False,
                    "dayOff": False,
                },
                {
                    "kind": "activity",
                    "family": "activity",
                    "title": "Coaching Visit",
                    "meta": VISIT["meta"],
                    "href": "/my-plan/a1",
                    "pickId": "a1",
                    "continued": False,
                    "dayOff": True,
                },
            ],
        )
        self.assertTrue(second["today"])
        self.assertEqual(second["events"][0]["kind"], "leave")
        self.assertEqual(second["events"][0]["href"], "/personal-time-off")
        self.assertTrue(second["events"][1]["continued"])
        self.assertEqual(second["events"][1]["pickId"], "a1")

    def test_a_page_without_a_phone_month_has_no_calendar_block(self):
        html = PAGE.replace("calendar-mobile", "something-else")
        html = engines["django"].from_string(html).render({"agenda_days": []})
        blocks = page_blocks.read(html)["blocks"]
        self.assertFalse(any("calendar" in block for block in blocks))
