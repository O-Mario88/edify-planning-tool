export const meta = {
  name: 'edify-truth-audit',
  description: 'Strict computation/data-quality/workflow/role-scope truth audit across all Edify domains, with adversarial verification of P0/P1 findings',
  phases: [
    { title: 'Audit', detail: 'one deep auditor per domain — trace FE→backend→live Postgres, check formulas/scope/period/mock-leak' },
    { title: 'Verify', detail: 'adversarial skeptic per domain re-checks each P0/P1 finding against source' },
  ],
}

// ---------------------------------------------------------------------------
// Shared environment + method preamble handed to every auditor.
// ---------------------------------------------------------------------------
const ENV = `
ENVIRONMENT (production-like: NEXT_PUBLIC_USE_MOCK_DATA=false, EDIFY_USE_BACKEND=true)
- Frontend (Next.js) source root: this working directory (edify-web). Pages: src/app/(shell)/<route>/page.tsx. API proxies: src/app/api/**/route.ts. Computation libs: src/lib/**.
- Backend (NestJS) source root: ../edify-api/src. Services hold the server-side formulas: ../edify-api/src/modules/<m>/<m>.service.ts and ../edify-api/src/common/{fy,scope,rbac,readiness,authz}.
- Prisma data model (source of truth for columns/enums): ../edify-api/prisma/schema.prisma (1838 lines). Read the relevant model before reasoning about a formula.
- LIVE Postgres (the real source records): run
    export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"; psql -d edify_pm -c '<SQL>'
  Use double-quoted "PascalCase" table names. Example: psql -d edify_pm -c 'select count(*) from "Activity" where status=\\'completed\\';'
- LIVE backend API: http://localhost:4000/api (health: curl -s http://localhost:4000/api/health). Most endpoints require an authenticated session, so prefer psql + reading service code over unauthenticated curl. The FE API proxies in src/app/api inject the session.
- Mock policy: src/lib/mock-policy.ts. isMockAllowed() returns FALSE in production. A FE file that *imports* a *-mock module is only a real leak if, in production mode, it RENDERS those mock numbers to the user instead of fetching the backend or showing an empty/"Insufficient data" state. You MUST open the page and trace whether the mock value reaches the rendered output when isMockAllowed()===false / backend is on. Distinguish: (a) hard leak = mock numbers shown in prod; (b) guarded = mock only behind isMockAllowed(); (c) live = fetches backend.

SEEDED DATA STATE (so you can reconcile and spot empties):
- 700 School, 38 User, 268 Activity. Activity.status: completed 234, ia_verified 9, awaiting_ia_verification 9, scheduled 4, partner_scheduled 3, assigned_to_partner 3, evidence_uploaded 3, planned 2, in_progress 1.
- FundRequest: 1 (disbursed). PaymentRequest: 8 (4 netsuite_accountability, 4 ia_confirmed). Leave: 0. EvidenceRecord: 26 (7 uploaded, 19 accepted). LeadershipDecisionInsight: 0.
- Activity columns: id activityType schoolId clusterId projectId fy quarter month week scheduledDate plannedMonth plannedWeek responsibleStaffId monitoredByStaffId assignedPartnerId deliveryType purposeIntervention status evidenceStatus salesforceActivityId iaVerificationStatus paymentStatus teachersAttended leadersAttended otherParticipants rescheduleCount clusterSlot deletedAt lastReason.
- SsaRecord columns: id schoolId dateOfSsa fy quarter newEnrollment averageScore verificationStatus collectorType collectedByPartnerId collectedByUserId qaReviewedAt verificationSource. Intervention scores live in SsaScore.

THE TEN TRUTH QUESTIONS — for every metric/number a user sees, answer:
1) What source records produce it? 2) What filters applied? 3) What role scope applied? 4) What period applied? 5) What formula? 6) Can you reproduce the value from raw records (show the psql)? 7) Does it update after the workflow action? 8) Does it correctly exclude cancelled/draft/completed where required? 9) Could a wrong role see/act on it? 10) Is it safe for a leadership decision?

METHOD (be a hostile QA + data analyst — do NOT trust existing formulas or "looks ok"):
- Open the actual FE page files and the backend service. Quote real file:line. Trace the exact formula, not what a label implies.
- Reconcile at least the 2-3 most decision-critical numbers in your domain against psql raw records — show the query and the expected vs the code's value.
- Test edge cases & period boundaries relevant to your domain.
- Classify each finding P0/P1/P2/P3:
  P0 = first-test blocker (wrong fund totals, role data leak, payment bypasses IA, planning/My-Plan broken, major dashboard number wrong, FAKE PRODUCTION DATA visible, build/login broken, evidence broken).
  P1 = must fix before external testing (wrong KPI formula, missing role scope, stale-after-action, report total mismatch, missing validation).
  P2 = before contract demo (secondary analytics/export/minor). P3 = later.
- DO NOT EDIT ANY FILES. This is read-only discovery. Report findings + a concrete recommended fix (file:line + what to change) so the orchestrator can apply it.
- Be specific and evidence-bearing. A finding with no file:line and no reconstruction is worthless. If something is correct, say so explicitly with proof — passing evidence matters as much as failures.
`

