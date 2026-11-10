/**
 * An export being prepared, in its drawer, as the web's status shows it
 * (partials/exports/status.html): "Preparing your file…", asked again every
 * few seconds, then the file's name and Download — which opens the file's
 * short-lived link in the phone's browser, where it is saved or opened.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Linking, StyleSheet, Text, View } from 'react-native';
import { FileSpreadsheet } from 'lucide-react-native';

import { describe, useSession } from '../auth/SessionContext';
import type { GetExportResponse } from '../gen/edify/screens/v1/export_pb';
import { fonts, radius, useTheme } from '../theme';
import { DrawerButton, DrawerNote } from './drawerParts';

/** The web's status asks every three seconds. */
const POLL_MS = 3000;

export function ExportProgress({ jobId }: { readonly jobId: string }) {
  const { api, environment } = useSession();
  const { colors } = useTheme();
  const [job, setJob] = useState<GetExportResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let isLive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = () => {
      api
        .getExport(jobId)
        .then((answer) => {
          if (!isLive) {
            return;
          }
          setJob(answer);
          if (answer.status !== 'ready' && answer.status !== 'failed') {
            timer = setTimeout(ask, POLL_MS);
          }
        })
        .catch((cause: unknown) => isLive && setError(describe(cause)));
    };
    ask();
    return () => {
      isLive = false;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [api, jobId]);

  if (error || job?.status === 'failed') {
    return <DrawerNote tone="danger" text={error || job?.error || 'The file could not be made.'} />;
  }
  if (!job || !job.downloadUrl) {
    return (
      <View style={styles.row} accessibilityLiveRegion="polite">
        <ActivityIndicator color={colors.primary} />
        <Text style={[styles.text, { color: colors.text }]}>Preparing your file…</Text>
      </View>
    );
  }
  return (
    <View style={styles.ready} accessibilityLiveRegion="polite">
      <View style={[styles.file, { backgroundColor: colors.successSoft }]}>
        <FileSpreadsheet size={18} color={colors.success} />
        <Text style={[styles.name, { color: colors.text }]} numberOfLines={2}>
          {job.filename}
        </Text>
      </View>
      <DrawerButton
        label="Download"
        isPrimary
        onPress={() => void Linking.openURL(`${environment.identityUrl}${job.downloadUrl}`)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  text: { fontFamily: fonts.semibold, fontSize: 13 },
  ready: { gap: 12 },
  file: { flexDirection: 'row', alignItems: 'center', gap: 10, borderRadius: radius.md, padding: 12 },
  name: { flex: 1, fontFamily: fonts.semibold, fontSize: 13 },
});
