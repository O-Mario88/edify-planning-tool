# Impact Assessment role and functionality alignment

Reviewed 13 September 2026. The matrix records the initial source-code assessment; the implementation update below identifies the changes subsequently made.

## Review and improvement (14 September 2026)

The Codex pass (the implementation update below) was reviewed against the role description (framework and strategy, baseline and field collection, evaluating school progress, analysis and performance tracking, stakeholder reporting). The review found that Outcomes and Collection covered only 25 project enrolments (all "baseline missing" although every school had a confirmed SSA), the Framework and Programme learning tabs were link cards, the draft report was never saved, reviewed or released, every tab rebuilt the whole verification dashboard, and several IA surfaces were not country-bound.

Owner decisions (13 September 2026): IA opens on Outcomes; a second IA officer in the same country reviews rules, findings, stories and reports, with the Country Director acknowledging where a country has one IA officer; the RVP approves donor versions; IA captures student learning results, discipleship indicators and EdTech rollout; every keyed SSA stays pending until someone other than its collector confirms it. Classroom observations were not added. The proposed third "assessment form" evidence document for staff SSA visits was not adopted: the owner's two-form rule stands.

What changed:

- **Navigation.** IA's sidebar follows the responsibilities (Framework & Strategy, Baseline & Field Data, School Progress, Analysis & Learning, Reporting & Accountability, Data Quality & Verification); Team Oversight, Quality Flags, My Actions, Actions Sent, Work Plan, Budget and the generic Analytics door left it. One IA strip groups every IA page by responsibility. Phone bar: Dashboard, To-Do, Verify, Messages.
- **Dashboard.** Outcomes, Collection, Impact reports, Map and Operations, under one fixed header of registry tiles; each view builds only its own data; every count is bounded to the reader's country; tile drill-downs filter the queue.
- **Framework.** /ia/framework/: outcome areas, versioned indicators, measurement rules and loan purposes with draft → review → published and change reasons. Mapping edits keep every saved field and never convert flexible mappings to fixed ones; rules resolve by the delivered activity and are stamped on enrolments so republishing cannot rewrite past results. `apps/ssa/change_rules.py` is the single definition of improved and declined across Outcomes, Declining Schools, contribution analytics, the decision engine and project impact. Output counts that were filed as outcomes are recategorised, with a guard test.
- **Collection and SSA integrity.** A collection worklist over every school in scope (never assessed, follow-up due, pending verification, returned, scheduled, visited without scores, partner pending, project segment); SSAs pending until an independent verifier confirms (CD for IA-collected); returned SSAs carry a reason to the collector; imports, the unmatched queue and upload history are country-bound with row errors shown; field-visit SSAs link to their visit and its date; project baselines fill from the latest confirmed prior SSA (`capture_project_baselines`); sample checks per country cover SSAs and a dispute has consequences; "Ask owner to collect" sends a request, never a plan.
- **School progress and new measures.** Outcomes leads with portfolio-wide paired change by domain and outcome area with evidence grades, then learning results, discipleship and EdTech evidence, then project cohorts. /ia/school-evidence/ records learning results (with CSV upload), discipleship indicators, EdTech deployments and functioning checks, each independently verified. OneTest visits prompt for results. /ia/stories/ reviews Most Significant Change stories.
- **Analysis.** /ia/learning/ (Training, Lending, EdTech, Visits, Findings) compares exposed and similar schools with sample sizes, missingness, design and `evidence_strength` grades, never labelled causal; /impact is country-bound with corrected p-values and honest wording; impact attribution redirects into Programme Learning; findings are reviewed by a second person. /ia/lending-evidence/ puts loan-use, enrolment, asset and teacher verification on screen; loan impact conclusions are prepared by Business Transformation and verified by IA.
- **Reporting.** /ia/impact-reports/: draft, submit (evidence frozen with a hash), review, return, correction as a new version, release to country leadership (the CD answers each recommendation), per-school briefs through the account owner, and donor versions (aggregates only, cells under five suppressed, no names) approved by the RVP. The CSV draft is the evidence annex. The Country Director dashboard shows Impact findings and exports an impact dataset. Every transition is audited and appears in the Decision Log.

Still open: country-specific measurement rules need a schema change so a country rule does not supersede the deployment rule for planning elsewhere; the seeder and catalogue importer should skip IA-authored mappings; a live Salesforce integration remains an owner and integration decision.

## Implementation update

