import { create, toBinary } from '@bufbuild/protobuf';
import { base64Encode } from '@bufbuild/protobuf/wire';

import { ApiError } from '../api/connect';
import type { ConnectTransport, FetchLike, FetchResponse } from '../api/connect';
import { createEdifyApi } from '../api/edifyApi';
import {
  SignInError,
  appDevice,
  publicTransport,
  refreshTokens,
  requestPasswordReset,
  revokeSession,
  signIn,
  signInFigures,
  verifySignInCode,
} from '../auth/identityClient';
import { ErrorDetailSchema } from '../gen/edify/common/v1/common_pb';

function response(status: number, body: unknown, requestId = ''): FetchResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: (name) => (name === 'X-Request-Id' ? requestId : null) },
  };
}

function transport(fetchImpl: FetchLike, token: string | null = 'access-token'): ConnectTransport {
  return { baseUrl: 'http://localhost:8090', fetch: fetchImpl, getAccessToken: async () => token };
}

describe('gateway client', () => {
  test('lists schools through the contract route with the bearer token', async () => {
    const fetchImpl = jest.fn<ReturnType<FetchLike>, Parameters<FetchLike>>(async () =>
      response(200, {
        schools: [
          { id: 'cm1', schoolId: '1026', name: 'Central Primary', schoolType: 'client', enrollment: 173 },
          { id: 'cm2', schoolId: '1027', name: 'Hill View', schoolType: 'core' },
        ],
        page: { page: 2, pageSize: 50, total: '120', totalPages: 3 },
        aFieldFromANewerGateway: true,
      }),
    );

    const result = await createEdifyApi(transport(fetchImpl)).listMySchools({
      page: 2,
      pageSize: 50,
      search: 'hill',
    });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://localhost:8090/edify.schools.v1.SchoolService/ListMySchools');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer access-token');
    expect(JSON.parse(init.body ?? '')).toEqual({ page: { page: 2, pageSize: 50 }, search: 'hill' });

    expect(result.schools.map((school) => school.schoolId)).toEqual(['1026', '1027']);
    expect(result.schools[0].enrollment).toBe(173);
    expect(result.schools[1].enrollment).toBeUndefined();
    expect(result.page?.total).toBe(120n);
    expect(result.page?.totalPages).toBe(3);
  });

  test('sends no Authorization header when signed out', async () => {
    const fetchImpl = jest.fn<ReturnType<FetchLike>, Parameters<FetchLike>>(async () =>
      response(200, { session: { userId: 'u1' } }),
    );

    await createEdifyApi(transport(fetchImpl, null)).getSession();

    expect(fetchImpl.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  test('turns a structured gateway error into an ApiError with its reason and request id', async () => {
    const detail = toBinary(
      ErrorDetailSchema,
      create(ErrorDetailSchema, { code: 'AUTH_TOKEN_EXPIRED', requestId: 'req-12345678', traceId: 'abc' }),
    );
    const fetchImpl: FetchLike = async () =>
      response(401, {
        code: 'unauthenticated',
        message: 'Your session has expired. Please sign in again.',
        details: [{ type: 'edify.common.v1.ErrorDetail', value: base64Encode(detail, 'std_raw') }],
      });

    const failure = await createEdifyApi(transport(fetchImpl))
      .getSession()
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      code: 'unauthenticated',
      reason: 'AUTH_TOKEN_EXPIRED',
      requestId: 'req-12345678',
      message: 'Your session has expired. Please sign in again.',
    });
  });

  test('reports an unstructured failure by status, with the request id header', async () => {
    const fetchImpl: FetchLike = async () => ({
      ...response(502, null, 'edge-req-0001'),
      json: async () => {
        throw new Error('not json');
      },
    });

    const failure = await createEdifyApi(transport(fetchImpl))
      .getSession()
      .catch((error: unknown) => error);

    expect(failure).toMatchObject({ code: 'http_502', reason: '', requestId: 'edge-req-0001' });
  });

  test('reports a network failure without leaking its cause', async () => {
    const fetchImpl: FetchLike = async () => {
      throw new Error('getaddrinfo ENOTFOUND internal-host');
    };

    const failure = await createEdifyApi(transport(fetchImpl))
      .getSession()
      .catch((error: unknown) => error);

    expect(failure).toMatchObject({ code: 'network', message: 'Could not reach the server.' });
  });

  test('a response without a session is an error, not an empty session', async () => {
    const fetchImpl: FetchLike = async () => response(200, {});

    await expect(createEdifyApi(transport(fetchImpl)).getSession()).rejects.toBeInstanceOf(ApiError);
  });
});

// Signing in goes to the Go gateway's SignInService (owner brief, 2026-11-11).
const SIGN_IN = 'http://localhost:8090/edify.identity.v1.SignInService';

function gatewayFetch(answer: FetchResponse | (() => never)) {
  return jest.fn<ReturnType<FetchLike>, Parameters<FetchLike>>(async () =>
    typeof answer === 'function' ? answer() : answer,
  );
}

function sent(fetchImpl: jest.Mock<ReturnType<FetchLike>, Parameters<FetchLike>>) {
  const [url, init] = fetchImpl.mock.calls[0];
  return { url, body: JSON.parse(init.body) as unknown, auth: init.headers.Authorization };
}

const offline = () => {
  throw new Error('offline');
};

describe('signing in through the gateway', () => {
  test('a native build says phone or tablet; the web build says nothing', async () => {
    expect(appDevice('android', false, 412, 915)).toBe('mobile');
    expect(appDevice('android', false, 800, 1280)).toBe('tablet');
    expect(appDevice('ios', true, 1024, 1366)).toBe('tablet');
    expect(appDevice('web', false, 390, 844)).toBeNull();

    const fetchImpl = gatewayFetch(response(200, {}));
    await signInFigures(publicTransport('http://localhost:8090', fetchImpl, 'mobile'));
    expect(fetchImpl.mock.calls[0][1].headers['X-Edify-Device']).toBe('mobile');
    const web = gatewayFetch(response(200, {}));
    await signInFigures(publicTransport('http://localhost:8090', web));
    expect(web.mock.calls[0][1].headers['X-Edify-Device']).toBeUndefined();
  });

  test('posts the normalised email to SignIn, without a token, and returns the session', async () => {
    const fetchImpl = gatewayFetch(
      response(200, { session: { accessToken: 'a', refreshToken: 'r', account: { userId: 'u1' } } }),
    );

    const result = await signIn(publicTransport('http://localhost:8090', fetchImpl), '  Officer@Example.org ', 'the-password');

    expect(result).toEqual({ kind: 'session', tokens: { accessToken: 'a', refreshToken: 'r' } });
    expect(sent(fetchImpl)).toEqual({
      url: `${SIGN_IN}/SignIn`,
      body: { email: 'officer@example.org', password: 'the-password' },
      auth: undefined,
    });
  });

  test('an account with a second factor is asked for its code, then the code opens the session', async () => {
    const asked = gatewayFetch(
      response(200, {
        codeRequired: { challengeToken: 'ch-1', channel: 'email', destinationHint: 'p•••••@edify.org', expiresInSeconds: 600 },
      }),
    );
    const result = await signIn(publicTransport('http://localhost:8090', asked), 'paul@edify.org', 'x');
    expect(result).toEqual({
      kind: 'code',
      challenge: { token: 'ch-1', channel: 'email', hint: 'p•••••@edify.org', expiresInSeconds: 600 },
    });

    const verified = gatewayFetch(response(200, { session: { accessToken: 'a', refreshToken: 'r' } }));
    const challenge = result.kind === 'code' ? result.challenge : null;
    await expect(
      verifySignInCode(publicTransport('http://localhost:8090', verified), challenge!, '123 456'),
    ).resolves.toEqual({ accessToken: 'a', refreshToken: 'r' });
    expect(sent(verified)).toMatchObject({ url: `${SIGN_IN}/VerifySignInCode`, body: { challengeToken: 'ch-1', code: '123456' } });
  });

  test.each([
    ['a rejected password', response(401, { code: 'unauthenticated', message: 'Invalid email or password.' }), 'rejected'],
    ['too many attempts', response(429, { code: 'resource_exhausted', message: 'Too many attempts.' }), 'rate_limited'],
    ['an answer without tokens', response(200, { session: {} }), 'unexpected'],
  ])('reports %s', async (_name, answer, kind) => {
    const failure = await signIn(publicTransport('http://localhost:8090', gatewayFetch(answer)), 'a@b.org', 'x').catch(
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(SignInError);
    expect(failure).toMatchObject({ kind });
  });

  test('the gateway\'s refusal is shown in its own words', async () => {
    const answer = response(401, { code: 'unauthenticated', message: 'Invalid email or password.' });
    await expect(signIn(publicTransport('http://localhost:8090', gatewayFetch(answer)), 'a@b.org', 'x')).rejects.toThrow(
      'Invalid email or password.',
    );
  });

  test('reports an unreachable server', async () => {
    await expect(signIn(publicTransport('http://localhost:8090', gatewayFetch(offline)), 'a@b.org', 'x')).rejects.toMatchObject({
      kind: 'network',
    });
  });
});

describe('short-lived access tokens', () => {
  const expired = () => response(401, { code: 'unauthenticated', message: 'Your session has expired.' });

  test('a call refused as expired is retried once after the session is refreshed', async () => {
    let token = 'old-token';
    const seen: string[] = [];
    const fetchImpl: FetchLike = async (_url, init) => {
      seen.push(init.headers.Authorization);
      return init.headers.Authorization === 'Bearer new-token'
        ? response(200, { session: { userId: 'u1' } })
        : expired();
    };
    const refresh = jest.fn(async () => {
      token = 'new-token';
      return true;
    });

    const session = await createEdifyApi({
      baseUrl: 'http://localhost:8090',
      fetch: fetchImpl,
      getAccessToken: async () => token,
      refresh,
    }).getSession();

    expect(session.userId).toBe('u1');
    expect(seen).toEqual(['Bearer old-token', 'Bearer new-token']);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  test('when the session cannot be refreshed the call fails as unauthenticated, without a retry', async () => {
    const fetchImpl = jest.fn<ReturnType<FetchLike>, Parameters<FetchLike>>(async () => expired());

    const failure = await createEdifyApi({
      baseUrl: 'http://localhost:8090',
      fetch: fetchImpl,
      getAccessToken: async () => 'old-token',
      refresh: async () => false,
    })
      .getSession()
      .catch((error: unknown) => error);

    expect(failure).toMatchObject({ code: 'unauthenticated' });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  test('a refresh presents the refresh token once, to the gateway, and returns the new pair', async () => {
    const fetchImpl = gatewayFetch(response(200, { accessToken: 'a2', refreshToken: 'r2' }));

    const tokens = await refreshTokens(publicTransport('http://localhost:8090', fetchImpl), 'r1');

    expect(tokens).toEqual({ accessToken: 'a2', refreshToken: 'r2' });
    expect(sent(fetchImpl)).toEqual({ url: `${SIGN_IN}/RefreshSession`, body: { refreshToken: 'r1' }, auth: undefined });
  });

  test('a refused refresh means the session is over; an unreachable server keeps it', async () => {
    const refused = gatewayFetch(response(401, { code: 'unauthenticated', message: 'Invalid or expired refresh token.' }));
    await expect(refreshTokens(publicTransport('http://localhost:8090', refused), 'r1')).resolves.toBeNull();

    await expect(refreshTokens(publicTransport('http://localhost:8090', gatewayFetch(offline)), 'r1')).rejects.toMatchObject({
      kind: 'network',
    });
    const broken = gatewayFetch(response(503, { code: 'unavailable', message: 'down' }));
    await expect(refreshTokens(publicTransport('http://localhost:8090', broken), 'r1')).rejects.toBeInstanceOf(SignInError);
  });
});

describe('the sign-in screen\'s other calls to the gateway', () => {
  test('a reset link is asked for with the address as typed, lower-cased', async () => {
    const fetchImpl = gatewayFetch(response(200, {}));
    await expect(requestPasswordReset(publicTransport('http://localhost:8090', fetchImpl), ' Grace@School.ORG ')).resolves.toBe(true);
    expect(sent(fetchImpl)).toMatchObject({ url: `${SIGN_IN}/RequestPasswordReset`, body: { email: 'grace@school.org' } });
  });

  test('a refused or unreachable reset request says so', async () => {
    const refused = gatewayFetch(response(429, { code: 'resource_exhausted', message: 'Too many attempts.' }));
    await expect(requestPasswordReset(publicTransport('http://localhost:8090', refused), 'a@b.org')).resolves.toBe(false);
    await expect(requestPasswordReset(publicTransport('http://localhost:8090', gatewayFetch(offline)), 'a@b.org')).resolves.toBe(false);
  });

  test('signing out revokes the refresh token, and never fails the sign-out', async () => {
    const fetchImpl = gatewayFetch(offline);
    await expect(revokeSession(publicTransport('http://localhost:8090', fetchImpl), 'refresh-1')).resolves.toBeUndefined();
    expect(sent(fetchImpl)).toMatchObject({ url: `${SIGN_IN}/SignOut`, body: { refreshToken: 'refresh-1' } });
  });

  test('the figures are read as the web page shows them, or not at all', async () => {
    const figures = { portfolio: '700', schoolsReached: '700', schoolsVisited: '0', schoolsTrained: '0', ssaCompleted: '306' };
    const fetchImpl = gatewayFetch(response(200, figures));
    await expect(signInFigures(publicTransport('http://localhost:8090', fetchImpl))).resolves.toEqual(figures);
    expect(sent(fetchImpl).url).toBe(`${SIGN_IN}/GetSignInFigures`);
    const partial = gatewayFetch(response(200, { portfolio: '700' }));
    await expect(signInFigures(publicTransport('http://localhost:8090', partial))).resolves.toBeNull();
  });
});
