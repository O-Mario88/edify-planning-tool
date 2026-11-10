/**
 * Schedule visit's fields, in the web drawer's order
 * (templates/partials/planning/schedule_drawer.html): the notes and SSA
 * evidence, Purpose of visit, the Training and its SSA intervention and
 * ceiling, Focus intervention, the SSA departure note, the training followed
 * up, Facilitated by, the date, participants, the responsible person, Goal
 * and the visit justification.
 */
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type {
  GetTrainingCapacityResponse,
  PlanningDrawer,
  PlanningLeadItem,
} from '../../gen/edify/screens/v1/planning_drawer_pb';
import { fonts, useTheme } from '../../theme';
import { DateField } from '../DateField';
import { DrawerButton, DrawerInput, DrawerNote, DrawerText, FieldShell, partStyles } from '../drawerParts';
import { ChoiceField, FollowUpFields, ReadOnlyField, SELECT_MISSING, TEXT_MISSING, TrainingMeta } from './planningParts';
import { changePurpose, chooseTraining, lockFor, trainingsFor } from './planningLogic';
import type { PlanningState, RequiredField, ScheduleParts } from './planningLogic';

interface ScheduleFieldsProps {
  readonly drawer: PlanningDrawer;
  readonly state: PlanningState;
  readonly parts: ScheduleParts;
  readonly capacity: GetTrainingCapacityResponse | undefined;
  readonly onChange: (next: PlanningState) => void;
  readonly onCancel: () => void;
  /** The required field the form stopped at, or ''. */
  readonly missing: RequiredField | '';
}

/** The date field's browser message: empty, or not a day. */
function dateMessage(date: string): string {
  return date ? 'Please enter a valid date.' : TEXT_MISSING;
}

