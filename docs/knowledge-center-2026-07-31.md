# Edify Knowledge Center

**2026-07-31 · implementation report (§38)**

The Help page is now a two-column enterprise documentation surface: a
hierarchical, role-aware Table of Contents on the left, the selected article on
the right, on every Knowledge Center page.

---

## 1. What was already there (inventory first, §3)

The `help_center` app was not a stub. Before any writing, the inventory found:

| Asset | State before |
|---|---|
| Data model | `HelpCategory`, `HelpArticle`, `HelpArticleVersion`, `HelpArticleRoleAccess`, `HelpArticleRouteContext`, `HelpArticleFeedback`, `HelpSearchKeyword`, `HelpReleaseNote`, `HelpGlossaryTerm`, `HelpWalkthrough` — already matching the requested model |
| Routes | `/help/`, `/help/roles/<slug>`, `/help/workflows/<slug>`, `/help/features/<slug>`, `/help/articles/<slug>`, troubleshooting, glossary, release-notes, context, print, feedback, role/complete exports, `manage` — already the requested information architecture |
| Publishing | Draft → technical review → product review → published → review-due, with versions and audit |
| Content | 114 published articles, 10 role guides, 48 workflow guides, 21 troubleshooting articles, 100 glossary terms, 6 walkthroughs |
| Coverage tooling | `documentation_drift_report()` already reporting route/status/link/overdue drift |
| Layout | **Home was a hero + topic-card grid. There was no persistent Table of Contents anywhere.** |

So the work was not "write a help system". It was: replace the landing
experience with the two-column manual shell, close the coverage gap opened by
recently shipped features, and fix what verification exposed.

## 2. The two-column shell (§4, §5)

New `templates/layouts/help_center.html` — every Knowledge Center page extends
it. New `templates/partials/help/toc.html` renders the tree; new
`services.knowledge_tree(role, active_slug)` builds it.

- **Left**: categories with article counts, the group holding the open article
  auto-expanded, the open article marked with `aria-current="page"`, weight, a
  left marker **and** colour — never colour alone. Sticky, independently
  scrollable, keyboard reachable.
- **Right**: breadcrumbs, title, summary, article metadata (version, last
  reviewed, next review, reviewer, reading time, applicable roles), an
  "On this page" index for long articles, the body, walkthrough, related
  articles, and the feedback controls.
- **Responsive**: at ≥64rem the rail is shown and the Contents button is
  hidden; below that the rail becomes a modal slide-over drawer opened from a
  sticky Contents button. Verified at 390px: no horizontal overflow, drawer is
  `role="dialog"` + `aria-modal`, closes on Escape and backdrop click.
- The tree is built with `values()` over four columns — the landing page never
  loads article bodies to draw its own navigation.

Pages moved onto the shell: home, article, category, glossary, release notes,
search, troubleshooting.

## 3. Coverage closed to 100% (§36)

Route coverage was 95.6% — the gap was every feature shipped recently.
Seven new feature articles were written from the code, not from assumption:

- **Work Plan** — what it is, and why it is not My Plan
- **Add a Non-School Activity** — the dated programme-work funnel
- **Activity Calendar** — a projection of Activities, never a second diary
- **Activity Catalogue** — governed master data and its lifecycle
- **Strategic Priorities and milestones** — define → approve → allocate
- **Special Project creation and assignment**
- **School geography pickers**

| Metric | Before | After |
|---|---|---|
| Route coverage | 95.6% | **100.0%** (436 / 436) |
| Published articles | 114 | **121** |
| Missing routes | 19 | **0** |
| Broken links | 0 | 0 |
| Unknown statuses | 0 | 0 |
| Overdue articles | 0 | 0 |
| Published without version | 0 | 0 |

## 4. Defects found by verification

Checking contextual Help properly — resolving each route and reading which
article came back, rather than just asserting "not null" — exposed three real
defects:

1. **Contextual Help opened the wrong guide.** `_article_slug_for_route` built
   its map with a last-wins dict comprehension, so where two articles both
   referenced a route, the last one declared won: `/my-plan` opened the
   *Salesforce Activity IDs* guide and `/calendar` opened *Daily Visit
   Batches*. Now the first article that claims a route — the one whose subject
   it is — owns it.
2. **Stale route mappings survived a re-sync.** When a new article took over a
   route, the old fallback row stayed at equal priority, so the guide that
   opened depended on insertion order. `sync_route_contexts` now retires the
   superseded mapping (10 removed on first run).
3. **A duplicate article.** My own "Partner assignment scheduling" feature
   article sat beside the existing "Partner Assignment and Scheduling"
   workflow guide — the near-duplicate the standard forbids, invisible in
   review because both read correctly alone. Deleted; the partner scheduling
   routes now belong to the existing **Partners** article, which absorbed the
   assignment-is-not-scheduling rule.

My first test only asserted the contextual article was non-null, which is
exactly why it passed while pointing at the wrong guide. It now pins the owning
slug per route.

## 5. Tests added (§34)

`KnowledgeCenterShellTest`:

- every Knowledge Center page renders the contents rail (7 routes, subtests)
- the open article is marked current, with `aria-current`
- the contents tree is role-aware, and every entry offered to a role actually
  opens for that role
- contents groups are never empty and counts match
- the group holding the open article is expanded
- new platform features are documented and reachable
- **contextual Help opens the guide that owns the page** (pins slugs)
- a route has exactly one owning article (no duplicate contexts)
- restricted contextual Help falls back for other roles, and resolves for
  authorised ones
- no two articles explain the same workflow (normalised-title collision guard)

The pre-existing home test asserted the retired hero copy; it was updated to
the new contract and now also asserts the old hero is **gone**, so the two
systems cannot run side by side.

## 6. Verification

- `apps/help_center`: **15 passed, 36 subtests**
- Design-system, UI-quality, table-bounds and page-inventory gates: the new
  Help templates pass all of them (no arbitrary radius/shadow, no one-off tiny
  type, semantic primary utilities, no page-level `<main>`, no unbounded table)
- Responsive: verified at 1440px (two columns) and 390px (drawer, no overflow)
- Role-awareness measured, not assumed: Program Lead sees 160 TOC links across
  22 groups; Accountant sees 96 across 18

## 7. Remaining gaps

The structural replacement, the coverage gap and the defects above are done.
Two things from the brief are explicitly **not** claimed as complete:

1. **Article depth.** The 121 articles follow the house structure and are
   grounded in current code, but the brief's full 18-section template
   (statuses, disabled actions, returned-and-correction, completion criteria as
   separate mandated headings) is applied unevenly across the inherited 114.
   Retro-fitting every one is a content pass, not an engineering pass.
2. **Screenshots and diagrams.** No screenshots were added; the brief requires
   them to come from a production-like staging environment with sanitised
   data, which does not exist yet on this machine.

Neither is a broken link, a wrong instruction or an unmapped route — coverage,
accuracy and access control are all green.
