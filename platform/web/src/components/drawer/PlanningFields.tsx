'use client';

/*
 * The fields of a school's Schedule visit and Assign to Partner drawers, in
 * the existing drawers' order. Their rules are planningLogic's; their words
 * are the drawer Go answered (labels, placeholders, captions).
 */
import { useState } from 'react';
import type { ReactNode } from 'react';

import type { TrainingCapacity } from '@/app/(app)/actions/planningDrawer';
import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';
import type { PlanningDrawer, PlanningLeadItem, PlanningTraining } from '@/gen/edify/screens/v1/planning_drawer_pb';
import { withDrawer } from '@/lib/feedPage';
import { changeAssignPartner, changeAssignPurpose, changePurpose, chooseAssignTraining, chooseTraining, lockFor, trainingsFor } from '@/lib/planningLogic';
import type { PlanningState, RequiredField, ScheduleParts } from '@/lib/planningLogic';

import { CONTROL, Note } from './drawerParts';

const SELECT_MISSING = 'Please select an item in the list.';
const TEXT_MISSING = 'Please fill out this field.';

interface FieldProps {
  readonly id: string;
  readonly label: string;
  readonly required?: boolean;
  readonly optional?: boolean;
  readonly help?: string;
  readonly error?: string;
  readonly children: ReactNode;
}

function Field({ id, label, required, optional, help, error, children }: FieldProps) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]">
        {label}
        {required ? <span className="text-[var(--edify-danger-text,inherit)]"> *</span> : null}
        {optional ? <span className="font-normal text-[var(--edify-text-muted)]"> (optional)</span> : null}
      </label>
      {children}
      {error ? <p role="alert" className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-danger-text,inherit)]">{error}</p> : null}
      {help ? <p className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{help}</p> : null}
    </div>
  );
}

interface Choice {
  readonly value: string;
  readonly label: string;
  readonly disabled?: boolean;
}

interface ChoiceFieldProps extends Omit<FieldProps, 'children'> {
  readonly value: string;
  readonly choices: readonly Choice[];
  readonly placeholder: string;
  readonly onChange: (value: string) => void;
}

function ChoiceField({ id, value, choices, placeholder, onChange, ...field }: ChoiceFieldProps) {
  return (
    <Field id={id} {...field}>
      <select id={id} name={id} className={CONTROL} value={value} required={field.required} aria-invalid={field.error ? true : undefined} onChange={(event) => onChange(event.target.value)}>
        {placeholder ? <option value="">{placeholder}</option> : null}
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value} disabled={choice.disabled}>{choice.label}</option>
        ))}
      </select>
    </Field>
  );
}

function ReadOnlyField({ label, text, placeholder, help }: { label: string; text: string; placeholder?: string; help?: string }) {
  return (
    <div className="space-y-1">
      <p className="text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]">{label}</p>
      <p className={`rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-3 py-2 text-[length:var(--edify-text-body-size)] ${text ? 'text-[var(--edify-text)]' : 'text-[var(--edify-text-muted)]'}`}>
        {text || placeholder || '—'}
      </p>
      {help ? <p className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{help}</p> : null}
    </div>
  );
}

function Words({ text, tone }: { text?: string; tone?: 'warning' | 'danger' }) {
  if (!text) return null;
  const colour = tone === 'danger' ? 'text-[var(--edify-danger-text,inherit)]' : tone === 'warning' ? 'text-[var(--edify-warning-text,inherit)]' : 'text-[var(--edify-text-muted)]';
  return <p className={`text-[length:var(--edify-text-micro-size)] ${colour}`}>{text}</p>;
}

function TrainingMeta({ training }: { training: PlanningTraining | undefined }) {
  if (!training) return null;
  return <Words text={`Training category ${training.category} · SSA intervention association ${training.ssaIndicator}`} />;
}

interface FollowUpProps {
  readonly drawer: PlanningDrawer;
  readonly selectId: string;
  readonly source: string;
  readonly onChange: (source: string) => void;
  readonly inheritedHelp?: string;
  readonly error?: string;
}

function FollowUpFields({ drawer, selectId, source, onChange, inheritedHelp, error }: FollowUpProps) {
  const hasTrainings = drawer.followUps.length > 0;
  const chosen = drawer.followUps.find((item) => item.id === source);
  const caption = hasTrainings ? drawer.captions.followUpDone : drawer.followUpRequiresTraining ? drawer.captions.followUpNoneRequired : drawer.captions.followUpNoneOptional;
  return (
    <>
      <div className="space-y-1">
        <ChoiceField
          id={selectId}
          label={drawer.labels[selectId] ?? 'Training followed up'}
          value={source}
          placeholder={drawer.placeholders[selectId] ?? ''}
          choices={drawer.followUps.map((item) => ({ value: item.id, label: item.label }))}
          onChange={onChange}
          required={drawer.followUpRequiresTraining}
          optional={!drawer.followUpRequiresTraining}
          error={error}
        />
        <Words text={caption} tone={!hasTrainings && drawer.followUpRequiresTraining ? 'warning' : undefined} />
      </div>
      {chosen ? <ReadOnlyField label="Focus intervention" text={chosen.interventionLabel} help={inheritedHelp} /> : null}
    </>
  );
}