export function ScheduleFields({ drawer, state, parts, capacity, onChange, onCancel, missing }: ScheduleFieldsProps) {
  const selectError = (field: RequiredField) => (missing === field ? SELECT_MISSING : undefined);
  const labels = drawer.labels;
  const placeholders = drawer.placeholders;
  const captions = drawer.captions;
  const held = new Set(parts.heldTrainings);
  return (
    <>
      <Lead drawer={drawer} />
      <ExistingPlans
        drawer={drawer}
        onFollowUp={() => onChange(changePurpose(drawer, state, 'training_follow_up'))}
        onCancel={onCancel}
      />
      <View style={{ gap: 7 }}>
        <ChoiceField
          label={labels.purpose_of_visit ?? 'Purpose of visit'}
          value={state.purpose}
          placeholder={placeholders.purpose_of_visit ?? ''}
          choices={drawer.purposes.map((purpose) => ({
            ...purpose,
            disabled: purpose.disabled || Boolean(lockFor(drawer, purpose.value, state.date)),
          }))}
          onChange={(purpose) => onChange(changePurpose(drawer, state, purpose))}
          isRequired
          error={selectError('purpose')}
        />
        {drawer.purposeNotes.map((note) => (
          <DrawerText key={note} text={note} tone="warning" />
        ))}
        {captions.lockTail && parts.visitLockReasons.length > 0 ? (
          <DrawerText text={`${parts.visitLockReasons.join(' ')} ${captions.lockTail}`} tone="warning" />
        ) : null}
        <DrawerText text={parts.unavailableReason} tone="danger" />
      </View>
      {parts.showTrainingPicker ? (
        <View style={{ gap: 7 }}>
          <ChoiceField
            label={labels.training_activity_id ?? 'Training'}
            value={state.training}
            placeholder={placeholders.training_activity_id ?? ''}
            choices={trainingsFor(drawer, state).map((training) => ({
              value: training.id,
              label: training.label,
              disabled: held.has(training.id),
            }))}
            onChange={(training) => onChange(chooseTraining(drawer, state, training))}
            isRequired
            error={selectError('training')}
          />
          {parts.trainingLockReason ? (
            <DrawerNote
              tone="warning"
              text={`Only ${parts.universalTrainingNames} can still be scheduled: it is on top of the school’s own training for the year.`}
            />
          ) : null}
          <TrainingMeta training={parts.selected} />
          <DrawerText text={captions.trainingHelp ?? ''} />
        </View>
      ) : null}
      {parts.showLinkedIntervention ? (
        <ReadOnlyField
          label={labels['training-ssa-label'] ?? 'SSA intervention'}
          text={parts.selected?.ssaInterventionLabel ?? ''}
          placeholder="Filled in from the training"
          help={captions.linkedIntervention}
        />
      ) : null}
      {parts.showTrainingPicker ? <Ceiling parts={parts} capacity={capacity} /> : null}
      {parts.showManualIntervention ? (
        <ChoiceField
          label={labels.focus_intervention ?? 'Focus intervention'}
          value={state.intervention}
          placeholder={placeholders.focus_intervention ?? ''}
          choices={drawer.interventions}
          onChange={(intervention) => onChange({ ...state, intervention })}
          help={`Suggested from ${
            parts.showTrainingPicker && parts.selected?.ssaIntervention ? 'the selected training' : 'the weakest confirmed score'
          }; change it if the work is aimed elsewhere.`}
        />
      ) : null}
      {parts.ssaDeviation ? (
        <DrawerNote tone="warning" text={state.intervention ? (captions.deviationNamed ?? '') : (captions.deviationUnnamed ?? '')}>
          <FieldShell label={labels.ssa_deviation_reason ?? 'Why this plan departs from the SSA'} isOptional>
            <DrawerInput
              value={state.deviation}
              onChangeText={(deviation) => onChange({ ...state, deviation })}
              multiline
              maxLength={2000}
              accessibilityLabel={labels.ssa_deviation_reason}
            />
          </FieldShell>
        </DrawerNote>
      ) : null}
      {captions.ssaStale ? <DrawerNote tone="warning" text={captions.ssaStale} /> : null}
      {parts.showSsaDataGathering ? <ReadOnlyField label="Focus intervention" text="Data Gathering" /> : null}
      {parts.showFollowUp ? (
        <FollowUpFields
          drawer={drawer}
          selectId="source_activity_id"
          source={state.source}
          onChange={(source) => onChange({ ...state, source })}
          inheritedHelp="Inherited from the selected training."
          error={selectError('source')}
        />
      ) : null}
      {parts.showTrainingPicker && drawer.facilitators.length > 0 ? (
        <ChoiceField
          label={labels.school_facilitating_partner_id ?? 'Facilitated by'}
          value={state.facilitator}
          placeholder={drawer.facilitators[0].label}
          choices={drawer.facilitators.slice(1)}
          onChange={(facilitator) => onChange({ ...state, facilitator })}
          help={captions.facilitated}
        />
      ) : null}
      <DrawerText text={captions.monitoredBy ?? ''} />
      <FieldShell
        label={labels.scheduled_date ?? 'Scheduled date'}
        isRequired
        error={missing === 'date' ? dateMessage(state.date) : parts.followUpBlocked ? captions.dateYearUsed : undefined}
      >
        <DateField
          value={state.date}
          onChange={(date) => onChange({ ...state, date })}
          label={labels.scheduled_date ?? 'Scheduled date'}
          isRequired
          hasError={missing === 'date'}
        />
      </FieldShell>
      {parts.showParticipants ? (
        <FieldShell label={labels.expected_participants ?? 'Planned participants'}>
          <DrawerInput
            value={state.participants}
            onChangeText={(participants) => onChange({ ...state, participants })}
            keyboardType="number-pad"
            accessibilityLabel={labels.expected_participants}
          />
        </FieldShell>
      ) : null}
      {captions.responsible ? (
        <ReadOnlyField label="Responsible person" text={captions.responsible} help={captions.responsibleHelp} />
      ) : null}
      <FieldShell label={labels.activity_purpose_text ?? 'Goal'}>
        <DrawerInput
          value={state.goal}
          onChangeText={(goal) => onChange({ ...state, goal })}
          multiline
          placeholder={captions.goalPlaceholder}
          accessibilityLabel={labels.activity_purpose_text ?? 'Goal'}
        />
      </FieldShell>
      {drawer.hasJustification ? (
        <FieldShell
          label={labels.visit_justification ?? ''}
          isRequired
          help={captions.justificationHelp}
          error={missing === 'justification' ? TEXT_MISSING : undefined}
        >
          <DrawerInput
            value={state.justification}
            onChangeText={(justification) => onChange({ ...state, justification })}
            multiline
            placeholder={captions.justificationPlaceholder}
            accessibilityLabel={labels.visit_justification}
          />
        </FieldShell>
      ) : null}
    </>
  );
}

/** The notes and SSA evidence above Purpose of visit. A heading and the
 * lines and caption under it are one section, set tight as the web's list. */
