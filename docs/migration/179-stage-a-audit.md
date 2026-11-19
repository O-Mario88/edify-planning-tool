# 179 · Stage A: the current application, audited (2026-11-19)

Stage A of the modernization program (177): what the existing application is
today, per role and per screen size, before anything is redesigned. Every
statement below rests on the evidence listed in "How it was gathered"; where
the evidence is thin it says so.

## How it was gathered

- **Screens.** `platform/tools/stage-a/capture.py` signed in to the local
  development application (`http://127.0.0.1:8010`, the existing Django app
  over the local `edify_gorn_dev` database; never production) as each role's
  seeded account, opened its landing page and its first twelve sidebar
  destinations, and took a screenshot at phone (375×812), tablet (768×1024)
  and desktop (1440×900). 576 captures across 16 roles, taken 2026-11-19
  13:2x. They are kept outside the repository (size) in
  `stage-a-capture/2026-11-19/` beside the checkouts, with `index.json` (one
  row per capture: role, size, path, status, timings, file) and three
  contact sheets of the landing pages.
- **What a capture shows.** The application scrolls inside its own frame, so
  a "full page" capture is the first screen only — which is what a person
  sees on opening the page, and is what the mobile-first findings below
  judge.
- **Data.** The seeded development data, not production. Some accounts hold
  little: the seeded CCEO has no assigned schools in this database, so most
  of the CCEO's pages show their empty states. Screens are judged for their
  structure; numbers on them mean nothing.
- **Permissions.** `platform/tools/stage-a/permissions_matrix.py` asked the
  site's own URL gate (`can_open_url`) for every full page of
  `docs/platform-page-inventory.json` and every role, plus an Acting Program
  Lead and an Acting Country Director (the acting role less what
  `apps.acting.policy` withholds): `179-stage-a/permissions-matrix.md` and
  `.csv`. A page that opens may still narrow what it shows to the reader.
- **Timings.** Measured by the browser on this development machine (Navigation
  Timing, Largest Contentful Paint and layout shift observers), against the
  local Django server, single user. They are a local baseline to compare
  later builds with, **not** production figures and not the 177 targets'
  conditions.

## Pages each role opens (URL gate)

| CCEO | PL | CD | IA | Acct | RVP | RPL | HR | BT | PC | Admin | Partner Admin | Partner FO | Lender Admin | Loan Officer | Cluster Leader | Acting PL | Acting CD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 122 | 132 | 152 | 213 | 124 | 114 | 84 | 122 | 80 | 114 | 227 | 92 | 92 | 75 | 75 | 41 | 118 | 116 |

Of 232 full pages. The URL gate is generous (Impact Assessment's 213 are
mostly read pages its views then narrow); the redesign's navigation should be
built from what each role *works in*, not from what the gate allows.

## Local timing baseline

| Size | Loads | Load p50 | Load p75 | Load p95 | LCP p75 | Worst layout shift |
|---|---|---|---|---|---|---|
| Phone | 191 | 299 ms | 453 ms | 687 ms | 440 ms | 0.003 |
| Tablet | 191 | 278 ms | 415 ms | 626 ms | 404 ms | 0.177 |
| Desktop | 191 | 276 ms | 404 ms | 650 ms | 404 ms | 0.131 |

Slowest loads: Loan Officer `/mfi-portal/data-issues` 2.7 s (tablet), CCEO
`/debriefs` 2.2 s (phone), CCEO `/cluster-oversight/` 1.1 s. Heaviest page:
`/schools` for the Admin (674 KB of HTML) and Impact Assessment (588 KB).
Layout shift above the 0.1 target: the Program Lead's Home on tablet (0.177)
and `/debriefs` on tablet for four roles (0.169).

## Defects found

1. **The Cluster Leader cannot reach a page.** Signing in lands on `/`, which
   redirects in a loop (`ERR_TOO_MANY_REDIRECTS`) at every size. The Cluster
   Leader Portal lives in Go (its own schema); the existing application has
   no home for the role.
2. **Layout shift on tablet** on the Program Lead's Home and on `/debriefs`
   (above).

## What every screen shares (mobile first)

From the contact sheets of every role's landing page and of the CCEO's
thirteen pages at phone width:

- **The first screen is chrome.** A typical page opens with an eyebrow, a
  title, a two-to-four-line description, its action buttons, a row of
  filter selects, "More" and a clear button — and only then its content. On
  a 375-wide phone that is most of the first screen (Planning, Clusters,
  Core Schools, Programme Schools, Field Debriefs).
