# 64. Web fixes after the School Profile review

The coordinator's review of the web School Profile (Django
`agent40_django_cceo_schools_1000_1440.png` beside Next
`agent40_next_cceo_schools_1000_1440.png`) found four differences. All four
are fixed here, for every page that draws the same parts. The branch merges
`agent/web-school-profile` (doc 53, not yet on the migration branch) so the
profile it fixes is there.

## 64.1 What changed

| Review item | Cause | Fix |
|---|---|---|
| 1. Fiscal year / Period stretch the full width | The web's filter row always shared the width among its fields. micro-ux.js `arrangeFilterRows` lays out a shared row only for three or more fields on a tablet or desktop and two or more on a phone; fewer keep their own width. The profile also has no Clear (`_filters.html` passes no `reset_url`), so no × | `lib/filterSlots.ts` `arrangesRow(count, phone)`; `FilterBar` draws a bar of fewer fields as a wrapping flex row, each select as wide as its words (`field-sizing: content`, 10px / 30px padding, the profile's own), and draws the × only when given a `clearHref`. `FeedBlocks` takes `clearFilters` (default on); `ProfilePage` turns it off |
| 2. Eight KPI tiles cut to six with Swipe for more | The web kept every strip one swiping row from 640px with labels on one line. components.css `.context-metrics`: below 48rem a grid, two cells a row (four from 37.5rem); 48–64rem one scrolling row of 130px cells; from 64rem a strip of eight or fewer shares the row (a grid of label / figure / helper rows by subgrid, labels and helpers wrap, figures never), nine or more keep the scrolling row with two-line helpers | The same rules as `.edify-strip` in `app/globals.css`; `FeedStrip` cells carry `edify-strip__label/__value/__helper`; `StripRail`'s scrolling and navigation start at 48rem (`md`). The notification centre's `KpiStrip` now draws through `FeedStrip`, so every page's strip follows one layout |
| 3. Missing icons | The contract had no icon for a badge; the header's pencil was not in the web's key → icon map | Additive `PageBadge.icon = 4` ("lock"). Go's profile header sets it on the visit-lock badge (`schoolprofile/header.go`); the feed reader sets it on a header pill with `data-visit-closed` (`page_blocks._header`), so both sides answer alike. The web draws the existing 16px filled lock (`BadgeIcon`) and adds `edit_details → edit` (the existing pencil) to `ACTION_ICONS` |
| 4. Notification badge count missing | The shell asked for no counts | New `NotificationCenterService.GetUnreadNotificationCount` (Go `notificationcenter/unread.go`): the caller's notifications with `status = 'unread' AND resolved_at IS NULL`, exactly `apps.core.context_processors.sidebar_counts`; no role refused (every role has the bell). The shell layout asks it and `MessagingService.GetUnreadCount` (existing) beside the session; a count it cannot read draws no badge, as `sidebar_counts` falls back to 0. `TopBar` draws the `.notification-badge` pill (18px, `--edify-notification`, "99+" past two digits, `lib/badgeCount.ts`) |

No grant: `notification` (recipient_id, status, resolved_at) was already
granted to `edify_gateway_ro`. Generated code regenerated for Go, web and
`platform/mobile/src/gen` (the worker's gen holds only analytics).

## 64.2 Measured against the existing page

Playwright, signed in, development database, Django 8182 against Next 3082
over the Go-only gateway 8082 (select widths in px; strip = cells, rows,
cells in view, swiping):

| Page, account, width | Django | Next |
|---|---|---|
| School 1000, cceo, 1440 | fy 119, period 98, no ×; strips 8/1/8, 6/1/6, 4/1/4, none swiping; lock 1 svg; bell 4 | the same |
| School 1000, cceo, 390 | fy 168, period 168, no ×; strips 8 in 4 rows, 6 in 3, 4 in 2 | fy 171, period 171; strips the same |
| Planning, cceo, 1440 | 10 cells, 1 row, 7 in view, swiping | the same |
| Planning, cceo, 390 | 10 cells in 5 rows | the same |
| My Plan, cceo1, 1440 / 390 | 8 cells, 1 row, none swiping / 4 rows | the same (and its second strip) |
| Clusters, cceo, 1440 | 8 cells, 1 row | the same |

Clusters' filter row folds after five fields on Django and six on Next: that
is the template-authored fold already listed as `web-fixes-2`. cceo's My Plan
is handed on by Go (doc 40), so My Plan was measured as cceo1.

## 64.3 Parity

The badge icon is part of `GetSchoolProfile`'s header, so the profile was
compared again (gateway 8082 with Django 8182 behind it, `-tab overview
-sample 15`), as printed:

```
cceo@edify.org               699 profiles compared, 0 differing (597 not Core)
pl1@edify.org                15 profiles compared, 0 differing (14 not Core)
admin@edify.org              699 profiles compared, 0 differing (597 not Core)
ia@edify.org                 699 profiles compared, 0 differing (597 not Core)
cceo1@edify.org              15 profiles compared, 0 differing (14 not Core)
2127 profiles compared (1819 not Core), 0 differing
```

School 1000 carries the lock on both sides, so the new field is compared,
not defaulted. Tests: `apps.mobile_feed.test_page_blocks` (the header test now
has a visit-lock pill: 61 tests OK); integration
`TestTheBellCountsTheReadersUnreadNotificationsLeavingOutTheResolved`
(hr@ with an unread, a resolved-unread, a read and an archived notice: 1) and
`TestTheBellIsCountedForARoleTheNotificationCentreTurnsAway` (a Cluster
Leader is counted, not refused); web `FilterBar.test.tsx`,
`FeedStrip.test.tsx`, `TopBar.test.tsx`, `badgeCount.test.ts`,
`filterSlots.test.ts` (`arrangesRow`), `ProfileBlocks.test.tsx` (lock and
pencil).

Screenshots (scratchpad): `agent47_{django,next}_cceo_{schools_1000,planning,clusters}_{1440,390}.png`,
`agent47_{django,next}_cceo1_my_plan_{1440,390}.png`.

## 64.4 Not done here

- web-fixes-2's Planning pill tones (Visit Plan / Training Plan status and
  Visit Lock): the feed reader does not read `school-planning-badge` chips
  as badges, and Go's planning and cluster-school builders would have to
  carry the same tones; that ripples over Planning and the cluster school
  lists' parity, so it stays the `web-fixes-2` item.
- The bell and Messages links still open the existing web's pages.
