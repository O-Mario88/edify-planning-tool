# API and database validation

All testing used local databases. Production was not read, written or migrated.

- Contract change: `GetSchoolLocationResponse` gains `accuracy_meters` (16) and `location_source` (17). Additive; generated code matches (`make proto`).
- Cluster Profile no longer reads `school_cluster_assignment`, which the gateway role may not read.
- Django `DRAWER_VIEWS` and `DRAWER_SAVES` now allow the four cluster forms. Their saves still run Django's own rules.
- No schema migration was added.

| Suite | Result |
|---|---|
| Go unit, with race detector | Pass |
| Go integration, race, CI-style data | 198 passed, 0 failed, 91 skipped |
| Django `apps.mobile_feed` | 263 passed |
| Web unit | 435 passed |
| Mobile Jest | 277 passed |
| Python analytics worker | 30 passed |
| Proto, gofmt, vet, web types, lint, production build | Pass |

The full Django suite was not run in this pass; only `apps.mobile_feed`, the Django area changed.
