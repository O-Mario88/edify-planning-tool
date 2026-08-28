# What has to happen before this release can be a Go

**Companion to `docs/release-readiness-2026-08-25.md`. Verdict there: NO-GO.**

That report is 1,700 lines because it has to show its evidence. This document exists
because none of the work left is engineering's to do, and the people who *can* do it
should not have to read 1,700 lines to find their part.

Everything below is either a **decision** — a judgement someone has to make, where
engineering has an opinion but no authority — or an **action** — something that needs
access this audit did not have. Nothing here is waiting on more code review.

---

## Decisions

### D-1 · Which achievement number is the true one? · **Product owner**

**Today, a team with no signed agreements makes the Country Director's dashboard read
200% and that team's own Programme Lead read 0%.** Both pages are working as written.
They disagree because they use different denominators: the CD weights against the whole
`TargetArea` catalogue, the PL derives areas from the agreed annual performance review
and honestly shows "Not Assigned" when there are none.

| Option | Consequence | Cost |
| --- | --- | --- |
| **A. CD adopts the agreed priority areas** | Leadership stops seeing achievement against targets nobody assigned. The PL's honest empty state becomes the platform's answer | Re-base 6 tests, incl. the four `test_target_percentage_consistent_q*` cases |
| **B. PL falls back to the catalogue** | The two pages agree at the CD's number | Breaks 3 tests, incl. `test_global_target_catalogue_does_not_invent_team_priority_rows` — the test that pins the no-fabricated-data rule |

**Engineering's recommendation: A.** Work should not be counted against a target nobody
assigned. Option B buys agreement by making the honest page dishonest.

**Why it can't wait for after the release:** the mandate names leadership receiving
truthful intelligence as the platform's purpose, and this is a fabricated number on
exactly that surface. It is quarantined by an expected-failure test, not fixed —
`apps/analytics/test_target_formula_unification.py:214`.

---

### D-2 · Should Impact Assessment be able to edit Master Priority rows? · **Product owner**

Approved extension GAP-02 asks for this. The platform deliberately built the opposite:
IA can *import*, *allocate* and *view* priorities and milestones, but not author or
amend them. `apps/hr/priority_cascade.py` says why in its own words — *"The RVP and CD
author STRATEGY … They never write an individual's milestones."*

**This is not an unbuilt feature.** Calling it that invites someone to build it. What is
actually being asked is whether to remove an authorship separation the cascade is
designed around.

| Option | Consequence |
| --- | --- |
| **A. Keep the split; re-scope the extension to an amendment path** | The CD owns amendments, IA can propose. Mirrors the loan-purpose pattern already in the platform: four roles, one object, nobody holding two ends |
| **B. Grant IA edit rights as written** | The role that *verifies* delivered work also authors what that work is measured against |

**Engineering's recommendation: A.** Option B is the same conflict SEC-03 spent a P0
closing one layer down — `Permission.IA_VERIFY` sits in `ADMIN_EXCLUDED_PERMISSIONS`
precisely so no account both certifies work and releases money for it. An IA that
authors the priority, allocates it, and verifies the work claimed against it holds all
three positions in that chain.

**Likely the real complaint:** an imported master priority cannot be corrected
afterwards. That is true today, and an amendment path fixes it without widening the
grant.

---

### D-3 · Does Salesforce reconciliation stay manual? · **Product owner + roadmap**

**"Confirm Salesforce" does not contact Salesforce.** A human types a string; it is
matched against a regex prefix (`TS-`/`SVE-`, or `Loan-<number>`), checked for local
uniqueness, and stored. There is no HTTP transport for Salesforce, NetSuite or the
Lending Partner feed anywhere in the codebase — `push_to_external` is a single
unconditional `raise IntegrationNotConfigured`.

That locally-typed string currently gates **activity closure, IA partner confirmation,
core-activity verification and partner-payment eligibility.**

The platform is behaving exactly as its authors intended; the seam is deliberate and
documented as "the credentialed half of Phase 2c". The blocker is that the mandate
treats Salesforce confirmation as a *gating* step, and what actually gates is a typed
string.

| Option | Consequence |
| --- | --- |
| **A. Declare it in scope: reconciliation is manual and unverified** | Honest, shippable now. The release notes must say the gate is a typed reference, not a verified one |
| **B. Build the transport** | Needs credentials and a work programme. The outbox around it is already real and well-built — claims with `SELECT … FOR UPDATE SKIP LOCKED`, crash reclaim, deterministic backoff, dead-letter with replay. It simply has nothing to deliver to |

**Engineering has no recommendation here** — this is genuinely a scope question, and both
answers are defensible. What is *not* defensible is shipping without saying which one is
true.

---

### D-4 · What does a Core Assessment cost? · **Country Director**

No catalogue item carries `core_assessment_visit`, so a mandatory Core package slot
cannot be scheduled at all. The costing layer says so itself rather than guessing: an
unknown profile raises *"Country Director configuration must be repaired before
scheduling."*

**This is one configuration value, not a build.** Name the cost, and the slot becomes
schedulable; `CorePlan.assessment_completed` stops being unreachable.

---

### D-5 · Offline field operation: build it, or descope it? · **Product owner**

The release scope names offline field operation. **It does not exist.** Of the four
required capabilities — start activity, capture evidence, survive app close, sync
without duplicates — three are absent and the fourth is partial and text-only.

Offline actions are not queued, they are *cancelled*: `platform-status.js` calls
`preventDefault()` and announces "This action was not sent because you are offline."
There is no IndexedDB and no background sync anywhere in first-party JavaScript. The
only offline persistence is a `localStorage` draft of seven text fields on one page.

| Option | Consequence |
| --- | --- |
| **A. Descope for this release** | Field staff need connectivity. Say so plainly in the release notes |
| **B. Build it** | IndexedDB queue, replay, server-side idempotency keys. A work programme, not a patch |

---

### D-6 · Is the KPI headline limit 4 or 6? · **Product owner** *(small, but unanswered)*

The stated rule is "operational 0–2, dashboard max 4, mobile max 2". Mobile max 2 is
correctly enforced. **The dashboard limit is enforced at 6.** The operational limit is
not enforced at all — and 14 payload groups feed more than six metrics into a six-slot
tray that truncates, so **metrics are being dropped with no UI affordance.**

Either the stated rule is wrong or the code is. Someone has to say which.

---

## Actions

These need access, not judgement.

| # | What | Who | Note |
| --- | --- | --- | --- |
| **A-1** | Rebuild the runtime image to clear **CVE-2026-14456** (OpenSSL QUIC DoS, HIGH) | Whoever can build the image | A fixed version exists: `3.5.7-1~deb13u2`. Proposed patch is on PR #64. Not pushed from here — no Docker daemon, so it could not be built or re-scanned first |
| **A-2** | Run `doctl apps spec get` and settle **DEP-01** | Ops | The repo's two records of the live app describe two different applications, by UUID. A guard test now fails the build until they agree |
| **A-3** | Perform a **restore from a production backup** | Ops + managed DB | This has never been done. The rehearsal harness exists and is rigorous |
| **A-4** | Rollback rehearsal, deployment rehearsal, production smoke | Ops | Three of the nine gates no source-only audit can produce evidence for |
| **A-5** | Log retention, an error tracker, alert rules, a named incident owner | Ops + org | Two alert rules exist. Nobody is named as incident owner |

---

## What engineering can still do without any of the above

**JRN-01 is closed (2026-08-28).** All twenty implemented journeys now reach a
real role-gated HTTP surface inside their whole-journey test. Seven also compute
registered display metrics. The traceability artefact was rebuilt and both the
route set and metric counts are regression-pinned.
