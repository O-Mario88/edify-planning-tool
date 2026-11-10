/**
 * The School Directory's row action drawers: Add to Cluster (or Change
 * Cluster) and Add to Project, as on the web (partials/schools/
 * add_to_cluster_drawer.html and assign_to_project_drawer.html).
 *
 * The choices, rules and messages are the web drawers' own: the existing
 * application runs its drawer flow and the app shows what it answers.
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Check } from 'lucide-react-native';

import { describe, useSession } from '../auth/SessionContext';
import type {
  ActionChoice,
  AddToClusterForm,
  AddToProjectForm,
  BulkActionResult,
  SchoolActionResult,
} from '../gen/edify/screens/v1/school_actions_pb';
import type { BulkProjectChoice } from '../gen/edify/screens/v1/school_directory_pb';
import { fonts, radius, toneColors, useTheme } from '../theme';
import { Drawer } from '../ui/Drawer';
import { DateField } from '../ui/DateField';
import { Select } from '../ui/Select';

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function Notice({ tone, children }: { readonly tone: string; readonly children: ReactNode }) {
  const { colors } = useTheme();
  const colour = toneColors(colors, tone);
  return (
    <Text
      style={[styles.notice, { color: colour.fg, backgroundColor: colour.soft }]}
      accessibilityRole={tone === 'alert' ? 'alert' : undefined}
    >
      {children}
    </Text>
  );
}

function Label({ text, isRequired }: { readonly text: string; readonly isRequired?: boolean }) {
  const { colors } = useTheme();
  return (
    <Text style={[styles.label, { color: colors.text }]}>
      {text}
      {isRequired ? <Text style={{ color: colors.danger }}> *</Text> : null}
    </Text>
  );
}

interface FooterProps {
  readonly submitLabel: string;
  readonly canSubmit: boolean;
  readonly isBusy: boolean;
  readonly onCancel: () => void;
  readonly onSubmit: () => void;
}

function Footer({ submitLabel, canSubmit, isBusy, onCancel, onSubmit }: FooterProps) {
  const { colors } = useTheme();
  return (
    <>
      <Pressable
        onPress={onCancel}
        accessibilityRole="button"
        style={[styles.button, { borderColor: colors.outlineBorder, backgroundColor: colors.raised }]}
      >
        <Text style={[styles.buttonText, { color: colors.link }]}>Cancel</Text>
      </Pressable>
      <Pressable
        onPress={onSubmit}
        disabled={!canSubmit || isBusy}
        accessibilityRole="button"
        accessibilityLabel={submitLabel}
        accessibilityState={{ disabled: !canSubmit || isBusy, busy: isBusy }}
        style={[styles.button, { backgroundColor: colors.primary, borderColor: colors.primary, opacity: canSubmit && !isBusy ? 1 : 0.5 }]}
      >
        {isBusy ? (
          <ActivityIndicator color={colors.primaryInk} />
        ) : (
          <Text style={[styles.buttonText, { color: colors.primaryInk }]}>{submitLabel}</Text>
        )}
      </Pressable>
    </>
  );
}

interface ActionDrawerProps {
  readonly schoolId: string;
  readonly onClose: () => void;
  /** Called with the web's confirmation once the change is saved. */
  readonly onSaved: (message: string) => void;
}

