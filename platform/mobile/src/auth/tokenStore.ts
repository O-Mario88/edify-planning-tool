/**
 * Where the app keeps its tokens: the platform keystore (iOS Keychain,
 * Android Keystore) through expo-secure-store. Never AsyncStorage, never a
 * file, never a log line.
 */
import * as SecureStore from 'expo-secure-store';

export interface Tokens {
  readonly accessToken: string;
  readonly refreshToken: string;
}

export interface TokenStore {
  load(): Promise<Tokens | null>;
  save(tokens: Tokens): Promise<void>;
  clear(): Promise<void>;
}

const ACCESS_KEY = 'edify.accessToken';
const REFRESH_KEY = 'edify.refreshToken';

export const secureTokenStore: TokenStore = {
  async load() {
    const [accessToken, refreshToken] = await Promise.all([
      SecureStore.getItemAsync(ACCESS_KEY),
      SecureStore.getItemAsync(REFRESH_KEY),
    ]);
    return accessToken && refreshToken ? { accessToken, refreshToken } : null;
  },
  async save(tokens) {
    await Promise.all([
      SecureStore.setItemAsync(ACCESS_KEY, tokens.accessToken),
      SecureStore.setItemAsync(REFRESH_KEY, tokens.refreshToken),
    ]);
  },
  async clear() {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_KEY),
      SecureStore.deleteItemAsync(REFRESH_KEY),
    ]);
  },
};
