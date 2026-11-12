# 20. Field Debriefs: where it stands (not moved)

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. The Field Debrief dashboard
(`/debriefs`, URL name `debriefs_list`) was the third page of this batch. It
turned out far larger than the other three together, so, as the batch's
instructions say for such a page, the Decision Log (18), Escalations (19) and
My Actions (21) were finished and proved first and this one is **not moved**:
there is no Go package for it, nothing is wired, and the app's
`PageScreenService.GetPage` still passes `/debriefs` to the existing
application.

## 20.1 What the page is

`apps.frontend.views.debrief_views.field_debrief_dashboard_view`, which hands
ten query values to `apps.debriefs.dashboard_service.FieldDebriefDashboardService.get_dashboard`
(597 lines) over `FieldDebriefService.scoped_queryset` (in the 1,400-line
`field_debrief_service.py`), drawn by `pages/debriefs/dashboard.html`,
`partials/debriefs/dashboard_body.html` and `dashboard_table.html` (376
template lines). The feed reads it, for every reader, as twelve blocks:

| Block | What it is drawn from |
|---|---|
| Filters | Fiscal year (`fy_options`), the range (7/30/90 days or the year), every district by name (`_district_options`), the risk levels less None |
| Strip "Debrief context" | Eight KPIs through the metric registry (`render_precomputed_metric_item`, `reconciled_registry`), each with a month-on-month change against the prior period (`_pct_delta`) |
| Chart "Debrief Trend Over Time" | One category a day over the range (`%b %d`), four series |
| Panels | Debriefs by activity type (the six most common), top challenges (eight, with shares), the Action Center (five figures, two of them read from `daily_debrief_action` by owner and due date) |
| Section and segments | "Team & Partner Debriefs": the tabs (All Debriefs, My Debriefs, Team Debriefs, Partner Debriefs, Escalated, Peer Solutions and, first for a Programme Lead, Awaiting my review with its count), each a table of fifty a page with its own pager |
| Panels | Recent activity (the five latest), recent peer solutions (five, with endorsements), debriefs by risk level, and the intelligence highlights (the top challenge, up to three open insights by occurrence, repeated schools, criticals; six at most) |

## 20.2 Why it is large

- **Scope.** `scoped_queryset` has a branch per role, and several reach into
  rules Go does not have yet: HR's people reach (`apps.hr.reach.people_reach`,
  `scope_profiles`), restricted incidents routed through
  `daily_debrief_recipient`, a Programme Lead's team including the officers
  of an absent lead they cover (`apps.hr.team_roster.team_member_ids`), a
  CCEO's peers under their supervising lead (`supervising_pl`,
  `team_staff_ids`), the partner ids of `resolve_user_scope`, and the RVP's
  critical-only reading; then seven filters, one of them the schools of a
  district matched against an array column (`linked_school_ids__overlap`).
- **Figures.** Eight KPIs and their prior-period changes, a daily trend,
  two donuts, ranked challenges (`Counter.most_common`, whose order among
  equal counts is first-seen), the Action Center and the highlights, each
  over the same rows; the KPIs' labels, helpers and notes come from the
  metric registry rather than the template.
- **Words.** The KPI labels live in the registry, the tab names and empty
  states in three templates, the challenge, activity-type, status and risk
  words in model choices.

## 20.3 What was checked

- The existing feed was dumped for all 29 seed accounts as the page opens:
  the Business Transformation Officer is refused (404), every other account
  is given the twelve blocks above, the four Programme Leads with the extra
  Awaiting-my-review segment.
- The development database holds no debriefs, insights, peer solutions or
  debrief actions, so every figure there is zero and every list empty; a
  parity run over it would prove the page's furniture, not its rules.
- A partner's team member is refused the page by the existing feed (checked
  in the test database with a roster entry, for both partner roles: 404), so
  the shared `decisionlog.PartnerTeamMember` rule applies here as well.

## 20.4 What is left, in order

1. Export the vocabularies: the page and partner-team doors per role, the
   statuses, risk levels, completion statuses, challenge and activity-type
   words, the tab rules, the metric registry entries the strip shows, the
   page size and the ranges.
2. Port `scoped_queryset` (and `awaiting_review`) as its own Go piece,
   reusing the HR reach and the team roster once those are Go's; until then
   the HR and covering-lead branches cannot be proved.
3. Build the twelve blocks, then a golden comparison in the test database
   over many debriefs (as 18 to 21 do), since the development data reaches
   none of the figures.
4. Only then wire it in `server.go` and run the 29-account parity.
