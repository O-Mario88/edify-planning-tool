# UI/UX findings — rendered evidence

Method and limits: [06-uiux-method.md](06-uiux-method.md).
Every finding below was verified in a rendered browser, not inferred from code.

---

## UX-001 · HIGH · FIXED — the mandatory policy gate failed AA contrast, including its safeguarding escalation times

**Surface:** `/documents/<slug>/` (canonical document / agreement gate) — the
page **every user must pass before they can work**.

**Measured, dark theme, 1280px:** 12 strings below WCAG 2.2 AA.

| String | Ratio | Required |
| --- | --- | --- |
| "IMMEDIATE", "WITHIN 1 HOUR", "WITHIN 12 HOURS", "AS SOON AS POSSIBLE" | 3.87 | 4.5 |
| Policy body copy ("Edify is committed to ensuring the safety…") | 3.87 | 4.5 |
| "Welcome back, …" toast | 2.50 | 4.5 |

Those first four are the **safeguarding escalation timeframes** — the copy that
matters most at the moment someone needs it.

**Root cause, and it is systemic.** The agreement styles accents from
`--agreement-blue`/`--agreement-navy`, which resolve to `--edify-accent` and
`--edify-primary` → `--brand-primary: #1872bd`. `:root.theme-dark` redefines
`--brand-primary` to **the same #1872bd** as the light theme
(`static/css/design-system.css`). So brand-accent *text* on any near-black
surface lands at 3.87:1. The platform already knows the right answer elsewhere —
`main.css` maps `.dark .text-sky-700 → #93c5fd` — but the token does not follow
that rule.

**Fixed, in the design system rather than the page.** A new
`--edify-accent-text` token carries the accent *as text*: the brand blue on
light surfaces, `#93c5fd` under `:root.theme-dark` and `:root.theme-blue`. It is
deliberately separate from `--edify-accent`, because that token also fills
buttons — lightening those would break white-on-fill contrast the other way.
The agreement now points its accent at the token. **Re-measured in the browser:
12 failures → 0**, with the token resolving to `#93c5fd`. Pinned by
`apps/documents/test_agreement_contrast.py`.

A note on the fix itself: the first version hard-coded the hex in the template
and **tripped the platform's own raw-hex rule** — a finding my change had
introduced. Moving the value into the design system removed it and made the
AA-safe accent reusable.

**Still open (recorded, not fixed):** other surfaces. Any accent-coloured text
on a dark surface elsewhere still resolves through `--edify-accent` to the light
theme's blue and inherits the same 3.87:1. The token to fix it now exists;
applying it needs a sweep of accent-on-dark text, which should be measured
per surface rather than replaced blind.

---

## UX-002 · MEDIUM · The login page renders "no data" as a measured result

**Surface:** `/login`, visible to anyone, authenticated or not.

The public panel shows four live figures. Two of them currently read:

> **TASKS COMPLETED 100%** · Current FY  **TARGET PROGRESS 0%** · Validated results

`monthly_personal_target` holds **zero rows**, so `target_total` is 0 and
`apps/frontend/views/auth_views.py` returns `0` — which renders as **"0%"
labelled "Validated results"**. The honest state is "no targets have been set",
not "0% of targets achieved".

This is the platform's own integrity law — *missing data must never render as
zero* — broken on its most-viewed page, and it sits beside "100% tasks
completed", so the pair reads as either contradictory or broken.

**Recommendation:** when the denominator is zero, show the figure as unavailable
("—", "Not yet set") rather than 0%. The same guard the KPI registry applies
internally (`DataState`) should apply here.

**Also worth a decision:** these are live operational counts (16,988 schools,
322 field visits) published to unauthenticated visitors. That may well be
intended as marketing, but it should be a decision on record rather than a
side effect.

---

## UX-003 · LOW · "Submit without proceeding" does not say what it does

**Surface:** agreement gate, secondary action beside "I Accept → Continue".

A user cannot predict the outcome: does it record disagreement, block access,
notify someone, or simply exit? Mandate §25.2 requires action labels to describe
the result.

**Recommendation:** name the consequence — e.g. "Decline and sign out" — and
state in one line what happens next.

---

## Verified GOOD (rendered)

- **320px, agreement gate:** no horizontal overflow, no element wider than the
  viewport, and **zero interactive controls below the 44px touch target** —
  measured, not assumed.
- **Login form semantics:** the submit button's accessible name is "Access
  workspace" and the "Remember me" checkbox is correctly labelled (both were
  false positives from the inspection tool; the DOM is correct).
- **Login status region** carries `role="alert"` + `aria-live="polite"`, so
  sign-in errors are announced.
- **Loading feedback exists globally** (`.htmx-request` cursor treatment,
  `.htmx-indicator`, `.platform-skeleton`) — contrary to the inventory's
  per-template detector, which cannot see it.
