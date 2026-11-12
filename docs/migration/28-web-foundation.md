# 28. The web foundation (Next.js)

Owner, 2026-11-12: "Next.JS (TypeScript + Tailwind.CSS) is for Web browsers
frontend." This is M15's foundation ([04](04-migration-plan.md) M15,
[02](02-target-architecture.md) §2.10): `platform/web/`, a Next.js app that
signs in through the Go gateway, draws the Edify shell, and draws one real
page, the School Directory, from Go's answer. It changes no Django code and no
Go code, and nothing is cut over: the existing web keeps serving every
browser.

## 28.1 What was built

| Part | Where | What it does |
|---|---|---|
| App | `platform/web/` | Next.js 16.4.6 (App Router), React 19.3.0, TypeScript 6.0.3 strict (`noUncheckedIndexedAccess`), Tailwind CSS 4.3.3 (the existing web's version). Exact versions, `package-lock.json` committed |
| Tokens | `scripts/sync-tokens.mjs` → `src/styles/generated/`, `src/fonts/`, `public/images/` | Copies the existing web's `assets/css/_theme.css` verbatim, the custom properties of `:root`, `:root.light` and `:root.theme-dark` (with their `@media` wrappers) from `static/css/design-system.css`, Geist (`static/fonts/Geist-Variable.woff2`) and the logo and sign-in photo. Nothing is restated by hand; `scripts/sync-tokens.test.ts` fails when a copy differs from its source. The one literal named in the web app is the selected tab's `#1976d2`, which the existing web also writes as a literal (`static/css/components/interactions.css`) |
| Themes | `src/app/layout.tsx`, `TopBarControls.tsx` | Light and dark, chosen before paint from the same per-browser key the existing web uses (`edify_theme`); `.theme-dark` on the root, as there |
| Contracts | `platform/proto/buf.gen.web.yaml` → `src/gen` | The same pinned `protoc-gen-es` 2.17.0 as the app, with the same managed options; the output is byte-for-byte the app's `src/gen` (checked with `diff -r`). `make proto` runs it and `make proto-check` diffs `web/src/gen` |
| Transport | `src/lib/gateway.ts` | `@connectrpc/connect` + `@connectrpc/connect-web` 2.3.0 (Connect JSON over fetch), called from the Next.js server only, with the reader's token as a Bearer header |
| Environment | `src/lib/environment.ts` | `EDIFY_ENV` must be `development` or `staging`; any `edifyplanning.app` host is refused, plain http only on this machine or network, a staging build https only (the app's rule). `next.config.ts` runs the check, so a build or start against anything else fails |
| Sign-in | `src/app/login`, `src/app/auth/*` | Email and password through `SignInService.SignIn`; the code step (`VerifySignInCode`) when the account needs one; `RefreshSession` when the access token is no longer accepted; `SignOut` ends the session on the gateway too. Tokens live only in httpOnly cookies set by the route handlers: access `SameSite=Lax`, path `/`; refresh and the code challenge `SameSite=Strict`, path `/auth` only; `Secure` whenever the site is https. Form posts are refused unless they come from this site (Origin check); the page returned to after sign-in is a path on this site only (`safeNext`); failures are fixed codes the page words, never echoed text |
| Shell | `src/app/(app)/layout.tsx`, `src/components/shell/` | Session (`IdentityService.GetSession`) and navigation (`NavigationService.GetNavigation`) asked of the gateway in parallel. Sidebar as restored 2026-10-02: the gateway's sections in order, every link drawn, no search, no folding, the active link the lighter-blue pill with its white edge, the settings cog at the foot; sizes and colours from `sidebar.css`. Navigation icons are the existing SVG markup, drawn only when they pass an allow-list (`src/lib/icon.ts`). Top bar: the page's own search (the `/schools` placeholder and label from the Django view), the date chip (Kampala's day, ISO week), messages, notifications, report a problem, the theme switch, the account menu (Switch Active Role through `AccountService.SwitchRole`, Log out). History buttons show in the installed app, as there. On a phone: the bottom bar from the gateway's `bottom` items plus More, which opens the menu |
| Blocks | `src/components/blocks/` | `PageHeader` (eyebrow, title, description, one primary and outlined buttons), `FilterBar` (one row of labelled selects, square × at its end; three on a phone, the rest behind More), `TabRail` (segmented rail, straight dividers, selected segment filled and never a pill; on a phone the selected tab plus More), `KpiStrip`, `RowActions` (one Actions menu that drops down, disabled actions greyed with their reason), `Pager`, `Badge`, `Card`. They take the `edify.screens.v1` page messages (`PageHeader`, `PageFilters`, `PageLinkTabs`, `PageStrip`, `PagePager`), so pages drawn from `PageScreenService.GetPage` can reuse them |
| School Directory | `src/app/(app)/schools/page.tsx`, `src/lib/schoolDirectory.ts`, `src/components/schools/DirectoryList.tsx` | Drawn from `SchoolDirectoryScreenService.GetSchoolDirectory`, which Go answers ([12](12-school-directory.md)). Only words that live in the Django templates are written in the web app; every count, label, tone, permission, row and page is the gateway's |
| Pages not moved | `src/app/(app)/[...rest]/page.tsx` | Says so and opens the same page of the existing web |

**Why `GetSchoolDirectory` and not `GetPage("/schools")`.** The brief asked for
the page drawn from `PageScreenService.GetPage`. `/schools` is not one of the
existing feed's pages (`apps/mobile_feed/views.py` `NATIVE_PAGES` has no
`school_directory`) and no Go page service answers it: `GetPage` with
`path=/schools` answers `not_found` (asked of the gateway on 8090 as
`pl1@edify.org`). Go's proved answer for this page is
`SchoolDirectoryScreenService`, so the page uses that, laid out into the
generic page messages by `src/lib/schoolDirectory.ts`.

No rule is in the browser: who may add a school, which actions a row has and
why one is unavailable, the counts, tones and pages all arrive as data. The
browser only lays them out. The pager's page-number gaps follow Django's
`get_elided_page_range(on_each_side=1, on_ends=1)` (presentation; unit-tested).

## 28.2 How to run it

```bash
cd platform/web
npm ci
cp .env.example .env        # development: gateway 127.0.0.1:8090, existing web localhost:8010
npm run build && npm run start   # http://localhost:3000 (npm run dev for development)
npm run typecheck && npm run lint && npm test
npm run tokens              # after the existing web's tokens change
```

The browser comparison (local only; needs the existing web on 8010, the
gateway on 8090, this app on 3000, and the seed accounts):

```bash
EDIFY_COMPARE_PASSWORD=… EDIFY_COMPARE_OUT=/some/dir npm run test:compare
```

`EDIFY_COMPARE_ACCOUNTS` (default `cceo@edify.org`) and
`EDIFY_COMPARE_QUERIES` (default `|tab=unclustered|page=2`) choose what is
compared; it refuses any address not on this machine. Each run saves a
screenshot of both pages per account, width and query
(`agent10_compare_{django,next}_<account>_<width>_<query>.png`).

## 28.3 The comparison

`e2e/schools-compare.spec.ts` signs the same seed account into the existing
web and into the Next.js app, opens `/schools` on both at 1440 and 390 pixels,
and compares what a person sees: the header's words and buttons, every filter
and its selected value, the tabs and counts, the listed count, the rows
(School ID, name, district, cluster, visit status), the pager, and the order
of the page's blocks. It also asks the gateway directly and checks the
Next.js rows are its answer, in order. Run on 2026-11-12, as printed:

```
cceo@edify.org at 1440px, /schools
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 48 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
cceo@edify.org at 1440px, /schools?tab=unclustered
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 50 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
cceo@edify.org at 1440px, /schools?page=2
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 45 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
cceo@edify.org at 390px, /schools
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 48 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
cceo@edify.org at 390px, /schools?tab=unclustered
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 50 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
cceo@edify.org at 390px, /schools?page=2
  SAME      header text
  SAME      filters (label=selected)
  SAME      tabs and counts (the visible ones; a phone folds the rest into More)
  SAME      listed count
  SAME      row names in order (50 vs 50 rows)
  SAME      rows of the 45 schools on both pages: id | name | district | cluster | visit
  SAME      the Next.js rows are the gateway answer, in order (school IDs)
  DIFFERENT which school of a same-name group sits on this page and in what order (name ties are not ordered on either side)
  SAME      pager (summary and page numbers)
  DIFFERENT rows-per-page chooser (known gap: the contract has no page size)
  SAME      header buttons (known gap: Upload Center / Add SSA Score are not in the contract)
  DIFFERENT block order (known gap: the KPI strip is not in the contract)
  2 passed (22.3s)
```

What the three kinds of difference are:

- **Which school of a same-name group sits on a page.** Many seed schools share
  a name (twelve "Central Division Church of Uganda Primary"). Django orders
  the directory by `name` alone (`school_views.py`, `order_by("name")`) and Go
  by the same key (`schooldirectory/service.go`), so the order inside a tie is
  whatever each statement's plan returns, and at a page boundary a different
  school of the tied name can land on the page. The names in order are the
  same on every page compared, and every school on both pages has the same
  facts. This is the existing ordering, not the web's; settling it needs a tie
  key (for example the id) on both sides, which is the owner's call since it
  changes the existing page's order.
- **Rows per page.** The existing page has a 15/25/50 chooser (`per_page`);
  `GetSchoolDirectoryRequest` has no page size, and Go answers 50 a page (the
  owner's 2026-10-02 rule). The chooser is not drawn.
- **The KPI strip.** The existing page draws an eight-figure strip (Total,
  Client, Core, Unclustered, No SSA, Staff Required, Planning Ready,
  Duplicates); `GetSchoolDirectoryResponse` does not carry it. `KpiStrip` is
  built and ready, the figures are not in the contract.

Screenshots were looked at side by side at both widths; the shell, header,
filters, tab rail, list bar, rows, badges and Actions buttons read as the same
visual system. Pixels were not compared.

## 28.4 Checks run

| Check | Result |
|---|---|
| `npm run typecheck` (tsc 6.0.3, strict) | clean |
| `npm run lint` (`eslint-config-next` 16.4.6 core-web-vitals + typescript, `--max-warnings 0`) | clean |
| `npm test` (Vitest 5.0.5) | 7 files, 52 tests passed |
| `npm run build` | built: `/login`, `/schools`, `/auth/*`, `[...rest]`, the proxy |
| `buf generate --template buf.gen.web.yaml`, then `diff -r web/src/gen mobile/src/gen` | identical |
| `npm audit --audit-level=high` | no high or critical; 7 moderate in the ESLint toolchain (dev only) |
| Browser comparison (above) | 2 passed (desktop 1440, phone 390) |

## 28.5 What is left

- **Contract gaps for this page**: the KPI strip, the rows-per-page size, the
  Upload Center and Add SSA Score header buttons (`can_open_upload_center`,
  `can_upload_schools`, `can_add_ssa` are not in the answer; the compared CCEO
  has neither), the "N schools have no responsible staff" note (`unheld_count`),
  owner group headings for country and regional readers (`group_by_owner`),
  and the sub-county list arriving only when a district is chosen (the answer
  carries it; checked only with no district).
- **Saves and drawers**: Add School, Export and each row action open the
  existing web for now; the bulk bar (Assign cluster, Assign project, Match
  staff, Reassign owner) is not drawn beyond the tick boxes. They move as each
  domain's writes move (M5 onwards).
- **Shell data not in a contract**: unread message and notification counts;
  role labels (roles show in the gateway's vocabulary, e.g. "CountryDirector");
  acting leadership's Work as; the forced password change
  (`must_change_password`) page; Remember me and Forgot password on sign-in.
- **Sign-in rate limiting** sees every browser as the Next.js server's address;
  forwarding the browser's address needs the gateway to trust the web server
  as a proxy.
- **CSP**: security headers are set (frame denial, nosniff, referrer,
  permissions); a nonce-based Content Security Policy is not yet.
- **Not compared**: other accounts (only `cceo@edify.org` was run), dark
  theme, the opened row's details and SSA groups, the Actions menu contents,
  filters with values chosen, and the sign-in page beyond signing in.
