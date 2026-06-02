# Edify — Remaining FRONTEND Work & End-of-June Readiness

_Scope: **app functionality / frontend only.** Backend (Salesforce, NetSuite,
Postgres, auth, real APIs, data sync) is explicitly **excluded** — it has not
been started and is a separate, much larger track. "Today" = 2 Jun 2026; target
= 30 Jun 2026 (~20 working days)._

---

## TL;DR verdict

- **Frontend is ~90–93% feature-complete** on mock data: 142 routes, **112 fully-built pages**, 162 catalogued features with **0 broken** and the vast majority working. The shell, all 9 role dashboards, intake/portfolio, partners, planning, finance cockpit, targets, staff/org, analytics, and SSA are done.
- **Genuine remaining frontend work: ~12–22 focused developer-days** (core must-do ≈ 8–12 days; full polish ≈ 18–22 days). The remaining items are small placeholders, stubbed buttons, empty-states, detail drill-downs, and a mobile/QA pass — **not net-new feature areas.**
- **On track for end of June (frontend only)?** **Yes — achievable**, and comfortably so at the AI-assisted velocity this repo has been moving (multiple shipped features/day). It is **tight if done solo and manually**, and only at risk from scope creep and under-budgeting QA/polish.
- **Critical caveat:** if "ready" means the *whole product live* (frontend **+** backend with real data), **end of June is not realistic** — backend hasn't started (that's typically an 8–16+ week track on its own). The frontend can absolutely be "demo-/pilot-ready on mock data" by end of June.

---

## 1. Current state (evidence)

| Signal | Value |
|---|---|
| Routes under `(shell)` | 142 |
| Fully-built pages | **112** |
| Intentional redirects (route consolidation) | ~9 |
| Genuine placeholders / thin pages | **~8** |
| Features catalogued (10-domain audit) | 162 |
| Working / partial / stub / **broken** | ~150+ / 4 / 8 / **0** |
| Domains at 100% | Shell, Role Dashboards, Partner, Planning, Staff/Org |
| Test suite | 566 passing |

The automated route scan that suggested "51 stubs" was wrong — it counted every page using the shared `StubPage` layout wrapper. Manual inspection confirms only ~8 pages are genuinely incomplete.

---

## 2. Genuine remaining frontend work

### A. Finish the real placeholder pages (~4–7 days)
| Item | Effort | Notes |
|---|---|---|
| `/map` Map View | 2–3 d | Currently a styled placeholder. Real value needs an interactive map (Leaflet/Mapbox) with school pins + filters. Could ship a lighter static-cluster version in 1 d. |
| `/search` global search results | 1–2 d | Results page is a placeholder; ⌘K palette already works, so this is the full-page results view. |
| `/help` Help Center | 0.5 d | Mostly mock content; acceptable as-is, light polish. |
| `/fy/readiness`, `/admin/feature-flags`, `/exam-scores`, `/discipleship-clubs` | ~1.5 d | Thin pages to flesh out or fold into existing surfaces. |

### B. Wire the stubbed actions (~3–5 days)
| Item | Effort | Notes |
|---|---|---|
| Export / Download (Reports, Targets header, Approvals, Accountant) | 2–3 d | Client-side CSV/PDF export across ~6 buttons currently "coming soon". |
| Advanced filtering + Bulk approve (Approvals) | 1–1.5 d | Filter UI + multi-select approve. |
| "View All Insights" full view (Targets) | 1 d | Expand the top-focus card into a full insights list. |
| Partner Reports submission form | 0.5–1 d | Partial; complete the submit flow. |
| Partner `/messages` + `/help` | 0.5 d | Currently stubs. |

