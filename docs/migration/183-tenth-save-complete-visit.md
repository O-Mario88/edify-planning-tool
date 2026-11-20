# 183 · The tenth save: completing a staff school visit (2026-11-20)

M8's first save (doc 04; doc 182's order of the remaining writes). An
officer completes their own staff school visit from My Plan's Complete
drawer, with its Salesforce visit ID, and hands it to their Programme Lead.
Go makes it behind `EDIFY_GO_SAVES=complete_visit`, **off by default**, and
only in development and staging, like the nine saves before it. The existing
save is not switched off; nothing is cut over.

## 183.1 The case Go takes

Everything else is forwarded to the existing application unchanged, so no
completion is made by both:

- **Who:** a CCEO working in their own seat, with a staff profile, who holds
  no Programme Lead role. A lead's own work is approved as it lands
  (`approve_on_hand_in`), and acting seats are another person's seat.
- **The visit:** their own staff visit, at a school in their own portfolio
  that is not a Core school. Its type is a School Visit, or the visit a
  donor, story-gathering, invitation or social purpose is planned as. It is
  already started (`completion_started`; the drawer starts a visit as it
  opens, on the web and in the app). It has no cluster, project, partner,
  pair or monitoring officer, and no Salesforce ID yet. It is not IA-confirmed
  and not a OneTest visit. Its record type is a visit's (none, `VISIT`,
  `SSA_DATA_GATHERING`). It has no open overdue reminder or day-off notice.
- **The form:** no purpose given at completion other than the one it holds.
  No training ID, school feedback, register, visiting schools or advance
  accountability (`netsuite_id`). Counts are written as plain digits. The day
  done is its planned day, so neither the work nor its money moves.

Handed on, by design: SSA Support and Training Follow Up visits, In-school
Training pairs, cluster sessions, partner work, a TS- training ID typed into a
visit (the view's own notice), a day done other than the planned one
(`move_to_completed_day` moves money, which is M12), and returned work.

## 183.2 What one completion writes (measured)

Measured on `edify_shadow_m8_a` against an untouched `_b`, one completion of
a CCEO's School Visit (`cmd/shadow`, window 08:27:13–08:27:16 UTC). 8 of 366
tables changed:

| Table | Rows | What |
|---|---|---|
| `activity` | 1 updated | status `in_progress` → `submitted_to_pl`, `actual_delivery_date`, `actual_outcome`, `actual_observations`, `follow_up_note` "", `teachers_attended`/`leaders_attended`/`other_participants` 0, `salesforce_activity_id`, `salesforce_activity_type` "visit", `evidence_status` none → accepted, `execution_started_at` (set when the drawer opened), `updated_at` |
| `activity_salesforce_reference` | 1 new | the normalised ID, the raw ID, `staff_self_entry`, prefix `SVE-` |
| `activity_completion_verification` | 1 new | the ID, `pending` |
| `audit_log` + `domain_event_log` | 3 + 3 | `activity.salesforce_id_entered`, `notification.activity_submitted_for_review`, `complete_activity` |
| `notification` | 1 new | "Completion awaiting your review" to the Programme Lead |
| `target_ledger_dirty` | 1 | the owner's year marked |
| `user` | 1 | presence (`last_seen_*`) |

## 183.3 How Go makes it

The rules follow the view (`my_plan_views.complete_activity_action`), the
completion (`services.complete`) and the reservation
(`salesforce.reserve_salesforce_id`), in their order:

1. **The gateway** (`internal/screens/complete_save.go`) asks the existing
   application for the drawer's form (`POST /api/mobile/v1/drawer?form_only=1`;
   `complete_activity` is now one of `FORM_ONLY_SAVES`). Nothing is saved,
   and the drawer starts an unstarted visit, as its own GET does.
2. **The service** (`internal/activities/complete.go`) reads the visit and
   the form and hands on anything outside 183.1. It refuses in the existing
   words, prefixed `Submission Error:` as `error_fragment` writes it:
   - an ID that is not SV-…, SVE-… or a 15/18-character record ID
     (`Enter the Salesforce ID as SV-… or SVE-…, or the record's own
     Salesforce ID.`);
   - an ID live work already holds (`This Salesforce Activity ID is already
     used by the {what} at {school} ({School ID}) on {day}. …`).

   An ID held by cancelled or removed work is handed on, since the existing
   reservation releases it.
3. **One transaction** calls `gateway_completion.hand_in_school_visit`. It
   locks the visit, checks 183.1 again, then writes the reference, the
   activity's completion columns and the verification. In the same
   transaction it writes the reservation's audit row.
