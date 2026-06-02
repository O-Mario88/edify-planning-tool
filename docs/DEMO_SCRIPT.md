# Edify Planning & Monitoring Tool — Demo Script & Presentation Playbook

A sequenced, role-by-role walkthrough that shows the strongest, most reliable
surfaces and routes around the few thin ones. Pair this with `DEMO_AUDIT.md`
(the full feature/workflow inventory).

---

## 0. Pre-demo checklist (do this 10 min before)

- [ ] **Dev server running:** `npm run dev` → http://localhost:3000 (the demo runs on the dev server, not a production build).
- [ ] **Theme set to a crowd-pleaser:** open the avatar menu (bottom-left sidebar) → Appearance → **Dark** or **Glass** for a premium look on a projector. Light is best for bright rooms.
- [ ] **Log in once** with each role you plan to show so pages are warm (first paint compiles routes).
- [ ] **Zoom/responsive:** for a laptop demo use ~90% browser zoom. To show mobile, narrow the window or use device emulation (the app is fully responsive).
- [ ] **One password for everything:** `edify` (the only exception is `demo@edify.org` → `demo`).
- [ ] **Know the two "live workflow" surfaces** that start empty and fill as you act: the **IA Verification Queue** and the **Accountant Accountability Queue**. Either walk an activity through them live (impressive) or skip them — see §5.

---

## 1. Demo login matrix

| Persona | Email | Password | Role | Lands on |
|---|---|---|---|---|
| **Paul Chinyama** | `paul.chinyama@edify.org` | edify | CCEO (field officer) | My Targets |
| **Daniel Mwangi** | `daniel.mwangi@edify.org` | edify | Country Program Lead | CPL Dashboard |
| **Sarah Okello** | `sarah.okello@edify.org` | edify | Country Director | Director Dashboard |
| **Esther Wanjiru** | `esther.wanjiru@edify.org` | edify | Regional VP | RVP Dashboard (richest) |
| **Moses Tindi** | `moses.tindi@edify.org` | edify | Program Accountant | Accountant Dashboard |
| **Grace Alimo** | `grace.alimo@edify.org` | edify | M&E / Impact (IA) | Impact Dashboard |
| **Anne Wairimu** | `anne.wairimu@edify.org` | edify | Human Resource | HR Dashboard |
| **Edify Admin** | `admin@edify.org` | edify | Admin | Director Dashboard |
| **Daniel Mwangi (BFEP)** | `daniel.mwangi@brightfuture.org` | edify | Partner Admin | Partner Command Center |

**Switching roles live (best for the demo):** open the **avatar menu at the bottom of the sidebar → "Switch role"** (or press **⌘K / Ctrl+K** → type a role). All 8 staff roles **+ a Partner** are now in the switcher, so you can hop roles without logging out. (This control is dev-only and will be removed at deployment.)

---

## 2. The 90-second opener (shell + polish)

Goal: establish that this is one cohesive, premium, multi-role product.

1. Land on any dashboard. Point out the **unified sidebar brand** (white Edify logo + "PLANNING AND MONITORING TOOL") and the **bottom-left profile** (photo-frame avatar, name, **primary district**, role, online).
2. Open the avatar menu → **Appearance** → toggle **Light → Dark → Glass**. "One design system, theme-aware, instant, persists." 
3. Press **⌘K** → type "schools", "budget", "analytics". "Command palette — power-user navigation across every page and action."
4. Open **Switch role** → flip to **RVP (Esther)**. "Same product, role-aware — the sidebar, nav, and landing page all re-shape to who you are." This single move previews the breadth.

---

## 3. Recommended narrative arc (top → field → back office)

A clean story is **strategic → operational → field → assurance → finance**. Switch roles in this order:

### 3.1 RVP — Esther Wanjiru (the cockpit) — *richest dashboard*
- **Country Comparison table + burn-rate rail** — multi-country targets, SSA %, valid visits, funds, pipeline health (red/amber/green).
- Talking point: "Executives see the whole region at a glance, with money and impact side by side."

### 3.2 Country Director — Sarah Okello
- **Weekly Debrief Report Center** — country rollup + per-PL reports, late-submission flags, drill-down.
- Scroll to **Donor Reporting Impact** — verified vs pending reach/training, with green/amber status. "Donor-ready numbers, with an explicit verified-only contract."

### 3.3 Program Lead — Daniel Mwangi
- **Team Performance Overview** (monthly trend across the team) beside the PL's own targets.
- Go to **Team Targets** → the **7-period operating-targets view**: Monthly · Q1 (Oct–Dec) · Q2 (Jan–Mar) · **Mid-Year** · Q3 (Apr–Jun) · Q4 (Jul–Sep) · FY. "Cumulative 25 / 50 / 75 / 100 across the fiscal year — one source of truth for the calendar."

### 3.4 CCEO — Paul Chinyama (the field officer) — *the heart of the product*
- Start on **Dashboard** (Risk & Bottleneck Board + SSA heatmap + the **My School Portfolio** card).
- Open **My Portfolio** (`/portfolio`):
  - **Auto-distribution:** "These schools appeared the moment IA uploaded them with Paul as Account Owner — no manual assignment."
  - **Targets by Time Period** card: Q1 25% → Q4 100%, current quarter highlighted, **partner-supported schools count toward targets** (note the footer line).
  - **Assign a partner** to a school → show the school **stays in the portfolio** (ownership never transfers; only delivery is delegated). Cancel it to show it's reversible.
- Open **My Targets** → operating-targets tiles + **Staff Partner Monitoring** (every activity Paul delegated to a partner, by status).

