/**
 * Sign in, an exact replica of the web sign-in page (owner, 2026-11-11, with
 * the desktop and phone screenshots of it). Desktop: the classroom photo
 * panel beside the card. Tablet and phone: the card, with its coloured top
 * line, and the four figures two by two beneath it. Every measurement is in
 * signin/signInLook.ts, read from the rendered web page.
 *
 * It keeps the app's sign-in policies: the existing identity system checks
 * the password; "Remember me" keeps only the address; "Forgot password?"
 * asks that system for a reset link, as the web's does.
 */
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { describe, useSession } from '../auth/SessionContext';
import { requestPasswordReset, signInFigures } from '../auth/identityClient';
import { loadRememberedEmail, rememberEmail } from '../auth/rememberedEmail';
import { fonts } from '../theme';
import { EdifyLogo } from '../ui/EdifyLogo';
import { BrandPanel } from './signin/BrandPanel';
import { type Figures, SignInFigures } from './signin/SignInFigures';
import { AlertCircle, EyeClosed, EyeOpen, ShieldCheck } from './signin/signInIcons';
import { gradients, ink, shadows, signInLayout, typeSizes } from './signin/signInLook';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LOGO_HEIGHT = 112 * (123 / 300);

type Tone = 'error' | 'success' | 'info';

interface SignInScreenProps {
  readonly notice: string;
}