function Lead({ drawer }: { readonly drawer: PlanningDrawer }) {
  const { colors } = useTheme();
  const sections: PlanningLeadItem[][] = [];
  for (const item of drawer.lead) {
    const current = sections[sections.length - 1];
    const joins = item.kind.case !== 'heading' && item.kind.case !== 'note' && current?.[0]?.kind.case === 'heading';
    if (joins) {
      current.push(item);
    } else {
      sections.push([item]);
    }
  }
  return (
    <>
      {sections.map((section, index) => (
        <View key={`lead-${index}`} style={{ gap: 4 }}>
          {section.map((item, line) => {
            const key = `${item.kind.case}-${line}`;
            switch (item.kind.case) {
              case 'heading':
                return (
                  <Text key={key} accessibilityRole="header" style={[leadStyles.heading, { color: colors.text }]}>
                    {item.kind.value}
                  </Text>
                );
              case 'text':
                return <DrawerText key={key} text={item.kind.value} />;
              case 'note':
                return (
                  <DrawerNote key={key} tone={item.kind.value.tone} title={item.kind.value.title} text={item.kind.value.text} />
                );
              case 'line':
                return (
                  <Text key={key} style={[leadStyles.line, { color: colors.text }]}>
                    - <Text style={{ color: colors.danger }}>{item.kind.value.label}</Text>{' '}
                    <Text style={leadStyles.score}>{item.kind.value.value}</Text>
                  </Text>
                );
              default:
                return null;
            }
          })}
        </View>
      ))}
    </>
  );
}

const leadStyles = StyleSheet.create({
  heading: { fontFamily: fonts.bold, fontSize: 15, lineHeight: 21 },
  line: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  score: { fontFamily: fonts.semibold, fontSize: 12 },
});

/** "This school already has plans this year": View Existing Plans, Continue
 * Planning, Plan as Follow-Up, Cancel. */
function ExistingPlans({ drawer, onFollowUp, onCancel }: {
  readonly drawer: PlanningDrawer;
  readonly onFollowUp: () => void;
  readonly onCancel: () => void;
}) {
  const { colors } = useTheme();
  const [isShown, setIsShown] = useState(true);
  const [isListOpen, setIsListOpen] = useState(false);
  const existing = drawer.existingPlans;
  if (!existing || !isShown) {
    return null;
  }
  const buttons = existing.buttons;
  return (
    <DrawerNote tone="warning" title={existing.note?.title} text={existing.note?.text ?? ''}>
      {isListOpen
        ? existing.plans.map((plan) => (
            <View key={plan.label} style={partStyles.line}>
              <Text style={[partStyles.lineLabel, { color: colors.text }]}>{plan.label}</Text>
              <Text style={[partStyles.lineValue, { color: colors.text }]}>{plan.status}</Text>
            </View>
          ))
        : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
        <DrawerButton label={buttons.view ?? 'View Existing Plans'} onPress={() => setIsListOpen(!isListOpen)} />
        <DrawerButton label={buttons.continue ?? 'Continue Planning'} onPress={() => setIsShown(false)} />
        <DrawerButton
          label={buttons['follow-up'] ?? 'Plan as Follow-Up'}
          onPress={() => {
            onFollowUp();
            setIsShown(false);
          }}
        />
        <DrawerButton label={buttons.cancel ?? 'Cancel'} onPress={onCancel} />
      </View>
    </DrawerNote>
  );
}

/** What the officer has scheduled for this training against their ceiling. */
function Ceiling({ parts, capacity }: { readonly parts: ScheduleParts; readonly capacity: GetTrainingCapacityResponse | undefined }) {
  if (!parts.selected || !capacity?.fy) {
    return null;
  }
  const counter = capacity.managed
    ? `Training ceiling ${capacity.scheduled} / ${capacity.ceiling ?? ''} schools covered for this training${
        capacity.staffName ? ` by ${capacity.staffName}` : ''
      } in FY ${capacity.fy}.`
    : `${capacity.scheduled} schools covered for this training in FY ${capacity.fy}. No training ceiling is set.`;
  return (
    <View style={{ gap: 7 }}>
      <DrawerText text={counter} />
      {parts.trainingCeilingFull ? (
        <DrawerNote
          tone="warning"
          text={`You have reached the training ceiling and cannot add any more schools to this training in FY ${capacity.fy}. Choose another training, or ask your Programme Lead to raise the ceiling.`}
        />
      ) : null}
    </View>
  );
}
