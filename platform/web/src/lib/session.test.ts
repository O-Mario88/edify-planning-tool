import { describe, expect, it } from 'vitest';

import { accessCookie, refreshCookie, safeNext } from './session';

describe('safeNext', () => {
  it('keeps a path on this site', () => {
    expect(safeNext('/schools?tab=clustered')).toBe('/schools?tab=clustered');
  });

  it.each(['https://evil.example/', '//evil.example', '/\\evil.example', 'schools', '', null, undefined, '/auth/refresh', '/login'])(
    'refuses %s',
    (value) => {
      expect(safeNext(value)).toBe('/home');
    },
  );
});

describe('session cookies', () => {
  it('are httpOnly; the refresh token goes only to /auth, same-site strictly', () => {
    expect(accessCookie(true)).toMatchObject({ httpOnly: true, secure: true, path: '/', sameSite: 'lax' });
    expect(refreshCookie(false)).toMatchObject({ httpOnly: true, secure: false, path: '/auth', sameSite: 'strict' });
  });
});
