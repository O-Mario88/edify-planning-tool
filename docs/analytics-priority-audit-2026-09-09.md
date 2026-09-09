# Analytics and priority accountability audit — 9 September 2026

## Verdict

Not ready for five-star enterprise sign-off against the operating model requested in this review. My qualitative assessment is approximately **3.5/5 for visual finish and 2/5 for end-to-end accountability fit**. These are design judgments, not a certification or measured benchmark.

The compact typography, restrained surfaces, connected navigation and responsive KPI strips provide a solid foundation. The principal blockers are conflicting numbers, disconnected priority records and incorrect contribution boundaries. More styling alone will not resolve them.

This was an inspection. No application logic was changed. Existing regression tests and additional isolated database probes were used; distribution probes did not allocate targets to real users.

## Evidence and limits

- Opened Analytics, Priorities and My Performance with all 14 local role accounts. Partner, business-transformation and MFI accounts redirect to their designated workspaces; an HTTP 200 after a redirect is not evidence that those roles can use the original page.
- Inspected the accessible analytics sections, including the actual PL, CD and project-coordinator overview destinations, and exercised representative evidence disclosures.
- Checked desktop and phone layouts. The first pass covered 42 page/role requests across all 14 accounts; the deeper pass covered 107 additional role/section requests across the nine roles with main-workspace access. No browser runtime errors or document overflow were detected in those inspected states. Redirects are recorded separately from access to the requested page. This was not a full accessibility certification, load test or external report-delivery test.
- **197 existing regression tests passed** across target distribution, milestone planning progress, automatic performance, performance agreements, analytics target formulas and role dashboards.
- **Four isolated contract probes passed by reproducing the current gaps**: allocation-to-agreement disconnection; omitted PL personal delivery in team scope; excluded monitored partner delivery in employee/team scope; and CD personal rather than country-wide school-visit agreement measurement. Passing these probes confirms the gaps, not compliance with the requested model.
- Local database: operational FY2026; zero milestone allocations; zero performance-agreement priorities. FY2027 contains 68 milestones: 31 defined, 37 needing definition, none approved. Therefore populated production distribution cannot be certified from this local UI; fixtures are necessary.
- Local evidence: `/tmp/edify-priority-analytics-audit/`, including screenshots, route records and test outputs. Synthetic contract probe: `/tmp/edify_priority_contract_probe.py`.

## Findings requiring correction

### 1. Two analytics headline strips disagree on the same page — high

The CD overview showed **No Target Set** in the shared headline and **0% Overall Target Achievement** in the role panel. On the same screen, the shared strip showed zero teachers/leaders and a different selection of measures, while the country panel showed **189 Schools Impacted**. The PL page similarly repeats shared and team headline strips.

The shared strip defaults to Q2 when no quarter is supplied; PL/CD panels use the cumulative FY. The distinction is not expressed clearly in the shared headline. Separate calculation engines add a second source of disagreement. A manager cannot reliably tell which headline governs assessment.

Sources: `apps/analytics/analytics_dashboard_service.py:33`, `apps/frontend/views/analytics_render.py:34`, `apps/frontend/views/analytics_views.py:41`, `apps/frontend/views/analytics_views.py:810`.

**Recommendation:** one resolved role, reporting period and target basis per page, passed to every panel and export; one headline strip. Distinguish an unconfigured target from measured zero progress. Show supporting metrics within relevant sections.

### 2. Shared target achievement does not use the distributed target contract — critical

The shared analytics engine divides scoped achieved activity counts by all active `TargetSetting` values for the FY, with a fallback to all `StaffTargetProfile` visits/trainings. Neither denominator is restricted to the current person/team/selected geography. It approximates a quarter as annual target divided by four.

This does not read the IA/PL-approved `MilestoneAllocation` and its actual quarterly/monthly phasing. It can also mix target measures that should not be summed. The live absence of targets currently hides this defect behind “No Target Set.”

Source: `apps/analytics/analytics_dashboard_service.py:251`.

**Recommendation:** numerator and denominator must share metric, scope, FY and period. Use approved allocations and their phase, not a separate target catalogue or a 25% estimate. Display visit counts, school counts and participant counts separately; combine only normalized results under an explicit weighting policy.

### 3. IA → PL → CCEO allocation exists, but does not populate the agreement-priority page — critical