const AUDIT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['domain', 'metricsAudited', 'findings', 'summary'],
  properties: {
    domain: { type: 'string' },
    metricsAudited: {
      type: 'array',
      description: 'Each decision-critical metric you traced',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['metric', 'feLocation', 'backendSource', 'formula', 'roleScope', 'period', 'reconciled', 'status'],
        properties: {
          metric: { type: 'string' },
          feLocation: { type: 'string', description: 'file:line of where it renders' },
          backendSource: { type: 'string', description: 'service file:line or table/columns' },
          formula: { type: 'string' },
          roleScope: { type: 'string' },
          period: { type: 'string' },
          reconciled: { type: 'string', description: 'psql/raw expected vs actual, or why not reconcilable' },
          status: { type: 'string', enum: ['PASS', 'FAIL', 'UNVERIFIED', 'EMPTY_IN_PROD'] },
        },
      },
    },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'title', 'severity', 'category', 'evidence', 'fileRefs', 'recommendedFix'],
        properties: {
          id: { type: 'string', description: 'short slug, e.g. funds-weekly-total-mismatch' },
          title: { type: 'string' },
          severity: { type: 'string', enum: ['P0', 'P1', 'P2', 'P3'] },
          category: { type: 'string', enum: ['mock-leak', 'wrong-formula', 'role-scope', 'period', 'handoff', 'validation', 'stale-after-action', 'build', 'other'] },
          evidence: { type: 'string', description: 'concrete proof incl. file:line and/or psql reconstruction' },
          fileRefs: { type: 'array', items: { type: 'string' } },
          recommendedFix: { type: 'string', description: 'file:line + exact change' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['domain', 'verdicts'],
  properties: {
    domain: { type: 'string' },
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['findingId', 'verdict', 'correctedSeverity', 'reasoning'],
        properties: {
          findingId: { type: 'string' },
          verdict: { type: 'string', enum: ['CONFIRMED', 'REFUTED', 'PARTIAL'] },
          correctedSeverity: { type: 'string', enum: ['P0', 'P1', 'P2', 'P3', 'NONE'] },
          reasoning: { type: 'string', description: 'what you re-checked against source; why confirmed/refuted' },
        },
      },
    },
  },
}

