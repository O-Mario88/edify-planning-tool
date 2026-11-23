# Git delivery report

**Branch pushed:** `feature/edify-go-rn-migration`, by fast-forward only. Nothing was force-pushed, nothing went to `main`, and nothing was deployed. All `.do/*.yaml` apps have `deploy_on_push: false`.

**Pull request:** none is open for this branch, and none was opened.

## Commits

| Commit | What it did |
|---|---|
| `1e029fc0a` | Page actions open real forms in a web drawer; Close School fixed |
| `57cb9ed07` | Location answer carries accuracy and source |
| `776c73cd5` | School Profile rebuilt; Not Assessed |
| `63769e9d1` | Schedule, Assign and Add to Project in the web app |
| `639307bff` | Cluster Profile on the canonical engine and scope |
| `0bcecaa37` | Cluster Profile UI |
| `1f72f610a` | Smart Route Planner UI |
| `8b4ed4589` | Accessibility faults fixed |
| `6a6de5ecf` | Field-day Arrive fix |
| `fd111ed4e` | Nine rebuild reports |
| `7e1dd5826` | School, Cluster and Route match the six references; school icon replaces the photo |
| `908e68a71` | Route Planner shows every name in full; its list is reachable by keyboard |
| `a7f65c33f` | Design comparison report updated |

## Which system draws these pages

School Profile, Cluster Profile and Smart Route Planner are the Next.js pages on the Go gateway, at `localhost:3095` in development. With the Django server stopped, all 12 views checked (4 School tabs, 7 Cluster tabs, Route) still loaded with their data. The action forms, such as Schedule and Complete Visit, still open and save through Django until each save is cut over. The old Django pages on `localhost:8011` were not changed.

## Checks run on the final page code

- Web: types, lint, 438 unit tests and the production build pass.
- Ten screen widths: no sideways scroll or cut-off text on School, Core tab, Cluster and Route.
- axe accessibility scan at 1440 and 390: no serious or critical findings on those pages.
- The hosted sweep's own checks, run locally on Route for seven accounts at phone and desktop: no findings.
- Journey on the private database, from Directory through Complete Visit: every step reached `submitted_to_pl`. The Complete Visit step needed a correction to the test script's address and a valid visit ID.

The Go, Django, mobile and worker suites last passed on `fd111ed4e`. The later commits change only web files and reports.

## Hosted CI

- `fd111ed4e`: every job passed except **UI sweep**, which reported 13 page loads.
- 8 of those were Route findings, fixed in `7e1dd5826` and `908e68a71`.
- 5 were `/loans` timing out at desktop size. The same 5 roles failed on `4f5d6bec8`, before this work, and the cause is not yet diagnosed. UI sweep will stay red until it is fixed.
- The run for the latest commit had not finished when this report was written.

## Known limitations

- Comparison with the references was by eye; no pixel-difference tool was used.
- Expo native screens were not rebuilt to these designs.
- Terrain is not configured, and live traffic needs a Google key.
- Delete Cluster stays on the existing app; Reassign Owner still falls back.
- No Safari, Firefox or real-device testing was done, and no 1,000-user load test was run.

**Production readiness:** not ready. Production cutover needs the items above, a green CI run and separate approval.
