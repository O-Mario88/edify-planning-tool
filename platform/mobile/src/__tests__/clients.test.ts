import { create, toBinary } from '@bufbuild/protobuf';
import { base64Encode } from '@bufbuild/protobuf/wire';

import { ApiError } from '../api/connect';
import type { ConnectTransport, FetchLike, FetchResponse } from '../api/connect';
import { createEdifyApi } from '../api/edifyApi';
import { SignInError, refreshTokens, signIn } from '../auth/identityClient';
import type { IdentityFetch } from '../auth/identityClient';
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
    expect(JSON.parse(init.body)).toEqual({ page: { page: 2, pageSize: 50 }, search: 'hill' });

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

describe('sign-in against the existing identity system', () => {
  const identityUrl = 'http://localhost:8000';

  test('posts the normalised email and returns the tokens', async () => {
    const fetchImpl = jest.fn<ReturnType<IdentityFetch>, Parameters<IdentityFetch>>(async () =>
      response(200, { accessToken: 'a', refreshToken: 'r', user: { id: 'u1' } }),
    );

    const tokens = await signIn(identityUrl, fetchImpl, '  Officer@Example.org ', 'the-password');

    expect(tokens).toEqual({ accessToken: 'a', refreshToken: 'r' });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/auth/login');
    expect(JSON.parse(init.body)).toEqual({ email: 'officer@example.org', password: 'the-password' });
  });

  test.each([
    ['a rejected password', response(401, { message: 'Invalid email or password.' }), 'rejected'],
    ['an account that needs a sign-in code', response(200, { mfaRequired: true, channel: 'email' }), 'mfa_required'],
    ['an answer without tokens', response(200, {}), 'unexpected'],
  ])('reports %s', async (_name, answer, kind) => {
    const failure = await signIn(identityUrl, async () => answer, 'a@b.org', 'x').catch(
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(SignInError);
    expect(failure).toMatchObject({ kind });
  });

  test('reports an unreachable server', async () => {
    const fetchImpl: IdentityFetch = async () => {
      throw new Error('offline');
    };

    await expect(signIn(identityUrl, fetchImpl, 'a@b.org', 'x')).rejects.toMatchObject({ kind: 'network' });
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

  test('a refresh presents the refresh token once and returns the new pair', async () => {
    const fetchImpl = jest.fn<ReturnType<IdentityFetch>, Parameters<IdentityFetch>>(async () =>
      response(200, { accessToken: 'a2', refreshToken: 'r2' }),
    );

    const tokens = await refreshTokens('http://localhost:8000', fetchImpl, 'r1');

    expect(tokens).toEqual({ accessToken: 'a2', refreshToken: 'r2' });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/auth/refresh');
    expect(JSON.parse(init.body)).toEqual({ refreshToken: 'r1' });
  });

  test('a refused refresh means the session is over', async () => {
    const tokens = await refreshTokens('http://localhost:8000', async () => response(401, {}), 'r1');

    expect(tokens).toBeNull();
  });
});
