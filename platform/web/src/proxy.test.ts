import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { proxy } from './proxy';

describe('a request without a session', () => {
  it('sends a page to renew the session first', () => {
    const answer = proxy(new NextRequest('http://localhost:3000/my-plan/smart-route?date=2026-11-18'));
    expect(answer.status).toBe(307);
    expect(answer.headers.get('location')).toBe('http://localhost:3000/auth/refresh?next=%2Fmy-plan%2Fsmart-route%3Fdate%3D2026-11-18');
  });

  it('answers a save with 401, which the page renews and retries, not a redirect a POST cannot follow', async () => {
    const answer = proxy(new NextRequest('http://localhost:3000/route-planner', { method: 'POST', body: '{}' }));
    expect(answer.status).toBe(401);
    expect(await answer.json()).toEqual({ error: 'signed_out' });
  });
});
