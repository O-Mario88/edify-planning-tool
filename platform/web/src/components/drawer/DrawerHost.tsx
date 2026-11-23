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
import { choicesFor, clearedBy, initialValues, isShown, missingField, ticked, valuesToSend, withTicked } from '@/lib/drawerLogic';
import type { DrawerFieldJson, DrawerItemJson, DrawerJson, Reloaded, Values } from '@/lib/drawerLogic';
import { drawerFromHash } from '@/lib/feedPage';

const CONTROL =
  'w-full rounded-[var(--radius-control)] border border-[var(--edify-border-strong)] bg-[var(--edify-surface-raised)] px-3 py-2 text-[length:var(--edify-text-body-size)] text-[var(--edify-text)] outline-none focus:border-[var(--edify-accent)] focus:ring-2 focus:ring-[var(--edify-accent-soft,transparent)] disabled:opacity-60';

const NOTE_TONES: Readonly<Record<string, string>> = {
  danger: 'border-[var(--edify-danger-border,var(--edify-border))] bg-[var(--edify-danger-soft,var(--edify-surface-muted))] text-[var(--edify-danger-text,var(--edify-text))]',
  warning: 'border-[var(--edify-warning-border,var(--edify-border))] bg-[var(--edify-warning-soft,var(--edify-surface-muted))] text-[var(--edify-warning-text,var(--edify-text))]',
  success: 'border-[var(--edify-success-border,var(--edify-border))] bg-[var(--edify-success-soft,var(--edify-surface-muted))] text-[var(--edify-success-text,var(--edify-text))]',
  info: 'border-[var(--edify-border)] bg-[var(--edify-surface-muted)] text-[var(--edify-text)]',
};

function Note({ tone = 'info', text }: { tone?: string; text: string }) {
  return (
    <p role={tone === 'danger' ? 'alert' : undefined} className={`rounded-[var(--radius-control)] border px-3 py-2 text-[length:var(--edify-text-label-size)] ${NOTE_TONES[tone] ?? NOTE_TONES.info}`}>
      {text}
    </p>
  );
}

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
      return <EdifyDatePicker id={id} value={value} min={field.minDate || undefined} max={field.maxDate || undefined} required={field.required} disabled={field.readOnly} placeholder={field.placeholder || 'Select a date'} onChange={(iso) => onChange(field, iso)} />;
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
    case 'hidden':
      return null;
    default:
      return <input {...common} type={field.kind === 'number' || field.kind === 'tel' || field.kind === 'email' ? field.kind : 'text'} step={field.kind === 'number' ? 'any' : undefined} className={CONTROL} value={value} placeholder={field.placeholder} onChange={(event) => onChange(field, event.target.value)} />;
  }
}

function Item({ item, values, reloaded, onChange }: { item: DrawerItemJson } & Omit<FieldProps, 'field'>) {
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
      dialog.current?.showModal();
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
    setValues((current) => ({ ...current, [field.name ?? '']: value, ...Object.fromEntries(cleared.map((name) => [name, ''])) }));
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
