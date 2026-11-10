/**
 * Assign to Partner's fields, in the web drawer's order
 * (templates/partials/planning/assign_partner_drawer.html): Partner, Reason
 * for assigning, the project routes, the Training (In-school Training) or the
 * training followed up (Follow Up), the previous withdrawal, the assigned
 * date and who monitors it.
 */
import { View } from 'react-native';

import type { PlanningDrawer } from '../../gen/edify/screens/v1/planning_drawer_pb';
import { DrawerButton, DrawerNote, DrawerText, FieldShell } from '../drawerParts';
import { ChoiceField, FollowUpFields, ReadOnlyField, SELECT_MISSING, TrainingMeta } from './planningParts';
import {
  changeAssignPartner,
  changeAssignPurpose,
  chooseAssignTraining,
  trainingsFor,
} from './planningLogic';
import type { PlanningState, RequiredField } from './planningLogic';

interface AssignFieldsProps {
  readonly drawer: PlanningDrawer;
  readonly state: PlanningState;
  readonly onChange: (next: PlanningState) => void;
  /** Opens a web path (a project's own hand-over drawer). */
  readonly onOpenWeb: (path: string) => void;
  /** The required field the form stopped at, or ''. */
  readonly missing: RequiredField | '';
}

export function AssignFields({ drawer, state, onChange, onOpenWeb, missing }: AssignFieldsProps) {
  const errorFor = (field: RequiredField) => (missing === field ? SELECT_MISSING : undefined);
  const courses = trainingsFor(drawer, state);
  const selected = courses.find((training) => training.id === state.training);
  const labels = drawer.labels;
  const placeholders = drawer.placeholders;
  const captions = drawer.captions;
  return (
    <>
      <ChoiceField
        label={labels.partner_id ?? 'Partner'}
        value={state.partner}
        placeholder={placeholders.partner_id ?? ''}
        choices={drawer.partners}
        onChange={(partner) => onChange(changeAssignPartner(drawer, state, partner))}
        isRequired
        error={errorFor('partner')}
      />
      <View style={{ gap: 7 }}>
        <ChoiceField
          label={labels.purpose_of_visit ?? 'Reason for assigning'}
          value={state.purpose}
          placeholder={placeholders.purpose_of_visit ?? ''}
          choices={drawer.purposes}
          onChange={(purpose) => onChange(changeAssignPurpose(state, purpose))}
          isRequired
          error={errorFor('purpose')}
        />
        {drawer.purposeNotes.map((note) => (
          <DrawerText key={note} text={note} tone="warning" />
        ))}
      </View>
      {drawer.projectHandovers.length > 0 ? (
        <FieldShell label={captions.handoverTitle ?? ''} help={captions.handover}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {drawer.projectHandovers.map((route) => (
              <DrawerButton key={route.path} label={route.label} onPress={() => onOpenWeb(route.path)} />
            ))}
          </View>
        </FieldShell>
      ) : null}
      {state.purpose === 'in_school_training' ? (
        <View style={{ gap: 7 }}>
          <ChoiceField
            label={labels.partner_training_activity ?? 'Training'}
            value={state.training}
            placeholder={placeholders.partner_training_activity ?? ''}
            choices={courses.map((training) => ({ value: training.id, label: training.label }))}
            onChange={(training) => onChange(chooseAssignTraining(drawer, state, training))}
            isRequired
            error={errorFor('training')}
          />
          {drawer.partnerCourses[state.partner] ? <DrawerText text={captions.partnerCourses ?? ''} /> : null}
          <TrainingMeta training={selected} />
          <DrawerText text={captions.trainingHelp ?? ''} />
          {selected?.plannerChooses ? (
            <ChoiceField
              label={labels['partner-training-ssa-label'] ?? 'SSA intervention'}
              value={state.intervention}
              placeholder={placeholders.partner_training_focus_intervention ?? ''}
              choices={drawer.interventions}
              onChange={(intervention) => onChange({ ...state, intervention })}
              help={captions.plannerChooses}
            />
          ) : (
            <ReadOnlyField
              label={labels['partner-training-ssa-label'] ?? 'SSA intervention'}
              text={selected?.ssaInterventionLabel ?? ''}
              placeholder="Filled in from the training"
              help={captions.linkedIntervention}
            />
          )}
        </View>
      ) : null}
      {state.purpose === 'training_follow_up' ? (
        <FollowUpFields
          drawer={drawer}
          selectId="partner_source_activity"
          source={state.source}
          onChange={(source) => onChange({ ...state, source })}
          error={errorFor('source')}
        />
      ) : null}
      {state.purpose === 'ssa_support' ? <ReadOnlyField label="Focus intervention" text="Data Gathering" /> : null}
      {drawer.notes.map((note) => (
        <DrawerNote key={note.title + note.text} tone={note.tone} title={note.title} text={note.text} />
      ))}
      <ReadOnlyField
        label={captions.assignedDateLabel ?? 'Assigned date'}
        text={captions.assignedDate ?? ''}
        help={captions.assignedDateHelp}
      />
      <DrawerText text={captions.monitoredBy ?? ''} />
    </>
  );
}
