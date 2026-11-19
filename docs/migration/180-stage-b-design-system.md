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
Segmented. They draw only with the design system's tokens and stand apart
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

The three decisions in 179 (tables on phones, the greeting band, where
leadership lands) shape the next screens; the preview shows the proposed
answers so they can be judged side by side with today's screens.

## Next

The redesigned screens themselves (177 stage D), each reading Go: the CCEO's
Today first (the Home queue, the day package and the next visit Go already
answers), web and Expo together, each proved against the existing figures
before it replaces a screen; the drawers and depth each needs are ported
then (178).
