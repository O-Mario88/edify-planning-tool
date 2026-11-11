/**
 * The screen after an administrator set this account's password, as the
 * web's templates/pages/auth/change_password.html: one card, the same words
 * and requirements, and nothing else until a new password is set. The gateway
 * refuses every other call meanwhile (PASSWORD_CHANGE_REQUIRED).
 */
import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { describe, useSession } from '../auth/SessionContext';
import { EdifyLogo } from '../ui/EdifyLogo';
import { signInAlert, signInAlertInk, signInStyles as styles } from './SignInScreen';
import { AlertCircle, EyeClosed, EyeOpen } from './signin/signInIcons';
import { ink, signInLayout, typeSizes } from './signin/signInLook';

const LOGO_HEIGHT = 112 * (123 / 300);
const REQUIREMENTS = [
  'At least 8 characters',
  'Uppercase and lowercase letters',
  'At least one number and one symbol (e.g. !@#$%)',
  'Not your email address',
] as const;

export function NewPasswordScreen() {
  const { setNewPassword, signOut } = useSession();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const layout = signInLayout(width, height);
  const sizes = typeSizes(width);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [isShown, setIsShown] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const label = { fontSize: sizes.label, lineHeight: sizes.label * 1.5 };

  async function handleSubmit() {
    if (isBusy) {
      return;
    }
    if (!password || !confirm) {
      setError('Enter your new password twice.');
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      await setNewPassword(password, confirm);
    } catch (cause) {
      setError(describe(cause));
      setIsBusy(false);
    }
  }

  const field = (value: string, onChange: (text: string) => void, name: string) => (
    <View>
      <TextInput
        style={[styles.input, label, styles.passwordInput]}
        value={value}
        onChangeText={(text) => {
          onChange(text);
          setError('');
        }}
        secureTextEntry={!isShown}
        textContentType="newPassword"
        autoComplete="new-password"
        accessibilityLabel={name}
      />
      <Pressable
        style={({ pressed }) => [styles.toggle, pressed && styles.togglePressed]}
        onPress={() => setIsShown((shown) => !shown)}
        accessibilityRole="button"
        accessibilityLabel={isShown ? 'Hide passwords' : 'Show passwords'}
      >
        {isShown ? <EyeClosed size={19.2} color={ink.toggle} /> : <EyeOpen size={19.2} color={ink.toggle} />}
      </Pressable>
    </View>
  );

  return (
    <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.column, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }]}
        keyboardShouldPersistTaps="handled"
      >
        <View style={[styles.card, { width: layout.cardWidth }]}>
          <View style={{ paddingHorizontal: layout.innerSide, paddingVertical: layout.innerVertical }}>
            <View style={styles.logo}>
              <EdifyLogo height={LOGO_HEIGHT} color="navy" />
            </View>
            <Text style={[styles.title, { fontSize: sizes.display, lineHeight: sizes.display * 1.15 }]} accessibilityRole="header">
              Password Change Required
            </Text>
            <Text style={[styles.subtitle, label]}>
              Your administrator set a temporary password. Choose your own before continuing.
            </Text>
            <View style={styles.form}>
              <Text style={[styles.fieldLabel, label]}>New password</Text>
              {field(password, setPassword, 'New password')}
              <Text style={[styles.fieldLabel, label, { marginTop: 20 }]}>Confirm new password</Text>
              {field(confirm, setConfirm, 'Confirm new password')}
              <View style={{ marginTop: 14, gap: 4 }} accessibilityLabel="Password requirements">
                <Text style={[styles.fieldLabel, label, { marginBottom: 2 }]}>Password requirements</Text>
                {REQUIREMENTS.map((requirement) => (
                  <Text key={requirement} style={[styles.secureCopy, label]}>
                    • {requirement}
                  </Text>
                ))}
              </View>
              {error ? (
                <View style={[styles.alert, signInAlert.error, { marginTop: 12 }]} accessibilityRole="alert" accessibilityLiveRegion="polite">
                  <AlertCircle size={18.4} color={signInAlertInk.error} />
                  <Text style={[styles.alertText, label, { color: signInAlertInk.error }]}>{error}</Text>
                </View>
              ) : null}
              <Pressable
                onPress={() => void handleSubmit()}
                disabled={isBusy}
                accessibilityRole="button"
                accessibilityLabel="Set new password and continue"
                accessibilityState={{ disabled: isBusy, busy: isBusy }}
                style={({ pressed }) => [styles.submit, { marginTop: 16.8 }, isBusy && styles.submitBusy, pressed && !isBusy && styles.submitPressed]}
              >
                <Text style={styles.submitText}>Set new password and continue</Text>
                {isBusy ? <ActivityIndicator color="#ffffff" size="small" /> : null}
              </Pressable>
              <Pressable onPress={() => void signOut()} accessibilityRole="button" style={[styles.forgot, styles.startAgain]}>
                <Text style={[styles.forgotText, label]}>Sign out</Text>
              </Pressable>
            </View>
          </View>
          {layout.barHeight ? <View style={[styles.bar, { height: layout.barHeight }]} /> : null}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
