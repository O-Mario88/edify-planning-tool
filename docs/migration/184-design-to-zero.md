# 184 · Design to zero: what is closed, what needs the owner, the user-testing kit (2026-11-20)

The owner asked, of doc 181's remaining design work: "can you complete those
to zero". This records what was closed, what is measured and held by a gate
so it only goes down, and what cannot be closed without the owner or real
users. Nothing here was claimed without a check; each item names its
evidence.

## 1. Closed in this pass

| Item | What changed | Evidence |
|---|---|---|
| App parity for the week redesign | The app draws counted links as figure tiles, the week as one control, segment tabs with count badges (`platform/mobile/src/ui/page/presentBlocks.ts`, `PagePanelView`, `PageLinkTabsView`) | App type check clean; 269 app tests pass (incl. `presentBlocks.test.ts`) |
| Heroes for every role | Home leads with two deciding figures for every role: Overdue + To-Do where the role has a plan (CCEO, partners), Critical + To-Do at a desk (CD, IA, Accountant, Admin, HR, others). Web `lib/homeScreen.ts heroKeys`, app `screens/homeHeroes.ts` | Web 9 and app 4 hero tests; screenshots of CD and CCEO Home, desktop and phone |
| Hero grid | Two heroes side by side, the rest sharing the row; one left over takes the row (a desk role's three figures had stacked two-thirds wide) | Screenshots |
| Keyboard pass | Tabbed through Home, Dashboard, My Plan, Schools, Calendar and To-Do as a CCEO, desktop and phone: every stop shows a focus mark (the only exception is Next's development overlay, absent in production). Added "Skip to main content" as the first stop (WCAG 2.4.1) | Probe output; skip link verified: first stop, Enter lands in the page |
| Error and not-found states | A failed page shows a card in the shell with Try again, Go to Home and a support reference; an unknown address shows "This page is not here" with the way back. Never the framework's bare screens | Unknown address checked in the browser |
| Reduced motion | Honoured everywhere, not only in the phone layer | `globals.css` |
| Accessibility gate | axe: 0 serious or critical on every role's pages (doc 181 §9), now a CI gate | CI UI sweep: 896 page loads, 0 findings |

## 2. Figures: the audit, and the owner's decisions it needs

Each linked figure on Home, Dashboard, My Plan, Planning and Core Schools
was read against the list it opens, as a CCEO and as a Programme Lead
(local data):

- **Consistent:** the dashboard's week figures match the week (0 planned, 0
  behind, "Nothing left to complete"); "8 past due, any age" equals the three
  past-due tables it points at (6 visits + 0 trainings + 2 meetings); My
  Plan's visit figure matches its "Planned and remaining" table.
- **Inconsistent scope (owner decision):** a Programme Lead's dashboard counts
  the team (102 Core schools, 660 schools), while the same lead's **Core
  Schools** page opens on "0 Total Core Schools" and **Planning** on zeros:
  those pages open on the lead's own portfolio (none), with the team behind
  a "Team Core Oversight" tab. Neither page says whose figures they are.
  Options: (a) a lead opens Core Schools and Planning on the team lens;
  (b) both pages say "Your own schools" over the figures and keep the
  default; (c) as now. Recommendation: (a). It changes Go's answer from
  Django's for those pages, so it needs the owner's word and an entry in
  `internal/parity/intended.json`.
- **"No data" for a share with nothing planned** (My Plan's completed share):
  recommend "—" with "Nothing planned yet" under it, the same as other
  unmeasured figures (owner decision: it is the existing page's word).
- **Budget:** no Budget page answers at `/budget` for these roles in the Go
  web; the audit of its figures waits for its page.

## 3. One visual system on desktop: measured, gated, not finished

The existing web's stylesheets (`static/css`, 46 files, shared with the
Django pages until they retire) hold **4,105 forced overrides
(`!important`) and 2,550 hard-coded colours**, measured 2026-11-20. They
cannot be rewritten at once without changing the live Django pages; they
are retired page by page as each page moves wholly to the Next.js
components, with the parity tests green. From today the budget only goes
down: `platform/web/scripts/css-budget.test.ts` fails the build if either
count grows and says when it falls, so the baseline is lowered with each
retirement. Order: Home, Dashboard, My Plan, Schools, Calendar, To-Do, then
by page traffic. Target: 0 page-local colours on those six.

## 4. Polish still open

- **Drawers** stay the existing web's until each save moves to Go (doc 183
  is the first); each is redesigned with its save.
- **Save messages** ("Saved. Press Refresh to see it on the page.") are the
  existing feed's words; Go saves answer in the same words by design
  (parity). A new wording is one owner decision for all saves at once.
  Recommended: "Saved." with the row updated in place.
- **Copy guide:** plain words, sentence case for sentences and Title Case
  for table headings (already applied), numbers as figures, dates "20 Nov
  2026", no internal codes in text people read, a refusal says what to do
  next. Applied to everything written in this pass; the existing pages'
  words change with their pages (§3).

## 5. Proving it with people: the kit (needs the owner)

Real sessions need real staff; this kit is ready to run.

**Who:** 5 people per core role: CCEO, Programme Lead, Country Director,
Impact Assessment, Accountant, Partner. Each session is about 30 minutes, on
their own phone or laptop, against staging (never production data entry).

**Tasks, three per role, read aloud, no help given:**

| Role | Task 1 | Task 2 | Task 3 |
|---|---|---|---|
| CCEO | Find what is overdue and open the oldest | Schedule a school visit for next Tuesday | Complete today's visit with its Salesforce ID |
| Programme Lead | Find what waits on you and approve one | Find how many visits your team planned against target | Open one officer's week |
| Country Director | Find the most critical To-Do and open it | Find a school without an SSA | See how the partners are doing this week |
| Impact Assessment | Verify one waiting completion | Find a school's SSA history | Export this month's completions |
| Accountant | Find money awaiting your action | Open one weekly request's lines | Find an advance with accountability pending |
| Partner | Find your assigned schools | Date one assigned visit | Upload a completed visit's form |

**Record per task:** done unaided (yes/no), time, wrong turns, words the
person used for what they looked for.

**After the session: SUS** (each 1–5, strongly disagree to strongly agree):
1. I think I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think I would need help to be able to use this system.
5. I found the functions in this system well integrated.
6. I thought there was too much inconsistency in this system.
7. Most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot before I could get going with this system.

Score: odd items (score − 1), even items (5 − score), sum × 2.5.

**Targets (doc 181):** task success ≥ 90 %, SUS ≥ 80. Every failed task
becomes a fix, shipped and re-tested with the next person.

## 6. Where it stands

Closed and gated: visible defects (sweep 0), accessibility (axe 0),
keyboard, error and empty states, motion, heroes for every role, app parity
for this pass. Measured and only falling: the desktop system (§3). Waiting
on the owner: figure scope (§2), save wording (§4), the user sessions (§5).

## 7. The owner's word, 2026-11-21: "please proceed"

The three recommendations above were taken, and the first retirement made:

- **"No data" figures** read "—" with why under it ("Nothing planned yet"
  where the figure measures planned work, otherwise "Nothing recorded yet"),
  on the web and in the app (`presentBlocks.nothingYet`, tested on both).
- **Core Schools opens on the team's for a lead with none of their own.**
  With no lens asked, a reader who holds no core school directly but whose
  team does opens on Team Core Oversight; anyone holding core schools still
  opens on their own, and "My Core Schools" asks for its lens by name
  (`lens=mine`). Changed in the existing web (`core_schools_views.py`, its
  tab, hidden field and Clear link) and in Go (`internal/coreschools`) in
  the same commit, so the golden comparison stays equal. Django tests: the
  two that asserted the old default now ask for `lens=mine`, and a new one
  proves the team-first default (104 tests pass in those modules).
  **Planning is unchanged:** it is the officer's own scheduling page, built
  from the direct portfolio with Schedule on every row; a team lens there
  would be a new feature with write controls, not a default. A lead's
  team planning is the dashboard's and Planning Monitor's.
- **Save messages in the app say "Saved."** The app reads the page again
  after every save, so "Press Refresh to see it on the page" was untrue
  there; any other sentence a save gives is kept (`savedWords`, tested).
  The existing web keeps its words: its pages do not redraw after a save
  (owner, 2026-10-12), so the instruction is true there.
- **First retirement of hard-coded colours.** Every colour in the page
  stylesheets (`static/css/pages`) that exactly equals a light-theme design
  token now is that token: 127 colours across eight sheets (94 of them in
  Team Performance). Nothing changes in light mode by construction; those
  pages now follow the theme. The budget now measures hand-written debt
  only (not the compiled Tailwind bundles, not the tokens' own
  definitions): **4,002 forced overrides and 866 hard-coded colours**,
  the new ceiling.
