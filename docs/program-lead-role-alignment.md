# Program Lead role alignment

Aligned 13 September 2026 to the owner's description of the CCE Program Leader: strategic direction, team leadership and management, performance management, programme implementation, and collaboration.

## Navigation

The Program Lead's sidebar follows the five responsibilities, then the lead's own portfolio and personal pages (33 links in 10 groups; previously 40 in 8):

| Group | Links |
|---|---|
| My Work | Today · Dashboard · My Plan · Calendar · To-Do |
| Strategic Direction | Priorities (Priority Setting · Target Distribution · My Team · Team Guidance) · Work Plan |
| Team Leadership | My Team · Team Leave (Approvals · Leave Tracker · Team Availability) · Field Debrief · Escalations · Team Assignments (Actions Sent · Extra Work) |
| Performance & Coaching | Coaching · Team Performance (Performance Reviews · Recovery Plans · Professional Development · Policy Compliance) |
| Programme Implementation | Team Oversight · Completion Reviews · Programme Rollout |
| Collaboration | Regional Lead (Training Feedback · Regional Lead Coaching) · Quality Flags · My Actions · Partners |
| Schools & Field | Planning · Schools · Core Schools · Clusters (own portfolio) |
| Finance & Budget | Weekly Advance Request · Fund Approvals · Budget |
| My Performance | My Performance Agreement · My Targets · My Professional Development · Leave & Personal Time Off |
| Analytics | Program Lead analytics (one door) |

The group order is specific to the Program Lead (`ROLE_SIDEBAR_GROUP_ORDER`); other roles' sidebars are unchanged. Shared pages are registered once more for the lead and excluded from their original entries, so each page appears once. `apps/core/tests/test_program_lead_navigation.py` holds the layout.

Removed for the lead: HR Today, Coverage, Decision Intelligence, Reports, the Business Transformation workspace and reports, and the retired monthly request (access removed; the leadership and budget-intelligence engine grants went with them), plus People Directory, Closed Schools and Projects from the sidebar (pages still reachable).

## What was added or fixed, by responsibility

**Strategic direction**
- Team Guidance: the lead issues priority guidance to selected officers, who acknowledge it with a response; the lead sees acknowledgements and reviews them on the review date.
- Priority Setting is read-only for the lead (no country or project allocations); Target Distribution shows "Team received" beside "My share".
- To-Dos for distributing a received team target and approving officers' quarterly spreads.

**Team leadership**
- My Team: one row per officer (delivery, targets, SSA coverage, what waits on the lead, review stage, last coaching, leave, policies overdue, risk) with a "Needs your action" list linked to pages the lead can open.
- Team Leave strip; leave calendar narrowed to the lead's team; Field Debrief "mark reviewed" with feedback; escalation To-Dos for the lead; staff profile supervision panel.

**Performance management**
- Coaching log: monthly one-to-ones, observations, check-ins, debrief feedback and recognition; shared records are acknowledged by the officer on My Coaching; monthly cadence and follow-up To-Dos.
- Performance Reviews show only the officers the lead reviews, with "Open conversation"; reviewer To-Dos; the reviewer's sign-off waits for the officer's reflection; recovery plans limited to the lead's officers with check-ins; development approvals in place; reminder scope fixed.

**Programme implementation**
- Programme Rollout: trainings by intervention, course and officer; school self-assessment coverage per officer and cluster; Christlike Behaviour and Exposure to the Word of God progress.
- Completion Reviews works for every row (both owner id forms) as a plain register; supervising leads can open cluster activities; Team Oversight has a Whole team view; "trained" means in-school or cluster attendance everywhere; SSA Performance defaults to the full financial year; directories default to the operational FY; Fund Approvals opens on the week waiting for the lead; SSA upload pages gated.

**Collaboration**
- Regional Lead coaching shared with the lead, with acknowledgement; training feedback can be passed to the officer who delivered it.
- Country Director flags notify the CD when acknowledged or resolved (resolution note required).
- Partner engagement log on Partner Oversight and partner profiles; partner-delivery escalations go through the escalation channel to the lead's own Country Director.

## Dashboard, Today and To-Do

The dashboard rail is Map (default) · Priorities · Team · Coaching · Programmes · Collaboration, under six Team pulse tiles and an action-only Leadership Attention band. Only the active view is built. Removed: personal targets, Team Backlog, Funding & Execution, Smart Route & Capacity, Quick Actions and duplicate tiles. The lead's Today starts with "Waiting on you" and "Your team today". To-Dos about officers' schools no longer land on the lead's queue; duplicate fund-approval rows and a stale accountability link were fixed.

## Data

New tables: `cce_cceo_coaching`, `cce_team_guidance`, `cce_team_guidance_receipt` (apps/cce_leadership), `partner_engagement` (apps/partners). "Who is on my team" has one definition: `apps.hr.team_roster.team_members`.
