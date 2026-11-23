# Full journey regression

Run on the private database `edify_rebuild_dev`, as the seeded CCEO, school 1001, on 2026-11-23.

| Step | Desktop | Phone |
|---|---|---|
| School Directory | Pass | Pass |
| School Profile | Pass | Pass |
| Cluster Profile | Pass (separate cluster) | Pass (viewport check) |
| Schedule visit | Pass, activity saved | Not repeated |
| My Plan | Pass | Pass |
| Calendar | Pass | Pass |
| Route Planner | Pass | Pass |
| Save route | Pass | Not repeated |
| In-app directions | Pass, no external link | Not repeated |
| Start field day | Pass | Not repeated |
| Arrive and leave | **Failed, then fixed and passed** | Not repeated |
| End field day | Pass | Not repeated |
| Complete visit with evidence ID | Pass, `submitted_to_pl` | Not repeated |
| Programme Lead verification | **Not run on this stack** | Not run |
| Figures update after verification | **Not verified** | Not verified |
| Export matches PostgreSQL | **Not verified** | Not verified |
| Notifications page | Pass | Pass |
| No duplicate activity | Pass | Not repeated |

The Go PL approval sits behind a save switch that was off on this stack, so the browser journey stops at submitted. Integration tests cover the switched-on path.
