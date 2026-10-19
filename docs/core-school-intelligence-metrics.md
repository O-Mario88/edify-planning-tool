# Core School Intelligence: metric specification

Owner, 2026-10-17: the Core School Intelligence brief, Phase 2 ("Create a
metric-to-source specification covering every KPI ... before implementing the
analytics"). Every figure below is computed once, in
`apps/core_schools/intelligence.py`, and read by both the Core School Profile
and Core School Oversight, so one school gives one answer on every page.

Owner decisions, 2026-10-17:

- Teachers and school leaders trained are **headcounts**, labelled as such.
  The records hold how many people a school sent, never who they were, so no
  figure claims unique people.
- The Champion rule in `apps/core_schools/champion_services.py` is Edify's
  official criteria: latest confirmed SSA average ≥ 8.0, no intervention
  below 7.0, all 8 package visits and trainings done.
- Planning (planned work, plan exports) lives on My Plan and Planning
  Oversight; Core School Oversight is analysis.

## Population and scope

| | |
|---|---|
| **Core school** | An operating school (`schools.lifecycle_service.active_schools`) of a Core lifecycle type (`core_schools.lifecycle.CORE_LIFECYCLE_TYPES`): Core, Core Trained, Core Graduate and Champion — the schools Core School Oversight has always listed. The package figures apply where the school has a Core plan (Core); the others read "No package". A Champion-type school reads Champion. |
| **Who sees which schools** | CCEO: the schools they hold (`scoped_school_queryset`). Programme Lead: their own and their team's (account owner, or a cluster the team holds), as Core School Oversight already scoped them. IA, CD, RVP, RPL, Admin: `scoped_school_queryset` (country or region). Acting leadership: the effective scope of the appointment. Every drilldown re-reads the same scope; nothing is hidden only in the page. |
| **Financial year** | `apps.core.fy`: 1 October to 30 September. The page's year (`fy`) is the year compared *into*; the previous year is `fy − 1`. Nothing is hard-coded. |
| **Groups** | CCEO = the school's account owner. District = the school's own district (never inferred from its cluster). Sub-region = the school's own sub-region. Cluster = the school's own cluster. |

## SSA

| Metric | Definition and source | Missing data | Aggregation | Drilldown |
|---|---|---|---|---|
| **Latest SSA** | The school's latest *confirmed* SSA record in `fy` (`ssa.year_comparison.school_current_scores`): its average, else the mean of its scores. Duplicates in a year are settled by date, then creation, then id. | "No current-year SSA" | School-weighted mean over the schools that have one; the count of those schools is shown beside it. | School row → profile SSA tab |
| **Previous SSA** | The latest confirmed record in `fy − 1` (`ssa.year_comparison.school_year_scores`). | "—" | As above | As above |
| **SSA change** | Latest − previous, *only* for schools compared under `ssa.change_rules`: a confirmed record in both years, at least 120 days apart, and at least one intervention scored in both. It is the mean of the school's comparable intervention changes (`impact_engine.improvement_rows` → `change_rules.classify_pairs` → `school_verdicts`), the pairs every impact page reads. Points, never a percentage. | "Not compared", with the reason | Mean over compared schools only; the compared count is shown. | Compared schools |
| **Trajectory** | `change_rules` verdict: Improved / No Change / Maintained Strong / Declined, by IA's published threshold for each domain, else any movement ("Any change (no approved threshold)" is shown). | "Not compared" (never "No Change") | Counts per verdict; denominator = compared schools. | The schools in each verdict |
| **Weakest intervention** | The intervention with the lowest score on the latest confirmed `fy` record. | "—" | Most frequent weakest intervention across the group. | Profile SSA tab, area |

## Core package

| Metric | Definition and source | Missing data | Aggregation |
|---|---|---|---|
| **Visits / trainings done** | `CorePlan.visits_completed` / `trainings_completed` of the school's `fy` plan, against `visits_target` / `trainings_target` (4 and 4 by default; the plan's own targets win). | No plan: "No package" | Sums of done and target over schools with a plan. |
| **Package complete** | Done ≥ target on both, target > 0. | No plan: not counted | Count complete / schools with a plan. |
| **Staff and partner halves** | `core_schools.package_split.package_splits`: the work at the school dated in `fy` by who delivers it (`Activity.delivery_type`), group trainings that fill a package slot, and partner hand-overs still waiting for a date. Each half holds 2 visits and 2 trainings. | No package: "—" | Sums. |
| **Partner hand-overs** | `PartnerAssignment` at the school: *assigned* (assigned or pending scheduling), *scheduled* (scheduled or partner-scheduled), *completed*. Assigned is a commitment, never support delivered. | 0 is a real zero | Sums. |

