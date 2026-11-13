-- Snoozing a To-Do from Today, a Go save (docs/migration/50). Applied by
-- apply-roles.sh to a development, test or staging database; never to
-- production without the owner's approval at cutover.
--
-- Roles and grants only. Nothing here creates, alters or drops a table,
-- column, index or constraint, and no row is read or written.
--
--   edify_todos_rw  NOLOGIN, granted to edify_gateway. Exactly what one
--                   snooze writes (apps.command_center.today_actions.snooze:
--                   TodoSnooze.objects.update_or_create on (user_id,
--                   todo_id)): a new row, or the person's existing row's
--                   `until`, `title` and `updated_at`. No DELETE: undoing a
--                   snooze (today_unsnooze deletes the row) stays the
--                   existing application's. The row's id and key are
--                   readable, and its UPDATE right takes the row lock
--                   update_or_create's select_for_update takes.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): the save opens a read-write transaction on purpose (08 §8.2).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_todos_rw') THEN
    CREATE ROLE edify_todos_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_todos_rw;
GRANT USAGE ON SCHEMA public TO edify_todos_rw;
GRANT edify_todos_rw TO edify_gateway;

GRANT SELECT (id, user_id, todo_id) ON command_center_todo_snooze TO edify_todos_rw;
GRANT INSERT (id, created_at, updated_at, user_id, todo_id, title, until)
  ON command_center_todo_snooze TO edify_todos_rw;
GRANT UPDATE (updated_at, title, until) ON command_center_todo_snooze TO edify_todos_rw;
