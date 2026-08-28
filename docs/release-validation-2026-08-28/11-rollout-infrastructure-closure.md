# Rollout infrastructure closure — 2026-08-28

This record contains no credentials. Resource identifiers and measured results
were read from the DigitalOcean API after each operation.

## Production PostgreSQL high availability

- Cluster: `edify-production-fra`
  (`5c96f186-d354-43b9-ade2-e021f9470528`), PostgreSQL 17, Frankfurt.
- Before: one `db-s-1vcpu-1gb` node.
- After: two `db-s-1vcpu-2gb` nodes. The second node is a synchronous standby
  eligible for automatic promotion, not a read-only scaling replica.
- A managed backup dated `2026-08-28T02:43:30Z` existed before the resize. The
  isolated production restore rehearsal is recorded in
  `10-production-backup-restore-rehearsal.md`.
- DigitalOcean recorded `cluster_master_promotion` at `2026-08-28T16:13:35Z`.
- Web liveness and readiness returned HTTP 200 with database and cache `up`
  after the promotion.
- The scheduler exposed one real recovery weakness: its persistent job-store
  socket continued to receive `terminating connection due to administrator
  command`. Restarting only `scheduler` cleared the stale socket. Deployment
  `0d78f67d-dcec-4c98-ac1b-316f120f2a3c` became ACTIVE, registered all 23 jobs,
  and `outbox_drain_job` then executed successfully at `16:19:00Z`.

## External runtime-log retention

- Destination: DigitalOcean Managed OpenSearch 2.19 cluster
  `edify-runtime-logs-fra` (`6511cf26-f8e4-4f6e-9045-149af787277b`).
- Production log-forwarding deployment:
  `f45f3012-d5f2-4790-bc6b-cbb7cc73b28e`, ACTIVE.
- Four separate streams prevent production/staging and web/scheduler evidence
  from being mixed:
  - `edify-production-runtime`
  - `edify-production-scheduler`
  - `edify-staging-runtime`
  - `edify-staging-scheduler`
- `scripts/configure_opensearch_retention.sh` creates idempotent ISM policies,
  templates and write aliases. Indices roll at one day or 128 MiB and are
  automatically deleted after 90 days. One shard and zero replicas are
  deliberate for this single-node log cluster.
- The policy update path uses OpenSearch sequence-number/primary-term guards;
  two consecutive live reruns completed successfully for all four streams.
- Measured document counts after live traffic and scheduler execution were
  326 production-web, 602 production-scheduler, 95 staging-web and 85
  staging-scheduler records. Counts are evidence of delivery, not a retention
  promise; the ISM policy and alias queries prove the latter.

## Production-equivalent staging

- App: `edify-staging-fra` (`f55a8b58-a40e-4298-a355-2b2b0af455eb`).
- URL: `https://edify-staging-fra-gzbvn.ondigitalocean.app`.
- Initial deployment `8e4823ff-299a-4b61-9235-f36f05ec9f5d` became ACTIVE with
  two web instances, one scheduler, one pre-deploy migration job, resource
  alerts, managed PostgreSQL 17 and managed Valkey 8.
- Databases are isolated managed clusters:
  - `edify-staging-pg-fra` (`6a21d1f1-b662-44b4-8b2a-488adb8ca963`)
  - `edify-staging-cache-fra` (`b3d34f71-0fc6-41a3-8d80-9289bc43d531`)
- Staging PostgreSQL was upgraded to the production database shape: PostgreSQL
  17, two `db-s-1vcpu-2gb` nodes. DigitalOcean recorded a real master promotion
  at `2026-08-28T17:42:24Z`, and readiness remained healthy afterward.
- Object storage uses a new Spaces key scoped to the staging bucket and the
  separate `edify-staging` prefix. No production application secret was copied.
- The initial `seed --demo --reset` rehearsal found a real ordering defect:
  geography was built and then purged before sample schools chose a district.
  Commit `642419f4` moves the purge ahead of all reference rebuilding and adds a
  regression test. This is why staging exists: the local green suite had not
  exercised a first-estate reset in the managed deployment.
