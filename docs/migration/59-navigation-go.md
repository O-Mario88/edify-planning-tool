# 59. The navigation (sidebar and bottom bar), answered by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. The app and the Next.js web app
both draw their menu from `NavigationService.GetNavigation`; until now the
gateway passed that call to the existing application's feed
(`apps.mobile_feed.views.NavigationFeedView`). This piece answers it in Go.

| Piece | What moves | State |
|---|---|---|
| 1 | `GetNavigation`: the bottom bar and the grouped menu, for every role and for a partner's team member | This document |
| — | The menu of someone in an acting appointment | Still the existing application's (it withholds the pages the appointment leaves with the substantive leader) |
| — | The web page's own sidebar (HTML, active highlight, expanded groups) | Django's templates; the contract carries none of it |

## 59.1 What moved

`platform/backend/internal/navigation` answers `GetNavigation` for someone
working in their own role (`screens.Service.WithNavigation`, wired in
`server.go`). `GetNavigation` itself moved from `internal/screens/service.go`
to `internal/screens/navigation.go`; it still falls back to the existing
application for anything Go does not serve.

The menu is a pure function of the reader's role, with one exception (a
partner's team member). The registry and every rule that shapes it stay in
`apps.core.navigation`; `manage.py export_navigation_rules` writes each role's
answer, computed by the very functions the feed calls, into
`internal/navigation/rules.json`, and `apps/core/test_navigation_rules_export.py`
fails when the two differ.

| Part | Existing rule it follows | Where it is decided now |
|---|---|---|
| Which items a role is offered | `build_sidebar_for_user`: section and item audiences (`visible_to`, `PAGE_PERMISSIONS`), Admin's override (no duplicates, `BT_SPECIALIST_NAV_PAGES`), folds (`NAV_FOLDS`), the single Partner Oversight entry, per-role URLs and labels | Exported per role |
| The groups and their order | `_regroup_by_visit`: one link per URL (a specific page wins over Dashboard), visit tiers DAILY / WEEKLY / MONTHLY / PLANNING CYCLE / REFERENCE (`apps.core.nav_cadence`), the OVERSIGHT group after DAILY in its fixed order | Exported per role |
| The bottom bar | `build_mobile_nav_for_user`: `MOBILE_NAV_BY_ROLE`, the fallback, the sidebar's order, the phone-only Home and Messages, four at most, `MOBILE_NAV_SHORT_LABELS` | Exported per role |
| An item's fields | The feed's `nav_item`: label, url, icon SVG (`ICONS`, else the dashboard icon), page key, `native` (`_draws_natively`: a URL name in `NATIVE_PAGES` the reader's `can_open_url` allows) | Exported; icons stored once and named by place |
| A partner's team member | `member_scope.page_withheld` in the sidebar and in `can_view_page` (so `native` too): a roster login (`partner_member`, active, on an active partner) that does not lead the team | Go: `decisionlog.PartnerTeamMember` reads the roster; the member's menu is exported for both partner roles |
| A Partner Admin on a team whose partner record is not theirs | `leads_team` asks `resolve_partner_ids` | Left to the existing application (Go does not read the partner scope), as the Decision Log and My Actions do |
| A role the rules do not name | `get_user_role_slug`'s `role.upper()` fallback | Left to the existing application |
| Acting appointment | `apps.core.acting.page_withheld` | Left to the existing application |

The feed builds the menu for the path `/home`; nothing of the path reaches the
contract (no active or expanded flags), so the export uses the same path.

## 59.2 Grants

None. The only table read is `partner_member` joined to `partner`, through the
grants the Decision Log already added.

## 59.3 What was found by comparing

Nothing differed. ClusterLeader is offered an empty menu and an empty bar (it
holds no web permission); the export carries that as it is.

## 59.4 Parity

A new screen in the comparison tool, `-screen navigation`
(`cmd/parity/navigation.go`), signs each account in through a Go-only gateway
(no existing application behind it) and compares the whole answer with the
existing feed (`/api/mobile/v1/navigation`) of the same token.

    EDIFY_PARITY_PASSWORD=… go run ./cmd/parity -gateway http://127.0.0.1:8081 \
      -existing http://127.0.0.1:8181 -screen navigation -users <29 accounts> -pause 20s

All 29 seed accounts (20 CCEOs, 4 Programme Leads, the Country Director,
Impact Assessment, the Project Coordinator, Business Transformation and the
Admin), last lines as printed:

    coordinator@edify.org              same (4 bar items, 6 sections, 20 items in all)

    29 answers compared, 0 differing

The seed has no Accountant, HR, RVP, RPL, MFI or partner login. Their menus
are the exported ones (the drift test proves them equal to what the feed
builds for the role); the choice of the team member's menu is covered by
`internal/navigation/service_test.go`.

## 59.5 Tests

- `apps/core/test_navigation_rules_export.py`: the export is current; a team
  member's menu holds none of `MEMBER_WITHHELD_PAGES` and less than the
  Partner Admin's.
- `internal/navigation/service_test.go`: every role served from its own menu,
  only partner roles ask the roster, an unnamed role left to the existing
  application, the six roster cases (no entry, own login, someone's team, no
  partner login, a Partner Admin on someone's team, a Partner Admin's own),
  a failed roster read, answers not sharing their items.
- `internal/integration/navigation_test.go`: a CCEO, a Programme Lead and the
  Admin are given their role's bar and menu by Go; no token is refused.

## 59.6 What is left

- An acting appointment's menu (needs `acting.withheld_pages` in Go).
- A Partner Admin on a team they do not own (needs the partner scope).
- When the registry itself leaves Django, `rules.json` becomes its source.