export function SignInScreen({ notice }: SignInScreenProps) {
  const { signIn, environment } = useSession();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const layout = signInLayout(width, height);
  const sizes = typeSizes(width);
  const [figures, setFigures] = useState<Figures | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isPasswordShown, setIsPasswordShown] = useState(false);
  const [isRemembered, setIsRemembered] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [focused, setFocused] = useState<'' | 'email' | 'password'>('');
  const [status, setStatus] = useState<{ readonly tone: Tone; readonly text: string } | null>(notice ? { tone: 'info', text: notice } : null);
  const passwordRef = useRef<React.ComponentRef<typeof TextInput>>(null);
  const scrollRef = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const submitRef = useRef<React.ComponentRef<typeof View>>(null);
  const scrollY = useRef(0);

  // The keyboard never covers "Access workspace": when it opens, scroll just
  // far enough to keep the button above it.
  useEffect(() => {
    const event = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const subscription = Keyboard.addListener(event, (keyboard) => {
      setTimeout(() => {
        submitRef.current?.measureInWindow((_x, y, _width, buttonHeight) => {
          const overlap = y + buttonHeight + 16 - keyboard.endCoordinates.screenY;
          if (overlap > 0) {
            scrollRef.current?.scrollTo({ y: scrollY.current + overlap, animated: true });
          }
        });
      }, Platform.OS === 'ios' ? 50 : 0);
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    let isLive = true;
    signInFigures(environment.identityUrl, (url, init) => fetch(url, init)).then((values) => {
      if (isLive) {
        setFigures(values);
      }
    });
    loadRememberedEmail().then((saved) => {
      if (isLive && saved) {
        setEmail((current) => current || saved);
        setIsRemembered(true);
      }
    });
    return () => {
      isLive = false;
    };
  }, [environment.identityUrl]);

  const canSubmit = email.trim() !== '' && password !== '' && !isBusy;

  async function handleSubmit() {
    if (!canSubmit) {
      setStatus({ tone: 'error', text: 'Enter your email address and password.' });
      return;
    }
    setIsBusy(true);
    setStatus(null);
    try {
      await signIn(email, password);
      await rememberEmail(isRemembered ? email.trim().toLowerCase() : null);
    } catch (cause) {
      setStatus({ tone: 'error', text: describe(cause) });
      setIsBusy(false);
    }
  }

  async function handleForgot() {
    if (!EMAIL.test(email.trim())) {
      setStatus({ tone: 'error', text: 'Enter your email address first, then choose Forgot password.' });
      return;
    }
    setIsSending(true);
    setStatus({ tone: 'info', text: 'Sending a secure reset link…' });
    const isSent = await requestPasswordReset(environment.identityUrl, (url, init) => fetch(url, init), email);
    setIsSending(false);
    setStatus(
      isSent
        ? { tone: 'success', text: 'If that account exists, a password reset link has been sent.' }
        : { tone: 'error', text: 'We couldn’t send a reset link right now. Please try again shortly.' },
    );
  }

  const label = { fontSize: sizes.label, lineHeight: sizes.label * 1.5 };
  // The web's labels are inline-block in a 16 px line, which sets them a
  // little down: 2.5 px at desktop size, 3.5 px at a phone's.
  const labelDrop = 2.5 + (13.6896 - sizes.label) * 1.5;
  const field = (name: 'email' | 'password') => [styles.input, label, focused === name && styles.inputFocused];
  const card = (
    <View style={[styles.card, { width: layout.cardWidth }]}>
      <View style={{ paddingHorizontal: layout.innerSide, paddingVertical: layout.innerVertical }}>
        <View style={styles.logo}>
          <EdifyLogo height={LOGO_HEIGHT} color="navy" />
        </View>
        <Text style={[styles.title, { fontSize: sizes.display, lineHeight: sizes.display * 1.15 }]} accessibilityRole="header">
          Sign in
        </Text>
        <Text style={[styles.subtitle, label]}>Welcome back to your planning workspace.</Text>

        <View style={styles.form}>
          <Text style={[styles.fieldLabel, label, { marginTop: labelDrop }]} nativeID="email-label">
            Email address
          </Text>
          <TextInput
            style={field('email')}
            value={email}
            onChangeText={(text) => {
              setEmail(text);
              setStatus(null);
            }}
            onFocus={() => setFocused('email')}
            onBlur={() => setFocused('')}
            autoCapitalize="none"
            autoCorrect={false}
            spellCheck={false}
            keyboardType="email-address"
            textContentType="username"
            autoComplete="email"
            returnKeyType="next"
            onSubmitEditing={() => passwordRef.current?.focus()}
            accessibilityLabel="Email address"
            accessibilityLabelledBy="email-label"
          />

          <Text style={[styles.fieldLabel, label, { marginTop: 20 + labelDrop }]} nativeID="password-label">
            Password
          </Text>
          <View>
            <TextInput
              ref={passwordRef}
              style={[field('password'), styles.passwordInput]}
              value={password}
              onChangeText={(text) => {
                setPassword(text);
                setStatus(null);
              }}
              onFocus={() => setFocused('password')}
              onBlur={() => setFocused('')}
              secureTextEntry={!isPasswordShown}
              textContentType="password"
              autoComplete="current-password"
              returnKeyType="go"
              onSubmitEditing={() => void handleSubmit()}
              accessibilityLabel="Password"
              accessibilityLabelledBy="password-label"
            />
            <Pressable
              style={({ pressed }) => [styles.toggle, pressed && styles.togglePressed]}
              onPress={() => setIsPasswordShown((shown) => !shown)}
              accessibilityRole="button"
              accessibilityLabel={isPasswordShown ? 'Hide password' : 'Show password'}
              accessibilityState={{ selected: isPasswordShown }}
            >
              {isPasswordShown ? <EyeClosed size={19.2} color={ink.toggle} /> : <EyeOpen size={19.2} color={ink.toggle} />}
            </Pressable>
          </View>

          <View style={[styles.options, { marginTop: layout.isPhone ? 10.4 : 13.6, minHeight: layout.isSplit ? 40 : 48 }]}>
            <Pressable
              style={[styles.remember, { minHeight: layout.isSplit ? 40 : 48 }]}
              onPress={() => setIsRemembered((on) => !on)}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: isRemembered }}
              accessibilityLabel="Remember me"
            >
              <View style={[styles.checkbox, isRemembered && styles.checkboxOn]}>
                {isRemembered ? (
                  <Svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round">
                    <Path d="m5 12.5 4.5 4.5L19 7.5" />
                  </Svg>
                ) : null}
              </View>
              <Text style={[styles.rememberText, label]}>Remember me</Text>
            </Pressable>
            <Pressable
              onPress={() => void handleForgot()}
              disabled={isSending}
              accessibilityRole="button"
              style={[styles.forgot, { minHeight: layout.isSplit ? 40 : 48, paddingHorizontal: layout.isPhone ? 4 : 0 }]}
            >
              <Text style={[styles.forgotText, label]}>Forgot password?</Text>
            </Pressable>
          </View>

          {status ? (
            <View style={[styles.alert, ALERT[status.tone], { marginTop: layout.isPhone ? 10.4 : 12 }]} accessibilityRole="alert" accessibilityLiveRegion="polite">
              <AlertCircle size={18.4} color={ALERT_INK[status.tone]} />
              <Text style={[styles.alertText, label, { color: ALERT_INK[status.tone] }]}>{status.text}</Text>
            </View>
          ) : null}

          <Pressable
            ref={submitRef}
            onPress={() => void handleSubmit()}
            disabled={isBusy}
            accessibilityRole="button"
            accessibilityLabel="Access workspace"
            accessibilityState={{ disabled: isBusy, busy: isBusy }}
            style={({ pressed }) => [styles.submit, { marginTop: layout.isPhone ? 13.6 : 16.8 }, isBusy && styles.submitBusy, pressed && !isBusy && styles.submitPressed]}
          >
            <Text style={styles.submitText}>Access workspace</Text>
            {isBusy ? <ActivityIndicator color="#ffffff" size="small" /> : null}
          </Pressable>
        </View>

        <View style={[styles.secure, layout.isPhone && styles.securePhone]} accessibilityLabel="Security information">
          <View style={[styles.shieldTile, layout.isPhone && styles.shieldTilePhone]}>
            <ShieldCheck size={22.4} color={ink.shield} strokeWidth={1.8} />
          </View>
          <View style={styles.flex}>
            <Text style={styles.secureTitle}>Secure access</Text>
            <Text style={[styles.secureCopy, { fontSize: sizes.micro, lineHeight: sizes.micro * 1.45 }]}>
              {layout.isSplit ? 'Your data is encrypted and protected by\nenterprise-grade security.' : 'Your data is encrypted and protected by enterprise-grade security.'}
            </Text>
          </View>
        </View>
      </View>
      {layout.barHeight ? <View style={[styles.bar, { height: layout.barHeight }]} /> : null}
    </View>
  );

  if (layout.isSplit) {
    return (
      <View style={styles.split}>
        <BrandPanel
          width={layout.brandWidth}
          height={height}
          contentWidth={layout.brandContentWidth}
          isShort={layout.isShort}
          sizes={sizes}
          figures={figures}
        />
        <ScrollView
          style={[styles.access, { width: layout.accessWidth }]}
          contentContainerStyle={[styles.accessContent, { paddingHorizontal: Math.min(48, Math.max(24, width * 0.03)), paddingVertical: height <= 704 ? 20 : 32 }]}
          keyboardShouldPersistTaps="handled"
        >
          {card}
        </ScrollView>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.page} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        ref={scrollRef}
        onScroll={(event) => {
          scrollY.current = event.nativeEvent.contentOffset.y;
        }}
        scrollEventThrottle={32}
        contentContainerStyle={[styles.column, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }]}
        keyboardShouldPersistTaps="handled"
      >
        {card}
        {figures ? (
          <View style={{ width: layout.cardWidth }}>
            <SignInFigures figures={figures} layout="grid" micro={sizes.micro} />
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const ALERT = StyleSheet.create({
  error: { borderColor: '#ffacba', backgroundColor: '#fff7f8' },
  success: { borderColor: '#a9dfd2', backgroundColor: '#f1fbf8' },
  info: { borderColor: '#b7d9f1', backgroundColor: '#f3f9fd' },
});
const ALERT_INK: Readonly<Record<Tone, string>> = { error: ink.danger, success: ink.success, info: ink.info };

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: ink.page },
  column: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16, gap: 16 },
  split: { flex: 1, flexDirection: 'row', backgroundColor: ink.page },
  access: { flexGrow: 0, backgroundImage: gradients.access },
  accessContent: { flexGrow: 1, alignItems: 'center', justifyContent: 'center' },
  card: {
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: ink.cardBorder,
    borderRadius: 16,
    backgroundColor: '#ffffff',
    boxShadow: shadows.card,
  },
  bar: { position: 'absolute', top: 0, left: 0, right: 0, backgroundImage: gradients.bar },
  logo: { alignItems: 'center', marginBottom: 20 },
  title: { fontFamily: fonts.bold, color: ink.title, textAlign: 'center' },
  subtitle: { fontFamily: fonts.medium, color: ink.muted, textAlign: 'center', marginTop: 8 },
  form: { marginTop: 28 },
  fieldLabel: { fontFamily: fonts.semibold, color: ink.label, marginBottom: 6.4 },
  input: {
    height: 50,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: ink.fieldBorder,
    borderRadius: 12,
    backgroundColor: ink.field,
    color: ink.title,
    fontFamily: fonts.semibold,
  },
  inputFocused: { borderColor: ink.focus, backgroundColor: '#ffffff', boxShadow: '0px 0px 0px 4px rgba(24, 114, 189, 0.13)' },
  passwordInput: { paddingRight: 56 },
  toggle: { position: 'absolute', right: 6, top: 3, width: 44, height: 44, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  togglePressed: { backgroundColor: '#eef7fd' },
  options: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 16 },
  remember: { flexDirection: 'row', alignItems: 'center', gap: 9.92 },
  checkbox: {
    width: 20.5,
    height: 20.5,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: '#8f9ba6',
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxOn: { borderColor: ink.toggle, backgroundColor: ink.toggle },
  rememberText: { fontFamily: fonts.semibold, color: ink.label },
  forgot: { justifyContent: 'center' },
  forgotText: { fontFamily: fonts.semibold, color: ink.forgot },
  alert: { flexDirection: 'row', alignItems: 'center', gap: 11.2, minHeight: 49.6, paddingVertical: 12, paddingHorizontal: 16, borderWidth: 1, borderRadius: 12 },
  alertText: { flex: 1, fontFamily: fonts.medium },
  submit: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 11.52,
    height: 56.8,
    paddingHorizontal: 20,
    borderRadius: 10,
    backgroundImage: gradients.submit,
    boxShadow: shadows.submit,
  },
  submitBusy: { opacity: 0.72 },
  submitPressed: { backgroundImage: 'linear-gradient(105deg, #064984 0%, #0a5597 100%)' },
  submitText: { fontFamily: fonts.semibold, fontSize: 15.04, lineHeight: 22.56, color: '#ffffff' },
  secure: { flexDirection: 'row', alignItems: 'center', gap: 15.2, minHeight: 94.4, marginTop: 24, paddingTop: 20, borderTopWidth: 1, borderTopColor: ink.rule },
  securePhone: { alignItems: 'flex-start', minHeight: 88.8 },
  shieldTile: { width: 48.8, height: 48.8, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ffffff', boxShadow: shadows.shieldTile },
  shieldTilePhone: { width: 45.6, height: 45.6 },
  flex: { flex: 1 },
  secureTitle: { fontFamily: fonts.bold, fontSize: 14.4, lineHeight: 18.72, color: ink.title, marginBottom: 3.52 },
  secureCopy: { fontFamily: fonts.medium, color: ink.muted },
});