/** The notes and SSA evidence above Purpose of visit. */
function Lead({ items }: { items: readonly PlanningLeadItem[] }) {
  return (
    <>
      {items.map((item, index) => {
        switch (item.kind.case) {
          case 'heading':
            return <h3 key={index} className="pt-1 text-[length:var(--edify-text-body-size)] font-bold text-[var(--edify-text)]">{item.kind.value}</h3>;
          case 'text':
            return <Words key={index} text={item.kind.value} />;
          case 'note':
            return <Note key={index} tone={item.kind.value.tone} title={item.kind.value.title} text={item.kind.value.text} />;
          case 'line':
            return (
              <p key={index} className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text)]">
                - <span className="text-[var(--edify-danger-text,inherit)]">{item.kind.value.label}</span> <span className="font-semibold">{item.kind.value.value}</span>
              </p>
            );
          default:
            return null;
        }
      })}
    </>
  );
}

function ExistingPlans({ drawer, onFollowUp, onCancel }: { drawer: PlanningDrawer; onFollowUp: () => void; onCancel: () => void }) {
  const [isShown, setIsShown] = useState(true);
  const [isListOpen, setIsListOpen] = useState(false);
  const existing = drawer.existingPlans;
  if (!existing || !isShown) return null;
  const buttons = existing.buttons;
  const button = 'edify-action-button secondary h-9 px-3';
  return (
    <Note tone="warning" title={existing.note?.title} text={existing.note?.text ?? ''}>
      {isListOpen ? (
        <ul className="space-y-0.5">
          {existing.plans.map((plan) => (
            <li key={plan.label} className="flex justify-between gap-3"><span>{plan.label}</span><span className="font-semibold">{plan.status}</span></li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap gap-2 pt-1">
        <button type="button" className={button} onClick={() => setIsListOpen(!isListOpen)}>{buttons.view ?? 'View Existing Plans'}</button>
        <button type="button" className={button} onClick={() => setIsShown(false)}>{buttons.continue ?? 'Continue Planning'}</button>
        <button type="button" className={button} onClick={() => { onFollowUp(); setIsShown(false); }}>{buttons['follow-up'] ?? 'Plan as Follow-Up'}</button>
        <button type="button" className={button} onClick={onCancel}>{buttons.cancel ?? 'Cancel'}</button>
      </div>
    </Note>
  );
}

function Ceiling({ parts, capacity }: { parts: ScheduleParts; capacity: TrainingCapacity | null }) {
  if (!parts.selected || !capacity?.fy) return null;
  const counter = capacity.managed
    ? `Training ceiling ${capacity.scheduled} / ${capacity.ceiling ?? ''} schools covered for this training${capacity.staffName ? ` by ${capacity.staffName}` : ''} in FY ${capacity.fy}.`
    : `${capacity.scheduled} schools covered for this training in FY ${capacity.fy}. No training ceiling is set.`;
  return (
    <>
      <Words text={counter} />
      {parts.trainingCeilingFull ? (
        <Note tone="warning" text={`You have reached the training ceiling and cannot add any more schools to this training in FY ${capacity.fy}. Choose another training, or ask your Programme Lead to raise the ceiling.`} />
      ) : null}
    </>
  );
}

interface ScheduleFieldsProps {
  readonly drawer: PlanningDrawer;
  readonly state: PlanningState;
  readonly parts: ScheduleParts;
  readonly capacity: TrainingCapacity | null;
  readonly onChange: (next: PlanningState) => void;
  readonly onCancel: () => void;
  readonly missing: RequiredField | '';
}

export function ScheduleFields({ drawer, state, parts, capacity, onChange, onCancel, missing }: ScheduleFieldsProps) {
  const selectError = (field: RequiredField) => (missing === field ? SELECT_MISSING : undefined);
  const { labels, placeholders, captions } = drawer;
  const held = new Set(parts.heldTrainings);
  const dateError = missing === 'date' ? (state.date ? 'Please enter a valid date.' : TEXT_MISSING) : parts.followUpBlocked ? captions.dateYearUsed : undefined;
  const first = drawer.facilitators[0];
  return (
    <>
      <Lead items={drawer.lead} />
      <ExistingPlans drawer={drawer} onFollowUp={() => onChange(changePurpose(drawer, state, 'training_follow_up'))} onCancel={onCancel} />
      <div className="space-y-1">
        <ChoiceField
          id="purpose_of_visit"
          label={labels.purpose_of_visit ?? 'Purpose of visit'}
          value={state.purpose}
          placeholder={placeholders.purpose_of_visit ?? ''}
          choices={drawer.purposes.map((purpose) => ({ value: purpose.value, label: purpose.label, disabled: purpose.disabled || Boolean(lockFor(drawer, purpose.value, state.date)) }))}
          onChange={(purpose) => onChange(changePurpose(drawer, state, purpose))}
          required
          error={selectError('purpose')}
        />
        {drawer.purposeNotes.map((note) => <Words key={note} text={note} tone="warning" />)}
        {captions.lockTail && parts.visitLockReasons.length > 0 ? <Words text={`${parts.visitLockReasons.join(' ')} ${captions.lockTail}`} tone="warning" /> : null}
        <Words text={parts.unavailableReason} tone="danger" />
      </div>
      {parts.showTrainingPicker ? (
        <div className="space-y-1">
          <ChoiceField
            id="training_activity_id"
            label={labels.training_activity_id ?? 'Training'}
            value={state.training}
            placeholder={placeholders.training_activity_id ?? ''}
            choices={trainingsFor(drawer, state).map((training) => ({ value: training.id, label: training.label, disabled: held.has(training.id) }))}
            onChange={(training) => onChange(chooseTraining(drawer, state, training))}
            required
            error={selectError('training')}
          />
          {parts.trainingLockReason ? <Note tone="warning" text={`Only ${parts.universalTrainingNames} can still be scheduled: it is on top of the school’s own training for the year.`} /> : null}
          <TrainingMeta training={parts.selected} />
          <Words text={captions.trainingHelp} />
        </div>
      ) : null}
      {parts.showLinkedIntervention ? (
        <ReadOnlyField label={labels['training-ssa-label'] ?? 'SSA intervention'} text={parts.selected?.ssaInterventionLabel ?? ''} placeholder="Filled in from the training" help={captions.linkedIntervention} />
      ) : null}
      {parts.showTrainingPicker ? <Ceiling parts={parts} capacity={capacity} /> : null}
      {parts.showManualIntervention ? (
        <ChoiceField
          id="focus_intervention"
          label={labels.focus_intervention ?? 'Focus intervention'}
          value={state.intervention}
          placeholder={placeholders.focus_intervention ?? ''}
          choices={drawer.interventions}
          onChange={(intervention) => onChange({ ...state, intervention })}
          help={`Suggested from ${parts.showTrainingPicker && parts.selected?.ssaIntervention ? 'the selected training' : 'the weakest confirmed score'}; change it if the work is aimed elsewhere.`}
        />
      ) : null}
      {parts.ssaDeviation ? (
        <Note tone="warning" text={state.intervention ? (captions.deviationNamed ?? '') : (captions.deviationUnnamed ?? '')}>
          <Field id="ssa_deviation_reason" label={labels.ssa_deviation_reason ?? 'Why this plan departs from the SSA'} optional>
            <textarea id="ssa_deviation_reason" rows={2} maxLength={2000} className={CONTROL} value={state.deviation} onChange={(event) => onChange({ ...state, deviation: event.target.value })} />
          </Field>
        </Note>
      ) : null}
      {captions.ssaStale ? <Note tone="warning" text={captions.ssaStale} /> : null}
      {parts.showSsaDataGathering ? <ReadOnlyField label="Focus intervention" text="Data Gathering" /> : null}
      {parts.showFollowUp ? (
        <FollowUpFields drawer={drawer} selectId="source_activity_id" source={state.source} onChange={(source) => onChange({ ...state, source })} inheritedHelp="Inherited from the selected training." error={selectError('source')} />
      ) : null}
      {parts.showTrainingPicker && first ? (
        <ChoiceField
          id="school_facilitating_partner_id"
          label={labels.school_facilitating_partner_id ?? 'Facilitated by'}
          value={state.facilitator}
          placeholder={first.label}
          choices={drawer.facilitators.slice(1)}
          onChange={(facilitator) => onChange({ ...state, facilitator })}
          help={captions.facilitated}
        />
      ) : null}
      <Words text={captions.monitoredBy} />
      <Field id="scheduled_date" label={labels.scheduled_date ?? 'Scheduled date'} required error={dateError}>
        <EdifyDatePicker id="scheduled_date" value={state.date} required placeholder="Select a date" onChange={(date) => onChange({ ...state, date })} />
      </Field>
      {parts.showParticipants ? (
        <Field id="expected_participants" label={labels.expected_participants ?? 'Planned participants'}>
          <input id="expected_participants" type="number" min={0} inputMode="numeric" className={CONTROL} value={state.participants} onChange={(event) => onChange({ ...state, participants: event.target.value })} />
        </Field>
      ) : null}
      {captions.responsible ? <ReadOnlyField label="Responsible person" text={captions.responsible} help={captions.responsibleHelp} /> : null}
      <Field id="activity_purpose_text" label={labels.activity_purpose_text ?? 'Goal'}>
        <textarea id="activity_purpose_text" rows={2} className={CONTROL} placeholder={captions.goalPlaceholder} value={state.goal} onChange={(event) => onChange({ ...state, goal: event.target.value })} />
      </Field>
      {drawer.hasJustification ? (
        <Field id="visit_justification" label={labels.visit_justification ?? ''} required help={captions.justificationHelp} error={missing === 'justification' ? TEXT_MISSING : undefined}>
          <textarea id="visit_justification" rows={2} required className={CONTROL} placeholder={captions.justificationPlaceholder} value={state.justification} onChange={(event) => onChange({ ...state, justification: event.target.value })} />
        </Field>
      ) : null}
    </>
  );
}

interface AssignFieldsProps {
  readonly drawer: PlanningDrawer;
  readonly state: PlanningState;
  readonly onChange: (next: PlanningState) => void;
  readonly missing: RequiredField | '';
}

export function AssignFields({ drawer, state, onChange, missing }: AssignFieldsProps) {
  const errorFor = (field: RequiredField) => (missing === field ? SELECT_MISSING : undefined);
  const courses = trainingsFor(drawer, state);
  const selected = courses.find((training) => training.id === state.training);
  const { labels, placeholders, captions } = drawer;
  return (
    <>
      <ChoiceField id="partner_id" label={labels.partner_id ?? 'Partner'} value={state.partner} placeholder={placeholders.partner_id ?? ''} choices={drawer.partners} onChange={(partner) => onChange(changeAssignPartner(drawer, state, partner))} required error={errorFor('partner')} />
      <div className="space-y-1">
        <ChoiceField id="purpose_of_visit" label={labels.purpose_of_visit ?? 'Reason for assigning'} value={state.purpose} placeholder={placeholders.purpose_of_visit ?? ''} choices={drawer.purposes} onChange={(purpose) => onChange(changeAssignPurpose(state, purpose))} required error={errorFor('purpose')} />
        {drawer.purposeNotes.map((note) => <Words key={note} text={note} tone="warning" />)}
      </div>
      {drawer.projectHandovers.length > 0 ? (
        <div className="space-y-1">
          <p className="text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]">{captions.handoverTitle}</p>
          <div className="flex flex-wrap gap-2">
            {drawer.projectHandovers.map((route) => (
              <a key={route.path} href={withDrawer('', route.path)} className="edify-action-button secondary h-9 px-3">{route.label}</a>
            ))}
          </div>
          <Words text={captions.handover} />
        </div>
      ) : null}
      {state.purpose === 'in_school_training' ? (
        <div className="space-y-1">
          <ChoiceField id="partner_training_activity" label={labels.partner_training_activity ?? 'Training'} value={state.training} placeholder={placeholders.partner_training_activity ?? ''} choices={courses.map((training) => ({ value: training.id, label: training.label }))} onChange={(training) => onChange(chooseAssignTraining(drawer, state, training))} required error={errorFor('training')} />
          {drawer.partnerCourses[state.partner] ? <Words text={captions.partnerCourses} /> : null}
          <TrainingMeta training={selected} />
          <Words text={captions.trainingHelp} />
          {selected?.plannerChooses ? (
            <ChoiceField id="partner_training_focus_intervention" label={labels['partner-training-ssa-label'] ?? 'SSA intervention'} value={state.intervention} placeholder={placeholders.partner_training_focus_intervention ?? ''} choices={drawer.interventions} onChange={(intervention) => onChange({ ...state, intervention })} help={captions.plannerChooses} />
          ) : (
            <ReadOnlyField label={labels['partner-training-ssa-label'] ?? 'SSA intervention'} text={selected?.ssaInterventionLabel ?? ''} placeholder="Filled in from the training" help={captions.linkedIntervention} />
          )}
        </div>
      ) : null}
      {state.purpose === 'training_follow_up' ? (
        <FollowUpFields drawer={drawer} selectId="partner_source_activity" source={state.source} onChange={(source) => onChange({ ...state, source })} error={errorFor('source')} />
      ) : null}
      {state.purpose === 'ssa_support' ? <ReadOnlyField label="Focus intervention" text="Data Gathering" /> : null}
      {drawer.notes.map((note) => <Note key={note.title + note.text} tone={note.tone} title={note.title} text={note.text} />)}
      <ReadOnlyField label={captions.assignedDateLabel ?? 'Assigned date'} text={captions.assignedDate ?? ''} help={captions.assignedDateHelp} />
      <Words text={captions.monitoredBy} />
    </>
  );
}
