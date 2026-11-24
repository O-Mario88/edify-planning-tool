'use client';

/*
 * The web's drawer: any action a page marks as a drawer (Edit Details, Assign
 * to Partner, Add to Project, Close School, a row's menu) opens here, over
 * the page, from the gateway's form. Who may open it, its fields, its rules
 * and its save are all the gateway's; this draws them and sends them back.
 * An action link carries its drawer in its address (`#drawer=<path>`), so it
 * stays a real link. The dialog is the browser's own, in the top layer.
 */
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import { loadDrawer, loadDrawerOptions, submitDrawer } from '@/app/(app)/actions/drawer';
import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';
import { choicesFor, clearedBy, drawerLinksOf, initialValues, isShown, missingField, planningDrawerOf, ticked, valuesToSend, withHiddenReset, withTicked } from '@/lib/drawerLogic';
import type { DrawerFieldJson, DrawerItemJson, DrawerJson, DrawerLinkJson, Reloaded, Values } from '@/lib/drawerLogic';
import { drawerFromHash, withDrawer } from '@/lib/feedPage';

import { CONTROL, Note } from './drawerParts';
import { PlanningDrawerForm } from './PlanningDrawerForm';

function Facts({ facts }: { facts: readonly { label?: string; value?: string }[] }) {
  return (
    <dl className="divide-y divide-[var(--edify-border)] rounded-[var(--radius-control)] border border-[var(--edify-border)]">
      {facts.map((fact, index) => (
        <div key={index} className="flex items-baseline justify-between gap-3 px-3 py-1.5 text-[length:var(--edify-text-label-size)]">
          <dt className="text-[var(--edify-text-muted)]">{fact.label}</dt>
          <dd className="text-right font-semibold text-[var(--edify-text)]">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The kinds of file evidence accepts (apps.evidence.validation), as the existing drawers offer them. */
const FILE_ACCEPT = 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv';

/**
 * A file field: the chosen file goes to the gateway at once, is checked and
 * kept there, and the field's value becomes the kept file's id, which the
 * drawer's save sends. A refused file says why, and the field stays empty.
 */
function FileControl({ id, described, required, disabled, onStaged }: {
  readonly id: string; readonly described?: string; readonly required?: boolean; readonly disabled?: boolean;
  readonly onStaged: (stagedId: string) => void;
}) {
  const [state, setState] = useState<{ busy: boolean; name: string; error: string }>({ busy: false, name: '', error: '' });
  const choose = async (file: File | undefined) => {
    onStaged('');
    if (!file) {
      setState({ busy: false, name: '', error: '' });
      return;
    }
    setState({ busy: true, name: file.name, error: '' });
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('/api/files/stage', { method: 'POST', body: form });
      const answer = (await res.json().catch(() => ({}))) as { id?: string; error?: string };
      if (!res.ok || !answer.id) {
        setState({ busy: false, name: '', error: answer.error || 'The file could not be kept. Try again.' });
        return;
      }
      onStaged(answer.id);
      setState({ busy: false, name: file.name, error: '' });
    } catch {
      setState({ busy: false, name: '', error: 'The file could not be sent. Check your connection and try again.' });
    }
  };
  return (
    <div className="space-y-1">
      <input id={id} type="file" accept={FILE_ACCEPT} required={required} disabled={disabled || state.busy} aria-describedby={described}
        className={CONTROL} onChange={(event) => void choose(event.target.files?.[0])} />
      {state.busy ? <p className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">Sending {state.name}…</p> : null}
      {state.error ? <p role="alert" className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-danger,#b42318)]">{state.error}</p> : null}
    </div>
  );
}

interface FieldProps {
  readonly field: DrawerFieldJson;
  readonly values: Values;
  readonly reloaded: Reloaded;
  readonly onChange: (field: DrawerFieldJson, value: string) => void;
}

function FieldControl({ field, values, reloaded, onChange }: FieldProps) {
  const name = field.name ?? '';
  const value = values[name] ?? '';
  const id = `drawer-field-${name}`;
  const described = field.error || field.help ? `${id}-help` : undefined;
  const common = { id, name, disabled: field.readOnly, required: field.required, 'aria-describedby': described, 'aria-invalid': field.error ? true : undefined };
  const choices = choicesFor(field, values, reloaded);
  switch (field.kind) {
    case 'textarea':
      return <textarea {...common} rows={3} className={CONTROL} value={value} placeholder={field.placeholder} onChange={(event) => onChange(field, event.target.value)} />;
    case 'select':
      return (
        <select {...common} className={CONTROL} value={value} onChange={(event) => onChange(field, event.target.value)}>
          {choices.map((choice, index) => (
            <option key={`${choice.value}-${index}`} value={choice.value ?? ''} disabled={choice.disabled}>
              {choice.label || choice.value}
            </option>
          ))}
        </select>
      );
    case 'date':
      return <EdifyDatePicker id={id} label={field.label || undefined} value={value} min={field.minDate || undefined} max={field.maxDate || undefined} required={field.required} disabled={field.readOnly} placeholder={field.placeholder || 'Select a date'} onChange={(iso) => onChange(field, iso)} />;
    case 'radio':
      return (
        <div role="radiogroup" aria-labelledby={`${id}-label`} className="space-y-1">
          {choices.map((choice) => (
            <label key={choice.value} className="flex items-start gap-2 text-[length:var(--edify-text-body-size)]">
              <input type="radio" name={name} value={choice.value ?? ''} checked={value === choice.value} disabled={choice.disabled || field.readOnly} onChange={() => onChange(field, choice.value ?? '')} className="mt-1" />
              <span>{choice.label}{choice.detail ? <span className="block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{choice.detail}</span> : null}</span>
            </label>
          ))}
        </div>
      );
    case 'checkbox':
      return (
        <label className="flex items-center gap-2 text-[length:var(--edify-text-body-size)]">
          <input {...common} type="checkbox" checked={value === 'on' || value === 'true' || value === '1'} onChange={(event) => onChange(field, event.target.checked ? 'on' : '')} />
          <span>{field.placeholder || field.label}</span>
        </label>
      );
    case 'checklist': {
      const on = ticked(value);
      return (
        <div className="max-h-56 space-y-1 overflow-y-auto rounded-[var(--radius-control)] border border-[var(--edify-border)] p-2" tabIndex={0} role="group" aria-labelledby={`${id}-label`}>
          {choices.map((choice) => (
            <label key={choice.value} className="flex items-start gap-2 text-[length:var(--edify-text-label-size)]">
              <input type="checkbox" checked={on.includes(choice.value ?? '')} disabled={choice.disabled || field.readOnly} onChange={(event) => onChange(field, withTicked(value, choices, choice.value ?? '', event.target.checked))} className="mt-0.5" />
              <span>{choice.label}{choice.detail ? <span className="block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{choice.detail}</span> : null}</span>
            </label>
          ))}
        </div>
      );
    }
    case 'file':
      return <FileControl id={id} described={described} required={field.required} disabled={field.readOnly} onStaged={(staged) => onChange(field, staged)} />;
    case 'hidden':
      return null;
    default:
      return <input {...common} type={field.kind === 'number' || field.kind === 'tel' || field.kind === 'email' ? field.kind : 'text'} step={field.kind === 'number' ? 'any' : undefined} className={CONTROL} value={value} placeholder={field.placeholder} onChange={(event) => onChange(field, event.target.value)} />;
  }
}

/** A drawer's choices that lead to another drawer. One without an address is shown, and cannot be taken. */
function DrawerLinks({ links }: { links: readonly DrawerLinkJson[] }) {
  const words = (link: DrawerLinkJson) => (
    <>
      <span className="block text-[length:var(--edify-text-label-size)] font-semibold">{link.text}</span>
      {link.caption ? <span className="mt-0.5 block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{link.caption}</span> : null}
    </>
  );
  const box = 'block rounded-[var(--radius-control)] border border-[var(--edify-border)] p-3';
  return (
    <div className="grid gap-2">
      {links.map((link) =>
        link.href ? (
          <a key={`${link.text}-${link.caption}`} href={withDrawer('', link.href)} className={`${box} text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]`}>
            {words(link)}
          </a>
        ) : (
          <div key={`${link.text}-${link.caption}`} aria-disabled="true" className={`${box} text-[var(--edify-text-muted)]`}>
            {words(link)}
          </div>
        ),
      )}
    </div>
  );
}

function Item({ item, values, reloaded, onChange }: { item: DrawerItemJson } & Omit<FieldProps, 'field'>) {
  const links = drawerLinksOf(item);
  if (links.length > 0) return <DrawerLinks links={links} />;
  if (item.note) return <Note tone={item.note.tone} text={item.note.text ?? ''} />;
  if (item.heading) return <h3 className="pt-1 text-[length:var(--edify-text-label-size)] font-bold text-[var(--edify-text)]">{item.heading}</h3>;
  if (item.text) return <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{item.text}</p>;
  if (item.facts?.facts?.length) return <Facts facts={item.facts.facts} />;
  if (item.lines?.facts?.length) return <Facts facts={item.lines.facts} />;
  const field = item.field;
  if (!field || !isShown(field.showWhen, values) || field.kind === 'hidden') return null;
  const id = `drawer-field-${field.name}`;
  return (
    <div className="space-y-1">
      {field.kind === 'checkbox' ? null : (
        <label id={`${id}-label`} htmlFor={id} className="block text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]">
          {field.label}{field.required ? <span className="text-[var(--edify-danger-text,inherit)]"> *</span> : null}
        </label>
      )}
      <FieldControl field={field} values={values} reloaded={reloaded} onChange={onChange} />
      {field.error ? <p id={`${id}-help`} className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-danger-text,inherit)]">{field.error}</p> : field.help ? <p id={`${id}-help`} className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{field.help}</p> : null}
    </div>
  );
}

/** One drawer item as the drawer draws it, for a form a page shows itself (components/page/PageFormInline). */
export const DrawerFormItem = Item;

interface Open {
  readonly path: string;
  /** The page behind the action on the existing web, when there is one to fall back to. */
  readonly fallback: string;
}

export function DrawerHost() {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [drawer, setDrawer] = useState<DrawerJson | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [reloaded, setReloaded] = useState<Reloaded>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState('');

  const close = useCallback(() => {
    dialog.current?.close();
    setOpen(null);
    setDrawer(null);
    setError('');
    setDirty(false);
    setReloaded({});
    opener.current?.focus();
  }, []);

  const requestClose = useCallback(() => {
    if (dirty && !window.confirm('Discard the changes you have typed?')) return;
    close();
  }, [close, dirty]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const link = (event.target as Element | null)?.closest?.('a[href*="#drawer="]') as HTMLAnchorElement | null;
      if (!link) return;
      const target = drawerFromHash(link.getAttribute('href') ?? '');
      if (!target) return;
      event.preventDefault();
      opener.current = link;
      setSaved('');
      setError('');
      setDrawer(null);
      setOpen(target);
      if (!dialog.current?.open) dialog.current?.showModal();
      // A planning drawer's form loads itself.
      if (planningDrawerOf(target.path)) return;
      loadDrawer(target.path)
        .then((answer) => {
          if (answer.drawer) {
            setDrawer(answer.drawer);
            setValues(initialValues(answer.drawer));
          } else if (answer.notHere && target.fallback) {
            window.location.assign(target.fallback);
          } else {
            setError(answer.notHere ? 'This action is not available here yet.' : answer.refusal || 'This action could not be opened.');
          }
        })
        .catch(() => setError('This action could not be opened. Please try again.'));
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  const change = (field: DrawerFieldJson, value: string) => {
    if (!drawer) return;
    setDirty(true);
    const cleared = clearedBy(drawer, field.name ?? '');
    setValues((current) => withHiddenReset(drawer, { ...current, [field.name ?? '']: value, ...Object.fromEntries(cleared.map((name) => [name, ''])) }));
    if (field.reloadsPath && field.reloadsTarget) {
      const target = field.reloadsTarget;
      loadDrawerOptions(field.reloadsPath, field.name ?? '', value)
        .then((options) => setReloaded((current) => ({ ...current, [target]: options })))
        .catch(() => setError('The choices could not be loaded. Please try again.'));
    }
  };

  const save = async () => {
    if (!drawer || !open || busy) return;
    const missing = missingField(drawer, values);
    if (missing) {
      setError(`${missing} is required.`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const answer = await submitDrawer(open.path, valuesToSend(drawer, values));
      if (answer.saved) {
        close();
        setSaved(answer.message || 'Saved.');
        if (answer.redirect) router.push(answer.redirect);
        else router.refresh();
        return;
      }
      if (answer.drawer) {
        setDrawer(answer.drawer);
        setValues((current) => ({ ...initialValues(answer.drawer as DrawerJson), ...current }));
      }
      setError(answer.error || 'Check the highlighted fields.');
    } catch {
      setError('This could not be saved. Nothing was changed. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const planning = open ? planningDrawerOf(open.path) : null;
  const markDirty = useCallback(() => setDirty(true), []);
  const planningNotHere = useCallback(() => {
    if (open?.fallback) window.location.assign(open.fallback);
    else {
      close();
      setSaved('This action is not available here yet.');
    }
  }, [close, open]);
  const planningSaved = (message: string, redirect: string) => {
    close();
    setSaved(message);
    if (redirect) router.push(redirect);
    else router.refresh();
  };

  return (
    <>
      <dialog
        ref={dialog}
        aria-labelledby="edify-drawer-title"
        onCancel={(event) => {
          event.preventDefault();
          requestClose();
        }}
        onClick={(event) => {
          if (event.target === dialog.current) requestClose();
        }}
        className="edify-action-drawer m-auto w-[min(36rem,calc(100vw-1.5rem))] max-h-[min(88dvh,48rem)] overflow-hidden rounded-[var(--edify-drawer-radius,12px)] border border-[var(--edify-border)] bg-[var(--edify-surface-raised)] p-0 text-[var(--edify-text)] shadow-[var(--edify-shadow-lg)] backdrop:bg-[var(--drawer-backdrop-color,rgba(15,23,42,.45))] max-sm:mb-0 max-sm:w-full max-sm:max-w-full max-sm:rounded-b-none"
      >
        {planning ? (
          <PlanningDrawerForm
            key={open?.path}
            school={planning.school}
            kind={planning.kind}
            onRequestClose={requestClose}
            onDirty={markDirty}
            onSaved={planningSaved}
            onNotHere={planningNotHere}
          />
        ) : (
        <form
          method="dialog"
          className="flex max-h-[min(88dvh,48rem)] flex-col"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <header className="flex items-start justify-between gap-3 border-b border-[var(--edify-border)] px-5 py-3">
            <div className="min-w-0">
              <h2 id="edify-drawer-title" className="text-[length:var(--edify-text-title-size)] font-bold leading-tight">{drawer?.title || (error ? 'Action unavailable' : 'Loading…')}</h2>
              {drawer?.subtitle ? <p className="mt-0.5 text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{drawer.subtitle}</p> : null}
            </div>
            <button type="button" aria-label="Close" onClick={requestClose} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </header>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" tabIndex={-1}>
            {error ? <Note tone="danger" text={error} /> : null}
            {drawer?.hasRequired ? <p className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">Fields marked * are required.</p> : null}
            {drawer
              ? (drawer.items ?? []).map((item, index) => (isShown(item.showWhen, values) ? <Item key={index} item={item} values={values} reloaded={reloaded} onChange={change} /> : null))
              : !error ? <div role="status" className="h-24 animate-pulse rounded-[var(--radius-control)] bg-[var(--edify-surface-muted)]"><span className="sr-only">Loading</span></div> : null}
          </div>
          <footer className="flex flex-wrap justify-end gap-2 border-t border-[var(--edify-border)] px-5 py-3">
            <button type="button" onClick={requestClose} className="edify-action-button secondary h-10 px-4">{drawer?.cancelLabel || 'Close'}</button>
            {drawer?.canSubmit ? (
              <button type="submit" disabled={busy} aria-busy={busy} className="edify-action-button primary h-10 px-4 disabled:opacity-60">{busy ? 'Saving…' : drawer.submitLabel || 'Save'}</button>
            ) : null}
          </footer>
        </form>
        )}
      </dialog>
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex justify-center px-4 lg:bottom-6">
        {saved ? (
          <button type="button" onClick={() => setSaved('')} className="pointer-events-auto rounded-full bg-[var(--edify-text)] px-4 py-2 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-surface-raised)] shadow-[var(--edify-shadow-lg)]">
            {saved}
          </button>
        ) : null}
      </div>
    </>
  );
}