// ---------------------------------------------------------------------------
// Domains. Each is one deep auditor.
// ---------------------------------------------------------------------------
const DOMAINS = [
  {
    key: 'school-directory',
    title: 'School Directory + Geography',
    scope: `FE: src/app/(shell)/schools, /schools/[id], /map, /districts, /districts/[id], /fy/gateway. libs: src/lib/school-directory, schools-mock, schools-intelligence, geography. BE: schools.service.ts, geography.service.ts.
FOCUS: total/assigned/client/core school counts; region/district/sub-county/parish breakdowns; missing-SSA vs complete-SSA vs incomplete counts; clustered vs unclustered; owned-by-staff; partner-supported; no duplicate counting; archived/inactive/deletedAt handled (not counted active); owner-from-upload respected; geography filters match DB district ids. Reconcile total/assigned/core/client counts and at least one geography breakdown against psql.`,
  },
  {
    key: 'clusters',
    title: 'Clusters + Coverage',
    scope: `FE: /clusters, /clusters/[id], /coverage, /coverage/recommendations. libs: src/lib/cluster. BE: clusters.service.ts.
FOCUS: total clusters; by district; schools-per-cluster; schools missing/with SSA inside cluster; cluster average SSA; two weakest cluster interventions; meeting/training gaps; cycle status. Rules: multi-sub-county cluster includes only eligible schools; one active cluster per school; no school counted in wrong cluster; no cluster gap if a meeting is already scheduled; completed cluster activities update history. NOTE /clusters and /clusters/[id] import schools-mock/intake-mock — verify if cluster numbers are mock or live.`,
  },
  {
    key: 'ssa-core',
    title: 'SSA core logic (interventions, completeness, weakest-2, severity)',
    scope: `FE: /ssa, /ssa/core-candidates, /fy/ssa-comparison. libs: src/lib/ssa-planning, ssa-mock, planning/intervention-recommendation, core split. BE: ssa.service.ts (+SsaRecord/SsaScore).
FOCUS: all 8 interventions saved; a missing score marks SSA incomplete; complete SSA unlocks planning, incomplete locks it; two weakest interventions computed correctly with DETERMINISTIC tie handling; severity thresholds 0-4 Critical / 5-6 Needs Support / 7-8 Good / 9-10 Strong and struggling = score<7; latest COMPLETE current-FY SSA used for planning; previous+current FY used for impact; QA/verification status gating. Edge cases: all equal, one missing, multiple lowest ties, current FY missing, previous missing, current<previous, current>previous. The 8 canonical interventions: Christ-like Behavior, Exposure to the Word of God, Leadership Best Practice, Teaching Environment, Learning Environment, Government Requirements, Fees/Budget/Accounts, Enrollment — confirm the taxonomy matches SsaIntervention enum.`,
  },
  {
    key: 'ssa-impact',
    title: 'SSA Impact (improvement, baselines, attribution)',
    scope: `FE: /fy/ssa-comparison, /alerts, impact views, /quality-checks. libs: src/lib/impact-mock, ssa-comparison-mock, donor-metrics. BE: analytics.service.ts (intervention-improvement, ssa-performance), correlation.service.ts.
FOCUS: improvement = current score - previous score, per intervention and overall; label "insufficient baseline" when previous-FY missing and "current SSA missing" when current-FY missing — never claim impact without both; average improvement uses only schools with a valid comparison; denominator visible/documented; partner impact measured ONLY on assigned interventions; staff impact only on activities they completed/supervised. Edge cases: improved/declined/unchanged/no-baseline/no-current. NOTE impact-mock and ssa-comparison-mock are imported on several pages — verify mock vs live.`,
  },
  {
    key: 'planning-gaps',
    title: 'Planning gaps',
    scope: `FE: /planning, /work-plan, src/app/api/cceo/planning-gaps, /planning/core, /planning/setup. libs: src/lib/planning, planning-mock, ssa-planning. BE: planning.service.ts.
FOCUS: Planning shows UNSCHEDULED gaps only. Gap taxonomy NO_CLUSTER/NO_SSA/NO_VISIT/NO_TRAINING/TRAINING_DONE_NO_FOLLOWUP/SSA_COMPLETE_NOT_PLANNED + cluster/core/partner/project gaps. Rules: scheduled work LEAVES Planning; completed work does NOT appear; cancelled work may create a new gap only per rule; assigned partner work leaves Planning and appears in Partner Planning; SSA gate blocks unsupported planning; geography + role scope apply. Edge cases: no SSA, complete-SSA-no-visit, visit scheduled, visit completed, cancelled visit, core school missing slot, meeting scheduled, partner assigned not scheduled.`,
  },
  {
    key: 'my-plan',
    title: 'My Plan bucketing',
    scope: `FE: src/app/api/cceo/my-plan, /my-plan, /plans, /plans/[id]. libs: src/lib/my-plan-sections (+ tests/my-plan-sections.test.ts). BE: activities.service.ts / planning.service.ts.
FOCUS: sections in priority order Waiting on Me / Rescheduled-Needs-Attention / Due Today / Planned This Week / Planned This Month, FIRST matching section wins. Excluded statuses: completed, awaiting_ia_verification, ia_verified, evidence_accepted, accountant_confirmed, cancelled, closed, paid, accountability_closed. waitingOn logic; rescheduleCount + slip limit = 3; due-date timezone correctness; future items to correct bucket; partner-monitored cards appear for the responsible staff; partner My Plan shows only the partner's own scheduled work. Edge cases: due today, overdue, future, no date, rescheduled once, rescheduled 3x, waiting on Salesforce ID, waiting on evidence, returned, completed.`,
  },
  {
    key: 'team-partner-plan',
    title: 'Team Plan / Partner Planning rollups',
    scope: `FE: /team-plan, /team-targets, /partners, /partners/[id], partner planning. libs: src/lib/team-targets-mock, partner, partners-store. BE: targets.service.ts, partners.service.ts, planning.service.ts.
FOCUS: PL team rollups include ONLY supervised CCEOs (via StaffSupervisorAssignment); partner planning shows ONLY partner-assigned work (assignedPartnerId); no cross-team or cross-partner leakage; team target = sum over supervised CCEOs only. NOTE /partners, /partners/[id], /team-targets import team-targets-mock — verify mock vs live and reconcile a team rollup against psql.`,
  },
  {
    key: 'completed-activities',
    title: 'Completed Activities + visit/training counts',
    scope: `FE: /visits, /trainings, completed-activity views, /today. libs: activity, training-mock, training-stats, today-mock. BE: activities.service.ts.
FOCUS: completed/final inclusion only; counts correct; cancelled (deletedAt / cancelled status) excluded; rescheduled activity not double-counted as two activities; count basis = completion/verification rule not created date. Reconcile completed-visit and completed-training counts against psql Activity by activityType+status. NOTE /trainings imports training-mock, /today imports today-mock — verify mock vs live.`,
  },
  {
    key: 'cost-budget',
    title: 'Cost Catalogue + Budget lines',
    scope: `FE: /budget, /plans/new, cost-settings, /budget/cost-settings. libs: src/lib/cost-engine, plan-cost-calculator (+tests/plan-cost-calculator.test.ts, tests/cost-engine.test.ts), cost-settings-mock. BE: budget.service.ts, src/app/api/costing/preview, budget/from-schedule.
FOCUS: active cost selected by activity type/date; OLD scheduled activities keep their locked cost; NEW activities use the new active cost; used cost records can't be deleted; inactive costs not used for future scheduling. Budget line generated from a scheduled activity equals the cost-catalogue calculation. Cost formulas: staff visit primary vs secondary district; partner visit lump sum; training by participant count; cluster meeting by participant count; accommodation nights; SIT/special-project. Reconcile at least one budget line against the cost formula. NOTE /plans/new and several budget/approvals pages import cost-settings-mock — verify mock vs live.`,
  },
  {
    key: 'funds',
    title: 'Fund requests + Monthly country fund + RVP approvals',
    scope: `FE: /monthly-fund-request, /weekly-funds, /fund-requests, /budget/approvals/{active,amendments,funds-matching,rvp-queue,[id]}. libs: src/lib/funds, monthly-approval-mock, rvp-fund-approvals-mock, country-fund-approvals-mock, fund-approvals-mock. BE: fund-requests.service.ts, src/app/api/fund-requests, budget/weekly.
FOCUS: weekly staff fund-request total = sum of its budget lines; monthly country fund total = approved/planned lines; quarterly/annual roll up correctly; returned/rejected items excluded; disbursed amount updates the funding pill; accountant queue matches IA/fund status; RVP approval summaries correct. NOTE only 1 FundRequest exists (disbursed) — so budget/approvals/* pages importing monthly-approval-mock almost certainly render MOCK queues. Verify each approvals page: mock vs live, and whether totals reconcile.`,
  },
  {
    key: 'accountant',
    title: 'Accountant queues + payments',
    scope: `FE: /dashboards/accountant, /payments, accountant console. libs: src/lib/accountant-console-mock, performance. BE: src/app/api/activities/payment-queue, fund-requests.service.ts, PaymentRequest/PaymentDisbursement/PaymentActionLog models.
FOCUS: partner payment ready ONLY after IA confirmation; staff accountability requires IA confirmation + Netsuite ID where applicable; payment cannot clear if evidence missing; payment totals match budget line/payment record; NO duplicate payment records; cleared payments update reports. Reconcile the payment queue against PaymentRequest rows (8 exist: 4 netsuite_accountability, 4 ia_confirmed). NOTE /dashboards/accountant imports cceo-mock — verify the accountant dashboard numbers are live, not mock.`,
  },
  {
    key: 'evidence-ia',
    title: 'Evidence + IA verification queues',
    scope: `FE: /evidence, src/app/api/cceo/evidence-queue, cceo/salesforce-queue, /quality-checks, IA queue views, /activities/[id]/evidence. libs: verification, quality. BE: evidence.service.ts, src/app/api/evidence/*.
FOCUS: counts for evidence uploaded / waiting staff review / waiting PL / waiting IA / returned / accepted / Salesforce-ID pending / Netsuite-ID pending / payment-ready. Routing: partner evidence → staff first → PL where required → IA → accountant; returned evidence goes back to the correct actor; IA receives only evidence-ready items; accountant receives only IA-confirmed items; file-attachment counts match EvidenceRecord rows (26: 7 uploaded, 19 accepted). Reconcile the IA queue and evidence counts against psql.`,
  },
  {
    key: 'hr-leave',
    title: 'HR leave workflow',
    scope: `FE: /calendar, /leave, /dashboards/hr, src/app/api/hr/leave, leave/calendar. libs: src/lib/leave-mock, field-intelligence-mock. BE: hr.service.ts, Leave model.
FOCUS: approved leave disables planning dates; pending leave doesn't block unless configured; rejected doesn't block; multi-day leave blocks all days; existing scheduled activities on approved-leave days are flagged; PL is notified; HR dashboard updates availability/workload; target interpretation accounts for approved leave. NOTE Leave table is EMPTY (0 rows) and /calendar + /dashboards/hr import leave-mock/field-intelligence-mock — so any populated HR/leave UI is MOCK. Verify and reconcile.`,
  },
  {
    key: 'staff-performance',
    title: 'Staff performance (context-aware)',
    scope: `FE: /staff, /staff/[id], performance views, /dashboards/hr. libs: src/lib/performance, performance/fwi-engine (+tests/fwi-engine.test.ts), workload. BE: leadership/context-fairness.service.ts, data-confidence.service.ts, analytics.service.ts, StaffContextProfile model.
FOCUS: show RAW achievement and CONTEXT-ADJUSTED score SEPARATELY; rural vs urban fairness (560 rural ≠ 560 urban); partner/core/project load visible; promotion/PIP require human review (advisory only); performance not generated from fake data; leave impact considered. Inputs: target achievement, verified activities, evidence quality, Salesforce timeliness, IA return rate, reschedule count, slip breaches, debrief completion, fund accountability, schools/core/partners/districts, rural/urban load, distance burden, special projects, SSA improvement. Verify the score is computed from real records, not a hardcoded/mock number.`,
  },
  {
    key: 'partner-performance',
    title: 'Partner performance (intervention-specific)',
    scope: `FE: /partners, /partners/[id], /dashboards/partner, /partner/inbox/[tab]. libs: src/lib/partner, partner-review, partners-store, partner/partner-dashboard-mock, partner/partner-evidence-mock. BE: partners.service.ts, leadership/partner-performance.service.ts, PartnerPerformanceProfile model.
FOCUS: partner measured ONLY against assigned interventions; target achievement excludes unassigned work; evidence-return rate computed correctly; IA-confirmation denominator documented; inactive partners excluded from new-assignment suggestions; capacity = HR capacity + active workload; MOU recommendations show confidence + evidence. Metrics: assignments received, scheduled, completed, evidence submitted/accepted/returned, IA confirmation rate, payment readiness, overdue, reschedule rate, capacity utilization, schools/districts, intervention-specific SSA impact. NOTE /dashboards/partner imports partner-dashboard-mock + partner-evidence-mock — verify mock vs live.`,
  },
  {
    key: 'decision-engine',
    title: 'Leadership Decision Engine',
    scope: `FE: /decisions, /decisions/[id], /analytics/decision-engine, decision embeds (DecisionEngineEmbed). libs: src/lib/decisions, decisions/decisions-mock. BE: leadership-engine.service.ts, leadership.service.ts, data-confidence.service.ts, context-fairness.service.ts, recruitment.service.ts, LeadershipDecisionInsight/DecisionEvidencePoint models.
FOCUS: every recommendation includes EVIDENCE + CONFIDENCE; low data quality reduces confidence; NO automatic termination/promotion; context/fairness adjustment visible; no recommendation from fake data; urban/rural context in staff decisions; partner evaluated on assigned interventions only; recruitment depends on SSA performance + target achievement + workload + partner capacity + data quality. CRITICAL: LeadershipDecisionInsight table is EMPTY (0 rows). /decisions imports decisions-mock + field-intelligence-mock. Determine: does /decisions render MOCK recommendations in production? If a leader could act on fabricated recommendations, that is a P0. Verify whether the engine generates insights live or the page shows mock.`,
  },
  {
    key: 'donor-metrics',
    title: 'Donor metrics (dedup, methodology)',
    scope: `FE: donor reporting pages, src/app/api/donor-reporting/export/[kind]. libs: src/lib/donor-metrics, donor-metrics-types. BE: reports.service.ts, analytics.service.ts.
FOCUS: teachers trained from verified training participant counts (Activity.teachersAttended on verified trainings); students impacted from enrollment of reached/verified schools; school leaders trained from leadersAttended on verified records; districts covered from verified completed activities; schools reached unique (no double counting same school where the metric requires unique); do NOT count scheduled-only work as impact; show methodology/denominator. Reconcile teachers-trained and schools-reached against psql and check for double counting.`,
  },
  {
    key: 'analytics-reports',
    title: 'Analytics + Reports (source/formula/export parity)',
    scope: `FE: /analytics/*, /reports, /reports/[id], /field-analytics, /field-intelligence. libs: src/lib/analytics (+ several tests/analytics-*.test.ts), reports-mock, reports-types, insights. BE: analytics.service.ts, contribution.service.ts, correlation.service.ts, reports.service.ts, Report model.
FOCUS: for each analytics/report metric identify source records + formula; verify role scope + period filters; verify EXPORT matches UI and CHARTS match table totals; no fake data. Reports to verify: staff performance, partner performance, SSA impact, donor, fund/budget, completed activities, evidence verification, HR, RVP/CD country summary, IA data quality, accountant finance. NOTE /field-intelligence, /reports import field-intelligence-mock/reports-mock — verify mock vs live.`,
  },
  {
    key: 'role-dashboards',
    title: 'Role-scoped dashboards (every role)',
    scope: `FE: /dashboards/{accountant,hr,rvp,rvp/country-summary,director,partner,project-coordinator}, command-center, cceo/* API routes. libs: cceo-mock, director-mock, workflow-mock, field-intelligence-mock, special-projects-mock. BE: command-center.service.ts + per-role analytics.
FOCUS: each role sees the CORRECT metrics and NOT the forbidden ones. CD/RVP/HR must NOT receive planning-action counts; IA gets verification counts only; accountant finance only; partner own-only; CCEO own + monitored; PL own + supervised. CROSS-ROLE LEAK TEST: user A cannot see/inflate user B's metrics; partner cannot see another partner's totals. NOTE dashboards/accountant→cceo-mock, dashboards/rvp→workflow-mock, dashboards/hr→field-intelligence-mock, dashboards/project-coordinator→special-projects-mock, dashboards/partner→partner mocks. For EACH dashboard determine: live or mock, and whether forbidden metrics appear.`,
  },
  {
    key: 'period-fy',
    title: 'Period / FY / quarter / rollup logic',
    scope: `libs: src/lib/fy, fy-engine, clock, target-counting (+tests/target-counting.test.ts), period-target (+tests/period-target.test.ts), pace-status, operational-cycle. BE: ../edify-api/src/common/fy/fy.util.ts (+fy.util.spec.ts), targets.service.ts.
FOCUS: FY start/end correct per product rule; quarter boundaries correct; mid-year sits between Q2 and Q3; monthly→quarterly→mid-year/FY rollups; FY target achievement is cumulative; NO double counting across period boundaries; timezone does not shift dates; rescheduled activities count in the correct NEW period; completed activities count by completion/verification rule not created date. Edge cases: activity on first day of quarter, last day of quarter, rescheduled across months, scheduled in one period completed in another, leave crossing months, fund request crossing month boundary, FY rollover. Note the app clock may be frozen (src/lib/clock.ts) — verify what "current week/month" resolves to and whether that is consistent FE vs BE.`,
  },
  {
    key: 'notifications-messages',
    title: 'Notification + message/action counts',
    scope: `FE: notifications UI, /messages, /messages/[id], /partner/messages/[id], src/app/api/notifications/*, messages/*. libs: src/lib/notifications-store, notifications-types, messages-v2, messages-v2/mock. BE: notifications.service.ts, messages.service.ts, Notification/Message models.
FOCUS: notification/action counts match backend Notification records; resolved notifications disappear or mark resolved; the notification target route is correct for the role (no non-planning role routed to a planning action); counts update after the action; duplicate notifications avoided. NOTE /messages/[id] and /partner/messages/[id] import messages-v2/mock — verify message threads/counts are live, not mock. Reconcile notification counts against psql.`,
  },
  {
    key: 'target-achievement',
    title: 'Target achievement rollups',
    scope: `FE: src/app/api/cceo/target-progress, /team-targets, target views. libs: src/lib/targets, target-counting (+test), period-target (+test), my-targets-billion-mock, team-targets-billion-mock, operating-targets-mock. BE: targets.service.ts, TargetSetting model.
FOCUS: decide whether achievement counts on completion vs IA verification vs accountant closure and apply it CONSISTENTLY across the app; do not count cancelled; do not count duplicate reschedules as new; do not count unverified as verified; cumulative totals add correctly; PL team target includes supervised CCEOs only; partner target includes partner-assigned work only. Metric types: planned/completed/verified visits & trainings, cluster meetings, core visits 1-4, core trainings 1-4, SSA completion, evidence timeliness, Salesforce-ID completion, partner scheduling, fund accountability. CRITICAL: check the my-targets-billion / team-targets-billion mocks are NOT rendering fabricated target numbers in prod.`,
  },
]