For field-cascade milestones, the allocation services enforce reconciliation and authorization and support the PL distributing to themselves and supervised CCEOs. Specialist and country-owned milestones follow different allocation paths, so this is not one universal IA→PL→CCEO path for every priority. Approved employee allocations project into **My Targets**. However, approval does not create or connect a `PerformancePriority` on the employee's agreement. **My Performance / Priority Setting Dashboard** reads `PerformanceReview.priorities`, while distribution writes `MilestoneAllocation` and period targets.

A different strategy-rule cascade can populate agreements, but it derives targets from rule guidance/portfolio denominators, not the exact IA/PL-distributed allocation. These are separate paths, not one working chain.

An isolated test approved an IA→PL target and a PL→CCEO target: the allocation appeared in `personal_milestone_targets`, while the agreement-priority count did not change.

Sources: `apps/hr/target_distribution.py:1822`, `apps/hr/target_distribution.py:1863`, `apps/hr/milestone_allocations.py:311`, `apps/hr/milestone_allocations.py:666`, `apps/frontend/views/hr_views.py:1707`, `apps/hr/priority_cascade.py:249`.

**Recommendation:** render distributed priorities directly from one authoritative allocation record, linked to the performance review where needed. Avoid a second editable target copy.

### 4. PL personal contribution is not consistently consolidated with the team — critical

The allocation system allows a PL self-allocation, but team planned-output and verified-credit scopes use supervisee IDs without including the PL. The dedicated PL analytics target progress aggregates its CCEO roster. The separate HR scoring helper also deliberately returns personal and team scores separately.

The existing team view therefore cannot be assumed to equal “PL own work + team work,” as requested. A test with one PL visit and one CCEO visit confirmed that the team planned-output scope selected only the CCEO visit.

Sources: `apps/hr/target_distribution.py:1567`, `apps/hr/milestone_progress.py:255`, `apps/analytics/pl_analytics_service.py:847`, `apps/hr/performance_scores.py:258`.

**Recommendation:** use one deduplicated combined scope for the supervisory headline, with personal and team breakdowns beneath it. Include the PL's allocated target and actual delivery once.

### 5. Partner contributions use incompatible rules — critical

Distributed employee and team planned-output and verified-credit calculations explicitly exclude partner delivery. Country/project scope allows it. The agreement engine has a separate `partner_supported_schools` measure; direct visits/trainings exclude partners. PL execution analytics applies yet another ownership rule, crediting monitoring only when responsible staff is null.

This can show partner work in an operational report while leaving the assigned CCEO/PL priority unchanged. It does not meet the requested monitored-partner contribution model.

Sources: `apps/hr/target_distribution.py:1552`, `apps/hr/milestone_progress.py:228`, `apps/hr/performance_engine.py:145`, `apps/hr/performance_engine.py:191`, `apps/analytics/pl_analytics_service.py:744`.

**Recommendation:** record delivery ownership and accountable monitoring separately. Credit eligible monitored work into CCEO and PL supervisory progress; retain direct/partner breakdowns. The country counts each delivered activity once, not once for every person who receives supervisory credit.

### 6. CD performance is not one country-delivery measure — critical

Country analytics does have country-wide activity reporting. That is a useful working foundation. Its weighted target headline, however, is derived from CCEO target series. The employee-agreement `direct_visits` metric filters the agreement holder's own activity IDs, even when the holder is a CD. The available HR country-score helper averages eligible individual staff scores rather than computing country delivery against a national milestone target; repository search found no production call sites for that helper.

An isolated CD school-visit agreement probe returned zero after a CCEO completed qualifying country work. There is no canonical country-school-visit agreement metric in `performance_engine.METRIC_KEYS`.

Sources: `apps/hr/performance_engine.py:30`, `apps/hr/performance_engine.py:87`, `apps/analytics/cd_analytics_service.py:335`, `apps/analytics/cd_analytics_service.py:816`, `apps/hr/performance_scores.py:288`.

**Recommendation:** assess each CD milestone using the country's unique eligible delivery divided by its approved country target. The RVP should read that same country measure. Do not average individual percentages to stand in for a national visit target: 10/10 plus 0/100 is 10/110 = 9.1% country delivery, not 50%.

### 7. The requested four-tab priority experience is absent — high

The current strategic workspace uses **Priority Setting / Target Distribution / My Team**, depending on role. A CCEO gets no strategic workspace tab rail. The employee performance page separately uses **Agreed Priorities / Targets & Progress / Development Plans / Values & Commitments / Amendments / Conversations**. Values and spiritual formation are combined; neither the labels nor the navigation match the requested model.

