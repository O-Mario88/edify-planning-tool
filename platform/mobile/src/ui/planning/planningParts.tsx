/**
 * The parts both planning drawers draw the same way: a select field, the
 * training's catalogue line, the follow-up's "Training followed up" part and
 * the read-only "Focus intervention" box. Wording comes from the drawer the
 * web rendered (labels, placeholders, captions); a sentence the web's script
 * builds around a value is written here as the template writes it.
 */
import { View } from 'react-native';

import type { PlanningDrawer, PlanningTraining } from '../../gen/edify/screens/v1/planning_drawer_pb';
import { Select } from '../Select';
import { DrawerText, FieldShell, ReadOnlyBox } from '../drawerParts';

/** The browser's own words when it stops a form at an empty field. */
export const SELECT_MISSING = 'Please select an item in the list.';
export const TEXT_MISSING = 'Please fill out this field.';

interface Choice {
  readonly value: string;
  readonly label: string;
  readonly disabled?: boolean;
}

interface ChoiceFieldProps {
  readonly label: string;
  readonly value: string;
  readonly choices: readonly Choice[];
  /** The select's empty first line ("Select a purpose…"). */
  readonly placeholder: string;
  readonly onChange: (value: string) => void;
  readonly isRequired?: boolean;
  readonly isOptional?: boolean;
  readonly help?: string;
  readonly error?: string;
}

export function ChoiceField({
  label,
  value,
  choices,
  placeholder,
  onChange,
  isRequired,
  isOptional,
  help,
  error,
}: ChoiceFieldProps) {
  return (
    <FieldShell label={label} isRequired={isRequired} isOptional={isOptional} help={help} error={error}>
      <Select
        label={label}
        value={value}
        placeholder={placeholder}
        hasEmptyChoice={placeholder !== ''}
        choices={choices.map((choice) => ({ value: choice.value, label: choice.label, disabled: choice.disabled }))}
        onChange={onChange}
      />
    </FieldShell>
  );
}

/** "Training category … · SSA intervention association …". */
export function TrainingMeta({ training }: { readonly training: PlanningTraining | undefined }) {
  if (!training) {
    return null;
  }
  return (
    <DrawerText
      text={`Training category ${training.category} · SSA intervention association ${training.ssaIndicator}`}
    />
  );
}

/** A label over a grey box, as the web shows a value nobody edits here. */
export function ReadOnlyField({ label, text, placeholder, help }: {
  readonly label: string;
  readonly text: string;
  readonly placeholder?: string;
  readonly help?: string;
}) {
  return (
    <FieldShell label={label} help={help}>
      <ReadOnlyBox text={text} placeholder={placeholder} />
    </FieldShell>
  );
}

interface FollowUpProps {
  readonly drawer: PlanningDrawer;
  /** The select's id in this drawer (source_activity_id, partner_source_activity). */
  readonly selectId: string;
  readonly source: string;
  readonly onChange: (source: string) => void;
  /** The schedule drawer adds "Inherited from the selected training." */
  readonly inheritedHelp?: string;
  /** The browser's message when the form stopped here. */
  readonly error?: string;
}

/** "Training followed up" and, once one is chosen, its focus intervention. */
export function FollowUpFields({ drawer, selectId, source, onChange, inheritedHelp, error }: FollowUpProps) {
  const hasTrainings = drawer.followUps.length > 0;
  const chosen = drawer.followUps.find((item) => item.id === source);
  const caption = hasTrainings
    ? drawer.captions.followUpDone
    : drawer.followUpRequiresTraining
      ? drawer.captions.followUpNoneRequired
      : drawer.captions.followUpNoneOptional;
  return (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 7 }}>
        <ChoiceField
          label={drawer.labels[selectId] ?? 'Training followed up'}
          value={source}
          placeholder={drawer.placeholders[selectId] ?? ''}
          choices={drawer.followUps.map((item) => ({ value: item.id, label: item.label }))}
          onChange={onChange}
          isRequired={drawer.followUpRequiresTraining}
          isOptional={!drawer.followUpRequiresTraining}
          error={error}
        />
        <DrawerText text={caption ?? ''} tone={!hasTrainings && drawer.followUpRequiresTraining ? 'warning' : undefined} />
      </View>
      {chosen ? <ReadOnlyField label="Focus intervention" text={chosen.interventionLabel} help={inheritedHelp} /> : null}
    </View>
  );
}
