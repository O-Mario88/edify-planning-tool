/**
 * A school's Schedule visit or Assign to Partner drawer, drawn natively from
 * the drawer the web renders for the same person (apps.mobile_feed.
 * planning_drawers) and saved by the web view its form posts to. Its script
 * runs as planningLogic; a refused save says the web's reason at the top.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetTrainingCapacityResponse, PlanningDrawer as Drawn } from '../../gen/edify/screens/v1/planning_drawer_pb';
import { useTheme } from '../../theme';
import { Drawer } from '../Drawer';
import { DiscardPrompt, DrawerButton, DrawerNote } from '../drawerParts';
import { AssignFields } from './AssignFields';
import { ScheduleFields } from './ScheduleFields';
import { assignValues, initialState, missingField, scheduleBlocked, scheduleParts, scheduleValues } from './planningLogic';
import type { PlanningState, RequiredField } from './planningLogic';

/** The drawer's title while it loads, as the profile's button names it. */
const LOADING_TITLES: Readonly<Record<string, string>> = { schedule: 'Schedule', assign: 'Assign to Partner' };

interface PlanningDrawerProps {
  readonly schoolId: string;
  /** schedule or assign. */
  readonly kind: 'schedule' | 'assign';
  readonly onClose: () => void;
  /** Saved: the web's confirmation. */
  readonly onSaved: (message: string) => void;
  /** Opens a web path the drawer links to (a project's hand-over drawer). */
  readonly onOpenWeb: (path: string) => void;
}

export function PlanningDrawer({ schoolId, kind, onClose, onSaved, onOpenWeb }: PlanningDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [drawer, setDrawer] = useState<Drawn | null>(null);
  const [state, setState] = useState<PlanningState | null>(null);
  const [capacity, setCapacity] = useState<GetTrainingCapacityResponse | undefined>(undefined);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [refusals, setRefusals] = useState(0);
  const [missing, setMissing] = useState<RequiredField | ''>('');

  useEffect(() => {
    api
      .getPlanningDrawer(schoolId, kind)
      .then((answer) => {
        if (!answer.drawer) {
          setError(answer.refusal);
          return;
        }
        setDrawer(answer.drawer);
        setState(initialState(answer.drawer));
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, kind, schoolId]);

  // The script's loadCapacity(): read again whenever the training or the
  // date changes, and only for a training.
  const purpose = state?.purpose ?? '';
  const training = state?.training ?? '';
  const date = state?.date ?? '';
  const school = drawer?.hidden.school_id ?? '';
  const asksCapacity = kind === 'schedule' && ['in_school_training', 'in_school_training_ssa'].includes(purpose) && training !== '';
  useEffect(() => {
    if (!asksCapacity) {
      setCapacity(undefined);
      return undefined;
    }
    let isCurrent = true;
    api
      .getTrainingCapacity({ training, date, school })
      .then((answer) => {
        if (isCurrent) {
          setCapacity(answer);
        }
      })
      // The web drops a failed read too: the save counts again.
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [api, asksCapacity, date, school, training]);

  function change(next: PlanningState) {
    setIsDirty(true);
    setMissing('');
    setState(next);
  }

  /** As the web's drawer: closing with typed changes asks first. */
  function requestClose() {
    if (isDirty) {
      setIsAsking(true);
      return;
    }
    onClose();
  }

  const parts = drawer && state && kind === 'schedule' ? scheduleParts(drawer, state, capacity) : undefined;

  async function save() {
    if (!drawer || !state) {
      return;
    }
    setError('');
    // As the browser does, a required field left empty stops the post.
    const empty = missingField(drawer, state, parts);
    setMissing(empty);
    if (empty) {
      return;
    }
    const values = parts ? scheduleValues(drawer, state, parts) : assignValues(state);
    setIsBusy(true);
    try {
      const answer = await api.savePlanningDrawer(schoolId, kind, values);
      if (answer.saved) {
        onSaved(answer.message);
        return;
      }
      setError(answer.error || 'This could not be saved.');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
    setRefusals((count) => count + 1);
  }

  const footer = drawer ? (
    <>
      <DrawerButton label={drawer.cancelLabel || 'Cancel'} onPress={requestClose} />
      <DrawerButton
        label={drawer.submitLabel}
        onPress={() => void save()}
        isPrimary
        isBusy={isBusy}
        isDisabled={parts ? scheduleBlocked(parts) : false}
      />
    </>
  ) : undefined;

  return (
    <Drawer
      title={drawer?.title ?? LOADING_TITLES[kind]}
      onClose={requestClose}
      hasRequired={drawer !== null}
      footer={footer}
      topKey={refusals}
      overlay={isAsking ? <DiscardPrompt onKeep={() => setIsAsking(false)} onDiscard={onClose} /> : undefined}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {drawer && state ? (
        parts ? (
          <ScheduleFields
            drawer={drawer}
            state={state}
            parts={parts}
            capacity={capacity}
            onChange={change}
            onCancel={requestClose}
            missing={missing}
          />
        ) : (
          <AssignFields drawer={drawer} state={state} onChange={change} onOpenWeb={onOpenWeb} missing={missing} />
        )
      ) : error ? null : (
        <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
      )}
    </Drawer>
  );
}
