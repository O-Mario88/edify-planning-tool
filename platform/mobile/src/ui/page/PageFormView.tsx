/**
 * A form a page shows itself (Escalations' "Escalate to …"), drawn as the web
 * draws it: a card with its title and line, its fields as a drawer's fields,
 * and its button. It saves as the browser posts it — the form's own fields
 * to where it posts, through the page (PageDrawerService.SaveDrawer with
 * this form's key) — and a required field left empty stops it first.
 */
import { useContext, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { PageForm } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { DrawerItemView } from '../drawerFields';
import { asDrawer, initialValues, isShown, missingField, valuesToSend } from '../drawerLogic';
import { DrawerButton, DrawerNote } from '../drawerParts';
import type { DrawerField } from '../../gen/edify/screens/v1/form_pb';
import { PageFormContext, cardStyles } from './shared';

export function PageFormView({ form }: { readonly form: PageForm }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const host = useContext(PageFormContext);
  const drawer = useMemo(() => asDrawer(form), [form]);
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(drawer));
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  function change(field: DrawerField, value: string) {
    setValues((current) => ({ ...current, [field.name]: value }));
  }

  async function save() {
    if (!host) {
      return;
    }
    const missing = missingField(drawer, values);
    if (missing) {
      setError(`${missing} is required.`);
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      const answer = await api.saveDrawer(host.path, valuesToSend(drawer, values), form.key);
      if (answer.saved) {
        setValues(initialValues(drawer));
        host.onSaved(answer.message);
        return;
      }
      setError(answer.error || 'This could not be saved.');
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <View style={[cardStyles.card, styles.card, { backgroundColor: colors.raised, borderColor: colors.border }]}>
      {form.title ? (
        <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
          {form.title}
        </Text>
      ) : null}
      {form.text ? <Text style={[styles.text, { color: colors.textMuted }]}>{form.text}</Text> : null}
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {drawer.items.map((item, index) =>
        isShown(item.showWhen, values) ? (
          <DrawerItemView key={`${item.kind.case}-${index}`} item={item} values={values} reloaded={{}} onChange={change} />
        ) : null,
      )}
      {host ? (
        <View style={styles.footer}>
          {form.canSave ? (
            <DrawerButton label={form.submitLabel} onPress={() => void save()} isPrimary isBusy={isBusy} />
          ) : (
            // The app does not save this form yet: it is finished on the web.
            <DrawerButton label="Continue on the web" onPress={host.onOpenWeb} isPrimary />
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 20, gap: 12 },
  title: { fontFamily: fonts.bold, fontSize: 13 },
  text: { fontFamily: fonts.semibold, fontSize: 12, lineHeight: 17 },
  footer: { flexDirection: 'row', justifyContent: 'flex-end' },
});
