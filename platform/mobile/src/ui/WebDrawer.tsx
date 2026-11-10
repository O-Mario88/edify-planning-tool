/**
 * One of the web's drawers, drawn natively: read from the drawer the web
 * renders for the same person and saved by the web view that saves it
 * (apps.mobile_feed SchoolDrawerFeedView). Its parts are the drawer's own —
 * notes, headings, figures and fields, in order — and what its script does
 * (a field shown for one choice, a list another field reloads, a list tied
 * to another field's choice) follows drawerLogic. A refused save comes back
 * as the drawer again, the web's errors in it.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator } from 'react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { PageDrawer } from '../gen/edify/screens/v1/drawer_pb';
import type { DrawerField } from '../gen/edify/screens/v1/form_pb';
import { useTheme } from '../theme';
import { Drawer } from './Drawer';
import { DiscardPrompt, DrawerButton, DrawerNote } from './drawerParts';
import { DrawerItemView } from './drawerFields';
import { ExportProgress } from './ExportProgress';
import { clearedBy, initialValues, isShown, missingField, valuesToSend } from './drawerLogic';
import type { Reloaded } from './drawerLogic';

/** Which drawer: one of a school's (edit, close, ssa-entry), or any drawer a
 * page opens, by its web path. */
export type DrawerSource = { readonly schoolId: string; readonly kind: string } | { readonly path: string };

interface WebDrawerProps {
  readonly source: DrawerSource;
  readonly onClose: () => void;
  /** Saved: the web's confirmation, and where the web went next (or ''). */
  readonly onSaved: (message: string, redirect: string) => void;
  /** The feed does not draw this drawer: its opener takes it elsewhere. */
  readonly onUnavailable?: () => void;
}

export function WebDrawer({ source, onClose, onSaved, onUnavailable }: WebDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [drawer, setDrawer] = useState<PageDrawer | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [reloaded, setReloaded] = useState<Reloaded>({});
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [refusals, setRefusals] = useState(0);
  /** An export drawer's file being prepared (the drawer stays open on it, as on the web). */
  const [exportJob, setExportJob] = useState('');

  /** As the web's drawer: closing with typed changes asks first. */
  function requestClose() {
    if (isDirty) {
      setIsAsking(true);
      return;
    }
    onClose();
  }

  const sourceKey = 'path' in source ? source.path : `${source.schoolId}/${source.kind}`;
  useEffect(() => {
    const loading =
      'path' in source
        ? api.getDrawer(source.path).then((answer) => {
            if (!answer.drawer) {
              throw new Error(answer.refusal || 'This drawer could not be loaded. Please try again.');
            }
            return answer.drawer;
          })
        : api.getSchoolDrawer(source.schoolId, source.kind);
    loading
      .then((answer) => {
        setDrawer(answer);
        setValues(initialValues(answer));
      })
      .catch((cause: unknown) => {
        if (onUnavailable && cause instanceof ApiError && cause.code === 'not_found') {
          onUnavailable();
          return;
        }
        setError(describe(cause));
      });
    // The source is named by its key; a new object for the same drawer does not reload it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, sourceKey]);

  function change(field: DrawerField, value: string) {
    if (!drawer) {
      return;
    }
    setIsDirty(true);
    const cleared = clearedBy(drawer, field.name);
    setValues((current) => ({
      ...current,
      [field.name]: value,
      ...Object.fromEntries(cleared.map((name) => [name, ''])),
    }));
    if (field.reloadsPath && field.reloadsTarget) {
      const target = field.reloadsTarget;
      api
        .getDrawerOptions({ source: field.reloadsPath, name: field.name, value })
        .then((options) => setReloaded((current) => ({ ...current, [target]: options })))
        .catch((cause: unknown) => setError(describe(cause)));
    }
  }

  async function save() {
    if (!drawer) {
      return;
    }
    // As the browser does, a required field left empty stops the save here.
    const missing = missingField(drawer, values);
    if (missing) {
      setError(`${missing} is required.`);
      setRefusals((count) => count + 1);
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      const sent = valuesToSend(drawer, values);
      const answer =
        'path' in source ? await api.saveDrawer(source.path, sent) : await api.saveSchoolDrawer(source.schoolId, source.kind, sent);
      const job = 'exportJob' in answer ? answer.exportJob : '';
      if (answer.saved && job) {
        setIsDirty(false);
        setExportJob(job);
        return;
      }
      if (answer.saved) {
        onSaved(answer.message, answer.redirect);
        return;
      }
      if (answer.drawer) {
        setDrawer(answer.drawer);
        setValues({ ...initialValues(answer.drawer), ...values });
      }
      setError(answer.error);
      setRefusals((count) => count + 1);
    } catch (cause) {
      setError(describe(cause));
      setRefusals((count) => count + 1);
    } finally {
      setIsBusy(false);
    }
  }

  const footer = exportJob ? (
    <DrawerButton label="Close" onPress={onClose} />
  ) : drawer ? (
    <>
      <DrawerButton label={drawer.cancelLabel || 'Cancel'} onPress={requestClose} />
      {drawer.canSubmit ? (
        <DrawerButton label={drawer.submitLabel} onPress={() => void save()} isPrimary isBusy={isBusy} />
      ) : null}
    </>
  ) : undefined;

  return (
    <Drawer
      title={drawer?.title ?? ''}
      subtitle={drawer?.subtitle}
      onClose={requestClose}
      hasRequired={!exportJob && drawer?.hasRequired}
      footer={footer}
      topKey={refusals}
      overlay={isAsking ? <DiscardPrompt onKeep={() => setIsAsking(false)} onDiscard={onClose} /> : undefined}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {exportJob ? (
        <ExportProgress jobId={exportJob} />
      ) : drawer ? (
        drawer.items.map((item, index) =>
          isShown(item.showWhen, values) ? (
            <DrawerItemView key={`${item.kind.case}-${index}`} item={item} values={values} reloaded={reloaded} onChange={change} />
          ) : null,
        )
      ) : error ? null : (
        <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
      )}
    </Drawer>
  );
}
