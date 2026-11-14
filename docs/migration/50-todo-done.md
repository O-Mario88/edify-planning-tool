# 50. A To-Do put aside: Today's Snooze, saved by Go (first piece of `todo-done`)

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Backlog item `todo-done`:
"mark a To-Do done".

## 50.1 What "done" is in the existing application

There is no stored "done" for a To-Do. The queue
(`apps.command_center.todo_service.get_todos`, doc 36) is derived: each row
is computed from the record it is about and leaves when that work is done.
The To-Do page (`/todos`) has only links. What a person can save about a
To-Do is on the Today queue (`apps/frontend/views/today_views.py`):

| Save | Route | What it writes | State |
|---|---|---|---|
| Snooze (tomorrow / next week) | `POST /today/snooze` → `today_actions.snooze` | `command_center_todo_snooze`: `update_or_create(user_id, todo_id, defaults={until, title})`; no audit row | **Go's, proved in shadow (this document)** |
| Undo a snooze | `POST /today/unsnooze` → `today_actions.unsnooze` | DELETE of the person's row | The existing application's (the gateway holds no DELETE; 50.5) |
| A decision on the row (Confirm, Approve, Return, Verified, receipt) | `POST /today/act` → `today_actions.perform` | the record's own domain save (PL completion review, weekly fund approval, leave, visit request, weekly/monthly receipt, SSA verification, weekly advance request, partner evidence), then `command_center_today_action` and an audit row `today.decision` | The existing application's; backlog `todo-done-2` |

## 50.2 The rules

| Rule | Where it lives | In Go |
|---|---|---|
| Who opens Today: `require_page_permission("today")` per role (CCEO, Programme Lead, Impact Assessment, Admin, Project Coordinator) | `RolePermissionService.can_view_page` | `rules.json` `doors` (exported) |
| Partner roles are asked per person (`member_scope.page_withheld`) | `can_view_page` | `per_person` (exported): handed on |
| Acting appointments (`acting.page_withheld`), an account that must change its password or is not active | `can_view_page`, middleware | handed on |
| A refused reader: audit row `unauthorized_page_access` and the Access Denied page | `require_page_permission` | handed on (Go writes no refusal) |
| Choices and days | `today_actions.SNOOZE_DAYS` | `snooze_days` (exported) |
| An empty item or unknown choice: "Choose when the item comes back." | `today_actions.snooze` | `refusal` (exported by calling `snooze` itself, which refuses before reading) |
| `until` = local day (Africa/Kampala) + days | `timezone.localdate()` | `Service.Snooze` |
| Stored `todo_id[:128]`, `title[:255]` (characters) | `snooze` | `lengths` (exported model lengths; `cut` counts runes) |
| The answer: `"{title[:120]} — snoozed until {%a %-d %b}"`, an Undo for the posted id, in row `today-` + sha1(id)[:12]; a refusal into `#{slug} [data-today-error]` | `today_snooze`, `_refusal`, `row_slug`, `queue_item_done.html` | `Answer`, `Refusal`, `RowSlug` |
| The write: `select_for_update().get()` then UPDATE of `until, title, updated_at`, or INSERT with a fresh id and both stamps (a concurrent create: lock and update) | Django's `update_or_create` | `write` (same statement order; no `ON CONFLICT`, which needed reads of the title) |

`manage.py export_todo_snooze_rules` writes
`platform/backend/internal/todosnooze/rules.json`;
`apps/command_center/test_todo_snooze_rules_export.py` fails when they drift.

## 50.3 Writer role

`platform/deploy/db/todo_roles.sql` (wired into `apply-roles.sh` and the
integration TestMain): `edify_todos_rw`, granted to `edify_gateway`:
SELECT `(id, user_id, todo_id)`, INSERT `(id, created_at, updated_at,
user_id, todo_id, title, until)`, UPDATE `(updated_at, title, until)` on
`command_center_todo_snooze`. No DELETE; the title is never read.
`TestGatewayRoleCanNeitherWriteNorReadSecrets` now also refuses deleting a
snooze, re-owning one, reading its title and writing a Today decision.
dbguard's source lint allows `internal/todosnooze` that one table.

## 50.4 The proof (shadow)

Scenario `platform/backend/cmd/shadow/scenarios/snooze_todo.json`, 19 steps:
a new snooze, the same item again (update), a second item, an unknown
choice, an empty item, a 300-character accented title, the same item for a
second person, a 140-character id, a Programme Lead, the Admin, the Project
Coordinator, the Country Director and Business Transformation (the page
refuses both: handed on), then one Undo per person (handed on; one undoes a
real snooze), so every person's last request is the existing application's
on both copies. `django_runner.py` gained a step kind `post` (a form on a
page, not in a drawer); `cmd/shadow/todoplay` plays copy B through
`todosnooze.Service` as the gateway role and holds every answer to copy A's
word for word.

Copies `edify_shadow_s21_*` (base from `edify_gorn_dev` by pg_dump, Go
schemas dropped, roles applied to the base only). Run 4, last lines exactly
as printed:

```
0 of 19 steps answered differently
todoplay exit 0
shadow exit 0
366 tables, 4 changed by the runs
0 of 4 changed tables differ
```

The four tables: `command_center_todo_snooze` (7 rows), `audit_log` and
`domain_event_log` (the two refusals, handed on), `user` (`last_seen_*`).
`verify_chain(full=True)` on copy B: `{'ok': True, 'brokenAt': None,
'checkedRows': 19738, 'fromSeq': None}`.

Found on the way: reading the Today panel writes (presence, and an
"exceeds the 3000ms SLO" incident with its notice and delivery when slow),
so the scenario posts the menu's three hidden fields rather than opening
the panel first.

## 50.5 What is left

- Nothing calls the Go save yet: the app's feed carries no Today Snooze
  (only `hx-get` buttons become actions), so there is no contract RPC and no
  `EDIFY_GO_SAVES` switch. Both come with the wiring.
- Undo (`/today/unsnooze`) is a DELETE; the gateway holds none. It needs the
  coordinator's decision (a narrow function like
  `gateway_money.withdraw_unmoved_advances`, or it stays Django's).
- Today's decisions (`today_actions.perform`, eight adapters, each a domain
  save with money, notices and audit): backlog `todo-done-2`.
- Django's escaping of `'` (`&#x27;`) is matched in todoplay's reading of the
  answer; no step posted one.
