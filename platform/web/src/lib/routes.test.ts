import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { externalOrigin, isSameOrigin, isSecureRequest, seeOther } from './routes';

describe('proxy-aware routes helpers', () => {
  it('respects X-Forwarded-Proto and X-Forwarded-Host behind TLS proxy', () => {
    const req = new NextRequest('http://127.0.0.1:3000/auth/sign-in', {
      method: 'POST',
      headers: {
        'x-forwarded-proto': 'https',
        'x-forwarded-host': 'staging.example.org',
        origin: 'https://staging.example.org',
      },
    });
    expect(externalOrigin(req).origin).toBe('https://staging.example.org');
    expect(isSecureRequest(req)).toBe(true);
    expect(isSameOrigin(req)).toBe(true);
    expect(seeOther(req, '/home').headers.get('location')).toBe('https://staging.example.org/home');
  });

  it('rejects cross-site origins even behind a proxy', () => {
    const req = new NextRequest('http://127.0.0.1:3000/route-planner', {
      method: 'POST',
      headers: {
        'x-forwarded-proto': 'https',
        'x-forwarded-host': 'staging.example.org',
        origin: 'https://evil.example',
      },
    });
    expect(isSameOrigin(req)).toBe(false);
  });
});
