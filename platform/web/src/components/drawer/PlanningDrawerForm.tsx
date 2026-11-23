'use client';

/*
 * A school's Schedule visit or Assign to Partner form, inside the drawer
 * host's dialog: the form Go answers for this reader, its script's rules
 * (planningLogic), and a save through Go. A refused save says why at the top
 * and keeps what was entered.
 */
import { fromJson } from '@bufbuild/protobuf';
import { useEffect, useRef, useState } from 'react';

import { loadPlanningDrawer, loadTrainingCapacity, savePlanningDrawer } from '@/app/(app)/actions/planningDrawer';
import type { PlanningKind, TrainingCapacity } from '@/app/(app)/actions/planningDrawer';
import { PlanningDrawerSchema } from '@/gen/edify/screens/v1/planning_drawer_pb';
import type { PlanningDrawer } from '@/gen/edify/screens/v1/planning_drawer_pb';
import { assignValues, initialState, missingField, scheduleBlocked, scheduleParts, scheduleValues } from '@/lib/planningLogic';
import type { PlanningState, RequiredField } from '@/lib/planningLogic';

import { Note } from './drawerParts';
import { AssignFields, ScheduleFields } from './PlanningFields';

const LOADING_TITLES: Readonly<Record<PlanningKind, string>> = { schedule: 'Schedule', assign: 'Assign to Partner' };
const TRAINING_PURPOSES = ['in_school_training', 'in_school_training_ssa'];

interface PlanningDrawerFormProps {
  readonly school: string;
  readonly kind: PlanningKind;
  readonly onRequestClose: () => void;
  readonly onDirty: () => void;
  readonly onSaved: (message: string, redirect: string) => void;
  /** Go cannot answer this drawer here. */
  readonly onNotHere: () => void;
}

export function PlanningDrawerForm({ school, kind, onRequestClose, onDirty, onSaved, onNotHere }: PlanningDrawerFormProps) {
  const [drawer, setDrawer] = useState<PlanningDrawer | null>(null);
  const [state, setState] = useState<PlanningState | null>(null);
  const [capacity, setCapacity] = useState<TrainingCapacity | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState<RequiredField | ''>('');
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let isCurrent = true;
    loadPlanningDrawer(school, kind)
      .then((answer) => {
        if (!isCurrent) return;
        if (answer.drawer) {
          const drawn = fromJson(PlanningDrawerSchema, answer.drawer);
          setDrawer(drawn);
          setState(initialState(drawn));
        } else if (answer.notHere) {
          onNotHere();
        } else {
          setError(answer.refusal || 'This action could not be opened.');
        }
      })
      .catch(() => isCurrent && setError('This action could not be opened. Please try again.'));
    return () => {
      isCurrent = false;
    };
  }, [school, kind, onNotHere]);

  // Read again whenever the training or the date changes, and only for a training.
  const purpose = state?.purpose ?? '';
  const training = state?.training ?? '';
  const date = state?.date ?? '';
  const schoolCode = drawer?.hidden.school_id ?? '';
  const asksCapacity = kind === 'schedule' && TRAINING_PURPOSES.includes(purpose) && training !== '';
  useEffect(() => {
    if (!asksCapacity) return undefined;
    let isCurrent = true;
    loadTrainingCapacity(training, date, schoolCode)
      .then((answer) => {
        if (isCurrent) setCapacity(answer);
      })
      .catch(() => undefined); // a failed read is dropped: the save counts again
    return () => {
      isCurrent = false;
      setCapacity(null);
    };
  }, [asksCapacity, date, schoolCode, training]);

  const change = (next: PlanningState) => {
    onDirty();
    setMissing('');
    setState(next);
  };

  const parts = drawer && state && kind === 'schedule' ? scheduleParts(drawer, state, capacity ?? undefined) : undefined;

  const save = async () => {
    if (!drawer || !state || busy) return;
    setError('');
    const empty = missingField(drawer, state, parts);
    setMissing(empty);
    if (empty) return;
    setBusy(true);
    try {
      const answer = await savePlanningDrawer(school, kind, parts ? scheduleValues(drawer, state, parts) : assignValues(state));
      if (answer.saved) {
        onSaved(answer.message || 'Saved.', answer.redirect);
        return;
      }
      setError(answer.error || 'This could not be saved.');
    } catch {
      setError('This could not be saved. Nothing was changed. Please try again.');
    } finally {
      setBusy(false);
    }
    body.current?.scrollTo({ top: 0 });
  };

  return (
    <form
      method="dialog"
      noValidate
      className="flex max-h-[min(88dvh,48rem)] flex-col"
      data-planning-drawer={kind}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <header className="flex items-start justify-between gap-3 border-b border-[var(--edify-border)] px-5 py-3">
        <h2 id="edify-drawer-title" className="min-w-0 text-[length:var(--edify-text-title-size)] font-bold leading-tight">{drawer?.title ?? LOADING_TITLES[kind]}</h2>
        <button type="button" aria-label="Close" onClick={onRequestClose} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </header>
      <div ref={body} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" tabIndex={-1}>
        {error ? <Note tone="danger" text={error} /> : null}
        {drawer ? <p className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">Fields marked * are required.</p> : null}
        {drawer && state ? (
          parts ? (
            <ScheduleFields drawer={drawer} state={state} parts={parts} capacity={capacity} onChange={change} onCancel={onRequestClose} missing={missing} />
          ) : (
            <AssignFields drawer={drawer} state={state} onChange={change} missing={missing} />
          )
        ) : !error ? (
          <div role="status" className="h-24 animate-pulse rounded-[var(--radius-control)] bg-[var(--edify-surface-muted)]"><span className="sr-only">Loading</span></div>
        ) : null}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-[var(--edify-border)] px-5 py-3">
        <button type="button" onClick={onRequestClose} className="edify-action-button secondary h-10 px-4">{drawer?.cancelLabel || 'Close'}</button>
        {drawer ? (
          <button type="submit" disabled={busy || (parts ? scheduleBlocked(parts) : false)} aria-busy={busy} className="edify-action-button primary h-10 px-4 disabled:opacity-60">
            {busy ? 'Saving…' : drawer.submitLabel}
          </button>
        ) : null}
      </footer>
    </form>
  );
}