## Participation (owner: headcounts)

| Metric | Definition and source | Missing data | Aggregation |
|---|---|---|---|
| **Cluster sessions invited / attended** | The school's rows on the register (`ClusterActivityAttendance`) of cluster meetings and group trainings *delivered* in `fy` (completed and awaiting verification, or verified: the rule of the Cluster Profile's attendance register). Any cluster's session counts; the school's membership is not changed by it. | No invitation: "—" | Sums. |
| **Attendance rate** | Attended ÷ invited × 100, on the same delivered sessions. A cancelled or unheld session has no register and is in neither. | No invitation: "—" (not 0%) | Total attended ÷ total invited (not a mean of rates). |
| **Teacher attendances / leader attendances** | Headcounts: the `teachers` and `leaders` on the school's attended register rows, plus `teachers_attended` / `leaders_attended` on in-school trainings completed at the school in `fy`. Labelled "attendances", never "unique teachers". | Not recorded: "—" | Sums. |

## Outcomes

| Metric | Definition and source | Missing data | Aggregation |
|---|---|---|---|
| **Enrolment change** | `SchoolEnrollmentHistory`, `fy` against `fy − 1`; growth % only where the previous figure is above 0 (`clusters.outcomes._growth_pct`). | "—" | Sum of after − sum of before over schools with both years; growth over that same population. |
| **Learning change** | Confirmed learning results, each year's figure the learner-weighted share of marks (`clusters.outcomes._school_scores`, the Cluster Profile's Learning Results rule), `fy` against `fy − 1`, in percentage points. A result with no maximum mark is left out. Limitation: a year's figure pools the school's assessment types, grades and subjects, as the Cluster Profile does. | "—" | Mean over schools compared. |

## Champion readiness (official rule)

| Status | Rule |
|---|---|
| **Champion** | `CoreSchoolProfile.champion_status` is Champion (set only by the approval action). |
| **Potential Champion** | The official rule holds on the school's confirmed records: latest average ≥ 8.0, lowest intervention ≥ 7.0, all 8 package slots done (`ChampionEligibilityService`, read without writing). |
| **Progressing** | Latest average ≥ 8.0, or the school improved, with a criterion still open. |
| **Not Yet Ready** | A confirmed SSA and a package exist, and the rule does not hold. |
| **Insufficient Evidence** | No confirmed SSA or no Core plan to judge. |

A recommendation never changes the school's type; only the existing approval
does.

## Attention (what a school is listed for)

Each reason uses an existing rule; none is a new threshold.

- **SSA declined:** the `change_rules` verdict is Declined.
- **No current-year SSA:** no confirmed record in `fy`.
- **Package incomplete:** the plan's done is below its target.
- **Partner hand-over not scheduled:** an assigned hand-over with no date.
- **Champion candidate:** Potential Champion, awaiting review.

## Not computed, and why

- **Unique teachers or leaders trained:** no participant identity is recorded.
- **Teacher coverage rate:** no school records its total teachers.
- **Causal impact:** the page shows observed change beside delivered support,
  never "caused by".
