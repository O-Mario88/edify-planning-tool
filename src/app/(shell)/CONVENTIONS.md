# Edify shell route conventions

These rules govern how routes are added, named, and retired in the
authenticated `(shell)` group. They exist because the app drifted into
multiple-URLs-per-concept by accident, and untangling that is expensive.
Read this before adding a new route or renaming an existing one.

## Rule 1 — One canonical URL per concept

Every concept the user can reach has exactly one URL. If a concept can
be reached at two URLs, one of them is wrong and must redirect to the
other.

A "concept" is what the user thinks of as a thing — "the approvals
queue", "the partner today list", "the upload center". Not a database
table. Not a component. Not a role view (role views are *served by* the
canonical URL, not separate URLs).

### Test before adding a route

Ask: *Is there an existing URL where a user would expect to find this?*

- If yes → put it there (or as a sub-route under it). Do not create a
  parallel URL.
- If no → create the new URL, add it to the role's sidebar entry if
  it's a top-level concept, or make sure at least one existing page
  links to it so it's discoverable.

## Rule 2 — Deprecated URLs redirect, they don't 404

When you collapse two URLs into one, the loser becomes a
`permanentRedirect()` to the winner. Bookmarks, search engines, demo
recordings, and CCEO training materials all carry old URLs — a 308
redirect keeps them alive at zero cost.

Pattern:

```tsx
// src/app/(shell)/old-route/page.tsx
import { permanentRedirect } from "next/navigation";
export default function DeprecatedOldRoute() {
  permanentRedirect("/new-route");
}
```

For dynamic segments, await the params and forward them:

```tsx
export default async function Deprecated({
  params,
}: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  permanentRedirect(`/new-route/${id}`);
}
```

Leave a one-line comment at the top explaining what's canonical and
why. Future maintainers will thank you.

## Rule 3 — Sidebar = top-level. Sub-pages = drill-downs.

[`src/components/shell/EdifySidebar.tsx`](../../components/shell/EdifySidebar.tsx)
defines the entry points each role can reach in one click. It is
**not** an inventory of every URL.

- Top-level concepts go in the sidebar (e.g. `/approvals`,
  `/schools`, `/planning`).
- Detail pages (`/schools/[id]`), workflow sub-pages
  (`/budget/approvals/funds-matching`), and per-record drill-downs do
  *not* go in the sidebar — they're reached from their parent page,
  from cards, or from insights.
- If a sub-page has no parent that links to it, you have an
  orphan — either add a discoverability path or delete it.

## Rule 4 — Role-scoped views live at the same URL

If five roles need different versions of the approvals queue, the URL
is `/approvals` for all five. The page reads the user's role and
renders the right view:

```tsx
export default async function Page() {
  const user = await getCurrentUser();
  if (user.role === "RVP") return <RvpView />;
  if (user.role === "CountryDirector") return <CountryView />;
  return <PlView />;
}
```

Do **not** create `/approvals/rvp`, `/approvals/cd`, `/approvals/pl`.
URLs are user-facing concepts, not implementation details.

The exception: role-specific *dashboards* (`/dashboards/cpl`,
`/dashboards/director`, etc.) — these are explicitly different
products with different IA, not the same product filtered by role.

## Rule 5 — School-facing activity recommendations must be SSA-driven

Every activity the system recommends to a school — a visit, a training,
a coaching session, an SSA verification — must be traceable back to that
school's SSA data: a missing assessment, a low overall score, or a
weakness in a specific intervention area. **No school receives an
activity the SSA didn't ask for.**

The engine pattern (see [`lib/plan-builder-engine.ts`](../../lib/plan-builder-engine.ts)):

```ts
const recommendedActivity =
  ssaScore == null              ? "SSA Verification" :     // no assessment
  score   >= 80                 ? "Follow-up Visit"  :     // severe overall gap
  matchedTraining               ? "Cluster Training" :     // weakest intervention has a cohort
                                   "School Visit";         // catch-all
```

The `matchedTraining` join is the load-bearing piece for trainings:
`trainingForIntervention(school.weakestIntervention)` finds the
cluster cohort whose `mainWeakness` equals the school's weakest
intervention area. If the cohort exists, the school is recommended to
attend it; if not, the system falls back to a visit. **A school never
gets a training that doesn't match an SSA gap.**

This rule applies equally to cluster-level recommendations
(`mainWeakness → recommendedActivity` in `CLUSTER_SEED`) and to any
future recommendation surface (partner coaching, special projects,
etc.). New recommendation engines must accept SSA as input and emit a
`priorityReason` string that names the SSA signal they fired on. If
you can't explain the recommendation in terms of an SSA fact, the
recommendation doesn't ship.

Dashboards consume this discipline through `lib/training-stats.ts` →
[`TrainingCoverageCard`](../../components/director/TrainingCoverageCard.tsx),
which breaks delivery down by SSA intervention so the CD / RVP can see
whether the trainings being delivered match the gaps the SSA flagged.
A weak intervention area with 0% training coverage is an escalation,
not a metric.

## Rule 6 — Mobile is a render variant, not a separate route

`/m/*` is legacy. New mobile work goes through
`<ResponsiveDashboard mobile={…} desktop={…}>` on the same URL the
desktop user visits. The `/m/[...legacy]` catch-all redirects old
bookmarks; do not extend it.

## Current canonical URL map (load-bearing examples)

| Concept | Canonical | Deprecated → redirects |
|---|---|---|
| Partner workflow surfaces | `/partner/*` | `/dashboards/partner/{schools,reports,evidence,activities,planning,inbox/[tab]}` |
| Upload center | `/data-intake/upload` | `/data-upload`, `/data-upload/[id]` |
| Fund approvals (entry) | `/approvals` | `/budget/approvals` (bare; sub-pages still live) |
| CCEO operating view | `/dashboards/cceo` | `/work-plan` |
| Planning tool | `/planning` | — |
| Plans index + detail + new | `/plans`, `/plans/[id]`, `/plans/new` | — |
| Role-scoped current plan | `/my-plan` | — |

When you add to this table, also add the redirect file and grep the
codebase for hard-coded references to the deprecated URL.