Manual values and spiritual commitments exist, and development includes workflow and manual records. These useful pieces should be retained. An older generic `set_priorities` service also remains; it is not limited to the three requested manual categories, although no current production caller was found. It should not become the new operational-priority entry path.

Sources: `apps/frontend/views/priority_workspace.py:97`, `apps/frontend/views/hr_views.py:1867`, `apps/hr/performance_engine.py:696`, `apps/hr/performance_service.py:170`.

**Recommendation:** default to **Distributed Priorities**, then **Core Values**, **Spiritual Formation**, **Professional Development**. Keep distribution, approval and review controls role-gated within this coherent workspace. Operational priority targets should be read-only to recipients.

### 8. Completion and verified achievement need explicit treatment — high

There is a real milestone credit engine with idempotent credits and reversal support. Official credits require IA-verified/confirmed/closed state and the applicable source/rule requirements. Marking a plan complete alone does not advance verified achievement. A separate planning meter can show planned and completed activity.

Source: `apps/hr/milestone_progress.py:19`, `apps/hr/milestone_progress.py:160`, `apps/hr/target_distribution.py:1357`.

**Recommendation:** display planned coverage, completed work awaiting verification, and verified achievement clearly. Completion should immediately move the completion indicator; verification should move the official assessment measure. Returns/reversals must reduce the appropriate measure automatically.

## Design assessment across roles

- **CCEO:** compact visual foundation, but priorities are split between the master, targets and the agreement page. The next action is not clear when allocation is missing.
- **PL:** useful team context and evidence disclosures. Repeated strips, clipped select values and separate personal/team calculations prevent a clear supervisory workspace.
- **CD:** useful country scope and leadership actions. Duplicate headlines and conflicting target/period semantics are unacceptable for executive decision-making.
- **RVP:** regional summary access exists. Country performance is not yet tied consistently to the CD assessment contract requested here.
- **IA:** relevant verification and distribution surfaces exist, with authorization safeguards. Strategy definition, allocation and employee assessment need one connected workflow.
- **HR/accountant:** access is differentiated, but the shared field-oriented headline can displace role-relevant workforce/finance context. Keep programme context secondary to the role's decision.
- **Project coordinator:** a dedicated project analytics destination exists. Shared programme headlines still need consistent scope/period labeling and project-specific emphasis.
- **Partner admin/partner, BTO and MFI roles:** direct main-workspace routes redirect to their own portals. Treat these as separate role experiences, not successful access to the main Analytics or Priorities UI. Partner contribution still needs to reach the accountable staff rollups.

The layout generally stays within the viewport in the inspected states. That is necessary but insufficient for premium design. On a 1366×768 laptop, repeated headlines and filters consume most of the first screen before the decision content. Collapse secondary metrics, use one filter system, show full selected filter labels, and remove implementation-oriented explanatory copy.

The shared “AI Insights” recommendations are threshold-derived in the inspected implementation. Label them as recommendations/risk signals unless an actual AI explanation is provided. Some shared insight actions are clickable `div` elements without native keyboard semantics; keyboard behavior merits a dedicated accessibility pass.

## Recommended operating contract

1. IA assigns approved country milestone targets to PLs. A PL distributes their received total across themselves and their CCEOs. Every level reconciles; no duplicate independent target entry.
2. Assigned priorities appear immediately in the default Distributed Priorities tab, with target, unit, period, owner, source and progress.
3. Plans link to the allocation/metric. Completion and verification update the corresponding indicator without a user editing achievement.
4. CCEO accountability includes eligible monitored partner delivery. PL accountability includes own delivery plus team delivery. CD accountability uses unique country delivery. Rollups do not duplicate the same underlying event.
5. The same metric, period, denominator and credit rules drive priority pages, analytics, supervisor reviews and exports. Manual categories remain separate from operational delivery counts.

## Acceptance gate before five-star sign-off

Demonstrate a complete populated fixture: IA allocates → PL subdivides including self → CCEO sees default priority → direct and partner plans execute → completion/verification updates progress → PL and CD totals agree → RVP sees the same national result → a returned/reversed activity reduces all dependent views correctly. Test shared schools, reassignment, unequal target sizes, quarter phasing, no-target states and all relevant role permissions. Existing route/test success alone does not demonstrate this new business contract.