The IA dashboard now defaults to Outcomes, with Collection, Measurement framework, Programme learning, and Impact reports alongside the existing Map and Operations views. Existing view preferences remain respected. The school-level workspace uses the central access-scope resolver and filters project assignments before computing summaries or exports.

Outcomes show recorded project-school measurement coverage, improvement/decline classifications, and mean change by the eight existing SSA domains. Collection provides project and evidence-gap filters, pagination, account owners, dates, and school/project drill-downs. Invalid, unconfirmed, deleted, future-dated, or mismatched assessment references do not establish a measured pair. Missing data stays unmeasured.

Framework and learning views connect IA directly to existing mapping governance, strategic priorities, contribution analytics, project outcomes, and lending evidence. The report form downloads a draft CSV with the same scoped evidence, dates, references, mapping versions, and assessor-entered findings, limitations, recommendations, owners and follow-up dates. It requires export permission and protects text cells from spreadsheet formula execution.

Scope limits: this new outcome summary covers recorded project enrolments, not every programme participant. Programme-wide contribution and lending analysis remain in their existing linked workspaces. Reports are downloadable drafts; narratives are not persisted or sent, and no publication approval workflow is introduced. Separate IA Director permissions and live Salesforce synchronization remain future organisational/integration decisions. No database migration is required.

## Mission and evidence basis

IA should own the quality of evidence connecting training, lending, and educational technology to sustainable school improvement and spiritual and educational transformation. Verification supports that purpose; completed activities and people reached are outputs, not demonstrated transformation.

Edify's [Theory of Change](https://edify.org/theory-of-change/) connects equipping schools through training, loans, and technology to school improvement, student transformation, and community impact. Its [website](https://edify.org/) confirms those three programme areas. The [current careers page](https://edify.org/jobs-internships/) did not list an IA vacancy when reviewed. Consequently, the Officer/Director allocation below is a recommendation based on the user's supplied responsibilities, not a verified official Edify job description.

## Responsibility and functionality matrix

| Responsibility | IA Officer | IA Director / functional lead (proposed) | Existing implementation | Alignment needed |
|---|---|---|---|---|
| Framework development and strategy | Draft indicators and programme mappings; identify field measurement problems; apply approved methods. | Own theory-of-change alignment, indicator definitions, evaluation design, and methodological approval. | IA manages versioned activity-to-SSA mappings, expected direction, meaningful-change thresholds, and follow-up windows; also has priority configuration and milestone rights. | Extend SSA mappings into an explicit outcome framework covering spiritual formation, learning, and sustainability. Define indicator owner, source, calculation, population, frequency, limitations, and approval history. |
| Baseline and field collection | Coordinate baseline and follow-up collection, reconcile school identities, validate uploads, review field evidence, and resolve missing data. | Set collection standards, sampling protocols, quality requirements, and escalation rules. | School/SSA imports, duplicate review, evidence queues, Salesforce references, and confirmed assessments support this work. Project measurement selects a baseline and follow-up inside a defined window. | Provide a consolidated collection worklist for missing baselines, upcoming/overdue follow-ups, responsible staff, and unresolved quality issues. Clearly distinguish manual Salesforce confirmation/imports from automated synchronization. |
| Evaluating school progress | Compare confirmed assessments, investigate improvement/decline, and record contextual evidence with schools. | Approve evaluation methods and interpret results across programmes and cohorts. | SSA improvement, project impact classifications, and loan-impact assessments exist. Project measurement preserves missing evidence rather than treating it as zero. | Present domain-level outcomes alongside SSA proxies; add corroborating classroom, discipleship, and student-learning evidence where required. Do not imply that a school score directly measures individual student transformation. |
| Analysis and performance tracking | Analyse paired cohorts, programme exposure, qualitative findings, variation, and data gaps. | Lead cross-programme learning, assess strength of evidence, and recommend programme changes. | IA role analytics include SSA performance, activity pipeline, improvement, and recommendations. Contribution analytics explicitly describe association rather than causal proof. Lending has baseline requirements, evidence references, follow-up dates, and limitations. | Unite training, lending, and EdTech findings in one outcome review. Display sample size, coverage, missingness, time window, and limitations beside findings. Add documented qualitative synthesis and action follow-through. |
| Reporting and accountability | Prepare traceable findings and school feedback; explain completeness and uncertainty. | Review interpretations and methodological quality; coordinate release with authorised country leadership. | Export permissions, saved summary reports, and private scheduled analytics digests exist. The reviewed generic report generator primarily reports school counts and SSA completion. | Add an impact report with baseline/follow-up results, domain findings, qualitative evidence, limitations, recommendations, and accountable action owners. Provide audience-specific school, leadership, and donor versions with explicit review/release states. |