// ---------------------------------------------------------------------------
// Run: pipeline each domain through Audit -> Verify (no barrier).
// ---------------------------------------------------------------------------
phase('Audit')
log(`Auditing ${DOMAINS.length} domains; each finding adversarially verified as its audit completes.`)

const results = await pipeline(
  DOMAINS,
  (d) => agent(
    `You are a senior QA engineer + data analyst + backend reviewer running a STRICT TRUTH AUDIT of one domain of the Edify platform. $500k and a leadership online test are on the line. Do not beautify, do not trust existing formulas, verify every decision-critical number from source records.\n\nDOMAIN: ${d.title}\n${d.scope}\n${ENV}\n\nProduce the structured audit. Trace real file:line, reconcile the top numbers against psql, classify findings P0–P3 with concrete recommended fixes. Read-only — do NOT edit files.`,
    { label: `audit:${d.key}`, phase: 'Audit', schema: AUDIT_SCHEMA },
  ),
  async (audit, d) => {
    if (!audit) return { audit: null, verdicts: null, domain: d.key }
    const hot = (audit.findings || []).filter((f) => f.severity === 'P0' || f.severity === 'P1')
    if (hot.length === 0) return { audit, verdicts: { domain: d.key, verdicts: [] } }
    const verdicts = await agent(
      `You are an adversarial verifier. Another auditor produced these P0/P1 findings for the Edify "${d.title}" domain. Your job is to REFUTE each one — re-check it against the real source (read the cited files, run the psql, read the backend service). Default to skepticism: confirm a finding ONLY if you independently reproduce the problem. If the auditor misread the code (e.g. the page actually fetches live and only imports a mock type, or a guard exists), mark REFUTED. If real but mis-severitied, mark PARTIAL and set correctedSeverity.\n\nFINDINGS:\n${JSON.stringify(hot, null, 2)}\n${ENV}\n\nReturn a verdict per findingId.`,
      { label: `verify:${d.key}`, phase: 'Verify', schema: VERDICT_SCHEMA },
    )
    return { audit, verdicts, domain: d.key }
  },
)

