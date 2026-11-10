/**
 * What a web drawer's own script does, for the native drawer: which parts
 * are shown for the choices made, which choices a field offers, what a
 * change clears, and what a save sends. Pure, so it is tested without a
 * device.
 */
import type { DrawerCondition, DrawerField, DrawerOption, PageDrawer } from '../gen/edify/screens/v1/drawer_pb';

export type Values = Readonly<Record<string, string>>;
/** Choices a field's reload brought, by the field they belong to. */
export type Reloaded = Readonly<Record<string, readonly DrawerOption[]>>;

/** Shown when there is no condition, or any condition's field holds one of its values. */
export function isShown(conditions: readonly DrawerCondition[], values: Values): boolean {
  return (
    conditions.length === 0 ||
    conditions.some((condition) => condition.values.includes(values[condition.field] ?? ''))
  );
}

export function fieldsOf(drawer: PageDrawer): DrawerField[] {
  return drawer.items.flatMap((item) => (item.kind.case === 'field' ? [item.kind.value] : []));
}

export function initialValues(drawer: PageDrawer): Record<string, string> {
  return Object.fromEntries(fieldsOf(drawer).map((field) => [field.name, field.value]));
}

/** The choices a field offers now: reloaded ones first, and only those that
 * belong to the value of the field it is grouped by (a parish's sub-county).
 * A choice with no group (the "Select ..." line) always stays. */
export function choicesFor(field: DrawerField, values: Values, reloaded: Reloaded): readonly DrawerOption[] {
  const choices = reloaded[field.name] ?? field.options;
  if (!field.groupBy) {
    return choices;
  }
  const owner = values[field.groupBy] ?? '';
  return choices.filter((choice) => !choice.group || choice.group === owner);
}

/** The fields a change to `name` empties: the one it reloads, and every
 * field tied to that one, as the web's script empties them. */
export function clearedBy(drawer: PageDrawer, name: string): string[] {
  const fields = fieldsOf(drawer);
  const cleared: string[] = [];
  const queue = [name];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    const source = fields.find((field) => field.name === current);
    const dependants = fields.filter(
      (field) =>
        (source?.reloadsTarget === field.name || field.groupBy === current) && !cleared.includes(field.name),
    );
    for (const field of dependants) {
      cleared.push(field.name);
      queue.push(field.name);
    }
  }
  return cleared;
}

/** What a save sends: every shown field's value. A hidden field is not sent,
 * as a browser does not send a field its script has hidden and disabled. */
export function valuesToSend(drawer: PageDrawer, values: Values): Record<string, string> {
  const sent: Record<string, string> = {};
  for (const item of drawer.items) {
    if (item.kind.case !== 'field') {
      continue;
    }
    const field = item.kind.value;
    if (isShown(item.showWhen, values) && isShown(field.showWhen, values)) {
      sent[field.name] = values[field.name] ?? '';
    }
  }
  return sent;
}
