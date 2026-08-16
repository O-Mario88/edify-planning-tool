# UI/UX audit — method, scope, and what this environment can evidence

Baseline: commit b295de61 + working changes, 532 routed surfaces, 14 roles.
Dev server rendered at http://localhost:8000, Chromium via the in-app browser,
themes as shipped, viewports 320px–1280px.

## What this audit can and cannot evidence

The mandate asks for observed time studies with named user counts (5 CCEOs, 5
Program Leads, 3 Country Directors, and so on), interviews, screen recordings,
and satisfaction scoring. **None of that is performable from here** and none of
it is reported. Where the mandate asks a question only a real user can answer,
this audit says so rather than substituting a plausible guess.

**Evidenced here:**
- Rendered inspection of live pages: computed colour contrast, layout overflow,
  touch-target geometry, accessible names read from the DOM.
- Static review of all 532 surfaces via the generated inventory.
- Code-level review of navigation, roles, content, components, forms,
  notifications, To-Dos and data presentation.

**Not evidenced (carried as open obligations):**
- Time-on-task and the 15-minute standard — the instrument exists (interaction
  telemetry with the §3a planning/execution split) but has no production data.
- First-attempt success rates, help requests, user confidence and trust.
- Real-device field conditions: bright sunlight, low-end Android, intermittent
  connectivity.
- Offline field behaviour — the client half is unbuilt.

## A methodological warning worth recording

Three of this audit's first findings were **false**, and each was caught only by
verifying before reporting:

1. The accessibility tree reported the login page's primary button as unnamed
   and its checkbox as named "on". The DOM disagreed: the button reads "Access
   workspace" and the checkbox is properly labelled. The tree output was a
   serialization artifact of the inspection tool.
2. A first contrast pass reported failures on strings using `oklch()` colours.
   The measurement was wrong, not the page — the luminance helper parsed
   `oklch(0.968 …)` as if it were RGB. Re-measured by painting each colour to a
   canvas and reading the sRGB pixel.
3. A "disagree" button label turned out to be the `value` attribute; the visible
   label is "Submit without proceeding".

The same discipline applies to the generated inventory. Its state-coverage
detector greps each page's own template, so it reports 346 of 351 full pages as
having "no loading state" — but the platform serves loading feedback globally
from `static/css/platform.css` (`.htmx-request` cursor treatment,
`.htmx-indicator`, and a reusable `.platform-skeleton`). **That figure is a
detector artifact and must not be quoted as a finding.** The real question —
whether the feedback is *sufficient* — needs rendered evidence per surface.

Any UI/UX number in this audit that came from a detector rather than from
rendering is labelled as such.
