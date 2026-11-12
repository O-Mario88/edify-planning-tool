# 27. The first save in Go: scheduling a school visit (design)

Owner, 2026-11-12: the Next.js web foundation starts after the first save.
This is that save's design, measured with the shadow harness (26) before any
code. M5 (04): "schedule … Each write appends the same audit and timeline
rows as today."

## 27.1 What one visit save writes (measured)

`cceo@edify.org` saving Planning's Schedule drawer for one client school
(SSA Support, 25 November 2026), on a fresh copy, compared with the
untouched base:

| Table | Row | Written by |
|---|---|---|
| `activity` | one row, about 100 columns: the purpose's activity type (SSA Support is "School Visit + SSA Collection"), the catalogue item and version, the workflow profile's costing and evidence profiles, planned date, month, week, quarter and FY, delivery and executor, the planning source, the SSA verdict in `recommendation_source` (`apps.ssa.plan_alignment`), its day's batch | `activities.services._create` |
| `audit_log` | `activity.scheduled`, the planning payload, on the hash chain | the audit pipeline |
| `domain_event_log` | `activity.scheduled`, carrying the audit row's sequence | the audit pipeline |
| `target_ledger_dirty` | the owner and FY whose counts must be read again | the target ledger |
| `daily_visit_costs_to_follow` | the days to price again (`steps.days`: batch and owner), who asked, provenance | `daily_visit_batches.costs_follow` |

Everything else the earlier seven-step run showed (cost snapshots and lines,
fund request items, weekly request lines, transport and advance rows) is
the **pricing that follows**: `costs_follow` answers the save first and
prices the day's visits in a thread once it commits, or on the saver's next
request, or before any fund-request step (`settled_first`).

## 27.2 The split

1. **Go does the save:** every rule `_create` and the drawer's view ask for
   this save; the activity row; joining its day's batch (made if the day has
   none); the audit row on the same chain under the same advisory lock (as
   sign-in does, 08 §8.2); the domain event; the ledger mark; the costs to
   follow. It also asks what the pricing would refuse
   (`_assert_days_can_follow`: a day whose rates are missing, whose transport
   is paid, a member whose advance or weekly or monthly request has moved),
   read-only, with the same words, so a save the existing application
   refuses is refused.
2. **Money stays the existing application's until M12** (01 risk 7: money
   moves last, after a period of shadow comparison). Once its save commits,
   Go asks the existing application, server to server with the internal key
   (the pattern sign-in uses for security events), to settle the costs to
   follow it wrote. Only the queued work is passed; the pricing code is
   untouched.

## 27.3 Scope of the first piece

Go takes a visit only when every part of it is ported, and hands the rest to
the existing application unchanged (the gateway forwards the drawer's
request):

- **In:** a staff-delivered school visit (the purposes Training Follow Up,
  SSA Support, Donor Visit, Content/Story Collection, School Invitation,
  Social Visit), planned by its owner at a school in their own portfolio,
  from Planning's Schedule drawer, with no project, priority allocation,
  source activity or partner.
- **Handed on:** In-school Training (the training-and-visit pair), Core
  School visits (the package route), partner delivery and facilitation,
  visit requests to another owner, cluster work, reschedules and edits.

## 27.4 Contract, roles and proof

- **Contract:** `edify/activities/v1/activities.proto`,
  `ActivityService.ScheduleSchoolVisit`: the drawer's own fields (school,
  purpose, date, purpose text, expected outcome, SSA deviation reason), the
  answer (the activity's id and status, or the refusal's words), the
  blueprint's `activity.proto`.
- **Writer role:** `edify_activities_rw`, granted column by column only what
  27.1 lists (`INSERT` on those `activity` columns; `INSERT` on the audit and
  event logs, the ledger mark and the costs to follow; the batch's insert
  and the columns a join updates). No `DELETE`, no `UPDATE` of an audit row.
  The gateway stays read-only by default and opens a read-write transaction
  for the save only (08 §8.2); `TestGatewayRoleCanNeitherWriteNorReadSecrets`
  grows to refuse everything else.
- **Proof, in shadow (26):** the drawer scenario on copy A through the
  existing application, the same steps on copy B through Go, nothing
  differing and the same answer for every step: each in-scope purpose,
  a school with and without a batch that day, each refusal (a past date, a
  closed school, a school outside the portfolio, a day the pricing would
  refuse, the one-visit rule), then a replayed month of real scheduling on
  a sanitised restore (M5's exit). The audit chain is then verified by the
  existing `verify_chain(full=True)`.

## 27.5 Decision for the owner

**One writer per table (03, 3.7) cannot hold save by save for `activity`.**
Dozens of saves write that table (schedule, edit, reschedule, cancel,
complete, verify, approve, pay). Moving them in one step would be one
release of all of M5 to M9. The practical path is the one sign-in took
(08 §8.4): one save at a time moves to Go, both systems writing the same
table under the same row locks and the same rules until the table's last
save has moved, each save switched off in Django in the same release that
switches it on in Go. Nothing is cut over without the owner's approval
either way; this asks which rule the cutovers follow.
