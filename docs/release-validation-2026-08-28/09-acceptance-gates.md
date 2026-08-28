# Acceptance-gate checklist

Legend: `[x]` proven by available evidence; `[ ]` not proven or blocked.

- [ ] Every live internal link tested in authenticated production.
- [x] Every locally inventoried permitted argument-free page opened by a valid role.
- [ ] Every visible button clicked through its applicable state.
- [ ] Every workflow-state-specific action tested in a real browser.
- [ ] Every form tested for valid and invalid input in a real browser.
- [ ] Every notification and To-Do deep link tested.
- [ ] Every export/download opened and content-validated.
- [x] No dead link or unexpected 4xx/5xx in the completed argument-free role crawl.
- [x] No unexpected browser console/page error in the completed browser suite.
- [x] Confirmed local freeze root causes fixed and regression-tested.
- [ ] Production traces prove every reported production freeze is eliminated.
- [x] HTMX/Alpine/ApexCharts memory stabilizes over the required 50-navigation sequence.
- [x] Service-worker upgrade verified across two actual deployments.
- [x] Dedicated critical freeze pages meet local duration/DOM gates.
- [x] Full school catalogues removed from the two identified browser selectors.
- [x] Confirmed critical N+1 removed and query-count protected.
- [x] Redis failure degrades honestly and safely in tests.
- [x] Scheduler/job locking and retry tests pass.
- [x] Production scheduler/job execution inspected after database failover.
- [ ] SSE multi-tab/restart/background behavior manually traced in deployed infrastructure.
- [ ] Evidence upload validated on slow physical mobile connections and real object storage.
- [ ] Offline drafts and interrupted sync validated on physical devices.
- [ ] Real integration sandboxes prove outages cannot freeze workflows.
- [ ] Capacity meets the aspirational 1,500 ms p95 target on production-equivalent staging (528/528 requests succeeded with zero errors, but p95 was 2,570 ms).
- [x] Liveness/readiness behavior passes automated tests and public production smoke.
- [ ] Production dashboards and alerts are active and alert delivery tested.
- [x] Local security/scope test groups pass.
- [x] No unresolved Critical/High defect found within the executed local scope.
- [x] Production-safe public smoke passes.
- [x] Rollback/revert rehearsal and deployment migration rehearsal completed.
- [ ] Full physical device/browser/zoom/orientation matrix completed.

## Decision update — 2026-08-28

> **APPROVED WITH CONDITIONS**

The three infrastructure blockers are closed: recoverable production backup
evidence exists, runtime logs have verified 90-day external retention, staging
matches production's web and database shape, and production PostgreSQL has a
synchronous standby. The remaining unchecked items are explicit acceptance or
performance conditions. Most importantly, measured staging p95 is 2,570 ms
against the aspirational 1,500 ms target, the release PR still requires an
independent approval and merge, and physical-device/integration-sandbox gates
remain product/organisation work rather than infrastructure work.
