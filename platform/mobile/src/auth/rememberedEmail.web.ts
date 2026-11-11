/**
 * Web build of "Remember me": the address only, in localStorage, as the web
 * sign-in keeps it in a cookie. Never a token or a password.
 */
const KEY = 'edify.rememberedEmail';

export async function loadRememberedEmail(): Promise<string> {
  try {
    return globalThis.localStorage?.getItem(KEY) ?? '';
  } catch {
    return '';
  }
}

export async function rememberEmail(email: string | null): Promise<void> {
  try {
    if (email) {
      globalThis.localStorage?.setItem(KEY, email);
    } else {
      globalThis.localStorage?.removeItem(KEY);
    }
  } catch {
    // A convenience only.
  }
}
