-- Undoing a To-Do snooze from Today, a Go save (docs/migration/63). The
-- existing undo (apps.command_center.today_actions.unsnooze:
-- TodoSnooze.objects.filter(user_id=..., todo_id=...).delete()) removes the
-- person's own snooze of one To-Do. The coordinator chose a narrow function
-- for it (2026-11-13, the shape of gateway_money.withdraw_unmoved_advances):
-- the gateway holds no DELETE anywhere, and may only ask this function,
-- which removes at most that person's row for that To-Do (the table's
-- unique constraint todo_snooze_one_per_item is on (user_id, todo_id)) and
-- nothing else.
--
-- The function's owner is a NOLOGIN role nobody is a member of, holding only
-- DELETE on command_center_todo_snooze and the SELECT its filter reads.
-- EXECUTE is granted to edify_todos_rw only (todo_roles.sql, applied first).
--
-- Applied after todo_roles.sql (apply-roles.sh, the integration TestMain).
-- Idempotent. A new database object: production needs the owner's approval
-- at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_todo_unsnooze_owner') THEN
    CREATE ROLE edify_todo_unsnooze_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_todo_unsnooze_owner;
GRANT USAGE ON SCHEMA public TO edify_todo_unsnooze_owner;
GRANT SELECT (user_id, todo_id) ON command_center_todo_snooze TO edify_todo_unsnooze_owner;
GRANT DELETE ON command_center_todo_snooze TO edify_todo_unsnooze_owner;

CREATE SCHEMA IF NOT EXISTS gateway_todos AUTHORIZATION edify_todo_unsnooze_owner;
REVOKE ALL ON SCHEMA gateway_todos FROM PUBLIC;

SET ROLE edify_todo_unsnooze_owner;
CREATE OR REPLACE FUNCTION gateway_todos.unsnooze(target_user varchar, target_todo varchar) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  removed integer;
BEGIN
  -- No person, no row: the existing undo is always a signed-in person's.
  IF target_user IS NULL OR target_user = '' OR target_todo IS NULL THEN
    RETURN 0;
  END IF;
  DELETE FROM public.command_center_todo_snooze s
  WHERE s.user_id = target_user
    AND s.todo_id = target_todo;
  GET DIAGNOSTICS removed = ROW_COUNT;
  IF removed > 1 THEN
    RAISE EXCEPTION 'gateway_todos.unsnooze: % rows for one person and To-Do', removed;
  END IF;
  RETURN removed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_todos.unsnooze(varchar, varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_todos TO edify_todos_rw;
GRANT EXECUTE ON FUNCTION gateway_todos.unsnooze(varchar, varchar) TO edify_todos_rw;
