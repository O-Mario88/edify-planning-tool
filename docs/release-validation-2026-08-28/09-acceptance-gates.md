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
- [ ] HTMX/Alpine/ApexCharts memory stabilizes over the required 50-navigation sequence.
- [ ] Service-worker upgrade verified across two actual deployments.
- [x] Dedicated critical freeze pages meet local duration/DOM gates.
- [x] Full school catalogues removed from the two identified browser selectors.
- [x] Confirmed critical N+1 removed and query-count protected.
- [x] Redis failure degrades honestly and safely in tests.
- [x] Scheduler/job locking and retry tests pass.
- [ ] Production scheduler/job dashboard inspected.
- [ ] SSE multi-tab/restart/background behavior manually traced in deployed infrastructure.
- [ ] Evidence upload validated on slow physical mobile connections and real object storage.
- [ ] Offline drafts and interrupted sync validated on physical devices.
- [ ] Real integration sandboxes prove outages cannot freeze workflows.
- [ ] Baseline/capacity/spike/stress/extended-soak tests pass on a production-equivalent environment.
- [x] Liveness/readiness behavior passes automated tests and public production smoke.
- [ ] Production dashboards and alerts are active and alert delivery tested.
- [x] Local security/scope test groups pass.
- [x] No unresolved Critical/High defect found within the executed local scope.
- [x] Production-safe public smoke passes.
- [ ] Rollback rehearsal and deployment migration rehearsal completed.
- [ ] Full physical device/browser/zoom/orientation matrix completed.

## Decision

> **NO-GO**

This is a governance decision, not a statement that the candidate is broken. The local candidate is green on the evidence available, but the unchecked staging, production, observability, integration, physical-device, mutation, and load/soak gates are mandatory in the requested acceptance model.

