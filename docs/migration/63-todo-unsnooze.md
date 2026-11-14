# 63. Undoing a To-Do snooze, saved by Go (`todo-unsnooze`)

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Backlog item `todo-unsnooze`,
the piece doc 50 (50.5) left: Today's Undo after a Snooze.

## 63.1 What the existing undo does

`POST /today/unsnooze` (`apps/frontend/views/today_views.py`
`today_unsnooze`, behind `require_POST`, `require_page_permission("today")`
and `_staff_guard`) calls `today_actions.unsnooze`:
`TodoSnooze.objects.filter(user_id=str(principal.id), todo_id=todo).delete()`.
No audit row, no signal that writes, no cache forgotten. It refuses nothing:
an empty or unknown id removes nothing. The posted id is matched whole (a
snooze stores `todo_id[:128]`, the undo filters on the posted value). The
answer is the whole Today panel drawn again (`partials/today/dashboard_view.html`
from `build_today_context`, exactly what `GET /today/panel` renders),
retargeted onto `[data-dashboard-today]` with `outerHTML`; the This Week Me
tab's `today_section=own` keeps a Programme Lead's redraw to their own day.

## 63.2 The coordinator's decision, as built

2026-11-13: "a narrow SECURITY DEFINER function `gateway_todos.unsnooze(user_id,
todo_id)` owned by a NOLOGIN role with only DELETE on
command_center_todo_snooze, deleting at most that user's row for that To-Do,
EXECUTE granted to edify_todos_rw only … the gateway keeps no DELETE of its
own; integration test that it deletes nothing else; production needs the
owner's approval at cutover."

`platform/deploy/db/todo_unsnooze_roles.sql` (wired into `apply-roles.sh`
after `todo_roles.sql`, and into the integration TestMain):

| Object | Rights |
|---|---|
| `edify_todo_unsnooze_owner` (NOLOGIN, NOINHERIT, member of nothing, nobody a member of it) | DELETE on `command_center_todo_snooze`; SELECT `(user_id, todo_id)` (what the filter reads); nothing else anywhere |
| schema `gateway_todos` | owned by that role; no PUBLIC rights; USAGE to `edify_todos_rw` |
| `gateway_todos.unsnooze(varchar, varchar) RETURNS integer` | SECURITY DEFINER, `search_path = pg_catalog, pg_temp`; returns 0 for a NULL/empty person or NULL To-Do; deletes `WHERE user_id = $1 AND todo_id = $2` (the unique constraint `todo_snooze_one_per_item` makes that at most one row; more than one raises); EXECUTE to `edify_todos_rw` only, revoked from PUBLIC |

The gateway (`edify_gateway`, a member of `edify_todos_rw`) still holds no
DELETE: `TestGatewayRoleCanNeitherWriteNorReadSecrets`'s "undo a snooze for
someone" (`DELETE FROM command_center_todo_snooze`) still refuses.

## 63.3 The rules

| Rule | Where it lives | In Go |
|---|---|---|
| Who may undo: the same door as Snooze (Today's page permission, partners per person, acting, must-change-password, inactive: handed on) | `require_page_permission("today")` | `Takes` (doc 50's `doors`) |
| The delete: the person's row for the posted id, whole | `today_actions.unsnooze` | `Service.Unsnooze` → `gateway_todos.unsnooze` in one read-write transaction |
| A NUL in the id: the existing undo fails (Postgres refuses it) | psycopg | handed on |
| The answer: the panel drawn again at `/today/panel`, into `[data-dashboard-today]`, `outerHTML`, with `today_section` carried | `today_unsnooze`, `today_panel`, `_include_team` | `Redraw{Path, Retarget, Reswap, Removed}` from `rules.json` `unsnooze` (exported) |

The view's literals were lifted to module constants, no behaviour change:
`TODAY_SECTION_FIELD`, `UNSNOOZE_RETARGET`, `UNSNOOZE_RESWAP`.
`export_todo_snooze_rules` now also writes `unsnooze` (`reverse("frontend:today_panel")`
and those constants); the drift test is unchanged and passes.

Go does not draw the Today panel (that is the Today page's migration); the
undo's answer names the redraw the gateway asks the existing application for.

## 63.4 The proof

Unit: `TestDecideUnsnoozeMatchesTheExistingUndo` (redraw path, section
encoding, empty id, a 140-character id matched whole, refused and
per-person roles, NUL).

Integration (`internal/integration/todo_unsnooze_test.go`, on
`edify_gorn_a21_test`): `TestTodoUnsnoozeRemovesOnlyThatPersonsRowForThatTodo`
(four rows; the undo removes the reader's row for that To-Do only, keeping
the reader's other snooze and two other people's snoozes of the same To-Do;
a repeat removes 0; the Country Director is handed on; a NULL or empty
person removes 0) and `TestTheUnsnoozeFunctionIsNarrow` (security definer,
owner, the owner's only table right is DELETE on the snooze table, its only
column rights SELECT user_id/todo_id, EXECUTE for `edify_todos_rw` and the
gateway, not `edify_gateway_ro`, not `edify_activities_rw`, not PUBLIC).

Shadow: scenario `platform/backend/cmd/shadow/scenarios/unsnooze_todo.json`
(20 steps: snoozes, undos of a real snooze, of the same id again, of an
unknown id, of an empty id, of a 140-character id, a Programme Lead's undo
with `today_section=own`, the Admin and Project Coordinator, the same To-Do
snoozed by IA surviving the CCEO's undo, a CCEO snooze never undone, and the
Country Director and Business Transformation, whom the page refuses).
`cmd/shadow/todoplay` now makes `/today/unsnooze` through `Service.Unsnooze`
on copy B as the gateway role, then reads the redraw from the existing
application (`django_runner.py` gained a step kind `get`) and holds the
panel's words (first 400 characters, full comparison) and target to copy A's.
Copies `edify_shadow_s21_*`, base made by `copies.sh base` and
`apply-roles.sh` on that base only.

Two runs; run 2 is the scenario as committed (run 1 undid every snooze, so the snooze table ended equal to the base and showed nothing; run 2 leaves two survivors).

## 63.5 Results and the one difference

Run 2, last lines exactly as printed:

```
18 of 20 steps made by Go, 2 handed on
0 of 20 steps answered differently
todoplay exit 0
shadow exit 1
366 tables, 4 changed by the runs
  user                                     DIFFERS: 5 rows only in a, 5 only in b
