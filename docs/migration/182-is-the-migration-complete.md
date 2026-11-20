# 182 · Is the Go migration complete? (2026-11-20)

The owner asked, after the redesign work: "check if Go migration was
completed properly". The short answer is **no**: the reads are largely in
Go, the writes are not. Below is what was counted, how, and what comes next.

## Reads (pages)

Counted with the coverage probe (doc 178's method,
`internal/server/zz_probe_test.go`, build tag `probe`, never committed),
over the dev database, 2026-11-20:

| | Routes |
|---|---|
| Inventory routes | 347 |
| Answered by a Go page builder | **206** |
| Detail routes not claimed (drawers, actions, detail pages) | 61 |
| Static routes not claimed | 80 |

The same figures as doc 178's evening recount on 2026-11-19: today's work
was the redesign and fixes, not new pages. The 80 static routes are Go's in
another service (doc 178 A), Django's or Python's by design (B), or the
Help manager, contextual help and `/profile`; the 61 are D's parts, which
moved into the redesign (doc 178, "Decided 2026-11-19").

Fixed today on the read side: every School ID column read empty in the
apps, because the feed ran pages without the middleware that fills
`{% school_code %}`. The feed now runs it, and every Go page writes the same
words (`internal/schoolcode`, about twenty pages, proved 0 differing by the
integration suite apart from School Evidence's pre-existing option order).

## Writes (saves)

| Where a save is made | Count |
|---|---|
| Django views marked POST-only (`@require_POST`, `require_http_methods(["POST"])`) | about 197, plus views that check the method in their body |
| Go saves of the existing app's records (`EDIFY_GO_SAVES`, all **off** by default) | 10: schedule, reschedule, cancel and edit a visit; the training pair; group reschedule and cancel; group training; cluster meeting; and, since doc 183, an officer completing their own staff school visit |
| Go-only records, written by Go alone (Go-owned schemas or new features) | loans and the school loan portal, the Cluster Leader portal, field routes and GPS capture, country settings (Edify Global), sign-in sessions, accounts administration, acting leadership, to-do snooze, My PD, the audit chain |

Every other write (drawers, approvals, completion and evidence, SSA,
partner hand-overs, fund requests and money, HR programmes, impact reports,
leave, priorities, coaching, documents) is still Django's. The Go gateway
passes those saves to Django (`internal/screens`, `SaveDrawer`).

Largest POST-only groups in `apps/frontend/views`: HR programmes (22),
impact reports (14), CCE leadership (9), leave (8), priorities (7),
oversight (7), extended views (7), team guidance (6), IA school evidence,
lending and framework (6 each), core schools (6).

## So Django cannot be retired yet

The owner's end goal (2026-11-12) is Go replacing Django completely, with
zero data loss. Reads are close; writes are about 9 of 200-plus, and those
9 are switched off. Each save moves one at a time, shadow-proved first
(docs 26, 27; owner 2026-11-12), and is switched off in Django in the same
approved release. That rule stands.

## Order of the remaining writes (doc 04)

1. **M8, evidence and completion**: staff complete with a School Visit ID,
   uploads, bulk completion.
2. **M9, approvals**: PL approve or return, IA verify.
3. **M7, SSA**: manual entry, upload, PL confirmation.
4. **M10, partner hand-overs** and partner dating.
5. **M11, notifications**: mark read, preferences.
6. **M12, budgets and weekly advances**: money, deliberately last.
7. The rest by family (HR programmes, impact reports, leave, priorities,
   coaching, documents), each with its page's redesign (doc 178 D).

Each needs, as the first nine did: the save's own doc (what it writes,
measured), the writer role's column grants (docs 03 §3.7), the Go service
behind `EDIFY_GO_SAVES`, and its shadow proof on fresh copies (0 tables
differing). Production cutover still needs the owner's approval,
reconciliation and recovery testing.

## The next save, M8: completing a visit (analysis, 2026-11-20)

`POST /my-plan/<id>/complete` (`my_plan_views.complete_activity_action`)
is one transaction (`transaction.atomic`) of five steps:

1. `_complete_with_purpose`: the purpose the drawer gave, which may move
   the activity's purpose fields.
2. `start_completion` (or `start_in_school_training_pair`) when the
   activity is still scheduled: status moves to in progress.
3. `_submit_accountability`: the advance's accountability, **money** (M12).
4. `_record_completion_ssa`: SSA scores collected on the visit (M7).
5. `complete_activity` (or `complete_in_school_training_pair`) with the
   payload (completed day, School Visit ID, attendance), then `audit_log`.

Opening the drawer can already write (step 2 runs on open: "Auto-start
completion if in scheduling status").

So completion crosses three milestones. As with the costs in doc 27, Go
makes its own part (purpose, start, completion, audit) and asks Django to
settle the money (accountability) and record the SSA scores, inside the
same refusal rules, until M7 and M12 move. Before building, its own doc
must measure every table one completion writes (a staff visit, a training
pair, a cluster session with attendance), and the writer role needs grants
for the completion columns dbguard refuses today (status, actual delivery
date, the School Visit ID, completion timestamps), each named in docs 03
§3.7. Then the shadow proof, scenario by scenario, as in doc 49.