## Role and permission design

The application currently defines one `ImpactAssessment` role in `apps/core/rbac.py`; there is no separate IA Director role. Do not silently reinterpret Country Director as IA Director or grant IA global access.

Retain the existing IA role for operational collection, verification, mapping, analysis, and report preparation. If organisational staffing requires separate levels, introduce explicit methodological approval permissions for a Director/functional lead, with assigned country or regional scope. Define who approves a framework when no separate IA lead is available, and record that decision before implementing a new approval gate.

Preserve existing product-owner decisions: IA can edit and allocate strategic priorities; strategic approval/publication remains with the authorised leadership roles. IA or the assigned monitoring staff may record partner Salesforce completion under the existing rules. Preserve independent verification of an IA officer's own field work. Framework ownership does not imply financial approval, unrestricted exports, or authority to approve one's own evidence.

## Recommended IA workspace

Make the primary question: **What changed in partner schools, how strong is the evidence, and what should we do next?**

1. **Outcomes:** spiritual formation, educational quality, and sustainability; paired results and school-level drill-downs.
2. **Measurement framework:** programme-to-outcome mappings, indicator definitions, versions, windows, and approvals.
3. **Collection and quality:** baselines, follow-ups, duplicates, missing evidence, and verification queues.
4. **Programme learning:** training, lending, and EdTech comparisons; qualitative explanations and recommended actions.
5. **Reports and feedback:** reviewed reports, school feedback, leadership decisions, and action follow-up.

Candidate outcome measures require IA approval rather than hard-coded invented targets. Examples include observed teaching-practice change, comparable learning-assessment change, documented discipleship engagement, and loan-purpose-specific improvement. Report training attendance, loans disbursed, and devices deployed separately as outputs. Programme comparisons should not be labelled causal effects without a suitable evaluation design.

Primary dashboard measures should include paired-assessment coverage, domain change, improvement/decline among measured schools, missing baselines, overdue follow-ups, and evidence completeness. Every rate needs an explicit denominator and period. Schools without follow-up remain unmeasured, and should be visible outside the measured-outcome denominator.

## Implementation priorities and acceptance criteria

1. **Unify navigation and outcome presentation.** Reuse existing measurement engines and retain the verification workspace. A user can move from an outcome finding to its cohort, assessment evidence, and programme exposure. Activity completion cannot appear as proof of transformation.
2. **Consolidate collection readiness.** Show missing baselines and due follow-ups using each mapping's approved window. Each item identifies its school, programme, owner where assigned, and evidence gap; out-of-scope users cannot retrieve it.
3. **Extend framework governance.** Add indicator definitions and explicit methodological review where the role structure supports it. Published historical measurements retain their applicable framework version; changed definitions cannot silently rewrite earlier results.
4. **Build evidence-based reporting.** Generate reviewed impact snapshots with methodology, denominators, missingness, findings, limitations, and actions. External release is a separate authorised action; a private analytics digest is not donor publication.
5. **Specify Salesforce integration separately.** If automated synchronization is required, define field ownership, identifier matching, retries, reconciliation, and audit history. Existing IDs or imported files must not be shown as proof of a successful live sync.

## Code evidence reviewed

- `apps/core/rbac.py`: IA role and permissions, including mapping management, exports, strategic priorities, and lending validation.
- `apps/core/permissions.py`: evidence review and partner Salesforce confirmation authority; independent verification rules.
- `apps/activity_catalogue/intervention_mapping.py`: versioned mappings, expected direction, thresholds, and measurement windows.
- `apps/projects/ssa_impact.py`: confirmed baseline/follow-up selection and evidence-aware outcome classification.
- `apps/analytics/role_analytics.py`: existing IA analytics payload.
- `apps/frontend/views/impact_views.py`: scoped contribution analytics and association caveat.
- `templates/partials/ia/dashboard_body.html`: geography and verification operations dashboard structure.
- `apps/schools/models.py`: school Salesforce metadata explicitly marked as not integrated yet.
- `apps/business_transformation/models.py` and migration `0013_impact_assessment_evidence.py`: lending baseline and impact-evidence structures.
- `apps/reports/services.py`: generic saved report contents.
- `apps/analytics/report_delivery.py`: private in-app analytics digest delivery.

The remaining specification is a backlog beyond the implementation update above. Existing production permissions and the single IA role are preserved.