- **Zeros as content.** KPI grids of six to ten tiles lead many pages, and in
  normal use many read 0, "—" or "No data" (Planning's ten tiles, My Plan's
  eight, Core Schools' six). Home's Priority actions list "0 Schools Not
  Clustered — All clear" beside real work, so the things that need the
  person compete with things that do not.
- **Home spends its first third on a greeting.** Every role's Home opens with
  a navy band ("Good afternoon, Moses / Here's what needs you today" and the
  role) before Today's overview; the overview's tiles are the same four for
  everyone, whatever the role does.
- **Leadership lands on a filter form.** The Country Director, Impact
  Assessment, the RVP and the Regional Lead land on Country Planning
  Oversight, which on a phone shows the flag, the title, "Last updated", two
  tabs and three filter selects with Clear and More filters before the first
  figure; on desktop eight selects.
- **Tables are tables on phones.** Wide tables scroll sideways behind an
  orange "Swipe to view more columns" pill (an owner rule of 2026-09-27).
  177's standards ask for mobile row alternatives instead — see Decisions.
- **The top bar carries five targets** (search, messages, notifications,
  theme, profile); the theme switch is the least used and sits among the
  most used.
- **Truncation** in selects and cards ("All Program Le…", "Demo Lending
  Partner - C…").
- **The bottom bar is consistent** — Home, two role destinations, Messages,
  More — and is worth keeping.
- **Desktop leaves half the canvas empty** on Home (two narrow columns under
  a full-width header), while oversight pages pack a dense table under eight
  filters; type is small throughout.

## Current against proposed, by role

Proposed is direction for Stage B–E, to be shown as before/after previews
before any page is rebuilt (177).

| Role | Lands on now | First screen now (phone) | Proposed first screen (phone) |
|---|---|---|---|
| CCEO | Home | greeting band; four tiles; priority list mixing zero rows | "Today": the next visit and route, then what waits on me (evidence due, follow-ups, partner work) as tasks with one action each; tiles only where non-zero |
| Program Lead | Home | as CCEO, plus team rows | two segments, My Work and Team; decisions waiting (approvals, completions, fund requests) first, with counts |
| Country Director | Country Planning Oversight | filters before figures | an executive strip (four figures with definitions and trend), priority decisions, exceptions; filters folded into one period control |
| Impact Assessment | Country Planning Oversight | filters before figures | the verification queue (SSA, Salesforce IDs, partner evidence) as the landing, coverage beside it |
| Accountant | Home | four tiles, empty priority list, quick access | money states kept apart — pending disbursement, approved budgets, payments ready — each a list with UGX totals |
| RVP / Regional Lead | Country Planning Oversight | filters before figures | consolidated performance and approvals; no field controls |
| HR | Home | empty priority list, quick access | reviews due, leave to decide, development requests |
| BT | Home | priority list of loan rows | loan pipeline stages with counts, then the overdue items |
| Project Coordinator | Home | 22 To-Dos, grouped | projects as cards with targets and next milestones |
| Admin | Home | priority list | users and access, uploads, alerts |
| Partner Admin / Field Officer | Home | priority list, Open My Plan | assigned work to accept or schedule, evidence to upload |
| Lender Admin / Loan Officer | Home | empty priority list | applications and repayments needing action |
| Cluster Leader | — (redirect loop) | — | the four large actions and "Needs your attention" (177) |

## Decisions for the owner

1. **Tables on phones.** The 2026-09-27 rule keeps every table a table on a
   phone (sideways scroll, no frozen columns); 177 asks for mobile row
   alternatives. Proposed: below 768 px a table becomes a list of rows that
   show the two or three columns that identify the record and its state,
   opening the rest; at 768 and wider it stays a table. **Decided
   2026-11-19 (owner: "Rows on phones")**: the redesign's tables are the
   design system's DataTable (180), rows below 768 px; the live web keeps its
   tables until each page is rebuilt.
2. **The greeting band on Home.** Proposed: drop it on phones (the role and
   date move to the top bar), so the first screen holds work. **Decided 2026-11-19
   (owner: "Drop it on phones")**: phone Home (the Expo app and the web
   app below 64rem) opens on a compact date and role line, then the work.
3. **Where leadership lands.** Proposed: the Country Director, Impact
   Assessment, the RVP and the Regional Lead land on a role home of their
   own, with Country Planning Oversight one tap away, rather than on its
   filter form. **Decided
   2026-11-19 (owner: "Own role home")**: in the web app and the Expo app
   every reader, the country readers included, lands on their own Home;
   Home's quick access already holds their oversight (the Country
   Director's "Dashboard" is Country Planning Oversight, Impact Assessment's
   is the IA dashboard). The existing application keeps its landing until
   the redesign replaces it.

## Next

Stage B, the design system: tokens shared by the Next.js app and the Expo
app (colour, type scale with tabular numerals, spacing, radius, elevation,
focus, states, chart colours) and the components 177 lists, shown on a
preview page with before/after pairs for the CCEO's Today, the PL's decisions
and the Accountant's money states, built from these captures.
