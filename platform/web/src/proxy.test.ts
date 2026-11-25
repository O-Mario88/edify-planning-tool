import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { ACCESS_COOKIE } from './lib/session';
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

describe('a download the gateway writes', () => {
  it("sends an impact report's evidence annex to the gateway's quick export", () => {
    const request = new NextRequest('http://localhost:3000/ia/impact-reports/cmwwi4g1600tspljcccqz/annex.csv');
    request.cookies.set(ACCESS_COOKIE, 'token');
    const answer = proxy(request);
    expect(answer.headers.get('x-middleware-rewrite')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fia%2Fimpact-reports%2Fcmwwi4g1600tspljcccqz%2Fannex.csv',
    );
  });

  it("sends a released version's download to the gateway's quick export", () => {
    const request = new NextRequest('http://localhost:3000/ia/impact-reports/cmwwi4g1600tspljcccqz/releases/cmwwl717p008prmhldfhk/download');
    request.cookies.set(ACCESS_COOKIE, 'token');
    const answer = proxy(request);
    expect(answer.headers.get('x-middleware-rewrite')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fia%2Fimpact-reports%2Fcmwwi4g1600tspljcccqz%2Freleases%2Fcmwwl717p008prmhldfhk%2Fdownload',
    );
  });

  it("sends an IA queue's Export to the gateway with the queue's own query", () => {
    const request = new NextRequest('http://localhost:3000/ia/returned/?export=xlsx&format=csv');
    request.cookies.set(ACCESS_COOKIE, 'token');
    const answer = proxy(request);
    expect(answer.headers.get('x-middleware-rewrite')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fia%2Freturned&export=xlsx&format=csv',
    );
  });

  it("sends the Verification queue's Export with its filters", () => {
    const request = new NextRequest('http://localhost:3000/ia/verification/?age=overdue&export=xlsx');
    request.cookies.set(ACCESS_COOKIE, 'token');
    expect(proxy(request).headers.get('x-middleware-rewrite')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fia%2Fverification&age=overdue&export=xlsx',
    );
  });

  it("sends a cluster's Export schools to the gateway", () => {
    const request = new NextRequest('http://localhost:3000/clusters/cmw9p8e4900p50wekhe46/schools/export');
    request.cookies.set(ACCESS_COOKIE, 'token');
    expect(proxy(request).headers.get('x-middleware-rewrite')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fclusters%2Fcmw9p8e4900p50wekhe46%2Fschools%2Fexport',
    );
  });

  it("sends Core School Oversight's CSV and its plan workbooks to the gateway, not its other tabs", () => {
    const send = (path: string) => {
      const request = new NextRequest(`http://localhost:3000${path}`);
      request.cookies.set(ACCESS_COOKIE, 'token');
      return proxy(request).headers.get('x-middleware-rewrite');
    };
    expect(send('/core-schools-oversight/?format=csv&fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcore-schools-oversight&format=csv&fy=2027',
    );
    expect(send('/core-schools-oversight/?tab=core_visits&format=xlsx')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcore-schools-oversight&tab=core_visits&format=xlsx',
    );
    expect(send('/core-schools-oversight/?tab=groups&format=xlsx')).toBeNull();
  });

  it("sends My Plan's Export to the gateway, but not the page", () => {
    const send = (path: string) => {
      const request = new NextRequest(`http://localhost:3000${path}`);
      request.cookies.set(ACCESS_COOKIE, 'token');
      return proxy(request).headers.get('x-middleware-rewrite');
    };
    expect(send('/my-plan/?export=xlsx&fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fmy-plan&export=xlsx&fy=2027',
    );
    expect(send('/my-plan?from_month=10&to_month=12&activity_type=planned')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fmy-plan&from_month=10&to_month=12&activity_type=planned',
    );
    expect(send('/my-plan?export=CSV')).toBe('http://localhost:3000/api/quick-export?target=%2Fmy-plan&export=CSV');
    expect(send('/my-plan?period=month&status=planned')).toBeNull();
    expect(send('/fund-requests/weekly?export=xlsx&fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Ffund-requests%2Fweekly&export=xlsx&fy=2027',
    );
    expect(send('/fund-requests/weekly?fy=2027')).toBeNull();
    expect(send('/my-plan?format=csv')).toBeNull();
  });

  it("sends a Country Planning Oversight table's Export to the gateway, but not All Tables yet", () => {
    const send = (path: string) => {
      const request = new NextRequest(`http://localhost:3000${path}`);
      request.cookies.set(ACCESS_COOKIE, 'token');
      return proxy(request).headers.get('x-middleware-rewrite');
    };
    expect(send('/country-planning-oversight/table-export/not-planned?fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcountry-planning-oversight%2Ftable-export%2Fnot-planned&fy=2027',
    );
    expect(send('/country-planning-oversight/table-export/all')).toBeNull();
    expect(send('/country-planning-oversight/export?fy=2027&activity_type=planned')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcountry-planning-oversight%2Fexport&fy=2027&activity_type=planned',
    );
    expect(send('/ssa/upload/template')).toBe('http://localhost:3000/api/quick-export?target=%2Fssa%2Fupload%2Ftemplate');
    expect(send('/ia/school-evidence/learning/template.csv')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fia%2Fschool-evidence%2Flearning%2Ftemplate.csv',
    );
    expect(send('/budget/export?period_type=fy&fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fbudget%2Fexport&period_type=fy&fy=2027',
    );
    expect(send('/country-planning-oversight/execution/export?fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcountry-planning-oversight%2Fexecution%2Fexport&fy=2027',
    );
    expect(send('/country-planning-oversight/execution/records-export/due?fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcountry-planning-oversight%2Fexecution%2Frecords-export%2Fdue&fy=2027',
    );
    expect(send('/country-planning-oversight/coverage-export?fy=2027')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fcountry-planning-oversight%2Fcoverage-export&fy=2027',
    );
    expect(send('/team-planning-oversight/export/?format=csv')).toBe(
      'http://localhost:3000/api/quick-export?target=%2Fteam-planning-oversight%2Fexport&format=csv',
    );
  });

  it('leaves the queue page itself to the page', () => {
    const request = new NextRequest('http://localhost:3000/ia/history/?page=2');
    request.cookies.set(ACCESS_COOKIE, 'token');
    expect(proxy(request).headers.get('x-middleware-rewrite')).toBeNull();
  });
});
