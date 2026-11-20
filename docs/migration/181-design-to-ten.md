# 181 · From 6.5 to 10: the design proposal (phone and desktop)

Owner, 2026-11-20: "give me a detailed proposal of how to transform the
designs from where it is to 10/10 enterprise grade level … for both mobile
and desktop screen."

This proposal builds on 177 (the programme), 179 (the Stage A audit) and 180
(the design system's tokens and parts). It respects the owner's decisions so
far, above all 2026-11-19: "i think i like the previous home screen
better". So the route to 10 **evolves the existing look**: same layouts,
same blue, same cards. It does not swap in a new one. Nothing here changes
a programme rule, a permission or a figure's meaning without the owner's
say. Production safety (177 §Safety) is unchanged.

## 1. Where it stands, honestly

Scored on what was measured on 2026-11-19 and 2026-11-20: the ui-sweep (16
roles × 3 sizes, 1,344 page loads), the browser and the iOS Simulator. Not
on how it looks in a screenshot.

| Dimension | Phone | Desktop | What holds it back |
|---|---|---|---|
| Trust in the figures | 5 | 5 | Figures that disagree on one screen (Overdue 8 vs "20 past their date"); figures that do not say what they count; many zeros with no "nothing yet" reading |
| Hierarchy: what matters first | 5 | 6 | Every figure the same size; four rows all "Critical"; no page says "do this first" |
| Visual consistency | 7 | 6 | Phone is one system (phone.css); desktop is the existing web's stylesheets plus Tailwind plus `!important` layers, three generations deep |
| Layout correctness | 7 | 8 | Fixed on 2026-11-20: card-in-card, rails overflowing, text run together or cut. The sweep still finds text cut-offs on desktop tables |
| Tables | 5 | 7 | Phone: sideways scroll with a "Swipe" hint. Desktop: dense, fixed-width and clipped |
| Forms and drawers | 6 | 6 | Drawers vary in width and footer; validation reads differently page to page |
| Loading, saving, motion | 6 | 5 | Skeletons now on page load (both); saves, errors and toasts still vary; almost no motion |
| Language | 6 | 6 | Jargon labels, long titles, mixed case, "View all" vs "To-Dos 33" kinds of drift |
| Accessibility | 7 | 7 | Contrast checked at build (180); targets fixed on phone; no screen-reader or keyboard audit yet |
| Web ↔ app parity | 7 | n/a | Aligned on 2026-11-20 by hand; nothing stops them drifting again |
| **Overall** | **6.5** | **6.5** | |

## 2. What "10/10 enterprise grade" means here: measurable, not a mood

A screen is 10/10 when all of these hold. Each has its own check.

1. **No defects a reader can see**: the ui-sweep finds 0 issues across every
   role × phone/tablet/desktop, and runs on every pull request (it fails the
   build).
2. **Every figure is trusted**: each says what it counts and for when;
   figures on one screen never contradict; each opens the list it counts
   (it does today) and that list's count equals it.
3. **Each page has one focal point**: a reader can say in five seconds what
   the page wants from them (tested with real users, §5 phase 7).
4. **One system**: every colour, size, space, radius and shadow comes from
   `platform/design/tokens.json`; no page-local hex values; one component
   for each job (one card, one table, one tab rail, one drawer).
5. **Fast and calm**: p95 time to a usable screen ≤ 1.0 s on desktop and
   ≤ 1.5 s on a mid-range phone on 4G; no layout shift (CLS < 0.05); a save
   answers in ≤ 300 ms (177's target), then confirms quietly.
6. **Accessible**: WCAG 2.2 AA, checked by axe in CI and by a keyboard and
   VoiceOver/TalkBack pass on the twelve core screens; 44 px targets on
   touch.
7. **Both apps the same**: the web's phone layout and the Expo app read from
   one design spec and one token file; a parity check compares their
   choices (what each shows, in what order).
8. **Proven with users**: five people per core role complete their top
   three tasks unaided, with SUS ≥ 80 (industry "excellent"). **This cannot
   be claimed without the sessions.** It is the step that turns a 9 into a
   10.

## 3. Principles

- **Evolve, do not replace.** Keep the layouts the owner chose; raise their
  quality underneath: the tokens, the spacing, the type, the states.
- **Phone-first, desktop-complete.** Design each pattern at 390 px first,
  then give the desktop what it gains from width (side by side, more
  columns, hover detail). The desktop never just shows the phone stretched.
- **Numbers before pixels.** A beautiful figure that is wrong costs more
  trust than an ugly one that is right.
- **One page, both apps, measured.** Each change ships to web and app
  together, with its sweep and its before/after captures.
- **The owner decides taste.** Every visual change is shown first, as
  before/after on phone and desktop, on `/design-preview`.

## 4. The workstreams

### A. Trust in figures (both)

| Do | Phone | Desktop |
|---|---|---|
| A figure contract: label, what it counts, period ("FY2027", "this week"), source, drill-down | Label + period under the figure; a tap opens what it counts | The same, plus the definition on hover/focus (already in `description`) |
| Reconcile figures that look the same and count differently (Home's Overdue vs "My Overdue Plans") | Wording now says "from any year" (2026-11-20). **Owner decision**: one figure, or two clearly named ones? | same |
| Zero reads as a state, not a number: "None overdue · all clear" in the tile's tone | Compact tiles (done 2026-11-20) | Tiles keep size; a zero tile goes quiet (muted) |
| "As of" on every computed page (the figures' time) | In the page header line | In the page header line |
| A figure audit per role: every tile and figure checked against the list it opens | — | — |

### B. Hierarchy: one focal point per page

- **Figure tiers.** Hero (1–2 figures that decide today's work, large),
  supporting (compact tiles, done), reference (behind "All figures").
  **Owner decision per role**: which figures are heroes.
- **One "Do this first" band** at the top of each work page: the top item
  of the queue with its action. On a phone it is the first thing under the
  title; on desktop it spans the top of the content column.
- **Severity that means something**: at most one "Critical" tone per
  screen; the rest step down (warning, info). Today four rows read
  "Critical".
- **Desktop layout**: main column (work) + right rail (context: figures,
  shortcuts, help). The rail already exists on several pages; make it the
  rule at ≥ 1280 px. Phone: one column, the rail's content after the work.

### C. One visual system (desktop is the bigger job)

- **Tokens everywhere.** Map the existing web's colours, sizes and radii to
  `tokens.json` (180) so both stylesheets read one source; then remove the
  page-local hex values and the `!important` layers one stylesheet at a time.
- **One component per job**: card, figure tile, table, tab rail/switch, chip
  rail, filter bar, drawer, empty state, skeleton, toast, row menu. Today
  the web has three generations (the existing web's markup, `components/ds`,
  `components/eds`); the app has its own. Converge on one spec per part in
  `platform/design/components.md`, built twice (web, app).
- **Type and space**: 13.7 px body, 500/600/700 weights (owner rule),
  one 4-px spacing scale, one content inset (16 px, owner rule).
- **Desktop density**: a comfortable/compact switch for tables and lists
  (people working all day on a laptop want compact); the phone is always
  comfortable.

### D. Tables, designed per screen

- **Phone**: the owner chose "Rows on phones" (2026-11-19). Each of the ten
  most-used tables becomes a row card: title (school), the 2–3 facts that
  matter, status pill, one action, details on tap. No sideways scroll on
  those ten; the rest keep the sideways table until their turn.
- **Desktop**: sticky header, first column pinned (except where the owner
  ruled no pinned columns on phones), wrap instead of clip, column chooser
  for the widest (Core Schools 18 columns, Work Plan 15), bulk-action bar
  (exists) consistent on every list.

### E. Forms, drawers and saving

- One drawer: same width (desktop 560 px; phone full-screen sheet), same
  header, same footer (primary right, cancel left), errors at the field and
  summarised at the top.
- Saves stay in place (owner rule) and confirm with one toast style, with
  Undo where the action allows it.
- Inline validation as the reader types for formats; on submit for rules.

### F. States, motion and feedback

- Loading: skeletons on every page (done 2026-11-20: web `loading.tsx`, app
  `PageSkeleton`); skeletons inside cards that load later.
- Empty states: what is missing, why, and the one action that fills it.
- Errors: plain cause + what to do + Try again; never a raw code.
- Motion: the token durations (120/180/260 ms) for drawers, menus, tab
  changes; nothing moves for reduced motion.

### G. Language

- A short copy guide: sentence case, plain verbs ("Plan", "Approve",
  "Send"), numbers with units, dates "Thu 20 Nov", money "UGX 1.2M".
- A label audit per role: titles under ~30 characters, no internal jargon
  on reader-facing screens, the same thing always called the same name
  ("To-Dos", not "View all" here and "To-Dos 33" there).

### H. Accessibility

- axe in CI on the twelve core screens (both sizes); keyboard order and
  visible focus on desktop; VoiceOver/TalkBack labels on the app's controls;
  44 px touch targets (started 2026-11-20).

### I. Web ↔ app parity

- One spec, two builds: each part's rules (what shows, how it folds, what it
  says when empty) live in shared, tested functions on both sides (the
  pattern started with `todayView`, `railChips`, `foldSegments`).
- A parity test per core screen: given the same Go answer, both apps choose
  the same rows, figures and labels.

### J. The quality system that keeps it at 10

- **ui-sweep in CI** (built 2026-11-20, `platform/tools/ui-sweep`): fail
  the build on any finding.
- **Visual regression**: per role × size screenshots of the core screens,
  compared on every PR; a reviewer approves intended changes.
- **Performance budgets** (Lighthouse CI on desktop and phone profiles).
- **A design review** once a week: the owner sees the before/after of every
  change on `/design-preview`.

## 5. Phases (estimates; each ends on its exit check, not a date)

| Phase | What | Exit check |
|---|---|---|
| 0 · Baseline (week 1) | Scorecard of §1 recorded with captures; sweep and axe wired to CI (report-only) | Baseline numbers written in this doc |
| 1 · Zero visible defects (weeks 1–3) | Fix every sweep finding on every role and size; desktop text cut-offs; drawers' widths | Sweep 0 findings; CI gate switched on |
| 2 · Trust in figures (weeks 2–5) | Figure contract on Home, Dashboard, My Plan, Planning, Core Schools, Budget; reconcile duplicates after the owner's decisions | Every figure on those pages says what/when, matches its list; owner signs off |
| 3 · One system under the existing look (weeks 3–8) | Tokens mapped; one card, tile, table, rail, drawer, toast spec built twice; legacy `!important` removed page by page | No page-local colours on the core screens; parity tests green |
| 4 · Hierarchy per role (weeks 5–10) | Hero figures + "Do this first" band, CCEO first, then PL, CD, IA, Accountant, Partner | Owner approves each role's before/after on phone and desktop |
| 5 · Phone tables as rows (weeks 6–12) | The ten most-used tables as row cards; desktop tables wrap, pin, choose columns | No sideways scroll on the ten; desktop clip-free |
| 6 · Polish (weeks 8–14) | Motion, empty/error states, copy guide applied, keyboard and screen-reader pass | axe 0 serious; copy audit done |
| 7 · Prove it (weeks 12–16) | Usability sessions: 5 users × core roles, top three tasks, SUS | Task success ≥ 90 %, SUS ≥ 80; fixes from the sessions shipped |

Phases overlap; the work is one page at a time across both apps.

## 6. Decisions the owner holds

1. **Which figures are heroes**, per role (B). Proposed for the CCEO:
   Overdue and Waiting on you.
2. **Overdue**: one figure for "past their date", or keep two clearly named
   ones (this year's plan vs any year's)?
3. **School Directory for Accountant, HR and the Regional VP**: their menu
   shows it, Django's page permission refuses them. Remove the link, or
   grant the page?
4. **Desktop density**: offer compact/comfortable, or one fixed density?
5. **Usability sessions**: who can take part (staff per role), and when.

## 7. Risks

- **Taste**: the owner rejected one redesign; every visual step therefore
  goes through before/after review first (§3).
- **Two apps double the work**: shared, tested choice functions (I) keep
  them honest.
- **Parity with Django**: while Go is checked against the existing pages
  (goldens), wording changes land on both sides together (done this way on
  2026-11-20).
- **Scope creep**: each phase has an exit check; nothing moves on until it
  holds.

## 8. Next, if approved

Phase 0 and Phase 1 need no new decisions: wire the sweep and axe into CI,
then work the sweep's findings to zero on every role and size. Phase 2 and 4
start the day the owner answers §6.1 and §6.2.

## 9. Progress

**2026-11-20**
- **Tiles** (owner: "look at those tiles they are more beautiful"): every
  figure strip is now a tile with its tinted icon, figure, label and line.
  On desktop they sit four across (`page/FeedStrip`); on phones the icon
  sits beside the figure, in both apps.
- **Phase 1, visible defects:**
  - Text no longer runs together: both readers join two parts with " · ",
    Go matches every golden, and the word-count rules decide as before.
  - Text is no longer cut: table cells, row sub-lines and Admin dashboard
    rows wrap.
  - Rails and switches fold into More instead of overflowing.
  - No card sits inside a card; an empty pager draws nothing.
  - On narrow phones the filter row holds two filters in both apps.
  - The Cluster Leader's web landing is "your work is in the Edify app".
  - Pages load as an outline of the page on web and app.
  - Tap targets on touch are at least 36px.
- **Accessibility:** axe runs in the sweep. The contrast, scrollable-region
  and label-in-name findings on the core pages are fixed.
- **Quality system:** `platform/tools/ui-sweep` (every role × phone, tablet
  and desktop, plus axe) runs in Platform CI, report-only until it reaches
  zero findings.
- **Phase 5, reversed by the owner the same day:** row cards, then a
  compact list with a detail sheet from 16 rows, were built in both apps;
  the owner chose "the spreadsheet list format better on all screen", so
  `ROWS_ON_PHONES` is off and the code is kept. Tables were then made more
  premium ("just make them look more premium"): a white title bar, a light
  column band closed by one fine line, no rules between column names, finer
  row hairlines, edges on the 16px content line, linked names in link blue
  on phones too, a quiet "—" in an empty cell, and column names in proper
  Title Case (`lib/titleCase`). Row height stays the owner's pinned 32px
  (2026-09-05; the owner declined 40px).
- **Explanations fold** (owner: "hide all the explanations ... using a
  chevron"): a table's footnote, and a title-less one-text panel right after
  a table (`lib/tableNote`), sit closed under "Explanation" on desktop,
  phone web and the app. A title-only panel is a section heading, not an
  empty card.
- **School IDs:** every School ID column read empty in both apps because
  the feed ran pages without the middleware that fills `{% school_code %}`.
  The feed now runs it, and every Go page writes the same words
  (`internal/schoolcode`, about twenty pages).
- **§6.1 and §6.2 answered** (owner, 2026-11-20): a CCEO's hero figures are
  Overdue and Waiting on you (Home draws them first and larger, both apps);
  Overdue is one figure, this financial year only: Home's tile and the "My
  Overdue Plans" row count the same work and open the same list. The
  dashboard's "What needs you now" table still lists every year's, and a
  Lead's team row stays that table's count.
- **Fewer tiles, platform-wide** (owner: "reduce the number of kpi stats to
  the major used ... do it throughout the platform"): every figure strip on
  web and app shows at most four figures, in the gateway's order, with
  "Not measured" ones moved to the fold first; the rest sit under a closed
  "All figures (n)" chevron (`lib/heroStrip` foldFigures). A Programme
  Lead's dashboard leads with Waiting on You and Visits Planned Against
  Target, lifted out of their strips into a larger hero strip (owner's
  choice the same day).
- **My Plan shows its planned work** (owner, 2026-11-20, "it should show
  tiles based on what has been planned"): up to three figures with
  something planned, in the owner's order (School Visits, Core Visits
  Scheduled when such a figure exists, Trainings, Cluster Meetings, then
  the period counts), with My Completed Share always in view; nothing
  planned shows School Visits. The rest fold.
- **Compact layout** (owner: "compact beautifully laid out cards, tables,
  tiles, filter, headers"): measured on seven pages at 1440 and 390 px, then
  one 12px rhythm between blocks and tiles, tighter phone headers (25–31px
  back), compact tiles (10–14px shorter), 12px card corners, and an empty
  table line on the 16px content line.
- **Sweep findings:** colour contrast on record cards, nameless selects,
  the calendar's grid rows, small phone targets, cut-off directory names,
  run-together parts and the unfocusable scroll region are fixed.

**Still open:** the sweep re-run to zero and its CI gate; Phase 3, one
visual system on desktop; Phase 6, drawers (Django's until each save cuts
over), toasts, copy and motion; Phase 7, sessions with users.

