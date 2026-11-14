# 66 — The app draws the Calendar's month block

The React Native app (`platform/mobile`) now draws `/calendar` from the
page contract's month block (`PageBlock.calendar`, doc 54.5) instead of the
event-type segments it carried as text. No Go, Django, proto, grant or web
change. The branch merges `agent/web-calendar-work-plan-2` (the block itself,
unmerged when this was cut); its only conflict was the generated
`page_pb.ts`, regenerated with the pinned `buf` and `protoc-gen-es` (app and
web `src/gen` identical, `buf lint` clean).

## 66.1 What the app draws

| Part | How |
|---|---|
| Where | `PageBlocksView`: a `segments` block followed by a `calendar` block is not drawn; the calendar block is drawn in its place by `PageCalendarView`, given that segments card's two panels (the phone month and the month card) for their words and the page filter form's hidden values (year, month, event_kind, person). |
| Event-type tabs | The block's `kinds` (label and count) in the segment shape, scrolling sideways. A tab changes the page's query through the filter form (`event_kind`, blank for All events), so the gateway answers the tab; it is not filtered on the phone. |
| Month card | Eyebrow (the phone month's subtitle, "Your schedule"), the month's title, ‹ Today ›. ‹ and › step `month` (and `year` over the year's ends); Today drops both, so the page opens on today's month, as the web's links do. |
| Grid | Monday first, as the page draws it; each day a button with its number, today ringed, the chosen day filled, one dot per kind it holds (activity, leave, holiday, event, in that order and in the page's dot colours). |
| Chosen day | Opens on today when the month is today's, else on All month; "No events for this date." for an empty day, the card's "No events in <month>." for an empty month. |
| Entries | Under each busy day ("Friday 13 November", a Today pill), each entry in its family's colour (calendar-workspace.css `.calendar-event--<family>`, its `color-mix()` values worked out for the light and dark surfaces), the title over the line under it; a later day of a run has a dotted left edge; work on a holiday or leave day is the holiday's colour with a solid red edge. An entry with a link opens it through the page's link handler (`/my-plan/<id>`, native). |
| Ticks | When the page has a selection bar (`PageSelection`), an entry with a `pick_id` has a tick box; the days of a run share one id, so ticking one ticks them all and the bar counts the activity once. Select all ticks or clears every activity of the open tab; part-ticked shows the dash. The bar (Reschedule / Cancel / Clear) is the page's existing one. |

Pure logic is in `src/ui/page/calendarMonth.ts` (month layout, dots, tones,
the filter changes); the drawing is `src/ui/page/PageCalendarView.tsx`.

## 66.2 Proved

- `src/__tests__/calendarBlock.test.ts` (15 tests): the month's days and their
  entries, the open tab's kind only, a run counted as one tick, the panels'
  words and the fallback title and empty sentence, today only in its month,
  Monday-first offsets, dot order, the agenda and chosen-day headings, family
  and kind colours, the day-off tone, tab/month/today filter changes over the
  year's ends.
- `src/__tests__/calendarView.test.tsx` (5 tests, rendered with
  `test-renderer`, which jest-expo already installs): the segments' text is
  gone and the month is drawn, it opens on today's entries and a day button
  shows that day's, a tick calls the page's picks with the activity, an entry
  opens its link, a tab and › change the page's filters.
- Checks as printed: `tsc --noEmit` exit 0; `jest` `Tests: 188 passed, 188
  total` (19 suites); Go `gofmt -l` empty, `go vet ./...` clean,
  `go test -race -count=1 ./...` exit 0 after the merge; `buf lint` clean;
  Django `apps.mobile_feed.test_calendar_block` +
  `apps.activities.test_calendar_page_rules_export` `Ran 4 tests` OK.
- In the app, run as a web build (`expo start --web`, react-native-web) at
  375×812 against a gateway on 127.0.0.1:8081 with my Django (8181) behind it,
  signed in as cceo@: November opened on Friday 13 with dots on the busy days;
  All month listed every busy day; ticking Donor Visit showed the bar
  "1 activities selected" and Select all part-ticked; Clear cleared it; ›
  opened December (4 events, holiday dots in red); the Holidays tab listed
  December Solstice, Christmas Day and Boxing Day in the holiday colour; dark
  and light both checked. Every `/calendar` answer in that session was Go's:
  my Django's log shows only the home requests, no page feed request. Reschedule
  and Cancel were not pressed (they open the existing drawers).
- Not run: the iOS simulator and Android emulator (the migration brief forbids
  them to agents). The dotted left edge on a run's later days relies on
  `borderStyle: 'dotted'` with one side's width; Android has drawn uneven
  dotted borders as solid in the past; check on a device.

## 66.3 What is left

- The month card's range and date badge ("NOV 01") and the page's note under
  the grid are not drawn (the app draws the phone month, as the web does under
  lg).
- The chips' tooltips (responsible person, status) are not in the block
  (doc 54.5.3).
- Seen while checking: the Django feed's month-card panel marked "Today" on
  14 November while the block's `today` and the phone grid said 13
  (18:33 Kampala); the card's mark may come from another clock. Not changed
  here.