// ---------------------------------------------------------------------------
// Reduce: merge verdicts back onto findings, surface confirmed P0/P1.
// ---------------------------------------------------------------------------
const clean = results.filter(Boolean).filter((r) => r.audit)
const allFindings = []
for (const r of clean) {
  const vmap = {}
  for (const v of (r.verdicts?.verdicts || [])) vmap[v.findingId] = v
  for (const f of (r.audit.findings || [])) {
    const v = vmap[f.id]
    allFindings.push({
      domain: r.domain,
      id: f.id,
      title: f.title,
      severity: f.severity,
      category: f.category,
      verdict: v ? v.verdict : (f.severity === 'P2' || f.severity === 'P3' ? 'UNVERIFIED(low-sev)' : 'NO-VERDICT'),
      correctedSeverity: v ? v.correctedSeverity : f.severity,
      evidence: f.evidence,
      fileRefs: f.fileRefs,
      recommendedFix: f.recommendedFix,
    })
  }
}

const confirmed = allFindings.filter((f) => f.verdict === 'CONFIRMED' || f.verdict === 'PARTIAL')
const confirmedP0 = confirmed.filter((f) => f.correctedSeverity === 'P0')
const confirmedP1 = confirmed.filter((f) => f.correctedSeverity === 'P1')

log(`Audit complete: ${allFindings.length} findings across ${clean.length} domains. Confirmed P0=${confirmedP0.length}, P1=${confirmedP1.length}.`)

return {
  domainsAudited: clean.map((r) => r.domain),
  totals: {
    findings: allFindings.length,
    confirmedP0: confirmedP0.length,
    confirmedP1: confirmedP1.length,
  },
  confirmedP0,
  confirmedP1,
  metricsAudited: clean.flatMap((r) => (r.audit.metricsAudited || []).map((m) => ({ domain: r.domain, ...m }))),
  allFindings,
}