/** Shows a save's outcome: refusals and corrections stay in the drawer. */
function useSave(onSaved: (message: string) => void) {
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(run: () => Promise<SchoolActionResult>) {
    setIsBusy(true);
    setError('');
    try {
      const result = await run();
      if (result.saved) {
        onSaved(result.message);
        return;
      }
      setError(result.refused || result.error || 'This could not be saved.');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }
  return { isBusy, error, save };
}

export function AddToClusterDrawer({ schoolId, onClose, onSaved }: ActionDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [form, setForm] = useState<AddToClusterForm | null>(null);
  const [loadError, setLoadError] = useState('');
  const [actionType, setActionType] = useState<'existing' | 'new'>('existing');
  const [clusterId, setClusterId] = useState('');
  const [newName, setNewName] = useState('');
  const [reason, setReason] = useState('');
  const [isConfirmed, setIsConfirmed] = useState(false);
  const { isBusy, error, save } = useSave(onSaved);

  useEffect(() => {
    api
      .getAddToCluster(schoolId)
      .then((answer) => {
        setForm(answer);
        setClusterId(answer.preselectedClusterId);
        setActionType(answer.hasSelectableCluster || answer.isChange ? 'existing' : 'new');
      })
      .catch((cause: unknown) => setLoadError(describe(cause)));
  }, [api, schoolId]);

  if (!form) {
    return (
      <Drawer title="Add to cluster" onClose={onClose}>
        {loadError ? <Notice tone="alert">{loadError}</Notice> : <ActivityIndicator color={colors.primary} />}
      </Drawer>
    );
  }
  if (form.refused) {
    return (
      <Drawer title="Add to cluster" onClose={onClose}>
        <Notice tone="alert">{form.refused}</Notice>
      </Drawer>
    );
  }

  const needsReason =
    form.isChange || (actionType === 'existing' && form.crossDistrictClusterIds.includes(clusterId));
  const hasTarget = actionType === 'existing' ? clusterId !== '' : newName.trim() !== '';
  const canSubmit =
    hasTarget && (!needsReason || reason.trim() !== '') && (!form.isChange || isConfirmed);

  function submit() {
    void save(() =>
      api.addToCluster({
        schoolId,
        actionType,
        clusterId: actionType === 'existing' ? clusterId : '',
        newClusterName: actionType === 'new' ? newName.trim() : '',
        reason: reason.trim(),
        confirmChange: isConfirmed,
      }),
    );
  }

  return (
    <Drawer
      title={form.title}
      onClose={onClose}
      hasRequired
      footer={
        <Footer submitLabel={form.submitLabel} canSubmit={canSubmit} isBusy={isBusy} onCancel={onClose} onSubmit={submit} />
      }
    >
      {error || form.error ? <Notice tone="alert">{error || form.error}</Notice> : null}

      <View style={styles.toggle} accessibilityRole="radiogroup">
        {(['existing', 'new'] as const).map((type) => {
          const isActive = actionType === type;
          return (
            <Pressable
              key={type}
              onPress={() => setActionType(type)}
              accessibilityRole="radio"
              accessibilityState={{ selected: isActive }}
              style={[
                styles.toggleOption,
                isActive
                  ? [styles.toggleActive, { backgroundColor: colors.primary, borderColor: colors.primary }]
                  : { backgroundColor: colors.raised, borderColor: colors.outlineBorder },
              ]}
            >
              <Text style={[styles.toggleText, { color: isActive ? colors.primaryInk : colors.link }]}>
                {type === 'existing' ? 'Owner’s clusters' : 'Create new cluster'}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {actionType === 'existing' ? (
        <View style={styles.field}>
          <Label text="Cluster" isRequired />
          {form.clusters.length > 0 ? (
            <Select
              label="Cluster"
              value={clusterId}
              choices={form.clusters}
              placeholder="Select a cluster"
              onChange={setClusterId}
            />
          ) : null}
          {form.ownerNote ? <Text style={[styles.help, { color: colors.textMuted }]}>{form.ownerNote}</Text> : null}
          {form.clusterNotice ? (
            <Notice tone={form.clusters.length > 0 ? 'caution' : 'info'}>{form.clusterNotice}</Notice>
          ) : null}
        </View>
      ) : (
        <View style={styles.field}>
          <Label text="Cluster name" isRequired />
          <TextInput
            value={newName}
            onChangeText={setNewName}
            placeholder={form.newClusterPlaceholder}
            placeholderTextColor={colors.textSubtle}
            accessibilityLabel="Cluster name"
            style={[styles.input, { borderColor: colors.fieldBorder, color: colors.text, backgroundColor: colors.surface }]}
          />
          <Text style={[styles.help, { color: colors.textMuted }]}>{form.newClusterNote}</Text>
        </View>
      )}

      <View style={styles.field}>
        <Label text="Reason" isRequired={needsReason} />
        <TextInput
          value={reason}
          onChangeText={setReason}
          placeholder={form.reasonPlaceholder}
          placeholderTextColor={colors.textSubtle}
          multiline
          accessibilityLabel="Reason"
          style={[
            styles.input,
            styles.textarea,
            { borderColor: colors.fieldBorder, color: colors.text, backgroundColor: colors.surface },
          ]}
        />
      </View>

      {form.isChange ? (
        <Pressable
          onPress={() => setIsConfirmed((value) => !value)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: isConfirmed }}
          style={[styles.check, { borderColor: colors.confirmBorder }]}
        >
          <View
            style={[
              styles.box,
              { borderColor: colors.borderStrong, backgroundColor: isConfirmed ? colors.primary : 'transparent' },
            ]}
          >
            {isConfirmed ? <Check size={12} color={colors.primaryInk} /> : null}
          </View>
          <Text style={[styles.checkText, { color: colors.text }]}>{form.confirmLabel}</Text>
        </Pressable>
      ) : null}
    </Drawer>
  );
}

export function AddToProjectDrawer({ schoolId, onClose, onSaved }: ActionDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [form, setForm] = useState<AddToProjectForm | null>(null);
  const [loadError, setLoadError] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projectType, setProjectType] = useState('');
  const [participationType, setParticipationType] = useState('');
  const [coordinatorId, setCoordinatorId] = useState('');
  const [supportArea, setSupportArea] = useState('');
  const [startDate, setStartDate] = useState('');
  const [notes, setNotes] = useState('');
  const { isBusy, error, save } = useSave(onSaved);

  useEffect(() => {
    api
      .getAddToProject(schoolId)
      .then(setForm)
      .catch((cause: unknown) => setLoadError(describe(cause)));
  }, [api, schoolId]);

  if (!form) {
    return (
      <Drawer title="Add to project" onClose={onClose}>
        {loadError ? <Notice tone="alert">{loadError}</Notice> : <ActivityIndicator color={colors.primary} />}
      </Drawer>
    );
  }
  if (form.refused) {
    return (
      <Drawer title="Add to project" onClose={onClose}>
        <Notice tone="alert">{form.refused}</Notice>
      </Drawer>
    );
  }

  const chosen = form.projects.find((project) => project.value === projectId);
  const capacityBlock = chosen?.reason ?? '';
  const isDateValid = startDate === '' || ISO_DATE.test(startDate);
  const canSubmit = projectId !== '' && capacityBlock === '' && isDateValid;
  // A full project stays listed so the person sees why; choosing it shows the reason.
  const projectChoices = form.projects.map((project) => ({ value: project.value, label: project.label }));

  function submit() {
    void save(() =>
      api.addToProject({
        schoolId,
        projectId,
        projectType: projectType.trim(),
        participationType,
        startDate,
        supportArea,
        coordinatorId,
        notes: notes.trim(),
      }),
    );
  }

  const inputStyle = [styles.input, { borderColor: colors.fieldBorder, color: colors.text, backgroundColor: colors.surface }];

  return (
    <Drawer
      title={form.title}
      onClose={onClose}
      footer={
        <Footer submitLabel="Assign to project" canSubmit={canSubmit} isBusy={isBusy} onCancel={onClose} onSubmit={submit} />
      }
    >
      {error || form.error ? <Notice tone="alert">{error || form.error}</Notice> : null}
      {form.emptyNotice ? <Notice tone="info">{form.emptyNotice}</Notice> : null}

      <View style={styles.field}>
        <Label text="Project" isRequired />
        <Select label="Project" value={projectId} choices={projectChoices} placeholder="Select a project" onChange={setProjectId} />
        {capacityBlock ? (
          <View style={[styles.block, { backgroundColor: toneColors(colors, 'caution').soft }]}>
            <Text style={[styles.blockTitle, { color: colors.warning }]}>Project capacity reached</Text>
            <Text style={[styles.help, { color: colors.warning }]}>{capacityBlock}</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.field}>
        <Label text="Project type" />
        <TextInput
          value={projectType}
          onChangeText={setProjectType}
          placeholder="e.g. Curriculum support"
          placeholderTextColor={colors.textSubtle}
          accessibilityLabel="Project type"
          style={inputStyle}
        />
      </View>
      <View style={styles.field}>
        <Label text="Expected support type" />
        <Select
          label="Expected support type"
          value={participationType}
          choices={form.supportTypes}
          placeholder="Select a support type"
          onChange={setParticipationType}
        />
      </View>
      <View style={styles.field}>
        <Label text="Project coordinator" />
        <Select
          label="Project coordinator"
          value={coordinatorId}
          choices={form.coordinators}
          placeholder="Project default"
          onChange={setCoordinatorId}
        />
      </View>
      <View style={styles.field}>
        <Label text="Focus area" />
        <Select
          label="Focus area"
          value={supportArea}
          choices={form.focusAreas}
          placeholder="Select a focus area"
          onChange={setSupportArea}
        />
      </View>
      <View style={styles.field}>
        <Label text="Start date" />
        <DateField value={startDate} onChange={setStartDate} label="Start date" hasError={!isDateValid} />
      </View>
      <View style={styles.field}>
        <Label text="Notes" />
        <TextInput
          value={notes}
          onChangeText={setNotes}
          multiline
          accessibilityLabel="Notes"
          style={[...inputStyle, styles.textarea]}
        />
      </View>
    </Drawer>
  );
}

interface BulkDrawerProps {
  readonly schoolIds: readonly string[];
  readonly onClose: () => void;
  /** Called with the web's confirmation and any skipped-school notes. */
  readonly onSaved: (message: string, warnings: readonly string[]) => void;
}

/** A bulk save's outcome: a refusal stays in the dialog with its notes. */
function useBulkSave(onSaved: (message: string, warnings: readonly string[]) => void) {
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState<readonly string[]>([]);
  async function save(run: () => Promise<BulkActionResult>) {
    setIsBusy(true);
    setError('');
    setWarnings([]);
    try {
      const result = await run();
      if (result.saved) {
        onSaved(result.message, result.warnings);
        return;
      }
      setError(result.error || 'Nothing was changed.');
      setWarnings(result.warnings);
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }
  return { isBusy, error, warnings, save };
}

function plural(count: number): string {
  return `${count} selected school(s)`;
}

export function BulkClusterDrawer({
  schoolIds,
  clusters,
  onClose,
  onSaved,
}: BulkDrawerProps & { readonly clusters: readonly ActionChoice[] }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [clusterId, setClusterId] = useState('');
  const { isBusy, error, warnings, save } = useBulkSave(onSaved);
  return (
    <Drawer
      title="Assign cluster to selected schools"
      onClose={onClose}
      footer={
        <Footer
          submitLabel="Assign cluster"
          canSubmit={clusterId !== ''}
          isBusy={isBusy}
          onCancel={onClose}
          onSubmit={() => void save(() => api.bulkAssignCluster(schoolIds, clusterId))}
        />
      }
    >
      {error ? <Notice tone="alert">{error}</Notice> : null}
      {warnings.map((warning) => (
        <Notice key={warning} tone="caution">
          {warning}
        </Notice>
      ))}
      <View style={styles.field}>
        <Label text="Cluster" isRequired />
        <Select label="Cluster" value={clusterId} choices={clusters} placeholder="Select a cluster" onChange={setClusterId} />
        <Text style={[styles.help, { color: colors.textMuted }]}>
          Assigns {plural(schoolIds.length)} to this cluster and marks them Clustered.
        </Text>
      </View>
    </Drawer>
  );
}

export function BulkProjectDrawer({
  schoolIds,
  projects,
  projectsOf,
  onClose,
  onSaved,
}: BulkDrawerProps & {
  readonly projects: readonly BulkProjectChoice[];
  /** The projects each ticked school is already in. */
  readonly projectsOf: (schoolId: string) => readonly string[];
}) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [projectId, setProjectId] = useState('');
  const { isBusy, error, warnings, save } = useBulkSave(onSaved);
  const chosen = projects.find((project) => project.value === projectId);
  const block = chosen?.block ?? '';
  const remaining = chosen?.remaining;
  // As on the web: only schools not already in the project use a place.
  const newCount = schoolIds.filter((id) => !projectsOf(id).includes(projectId)).length;
  const isOverCapacity = remaining !== undefined && newCount > remaining;
  const canSubmit = projectId !== '' && block === '' && !isOverCapacity;
  return (
    <Drawer
      title="Assign project to selected schools"
      onClose={onClose}
      footer={
        <Footer
          submitLabel="Assign project"
          canSubmit={canSubmit}
          isBusy={isBusy}
          onCancel={onClose}
          onSubmit={() => void save(() => api.bulkAssignProject(schoolIds, projectId))}
        />
      }
    >
      {error ? <Notice tone="alert">{error}</Notice> : null}
      {warnings.map((warning) => (
        <Notice key={warning} tone="caution">
          {warning}
        </Notice>
      ))}
      <View style={styles.field}>
        <Label text="Project" isRequired />
        <Select
          label="Project"
          value={projectId}
          choices={projects.map((project) => ({ value: project.value, label: project.label }))}
          placeholder="Select a project"
          onChange={setProjectId}
        />
        <Text style={[styles.help, { color: colors.textMuted }]}>
          Assigns {plural(schoolIds.length)}. Schools already in the project are skipped.
        </Text>
        {block ? (
          <View style={[styles.block, { backgroundColor: toneColors(colors, 'caution').soft }]}>
            <Text style={[styles.blockTitle, { color: colors.warning }]}>Project capacity reached</Text>
            <Text style={[styles.help, { color: colors.warning }]}>{block}</Text>
          </View>
        ) : null}
        {!block && isOverCapacity ? (
          <View style={[styles.block, { backgroundColor: toneColors(colors, 'caution').soft }]}>
            <Text style={[styles.blockTitle, { color: colors.warning }]}>Capacity exceeded</Text>
            <Text style={[styles.help, { color: colors.warning }]}>
              You can add a maximum of {remaining} more school{remaining === 1 ? '' : 's'} to this project.
            </Text>
          </View>
        ) : null}
      </View>
    </Drawer>
  );
}

const styles = StyleSheet.create({
  button: { minHeight: 36, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  buttonText: { fontFamily: fonts.semibold, fontSize: 12 },
  notice: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19, borderRadius: radius.sm, padding: 10, overflow: 'hidden' },
  toggle: { flexDirection: 'row', gap: 4, padding: 4 },
  toggleOption: { flex: 1, minHeight: 32, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm },
  toggleActive: { boxShadow: '0px 6px 14px -10px rgba(14, 93, 163, 0.44)' },
  toggleText: { fontFamily: fonts.semibold, fontSize: 12 },
  field: { gap: 7 },
  label: { fontFamily: fonts.semibold, fontSize: 13 },
  help: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 16 },
  input: { minHeight: 40, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, fontFamily: fonts.medium, fontSize: 16 },
  textarea: { minHeight: 66, paddingTop: 9, paddingBottom: 9, textAlignVertical: 'top' },
  check: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, borderWidth: 1, borderRadius: radius.md, padding: 12 },
  box: { width: 16, height: 16, borderWidth: 1, borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
  checkText: { flex: 1, fontFamily: fonts.semibold, fontSize: 13 },
  block: { borderRadius: radius.sm, padding: 10, gap: 2 },
  blockTitle: { fontFamily: fonts.semibold, fontSize: 12 },
});
