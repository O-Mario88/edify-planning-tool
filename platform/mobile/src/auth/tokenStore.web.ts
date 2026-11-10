/**
 * Web build of the token store, used for development in a browser.
 *
 * A browser has no keystore, and localStorage or sessionStorage is readable by
 * any script on the page. Tokens are therefore kept in memory only: reloading
 * the page signs the person out. The native apps use tokenStore.ts.
 */
import type { TokenStore, Tokens } from './tokenStore';

export type { TokenStore, Tokens } from './tokenStore';

let current: Tokens | null = null;

export const secureTokenStore: TokenStore = {
  async load() {
    return current;
  },
  async save(tokens) {
    current = { accessToken: tokens.accessToken, refreshToken: tokens.refreshToken };
  },
  async clear() {
    current = null;
  },
};
