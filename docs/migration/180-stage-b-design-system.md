# 180 · Stage B: the Enterprise Design System, first cut (2026-11-19)

Stage B of the modernization program (177), started from Stage A's audit
(179). What exists, and what it is for.

## Tokens: one source for both apps

`platform/design/tokens.json` holds the design system's tokens: light and
dark colours (surfaces, borders, three text levels, primary and the brand's
ink, focus, four statuses each with a soft background and a border, six
chart colours), Geist with only weights 500/600/700 and tabular numerals,
the type scale (caption 12, body 13.7, control 15, lead 16, title 20,
display 26, figure 28 — the owner's 13.7 px text standard of 2026-10-10 kept
for body text; controls are 15 so phone fields do not zoom), spacing,
radii, two shadows, the 44 px target, the 177 breakpoints and motion
durations. The brand colours are the existing application's (#0e5da3,
#073962).

`node platform/design/build-tokens.mjs` (`npm run tokens:ds` in either app)
writes them to the web app as CSS variables and a Tailwind v4 theme
(`platform/web/src/styles/ds/tokens.css`, imported by `globals.css`; the
utilities are `bg-ds-surface`, `text-ds-body`, `rounded-ds-lg`, …) and to the
Expo app as a typed module (`platform/mobile/src/ds/tokens.ts`). Before
writing it checks every text and status colour against each surface it is
drawn on: 74 pairs, all at WCAG 2.2 AA (4.5:1; focus 3:1). The first draft
failed one (the dark theme's primary on a selected surface, 3.92) and was
corrected before it was written. `platform/web/scripts/ds-tokens.test.ts`
fails when either generated file differs from the source or a pair falls
below AA.

## Components

`platform/web/src/components/eds` — Button (primary, secondary, ghost; 44 px),
StatusBadge (a status in words, toned), SectionHeader (title, count, link),
Surface, KpiStat (a figure, its target and share), TaskRow and TaskList (a
task, where, its state and its one action), EmptyState, Skeleton and
Segmented, and DataTable: one set of columns drawn as a table from 768 px
and, below it (owner, 2026-11-19: "Rows on phones"), as a list of rows —
the record's title as its link, its context columns (a school's School ID
and district) as the second line, its status as a badge, and every other
column under "More details". Checked in the browser at 375 and 1280: only
one of the two is drawn, and the phone page has no sideways scroll. The
existing web's stylesheets hold `.hidden` over Tailwind's responsive
`md:block`, so the table is hidden below 768 with `max-md:hidden` instead.
They draw only with the design system's tokens and stand apart
from `components/ds`, which draws the live system's markup for the pages kept
at parity until each is redesigned. The Expo app has the tokens; its
components follow the web set.

## Preview

`/design-preview` in the web app (signed in): the colours, the type scale and
the components, then before/after pairs at phone width for the CCEO's,
the Program Lead's and the Accountant's Today. Each "before" is a Stage A
capture of the existing application on local data; each "after" is the
proposed layout with **sample content** (no data is read), to review the
structure before a page is rebuilt.

Checked in the browser pane at phone width (2026-11-19): the tokens and
components draw as specified. Two faults were found and fixed: Tailwind 4
read `font-[700]` as a font family, so weights now use `font-semibold` /
`font-bold`; and a task's context line was cut off with an ellipsis, against
the owner's rule that text wraps.

## Waiting on the owner

Tables on phones is decided (rows, above), and so is the greeting band
(owner, 2026-11-19: "Drop it on phones"): the web app's phone Home and the
Expo app's Home open on the role and the greeting on two quiet lines, then
the overview — checked in the browser at 375 and 1280 (the desktop page
header is unchanged) and in the iOS Simulator. Where leadership lands is
decided too ("Own role home"): both apps land every reader on Home. All
three of 179's decisions are made; the preview shows the proposed
answers so they can be judged side by side with today's screens.

## The CCEO's Today, built and kept as a preview

The CCEO's Today was built in both apps on the design system: web
`components/today/TodayScreen` (rules in `lib/todayView`), Expo
`screens/TodayScreen` on `ds/components` (rules in `ds/todayView`, the same
choice). It reads Go's Home answer and leaves out only the rows that report
"all clear". Checked against the existing Home for the same CCEO: the same
waiting rows, figures and To-Do total, in the browser at 375px and in the iOS
Simulator.

After seeing it, the owner kept the existing Home (2026-11-19: "i think i
like the previous home screen better"). The switch is off in both apps (web
`REDESIGNED` in `app/(app)/home/page.tsx`, Expo `TODAY_ROLES` in
`ds/todayView.ts`, both empty). The Today stays as the web preview
`/today-next`, and its components stay for later screens.

## Next

No role's Home is replaced unless the owner asks. Before another core
screen is redesigned, the owner says what to carry over from the existing
one.
