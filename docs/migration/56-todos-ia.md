# 56. The To-Do page, read by Go: Impact Assessment's queue (first piece)

Piece 1 of 36's backlog item `todos-ia`. `internal/todos` already answered `/todos` for a field officer
(CCEO); Go now answers Impact Assessment too, when every builder IA reaches either has a Go port or
finds nothing for the reader to do. Otherwise the reader is passed to the existing application, as
before. Marking done stays Django's.

## 56.1 Who Go answers

IA reaches 23 builders (`rules.json` `roles.ImpactAssessment.builders`, exported by
`export_todos_rules`). They fall in four kinds:

| Builder | For IA in Go | How |
|---|---|---|
| `_activity_todos`, `_partner_delay_todos`, `_project_ssa_todos`, `_extra_work_todos`, `_returned_assignment_todos`, `_fund_request_todos`, `_school_quality_todos` | the field officer's port | these read the reader's own records and do not branch on IA (checked in the Python: only PL/CD branches) |
| `_school_action_todos`, `_visit_request_todos`, `_pd_todos`, `_field_debrief_todos`, `follow_up_todos` | the field officer's guard | unchanged |
| `attendance_todos` | the field officer's port | only a Programme Lead's rows differ (their category); IA now allowed |
| `_ia_todos` | **ported** (`iaVerificationTodos`) | work in the reader's country awaiting IA verification, partner work or staff work with a Salesforce ID, never the reader's own, twenty by `submitted_to_ia_at` (nulls last) then `updated_at`; late a day after submission |
| `collection_todos` (IA branch) | **ported** (`collectionIA`) | schools in reach (`AnalyticsReach`, `active`/`reopened`) whose collection state is never assessed, follow-up due or visit without scores, a row per owner (eight, then "N more"), per district for unowned schools; blocked import rows of the reader's batches of the last 30 days; records returned to the reader |
| `missing_training_todos` | **ported** (`missingTrainingTodos`) | `coverage_service.training_coverage(...)["missing_count"]` for the local day's FY: operating trained-type schools in reach with no invited/attended cluster session and no in-school training planned in the year |
| `framework_todos` | **ported** for the unmapped row; guard for reviews | rules/definitions in review or returned pass the reader on; else "Set measurement rules for N activities" (school-outcome catalogue items with no live primary mapping) |
| `_business_transformation_todos` (IA branch) | guard | any loan (all three IA sections are loans') |
| `learning_todos` | guard | any loan or impact finding |
| `ia_queue_todos` | guard | any pending SSA record, open unmatched import row, potential duplicate or pending sample |
| `evidence_todos` (IA branch) | guard | any pending evidence record, evidence returned to the reader, or a submitted change story |
| `report_todos` | guard | any impact report |
| `_cd_flag_todos` | guard | any flag assigned to the reader, whatever its status |

Guards are deliberately wider than their builders (a superset of the records that make a row), so a
guard that stays quiet means the builder has nothing. The seed's ia@edify.org has a pending SSA
record, a submitted change story, a pending learning result and two loans on `edify_gorn_dev`, so on
the development database IA is still passed on; on the integration copy (`edify_gorn_a25_test`) none of
those exist and Go answers IA's page.

The role-branching builders keep the field officer's answer for every other role (`byRole`); the
IA-only builders pass any other role on (`onlyIA`). `PortedRoles` is now `CCEO, ImpactAssessment`.

## 56.2 Rules exported, not restated

`export_todos_rules` writes a new `ia` section and eight new link shapes (`can_open_url` answers per
role). Lifted to module constants, no behaviour change:

- `todo_service.IA_TODO_WAITING_STATUS` (`awaiting_ia_verification`)
- `ia_collection.COLLECTION_OPERATING_STATUSES`, `RECORD_RETURNED`, `RECORD_PENDING`, `RECORD_CONFIRMED`, `PARTNER`
- `collection_todos.BLOCKED_ROW_STATUS`
- `ia_todos.SSA_PENDING_STATUS`, `UNMATCHED_OPEN_STATUSES`, `DUPLICATE_OPEN_STATUS`, `SAMPLE_PENDING_STATUS`

`school_status.CLUSTER_SESSION_TYPES` is built from a set, so it is exported sorted (its order is not
stable between runs). The drift test (`apps/command_center/test_todos_rules_export.py`) covers the new
section.

Traps met: `urlencode` keeps the dict's order (`view` then `owner`), Go's `url.Values.Encode` sorts
keys, so the owner link is written by hand; Django's `scheduled_date__date` reads the day in
`Africa/Nairobi` (settings `TIME_ZONE`), so the coverage statement does too; `missing_training_todos`
takes the FY of the local day, while the collection states read the UTC FY (`get_operational_fy()`).

## 56.3 Proving it is the same

- Golden comparison on synthetic records in `edify_gorn_a25_test`: `$SP/agent48_ia_golden.py` files 20
  records (ids `gia…`, names `[Go parity check]`): four activities awaiting verification (staff with a
  Salesforce ID 30 hours old, partner without one, staff without one, a cluster's never stamped),
  three collection activities (staff open, partner open, delivered without scores), two in-school
  trainings (one cancelled), a cluster training with an invited and a not-invited school, a fresh and
  a 40-day-old import batch with blocked rows, a returned and a confirmed SSA record; asks the
  existing feed (cache bypassed) for ia@ with four questions; removes everything (verified 0 left).
  `TestTodosIAMatchTheExistingFeedOverSyntheticRecords` files the same rows and compares whole
  messages: `todos_ia_test.go:45: 4 answers of 1 accounts compared, 0 differing`.
- `TestTodosIAPassedOnWhenAGuardedRecordExists`: Go answers IA, then with one SSA record set pending
  (and put back) IA is passed on.
- Unit tests (`ia_test.go`): verification rows (late at more than 24 hours, partner wording, no due
  day), owner/district grouping (ranking, ties by id, the "more" row, unowned order, singular words),
  the local FY, other roles passed on.
- Parity over all 29 seed accounts on `edify_gorn_dev` (Go-only gateway 127.0.0.1:8094, my Django
  127.0.0.1:8125): see 56.4.

## 56.4 Parity numbers

All 29 accounts, Go-only gateway (no existing application behind it), 5 questions each:

```
coordinator@edify.org              5 questions, 5 differing

145 answers compared, 45 differing
```

The 20 CCEOs: 100 answers, 0 differing (unchanged by this piece). All 45 differing answers are the 9
accounts Go passes on, each `go error: unavailable: This screen is not available here yet` against
the existing 200: admin, business-transformation, cd, pl1–4, coordinator (roles not ported) and ia@
(on `edify_gorn_dev` its guards find a pending SSA record, a submitted change story, a pending learning
result and two loans). So on the development seed Go itself answers 0 of ia@'s 5 questions; Go's IA
answer is proved on the integration copy (56.3: 4 of 4 answered by Go, 0 differing).

The same 9 through the gateway with my Django behind it (127.0.0.1:8125), so the passed-on answers
come from the existing application:

```
coordinator@edify.org              5 questions, 0 differing

45 answers compared, 0 differing
```

## 56.5 What is left (todos-ia-2)

Port the guarded builders so the development seed's IA is Go's: `ia_queue_todos` (four aggregates:
pending SSA for a verifier other than the collector/uploader, unmatched rows in the country, potential
duplicates in reach, pending samples), `evidence_todos`' IA branch (`ReviewerResolver.basis`, stories
`visible_stories`), `learning_todos` (findings, lending queues), the three IA sections of
`_business_transformation_todos`, `framework_todos`' review rows, `report_todos`, `_cd_flag_todos`.
