/**
 * "Remember me" on the sign-in screen keeps the email address for next time,
 * as the web sign-in does (apps/frontend/views/auth_views.py: an address the
 * person chose to have prefilled, never a token or a password). Kept in the
 * phone's keystore like the tokens.
 */
import * as SecureStore from 'expo-secure-store';

const KEY = 'edify.rememberedEmail';

export async function loadRememberedEmail(): Promise<string> {
  try {
    return (await SecureStore.getItemAsync(KEY)) ?? '';
  } catch {
    return '';
  }
}

export async function rememberEmail(email: string | null): Promise<void> {
  try {
    if (email) {
      await SecureStore.setItemAsync(KEY, email);
    } else {
      await SecureStore.deleteItemAsync(KEY);
    }
  } catch {
    // A convenience only: failing to remember never blocks signing in.
  }
}
