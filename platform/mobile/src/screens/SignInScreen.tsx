/** Sign in, drawn as the web app's sign-in page. */
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { describe, useSession } from '../auth/SessionContext';
import { fonts, radius, signInPalette as palette, spacing, type } from '../theme';
import { EdifyLogo } from '../ui/EdifyLogo';

const GRADIENT_START = { x: 0, y: 0 };
const GRADIENT_END = { x: 1, y: 0.3 };
const INPUT_HEIGHT = 50;
const BUTTON_HEIGHT = 57;

interface SignInScreenProps {
  readonly notice: string;
}

export function SignInScreen({ notice }: SignInScreenProps) {
  const { signIn } = useSession();
  const insets = useSafeAreaInsets();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isPasswordShown, setIsPasswordShown] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');

  const canSubmit = email.trim() !== '' && password !== '' && !isBusy;
  const message = error || notice;

  async function handleSubmit() {
    if (!canSubmit) {
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      await signIn(email, password);
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.page}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={[
          styles.scroll,
          { paddingTop: insets.top + spacing.xl, paddingBottom: insets.bottom + spacing.xl },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.card}>
          <LinearGradient
            colors={palette.barGradient}
            start={GRADIENT_START}
            end={GRADIENT_END}
            style={styles.bar}
          />
          <View style={styles.body}>
            <View style={styles.logo}>
              <EdifyLogo height={46} color="navy" />
            </View>
            <Text style={styles.title} accessibilityRole="header">
              Sign in
            </Text>
            <Text style={styles.subtitle}>Welcome back to your planning workspace.</Text>

            {message ? (
              <Text
                style={[styles.message, error ? styles.messageError : null]}
                accessibilityRole="alert"
                accessibilityLiveRegion="polite"
              >
                {message}
              </Text>
            ) : null}

            <Text style={styles.label}>Email address</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              textContentType="username"
              autoComplete="email"
              accessibilityLabel="Email address"
            />

            <Text style={styles.label}>Password</Text>
            <View style={styles.passwordRow}>
              <TextInput
                style={[styles.input, styles.passwordInput]}
                value={password}
                onChangeText={setPassword}
                secureTextEntry={!isPasswordShown}
                textContentType="password"
                autoComplete="current-password"
                accessibilityLabel="Password"
                onSubmitEditing={() => void handleSubmit()}
              />
              <Pressable
                style={styles.eye}
                onPress={() => setIsPasswordShown((shown) => !shown)}
                accessibilityRole="button"
                accessibilityLabel={isPasswordShown ? 'Hide password' : 'Show password'}
                hitSlop={8}
              >
                {isPasswordShown ? (
                  <EyeOff size={20} color={palette.link} />
                ) : (
                  <Eye size={20} color={palette.link} />
                )}
              </Pressable>
            </View>

            <Pressable
              onPress={() => void handleSubmit()}
              disabled={!canSubmit}
              accessibilityRole="button"
              accessibilityLabel="Access workspace"
              accessibilityState={{ disabled: !canSubmit, busy: isBusy }}
              style={[styles.buttonShadow, !canSubmit && styles.buttonDisabled]}
            >
              <LinearGradient
                colors={palette.gradient}
                start={GRADIENT_START}
                end={GRADIENT_END}
                style={styles.button}
              >
                {isBusy ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.buttonText}>Access workspace</Text>
                )}
              </LinearGradient>
            </Pressable>

            <View style={styles.divider} />
            <View style={styles.secure}>
              <View style={styles.secureIcon}>
                <ShieldCheck size={22} color={palette.link} />
              </View>
              <View style={styles.secureText}>
                <Text style={styles.secureTitle}>Secure access</Text>
                <Text style={styles.secureBody}>
                  Your sign-in is kept in this phone's secure keystore.
                </Text>
              </View>
            </View>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: palette.page },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: spacing.lg },
  card: {
    backgroundColor: palette.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: palette.cardBorder,
    overflow: 'hidden',
    shadowColor: '#072641',
    shadowOpacity: 0.09,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 16 },
    elevation: 6,
  },
  bar: { height: 4 },
  body: { padding: spacing.xxl - spacing.xs },
  logo: { alignItems: 'center', marginTop: spacing.md, marginBottom: spacing.lg },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.title,
    color: palette.title,
    textAlign: 'center',
  },
  subtitle: {
    fontFamily: fonts.regular,
    fontSize: type.body,
    color: palette.subtitle,
    textAlign: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.xxl,
  },
  message: {
    fontFamily: fonts.medium,
    fontSize: type.body,
    color: palette.subtitle,
    marginBottom: spacing.lg,
  },
  messageError: {
    color: palette.danger,
    backgroundColor: palette.dangerSoft,
    borderRadius: radius.sm,
    padding: spacing.md,
    overflow: 'hidden',
  },
  label: {
    fontFamily: fonts.semibold,
    fontSize: type.body,
    color: palette.label,
    marginBottom: spacing.sm,
  },
  input: {
    height: INPUT_HEIGHT,
    borderWidth: 1,
    borderColor: palette.inputBorder,
    borderRadius: radius.md,
    backgroundColor: palette.inputBg,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.control,
    color: palette.inputText,
    marginBottom: spacing.xl,
  },
  passwordRow: { justifyContent: 'center' },
  passwordInput: { paddingRight: INPUT_HEIGHT },
  eye: {
    position: 'absolute',
    right: spacing.lg,
    top: (INPUT_HEIGHT - 20) / 2,
  },
  buttonShadow: {
    borderRadius: radius.sm,
    shadowColor: '#084c89',
    shadowOpacity: 0.18,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 10 },
    elevation: 4,
    marginTop: spacing.xs,
  },
  // No shadow while disabled: a faded button over its own shadow looks dirty.
  buttonDisabled: { opacity: 0.6, elevation: 0, shadowOpacity: 0 },
  button: {
    height: BUTTON_HEIGHT,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { fontFamily: fonts.semibold, fontSize: type.control, color: '#ffffff' },
  divider: { height: 1, backgroundColor: palette.divider, marginVertical: spacing.xl + spacing.xs },
  secure: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  secureIcon: {
    width: 46,
    height: 46,
    borderRadius: radius.md,
    backgroundColor: palette.card,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#072641',
    shadowOpacity: 0.1,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  secureText: { flex: 1 },
  secureTitle: { fontFamily: fonts.bold, fontSize: type.control - 1, color: palette.title },
  secureBody: {
    fontFamily: fonts.regular,
    fontSize: type.small,
    lineHeight: 17,
    color: palette.subtitle,
    marginTop: 2,
  },
});
