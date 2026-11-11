/**
 * A drawer that sends one change to the gateway: its frame (title, the
 * refusal in its own words at the top, Cancel and the primary button) and
 * the call's busy and refused state. Shared by the partner Team and Acting
 * Leadership drawers.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { describe } from '../auth/SessionContext';
import { Drawer } from './Drawer';
import { DrawerButton, DrawerNote } from './drawerParts';

/** One drawer's call: run it, show it busy, and keep its refusal. */
export function useSubmit(onSaved: (message: string) => void) {
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [topKey, setTopKey] = useState(0);
  async function run(work: () => Promise<string>) {
    setIsBusy(true);
    setError('');
    try {
      onSaved(await work());
    } catch (cause) {
      setError(describe(cause));
      setTopKey((key) => key + 1);
      setIsBusy(false);
    }
  }
  return { isBusy, error, setError, topKey, run };
}

interface SubmitDrawerProps {
  readonly title: string;
  readonly subtitle?: string;
  /** The primary button. */
  readonly label: string;
  /** The other button; "Cancel" unless the drawer's own action is a cancel. */
  readonly cancelLabel?: string;
  /** What the other button does instead of closing (a step's Back). */
  readonly onSecondary?: () => void;
  readonly isBusy: boolean;
  readonly isDisabled?: boolean;
  readonly error: string;
  readonly topKey: number;
  readonly onClose: () => void;
  readonly onSubmit: () => void;
  readonly children: ReactNode;
}

export function SubmitDrawer({
  title,
  subtitle,
  label,
  cancelLabel = 'Cancel',
  onSecondary,
  isBusy,
  isDisabled,
  error,
  topKey,
  onClose,
  onSubmit,
  children,
}: SubmitDrawerProps) {
  return (
    <Drawer
      title={title}
      subtitle={subtitle}
      onClose={onClose}
      topKey={topKey}
      footer={
        <View style={styles.footer}>
          <DrawerButton label={cancelLabel} onPress={onSecondary ?? onClose} />
          <DrawerButton label={label} onPress={onSubmit} isPrimary isBusy={isBusy} isDisabled={isDisabled} />
        </View>
      }
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {children}
    </Drawer>
  );
}

const styles = StyleSheet.create({
  footer: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
});
