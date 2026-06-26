import { describe, it, expect } from 'vitest';
import { validatePassword, isValidPassword } from './password-rules';
import { generateToken, hashToken, compareHashes } from './auth-tokens';

describe('password rules', () => {
  it('accepts a strong password', () => {
    expect(validatePassword('Str0ng!pass', 'user@edify.org')).toEqual([]);
    expect(isValidPassword('Str0ng!pass', 'user@edify.org')).toBe(true);
  });

  it('rejects shorter than 8 chars', () => {
    expect(validatePassword('Ab1!')).toContain('Password must be at least 8 characters long.');
  });

  it('requires uppercase, lowercase, digit, symbol', () => {
    expect(validatePassword('alllowercase1!')).toContain('Password must include at least one uppercase letter.');
    expect(validatePassword('ALLUPPERCASE1!')).toContain('Password must include at least one lowercase letter.');
    expect(validatePassword('MixedCase!')).toContain('Password must include at least one number.');
    expect(validatePassword('MixedCase1')).toContain('Password must include at least one symbol (e.g. !@#$%).');
  });

  it('rejects empty', () => {
    expect(validatePassword('')).toEqual(['Password cannot be empty.']);
  });

  it('rejects password equal to email (case-insensitive)', () => {
    expect(validatePassword('User@Edify.Org', 'user@edify.org')).toContain(
      'Password cannot be the same as your email address.',
    );
  });
});

describe('auth tokens', () => {
  it('generates a 64-char hex token', () => {
    const t = generateToken();
    expect(t).toMatch(/^[0-9a-f]{64}$/);
  });

  it('generates unique tokens', () => {
    expect(generateToken()).not.toBe(generateToken());
  });

  it('hashes deterministically (same token → same hash)', () => {
    const t = generateToken();
    expect(hashToken(t)).toBe(hashToken(t));
  });

  it('hash differs from raw token', () => {
    const t = generateToken();
    expect(hashToken(t)).not.toBe(t);
  });

  it('compareHashes is constant-time and correct', () => {
    const t = generateToken();
    const h = hashToken(t);
    expect(compareHashes(h, hashToken(t))).toBe(true);
    expect(compareHashes(h, hashToken(generateToken()))).toBe(false);
  });
});