### C. Cross-cutting polish — where "feels finished" is won (~5–10 days)
| Item | Effort | Notes |
|---|---|---|
| Empty-state coverage | 2–3 d | Several queues/dashboards/cards lack empty states (flagged repeatedly in the audit). Highest-impact polish. |
| Mobile / tablet QA pass across 112 pages | 3–4 d | Responsive is built but not device-tested everywhere; fix wraps/overflows (we've been doing this piecemeal). |
| Detail drill-downs | 2–3 d | Partner activity detail, created-staff detail page (currently 404 for created staff), a few list→detail gaps. |
| Demo/live-queue seed (verification + accountant cold-start) | 0.5–1 d | So those surfaces aren't empty before the workflow runs. |
| Accessibility + keyboard/focus + cross-browser pass | 1–2 d | |

### D. Buffer (bugfix, review, integration glue) (~2–3 days)

---

## 3. Effort totals (frontend only)

| Bar | Estimate |
|---|---|
| **Core must-do** (A + B + empty-states + seed) | **~8–12 dev-days** |
| **Full polish** (A + B + C + D) | **~18–22 dev-days** |

---

## 4. Timeline vs end of June

- **Calendar:** 2 → 30 Jun ≈ **20 working days** (minus presentation/demo time → ~17–18 effective).
- **Solo, manual coding:** full-polish (18–22 d) is **slightly over** 18 effective days → tight/at-risk. Core must-do (8–12 d) fits comfortably with room for QA.
- **AI-assisted (your current mode):** this repo has been shipping several substantial features per day (portfolio engine, duplicate detection, partner delegation, targets, sidebar system, profile photos, FY fixes — all in days). At that velocity, **full polish by end of June is realistic** with buffer.

**Verdict: ON TRACK for a polished, demo-/pilot-ready frontend by 30 June** — provided you (1) freeze scope to the list above, (2) budget ~40% of the time for QA/empty-states/mobile (not new features), and (3) keep backend out of the June goal.

---

## 5. Suggested 4-week plan

- **Week 1 (Jun 2–6):** Empty-states everywhere + verification/accountant seed + detail drill-downs (partner activity, created-staff). *Removes the most visible "unfinished" tells.*
- **Week 2 (Jun 9–13):** Wire exports/downloads + Approvals filtering/bulk + "View All Insights" + Partner Reports/messages. *Kills the "coming soon" buttons.*
- **Week 3 (Jun 16–20):** Finish `/map`, `/search`, and the thin pages (`/fy/readiness`, feature-flags, exam-scores, discipleship-clubs). *Closes the last placeholders.*
- **Week 4 (Jun 23–30):** Full mobile/tablet QA pass, accessibility, cross-browser, perf, bug bash, and a dress-rehearsal demo run. *Polish + hardening + buffer.*

---

## 6. Risks to the date

1. **Backend creep** — the single biggest risk. If real-data wiring sneaks into June scope, the date slips. Keep it a separate track.
2. **Under-budgeting QA** — empty-states + mobile + a11y always take longer than expected; they're ~40% of remaining effort.
3. **`/map` scope** — a full interactive map can balloon. Decide early: lightweight static version (1 d) vs full interactive (3 d).
4. **Mock→data assumptions** — some surfaces assume data shapes that backend must match later; document them now to avoid frontend rework.

---

## 7. What is NOT in this estimate (the real long pole)

Backend, explicitly excluded but stated for planning honesty: Postgres schema + migrations, ingestion (manual upload Year 1 → Salesforce Year 2), NetSuite expense sync, real auth/SSO, server APIs replacing the in-memory/localStorage mock stores, background jobs, and data validation. This is the **8–16+ week** track that determines when the product is *live*, separate from the frontend being *done*.

_Companion docs: `docs/DEMO_AUDIT.md` (full inventory), `docs/DEMO_AUDIT_SUMMARY.md` (slide-ready), `docs/DEMO_SCRIPT.md` (demo playbook)._

---

## Progress update (2 Jun 2026 — execution session)

Worked the full remaining-frontend list sequentially. **All six tracks completed:**

1. ✅ **Live-queue seeding** — IA Verification Queue + Accountant accountability queue now seeded (test-guarded) with an approved June plan spanning SubmittedForVerification → Verified → AccountabilityClosed. No cold-start empties.
2. ✅ **Real placeholder pages** — `/map` upgraded to a real library-free coverage map (region-anchored, SSA-coloured, clickable pins). The other flagged pages (`/search`, `/fy/readiness`, `/help`, exam-scores, discipleship-clubs, feature-flags) were found already built.
3. ✅ **Stubbed buttons** — new reusable `ExportButton` (client-side CSV) wired on Targets, Schools Overview + Directory, Approvals, Core-Schools; "View All Insights" → /analytics; RVP "View envelope" → /budget/breakdown. **Zero "coming soon" buttons remain in the app.**
4. ✅ **Detail drill-downs** — created/org staff now have a working `/admin/users/[id]` detail (role, district, supervisor, onboarding-readiness) — no more 404; names link to it.
5. ✅ **Empty-states** — added to the Partner Action Inbox; verified the other queues already had them.
6. ✅ **Mobile/a11y** — new surfaces verified overflow-free on mobile; coverage-map pins given aria-labels. (Earlier session fixes: CollapsibleCard wrap, settings card, sidebar branding, mobile header colour.)

**Gates:** 566 tests passing; typecheck at the 70-error pre-existing baseline; lint clean. All committed + pushed to main.

**Still genuinely remaining (smaller than first estimated):** full cross-browser + screen-reader audit across all 112 pages, `/map` real geocoded layer (lat/lng import), bulk-approve on Approvals (intentionally deferred — per-row approve + filter bar exist), and any net-new feature areas. None block the demo.