4. **After commit**, in the existing order:
   - the existing application is asked for what follows the hand-in
     (`POST /api/auth/internal/visit-completed`, `gateway_relay.visit_completed`):
     `_handed_in` tells the Programme Lead, `_resolve_overdue_reminder` runs,
     and `plan.changed` is announced. Notices stay Django's until M11;
   - then the view's `complete_activity` audit row is written;
   - then the ledger mark.

   None of it can undo the completion.

**Grants (docs 03 §3.7).** The completion writes columns dbguard never lets
the gateway change (`actual_delivery_date`, `salesforce_activity_id`,
`evidence_status`). It also writes two tables the gateway holds nothing on.
As with the cancel's advances (30 §30.4), the gateway gets no new grant, only
EXECUTE on one SECURITY DEFINER function, `deploy/db/completion_roles.sql`:

- **Owner:** the function is owned by `edify_completion_owner` (NOLOGIN,
  NOINHERIT, nobody a member).
- **The owner's own grants:** the owner holds only the columns it reads and
  writes, with no DELETE.
- **What the function does:** it makes one visit's hand-in and nothing else.
- **Applying it:** `apply-roles.sh` and the integration TestMain apply it.

It is a new database object, so production needs the owner's approval at
cutover.

## 183.4 The proof

**App-level shadow proof** (`cmd/shadow/appplay`; the scenario
`cmd/shadow/scenarios/complete_visit.json`, 12 steps):

- **Copies:** both were made fresh from `edify_shadow_m8_base`, then roles
  and grants were applied to them. Copy A went through gateway 8396 (switch
  off) over Django 8296; copy B through gateway 8397 with
  `EDIFY_GO_SAVES=complete_visit` over Django 8297.
- **Steps:** four visits scheduled for today, then eight completions:
  - the seed School Visit;
  - a bad ID (refused);
  - a duplicate ID (refused);
  - a lower-case, padded SVE- ID;
  - an SSA Support visit (handed on);
  - a TS- ID (handed on);
  - a story-gathering visit;
  - a 15-character record ID on a social visit.
- **Who made the saves on B:** Django served 8 form-only requests and 2
  forwarded saves. Go made the other 6 (4 hand-ins, 2 refusals); the
  hand-ins each asked `visit-completed` once.

Last lines as printed (`m8_cycle_3.txt`):

```
0 of 12 steps answered differently
compare exit 0
django b: form_only=8 forwarded=2 handed_in=4
366 tables, 17 changed by the runs
0 of 17 changed tables differ
shadow exit 0
```

`verify_chain(full=True)` was ok on both copies (68,150 rows each).

**Found while proving it, and fixed:**

1. The `complete_activity` audit row failed in Go. The payload's empty
   `attendedSchoolIds` was a `[]string`, which the chain's canonical form
   does not hash, so it is now `[]any`.
2. Freshly scheduled visits carry their purpose's activity type
   (`donor_visit`, `story_gathering_visit`, `social_visit`), not
   `school_visit`. The reference's `activity_type` and the ledger check now
   use the visit's own type, and the function and the Go list name the same
   five types (`TestTheHandInFunctionNamesTheCompletedVisitTypes`).
3. `cmd/shadow` now masks a made row's id inside a path's query too
   (`/pl/review-queue?open=<id>`), not only between slashes. Before, the
   review notices of Django-made completions differed by the new visit's id
   alone.
4. The copies need the Edify Global schema's grants (`country_registry`),
   which no roles file applies; `copies.sh` copies no grants. For this proof
   they were copied from the development database's ACLs onto the two shadow
   copies. A roles file for them is still to do.

**Tests.**
- `internal/activities/complete_test.go`: the ID normalised as Python
  normalises it; the forms judged; the day read as `completion_day` reads it;
  the payload; each hand-on; the hand-ons before any read; the type list held
  to the SQL.
- `internal/screens/complete_save_test.go`: forwarded while off; Go's save
  forwards nothing; hand-ons forwarded; refusal and failure words.
- `cmd/shadow` `main_test.go`: an id in a path's query.
- Django `test_gateway_relay`: the new door is closed without the key and
  takes only its fields.

## 183.5 Not done

Switching the existing save off and any cutover wait for the owner. Still the
existing application's: SSA scores at completion (M7), accountability and
money moves (M12), training pairs, cluster registers, partner completion,
bulk and ID-file completion uploads (the rest of M8), and the notices (M11).