1 of 4 changed tables differ
```

Of the 18 steps Go made, 10 are undos (Go removed the row; the panel was then
read from the existing application) and 8 are snoozes (doc 50's save, set up
for the undos). The 2 handed-on steps are the Country Director and Business
Transformation (the page refuses; their refusal audit rows are the existing
application's on both copies). `command_center_todo_snooze`, `audit_log` and
`domain_event_log` are the same on both copies; both end with exactly the
two survivors (IA's snooze of the To-Do the CCEO undid, and the CCEO's kept
snooze). `verify_chain(full=True)` on copy B: `{'ok': True, 'brokenAt':
None, 'checkedRows': 22472, 'fromSeq': None}`.

**The one difference is the person's presence stamp on `user`**, and only
that: every user row is equal on both copies apart from `last_seen_action`,
`last_seen_path` and the run's own time stamps (checked column by column).

- Four people whose last step was an undo read `POST /today/unsnooze` on A and
  `GET /today/panel` on B: the existing application stamps the request it
  answers, and in Go's world that request is the redraw.
- IA's last step was a Snooze. Go's Snooze (doc 50) stamps nothing, so B keeps
  IA's earlier `last_seen_path` (`/dashboard`) and A reads `POST /today/snooze`.
  This was already true of doc 50's save; its scenario hid it by ending every
  person's run with a handed-on step. Not fixed here.

What the stamp feeds (the Staff Activity Log and online lists read "last
seen") is the coordinator's call: accept the redraw's stamp, have the gateway
stamp the save it made (a narrow write of `last_seen_action/path/at`), or
leave the undo's redraw stamp as it is. Run 1 showed the same single
difference (`user`: 5 rows each side, the same columns).

## 63.6 What is left

- Wiring: nothing calls either Go save yet (the app's feed carries no Today
  Snooze/Undo; only `hx-get` buttons become actions), so no contract RPC and
  no `EDIFY_GO_SAVES` switch.
- The redraw's presence stamp (63.5) needs the coordinator's call.
- Production needs the owner's approval of the new role, schema and function
  at cutover.
