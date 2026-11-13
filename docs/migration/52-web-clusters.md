# 52. The web's Clusters page (Next.js, M15)

The Clusters page (`/clusters`) in the Next.js web app, drawn from the
gateway's `GetPage` answer, which Go gives for every reader the page admits
([14](14-districts-and-clusters.md) 14.1), with each card's schools loaded
when it opens (`/partials/clusters/<id>/schools`, 14.4). It is built on the
page blocks of [39](39-web-planning-my-plan.md) (Planning and My Plan), which
this branch carries as its first commit so it builds on its own; the two
branches merge cleanly in either order. No Django, Go or proto change.

## 52.1 What was built

| Part | Where | What it does |
|---|---|---|
| Route | `src/app/(app)/clusters/page.tsx` | `FeedPage` for `/clusters` with the browser's query |
| Cards that open | `src/components/page/FeedRecord.tsx` (now a client component) | A card with something more gets an opener. Opening shows what the card carries (the SSA panels), then asks for the part its `details_path` names: the cluster's schools, drawn as the page's table (ticks, opener with facts and SSA panels, Actions, the school's profile link), with the part's own bar for ticked schools under it. Loading, refused and not-moved answers are said in the card; an expired session reloads the page (which renews it) |
| Parts | `src/app/page-parts/route.ts`, `src/lib/pagePart.ts` | `GET /page-parts?path=…` asks the gateway as the reader (the access cookie) for an allow-listed part only (`/partials/clusters/<id>/schools`); anything else is refused before the gateway is asked. Reads only |
| Drawer links in panels | `FeedPanel.tsx` | A panel link the answer marks as a drawer ("Create Cluster", "Add Schools to Cluster") opens the same page on the existing web, never the drawer address (some drawers write when opened) |
| Selection bar | `SelectionBar.tsx` | A part's bar counts the ticks inside that card and sits under it; the page's bar leaves an opened card's ticks to the card |
| Search | `src/lib/pageSearch.ts` | "Search clusters…" (`cluster_views.py`) |

## 52.2 What renders

Go-only gateway (8085), development database, 2026-11-13: for cceo, Admin,
Country Director and Impact Assessment the header (eyebrow "Schools &
Field", Create Cluster, Schedule Group Training, Schedule Cluster Meeting),
eight filters, the eight-figure strip, five cards a page with pills, Actions
and facts, the pager with Prev/Next and gaps; a card opened shows its SSA
panels, "Schools in Cluster (7)", the seven schools in the gateway's order
(1546, 1598, 1286, 1650, 1572, 1676, 1624 for Cluster A) and, once one is
ticked, "1 selected · Assign to partner · Schedule visit". A cluster with no
schools shows "This cluster has no schools yet." with Add Schools to Cluster.
pl1 and cceo1 (no clusters): the empty panel, "No clusters found." with
Create Cluster and Open School Directory. Business Transformation: not found.

## 52.3 Comparing with the existing page

Headless Chromium, the same seed account on both (Django 8185, this app
3085 over the Go-only gateway 8085), 2026-11-13. The cards' names in order
and the pager summary, as printed:

```
cceo@edify.org /clusters: cards SAME (5 vs 5); pager SAME "Showing 1 to 5 of 22 clusters"
cceo@edify.org /clusters?page=2: cards SAME (5 vs 5); pager SAME "Showing 6 to 10 of 22 clusters"
cceo@edify.org /clusters?page=5: cards SAME (2 vs 2); pager SAME "Showing 21 to 22 of 22 clusters"
cceo@edify.org /clusters?q=Cluster%20A: cards SAME (1 vs 1); pager SAME ""
admin@edify.org /clusters: cards SAME (5 vs 5); pager SAME "Showing 1 to 5 of 22 clusters"
admin@edify.org /clusters?page=3: cards SAME (5 vs 5); pager SAME "Showing 11 to 15 of 22 clusters"
admin@edify.org /clusters?q=Cluster%20A: cards SAME (1 vs 1); pager SAME ""
cd@edify.org /clusters: cards SAME (5 vs 5); pager SAME "Showing 1 to 5 of 22 clusters"
cd@edify.org /clusters?page=3: cards SAME (5 vs 5); pager SAME "Showing 11 to 15 of 22 clusters"
ia@edify.org /clusters: cards SAME (5 vs 5); pager SAME "Showing 1 to 5 of 22 clusters"
ia@edify.org /clusters?page=3: cards SAME (5 vs 5); pager SAME "Showing 11 to 15 of 22 clusters"
ia@edify.org /clusters?q=Cluster%20A: cards SAME (1 vs 1); pager SAME ""
pl1@edify.org /clusters: cards SAME (0 vs 0); pager SAME ""
pl1@edify.org /clusters?page=3: cards SAME (0 vs 0); pager SAME ""
pl1@edify.org /clusters?q=Cluster%20A: cards SAME (0 vs 0); pager SAME ""
cd@edify.org /clusters?q=Cluster%20A: cards SAME (1 vs 1); pager SAME ""
```

(The cd search was asked twice: the first time this app's page did not reach
network idle within the script's 30 seconds; asked again, SAME.)

Title SAME for cceo, Admin, CD and pl1 on pages 1 and 2. Filters: the
visible ones SAME in value; the existing page shows five (three for pl1) and
folds the rest under More filters, this one shows all eight. Cluster A's
schools opened here are the gateway's answer in its order (1546, 1598, 1286,
1650, 1572, 1676, 1624), which 14.4 proved equal to the existing page's.

Header: the existing page draws Create Cluster as the filled primary with
icons, and an Export button; the answer marks no primary and carries no
Export, so here all three are outlined and Export is absent (contract gap).

Screenshots (scratch folder of the run): `agent23_django_cceo_clusters_{1440,390}.png`
beside `agent23_next_cceo_clusters_open_{1440,390}.png` (Cluster A opened,
one school ticked), `agent23_next_cceo_clusters_open_empty_{1440,390}.png`
(a cluster with no schools opened), `agent23_{django,next}_pl1_clusters_{1440,390}.png`.

## 52.4 Checks

| Check | Result |
|---|---|
| `npm run typecheck` | clean (exit 0) |
| `npm run lint` (`--max-warnings 0`) | clean (exit 0) |
| `npm test` | `Test Files  11 passed (11)`, `Tests  84 passed (84)` |
| `npm run build` (development, gateway 8085, existing web 8185) | built; routes include `/clusters` and `/page-parts` (exit 0) |

New tests: `src/lib/pagePart.test.ts` (the allow-list takes a card's schools
and refuses other paths, a drawer and a traversal included; the part's
address), and in `FeedBlocks.test.tsx` a card that loads its schools gets a
closed opener, a card with nothing more or a part off the list gets none,
and a panel's drawer link goes to the existing page and never names the
drawer.

## 52.5 What is left

- The existing filter row authors five filters and "More filters"; this one
  now folds by width as micro-ux.js does elsewhere (six and More at 1440
  pixels, three and More on a phone; 39.6). Which filters the template folds
  is not in the answer.
- The strip keeps one row on its rail ("1–8 of 8", 39.6), as the existing
  page.
- The existing card's name opens the card and its profile link sits inside
  it ("Open Cluster A cluster profile"); here the name links to the profile
  (owner, 2026-10-09: names link to profiles) and the chevron opens the card.
- The header's primary button and Export are not in the answer (52.3).
- Drawers and saves (Create Cluster, the card menus, the bar's buttons) open
  the existing page.
- The Cluster Page and Cluster Profile (`/clusters/<id>`, 14 piece 3) are
  not Go's yet: a card's link opens the "not moved yet" card.
- Navigation needs the existing application (39.5).
