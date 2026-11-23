/**
 * What a drawer's form does, for the web's drawer host: which parts are shown
 * for the choices made, which choices a field offers, what a change clears
 * and what a save sends. The same rules as the app's
 * (platform/mobile/src/ui/drawerLogic.ts), over the drawer's JSON form so it
 * can cross from a server action. Pure, so it is tested without a browser.
 */
export type Values = Readonly<Record<string, string>>;

export interface DrawerOptionJson {
  readonly value?: string;
  readonly label?: string;
  readonly group?: string;
  readonly disabled?: boolean;
  readonly detail?: string;
}

export interface DrawerConditionJson {
  readonly field?: string;
  readonly values?: readonly string[];
}

export interface DrawerFieldJson {
  readonly name?: string;
  readonly label?: string;
  readonly kind?: string;
  readonly value?: string;
  readonly required?: boolean;
  readonly help?: string;
  readonly error?: string;
  readonly placeholder?: string;
  readonly readOnly?: boolean;
  readonly options?: readonly DrawerOptionJson[];
  readonly showWhen?: readonly DrawerConditionJson[];
  readonly reloadsPath?: string;
  readonly reloadsTarget?: string;
  readonly groupBy?: string;
  readonly minDate?: string;
  readonly maxDate?: string;
}

export interface DrawerFactJson {
  readonly label?: string;
  readonly value?: string;
}

export interface DrawerItemJson {
  readonly note?: { readonly text?: string; readonly tone?: string };
  readonly heading?: string;
  readonly text?: string;
  readonly facts?: { readonly facts?: readonly DrawerFactJson[] };
  readonly lines?: { readonly facts?: readonly DrawerFactJson[] };
  readonly field?: DrawerFieldJson;
  readonly block?: unknown;
  readonly showWhen?: readonly DrawerConditionJson[];
}

export interface DrawerJson {
  readonly title?: string;
  readonly subtitle?: string;
  readonly hasRequired?: boolean;
  readonly items?: readonly DrawerItemJson[];
  readonly submitLabel?: string;
  readonly cancelLabel?: string;
  readonly canSubmit?: boolean;
}

/** Choices a field's reload brought, by the field they belong to. */
export type Reloaded = Readonly<Record<string, readonly DrawerOptionJson[]>>;

/** Shown when there is no condition, or any condition's field holds one of its values. */
export function isShown(conditions: readonly DrawerConditionJson[] | undefined, values: Values): boolean {
  if (!conditions?.length) return true;
  return conditions.some((condition) => (condition.values ?? ['']).includes(values[condition.field ?? ''] ?? ''));
}

export function fieldsOf(drawer: DrawerJson): DrawerFieldJson[] {
  return (drawer.items ?? []).flatMap((item) => (item.field ? [item.field] : []));
}

export function initialValues(drawer: DrawerJson): Record<string, string> {
  return Object.fromEntries(fieldsOf(drawer).map((field) => [field.name ?? '', field.value ?? '']));
}