- Corrected deployment `ef2c34ec-629f-43e0-bc6b-b56b98c2f36e` became ACTIVE
  at commit `642419f436c690e41c14a88ce7a2851c5be62681`. Its deployment-time
  migration job completed successfully and public readiness reported database
  and cache `up`.
- The corrected managed reset completed end to end: 37 demo users, 700 schools,
  1,006 SSA records, six partners, 24 cost settings, five projects, 25 project
  assignments and 260 activities.
- Final deployment `7a6ed9e2-b1b0-41d0-80c0-7838dcb105fb` became ACTIVE with
  two `apps-s-1vcpu-2gb` web instances, exactly matching the live production
  App Platform web shape. The scheduler registered its jobs and
  `outbox_drain_job` executed successfully every minute through `18:28:00Z`.

## Staging gate execution

- **Role/route crawl — Green.** Fourteen authenticated roles opened every
  permitted argument-free page. Twelve passed in the first live run; the local
  runner then lost DNS/network access (`ERR_INTERNET_DISCONNECTED` and
  `ENOTFOUND`) before MFI Officer/Admin and the focused checks. Both staging
  and production readiness remained HTTP 200, proving this was runner-side.
  The interrupted MFI/Admin subset was repeated after network recovery and all
  four selected profiles passed. GitHub's separate browser-and-role job also
  passed in 15m10s.
- **Freeze and CSS — Green.** Formerly freezing pages remained bounded and the
  live style-recalculation median stayed under the 16 ms one-frame budget.
- **Schools listener/DOM leak — Green.** The original defect grew from 264 to
  478 listeners and by about 6,000 nodes over 30 cycles. The corrected live
  50-cycle sequence stabilized after warm-up at exactly 277 listeners and
  3,217 connected nodes at cycles 20, 30, 40 and 50. A second broad soak held
  exactly 264 listeners and 15,549 DOM nodes across 50 full-page navigations.
- **Cross-page heap soak — Green.** One document was retained throughout 50
  navigations across Schools, Analytics, System Health, Dashboard and To-Dos;
  forced-GC heap decreased from 5,150,008 to 4,987,216 bytes.
- **Public smoke — Green.** Login interaction and liveness/readiness behavior
  passed against the managed staging URL.
- **Capacity — condition recorded.** The final external, warmed,
  CSRF-authenticated run against the exact production web/database shape
  completed 528/528 requests with zero errors and 7.94 requests/second. Overall
  p95 was 2,570 ms. That is within the repository's documented 3,200 ms
  degraded ceiling for normal pages, but it does not meet the aspirational
  1,500 ms target. This is a rollout condition, not a Green performance SLO.
  Earlier shape trials were retained in command evidence: four shared 1 GB
  instances reached 2,551 ms p95, and four dedicated 1 GB instances reached
  2,463 ms p95, insufficient improvement to justify the much higher cost.
- **Service-worker upgrade — Green.** `STATIC_VERSION` is now tied to the
  deployment commit. An authenticated browser remained usable across the live
  deployment, reloaded valid application pages, and observed its cache token
  change to `edify-static-642419f436c6`.
- **Rollback and revert — Green.** DigitalOcean validated the rollback target,
  rollback deployment `62468b84-2988-4be1-8993-513aa989cd15` became ACTIVE,
  and revert deployment `5f1dbbdd-92f2-4128-8e82-bf883e8c1ff1` also became
  ACTIVE. Readiness, database/cache state, commit identity and static-manifest
  identity were checked after the cycle.

## Cost and ownership

- The final staging App Platform compute proposal is US$74/month, matching the
  live production web shape. Four shared 1 GB instances (US$72/month) and four
  dedicated 1 GB instances (US$160/month) were tested and not retained.
- The log cluster is the smallest native Managed OpenSearch plan (about
  US$19.60/month before additional storage).
- Managed staging PostgreSQL/Valkey and the added production PostgreSQL node
  are billed separately at current DigitalOcean rates.
- The DigitalOcean balance response during provisioning showed an account
  balance of `-50.03`; billing ownership must keep the account current because
  suspended infrastructure defeats every availability control above.