### 3.5 Impact / M&E — Grace Alimo (data assurance)
- **Data Intake hub** (`/data-intake`): role-gated to IA/Admin, ownership-distribution KPIs.
  - **Owner-Mapping Queue:** map an unmatched owner name ("James Okot") to a registered staff → "the school auto-distributes into their portfolio."
  - **Duplicate Review Queue** (`/data-intake/duplicates`): side-by-side "Nakaseke Hill Primary" vs "Nakaseke Hills Primary School", **Strong 86** with plain-English reasons. Dismiss or confirm — **flagged, never blocked**.
- **Analytics** (`/analytics`): change FY / district / quarter → 40+ metrics recompute live; click "Schools Reached" to drill into the exact schools.
- **SSA** (`/ssa`): the intervention heatmap (districts × 8 areas).

### 3.6 Accountant — Moses Tindi (the money)
- **Disbursements** (`/disbursements`): the finance cockpit — inflow, disbursement queue, staff accountability, receipt tracking.
- **Approvals** (`/approvals`): inline-expanding fund-approval queue with live KPI counters.

### 3.7 Partner — Daniel Mwangi (BFEP) (the delivery side)
- Switch role → **Partner**. **Partner Delivery Command Center** (`/dashboards/partner`): the **8-step activity workflow tracker** with live counts, action inbox, evidence-quality trend, **partner health score**.
- "Partners deliver on behalf of the account owner — the staff member keeps ownership, planning, and reporting."

---

## 4. The hero end-to-end story (if you want ONE workflow that ties it together)

"From a spreadsheet of schools to a paid, verified field activity":

1. **IA (Grace)** uploads schools → they **auto-distribute** to owners; a **duplicate** is flagged; an **unmatched owner** is mapped. (`/data-intake`)
2. **CCEO (Paul)** sees the schools in **My Portfolio**, with the **quarterly target ladder**. He **delegates a partner** to deliver at one school (ownership stays). (`/portfolio`)
3. **Partner (BFEP)** delivers the activity and uploads **evidence**. (`/dashboards/partner`)
4. **CCEO → PL** confirm/approve; **IA** verifies with the Salesforce ID. (verification flow)
5. **Accountant (Moses)** closes accountability with the NetSuite expense ID; the activity is **Paid**. (`/disbursements`)
6. It all rolls up into **Director/RVP** dashboards and **donor reporting** as *verified* impact.

This is the cleanest 5-minute story and uses only confirmed-working surfaces.

---

## 5. Live "workflow" surfaces that start empty (handle deliberately)

The **IA Verification Queue** and **Accountant Accountability Queue** are driven by the *live* action store, which is empty on a fresh start. Two options:
- **Best:** walk one activity through live (Complete → enter Salesforce ID → switch to IA → Verify → switch to Accountant → enter NetSuite ID → Paid). This *demonstrates* the workflow rather than showing static data.
- **Or:** skip them and show the rich mock-backed cockpits instead (`/disbursements`, `/approvals`, the dashboard pipeline trackers), which are always populated.

Everything else (dashboards, portfolio, targets, intake, duplicates, partners, analytics, SSA, planning, approvals, disbursements, leaderboard) is **pre-populated** and safe to open cold.

---

## 6. Pages to avoid / route around (thin or placeholder)

These are reachable from some sidebars but are not yet fleshed out — don't click them on stage:

- **/calendar** — placeholder (appears in CPL/Impact menus + mobile nav).
- **/fy** and its sub-pages (Operating Cycle gateway/timeline/readiness) — placeholders.
- **/admin** index, **/admin/audit-log**, **/admin/feature-flags** — thin (use **/admin/users** instead, which is rich: health strip, Add Staff).
- **Budget drill-downs** (`/budget/approvals/[id]`, `/budget/breakdown|monthly|scenarios|variance`) — thin; the top **/budget** and **/approvals** are real.
- **/reports** — catalog renders but download/generate are placeholders; describe verbally.
- **Disabled buttons** with "coming soon" tooltips (Export Report on targets, Approve-All / Export / Advanced-filter on Approvals, View-All-Insights) — mention as roadmap, don't click expecting action.
- **/data-intake/readiness** and **/data-intake/quality** — thin; the hub, duplicates, and owner-mapping are the strong intake surfaces.

---

## 7. Likely questions & honest answers

- **"Is this live data?"** — "Year-1 runs on representative seed data with the full workflow logic; Year-2 swaps the mock layer for Salesforce + NetSuite + Postgres behind the same interfaces." (The code is explicitly structured this way.)
- **"Can I export this report?"** — "Export is on the roadmap (the button is stubbed); the data and layout are done."
- **"What stops a partner from inflating numbers?"** — "Only IA-verified, evidence-backed work counts toward targets and donor reports; participant de-duplication prevents double-counting."
- **"Why these quarter dates?"** — "FY runs Oct–Sep: Q1 Oct–Dec … Q4 Jul–Sep, mid-year at end of Q2, cumulative 25/50/75/100. It's a single source of truth in `fy-core`."

---

## 8. Reset / gotchas

- The action store + uploaded photos + created staff live **in memory / localStorage** — a server restart resets them and refreshing some live surfaces resets in-progress workflow state. Do a clean run-through once before the real demo.
- Role-switch does a hard reload — on a slow machine there's a ~1s blank flash; that's expected.
- If a sidebar link looks empty, it's one of the §6 placeholders — navigate back and continue.

---

_See `docs/DEMO_AUDIT.md` for the exhaustive per-domain feature, workflow, highlight, and risk inventory._