/** The values once every field that is now hidden is back to how the form opened, as a drawer's script resets a part it hides. */
export function withHiddenReset(drawer: DrawerJson, values: Values): Record<string, string> {
  const next: Record<string, string> = { ...values };
  const items = drawer.items ?? [];
  for (let pass = 0; pass <= items.length; pass += 1) {
    let changed = false;
    for (const item of items) {
      const field = item.field;
      if (!field?.name || (isShown(item.showWhen, next) && isShown(field.showWhen, next))) continue;
      const opened = field.value ?? '';
      if ((next[field.name] ?? '') !== opened) {
        next[field.name] = opened;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return next;
}

export interface DrawerLinkJson {
  readonly text?: string;
  readonly href?: string;
  readonly caption?: string;
  readonly drawer?: boolean;
}

/** The links a drawer's item offers. One without an address is a choice that cannot be taken. */
export function drawerLinksOf(item: DrawerItemJson): readonly DrawerLinkJson[] {
  const block = item.block as { panel?: { items?: readonly { links?: { links?: readonly DrawerLinkJson[] } }[] } } | undefined;
  return (block?.panel?.items ?? []).flatMap((part) => part.links?.links ?? []);
}

/** The choices a field offers now: reloaded ones first, and only those of the value it is grouped by. */
export function choicesFor(field: DrawerFieldJson, values: Values, reloaded: Reloaded): readonly DrawerOptionJson[] {
  const choices = reloaded[field.name ?? ''] ?? field.options ?? [];
  if (!field.groupBy) return choices;
  const owner = values[field.groupBy] ?? '';
  return choices.filter((choice) => !choice.group || choice.group === owner);
}

/** The fields a change to `name` empties: the one it reloads, and every field tied to that one. */
export function clearedBy(drawer: DrawerJson, name: string): string[] {
  const fields = fieldsOf(drawer);
  const cleared: string[] = [];
  const queue = [name];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    const source = fields.find((field) => field.name === current);
    for (const field of fields) {
      const fieldName = field.name ?? '';
      if ((source?.reloadsTarget === fieldName || field.groupBy === current) && !cleared.includes(fieldName)) {
        cleared.push(fieldName);
        queue.push(fieldName);
      }
    }
  }
  return cleared;
}

/** What a save sends: every shown field's value, as a browser sends no hidden, disabled field. */
export function valuesToSend(drawer: DrawerJson, values: Values): Record<string, string> {
  const sent: Record<string, string> = {};
  for (const item of drawer.items ?? []) {
    const field = item.field;
    if (field?.name && isShown(item.showWhen, values) && isShown(field.showWhen, values)) {
      sent[field.name] = values[field.name] ?? '';
    }
  }
  return sent;
}

/** A checklist's ticked choices, from its value (their values joined by commas). */
export function ticked(value: string): string[] {
  return value.split(',').filter((part) => part !== '');
}

/** A checklist's value with `choice` ticked or unticked, in the order the list shows them. */
export function withTicked(value: string, choices: readonly DrawerOptionJson[], choice: string, isOn: boolean): string {
  const current = new Set(ticked(value));
  if (isOn) current.add(choice);
  else current.delete(choice);
  const order = choices.map((option) => option.value ?? '');
  const shown = order.filter((option) => current.has(option));
  const elsewhere = [...current].filter((option) => !order.includes(option));
  return [...shown, ...elsewhere].join(',');
}

/** The first shown, required field left empty, by its label; '' when the save may go. */
export function missingField(drawer: DrawerJson, values: Values): string {
  for (const item of drawer.items ?? []) {
    const field = item.field;
    if (!field?.name) continue;
    const isAsked = field.required && !field.readOnly && isShown(item.showWhen, values) && isShown(field.showWhen, values);
    if (isAsked && (values[field.name] ?? '').trim() === '') return field.label || field.name;
  }
  return '';
}

/** A drawer path this web may open: its own origin's plain path. */
export function isDrawerPath(path: string): boolean {
  return /^\/[A-Za-z0-9_\-./]*(\?[^#\s]*)?$/.test(path) && !path.startsWith('//') && !path.includes('..') && path.length <= 512;
}

/** Where a save may send the reader: a path on this site. */
export function safeRedirect(redirect: string): string {
  return redirect.startsWith('/') && !redirect.startsWith('//') && !redirect.includes('\\') ? redirect : '';
}

const SCHOOL_DRAWERS: Readonly<Record<string, string>> = { 'edit-drawer': 'edit', 'close-drawer': 'close', 'ssa-entry': 'ssa-entry' };

/** A school's own drawers have their own service (as in the app's school profile). */
export function schoolDrawerOf(path: string): { schoolId: string; kind: string } | null {
  const match = /^\/schools\/([A-Za-z0-9_-]{1,64})\/(edit-drawer|close-drawer|ssa-entry)\/?$/.exec(path.split('?')[0] ?? '');
  const kind = match ? SCHOOL_DRAWERS[match[2] ?? ''] : undefined;
  return match && kind ? { schoolId: match[1] ?? '', kind } : null;
}

/** A planning drawer's school (its School ID or record id) and kind, from the path a Schedule or Assign button opens. */
export function planningDrawerOf(path: string): { school: string; kind: 'schedule' | 'assign' } | null {
  const [route, query = ''] = path.split('?');
  const kind = route === '/planning/schedule-modal' ? 'schedule' : route === '/planning/assign-partner-modal' ? 'assign' : null;
  const school = new URLSearchParams(query).get('school_id') ?? '';
  return kind && school ? { school, kind } : null;
}

/** The school an Add to Project button opens the drawer for. */
export function addToProjectOf(path: string): string | null {
  return /^\/schools\/([A-Za-z0-9_-]{1,64})\/assign-to-project\/?$/.exec(path.split('?')[0] ?? '')?.[1] ?? null;
}

export interface ActionChoiceJson {
  readonly value?: string;
  readonly label?: string;
  readonly disabled?: boolean;
  readonly reason?: string;
}

export interface AddToProjectFormJson {
  readonly refused?: string;
  readonly title?: string;
  readonly projects?: readonly ActionChoiceJson[];
  readonly supportTypes?: readonly ActionChoiceJson[];
  readonly coordinators?: readonly ActionChoiceJson[];
  readonly focusAreas?: readonly ActionChoiceJson[];
  readonly emptyNotice?: string;
  readonly error?: string;
}

/** A select's list: its empty first line, then the choices; one that cannot be taken stays, greyed with its reason. */
function actionOptions(placeholder: string, choices: readonly ActionChoiceJson[] = []): DrawerOptionJson[] {
  return [
    { value: '', label: placeholder },
    ...choices.map((choice) => ({
      value: choice.value ?? '',
      label: choice.reason ? `${choice.label ?? ''} (${choice.reason})` : (choice.label ?? ''),
      disabled: Boolean(choice.disabled || choice.reason),
    })),
  ];
}

/** Add to Project's form, in the drawer host's shape, with the fields and words of the existing drawer. */
export function addToProjectDrawer(form: AddToProjectFormJson): DrawerJson {
  const select = (name: string, label: string, placeholder: string, choices?: readonly ActionChoiceJson[], required = false): DrawerItemJson => ({
    field: { name, label, kind: 'select', value: '', required, options: actionOptions(placeholder, choices) },
  });
  const notes: DrawerItemJson[] = [
    ...(form.emptyNotice ? [{ note: { text: form.emptyNotice, tone: 'info' } }] : []),
    ...(form.error ? [{ note: { text: form.error, tone: 'danger' } }] : []),
  ];
  return {
    title: form.title ?? 'Add to project',
    hasRequired: true,
    submitLabel: 'Assign to project',
    cancelLabel: 'Cancel',
    canSubmit: (form.projects ?? []).some((project) => !project.disabled && !project.reason),
    items: [
      ...notes,
      select('project_id', 'Project', 'Select a project', form.projects, true),
      { field: { name: 'project_type', label: 'Project type', kind: 'text', value: '', placeholder: 'e.g. Curriculum support' } },
      select('participation_type', 'Expected support type', 'Select a support type', form.supportTypes),
      select('coordinator_id', 'Project coordinator', 'Project default', form.coordinators),
      select('support_area', 'Focus area', 'Select a focus area', form.focusAreas),
      { field: { name: 'start_date', label: 'Start date', kind: 'date', value: '' } },
      { field: { name: 'notes', label: 'Notes', kind: 'textarea', value: '' } },
    ],
  };
}
