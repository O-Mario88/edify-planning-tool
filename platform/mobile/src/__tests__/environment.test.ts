import { EnvironmentError, loadEnvironment } from '../config/environment';

const development = {
  EXPO_PUBLIC_EDIFY_ENV: 'development',
  EXPO_PUBLIC_EDIFY_GATEWAY_URL: 'http://localhost:8090/',
  EXPO_PUBLIC_EDIFY_IDENTITY_URL: 'http://10.0.2.2:8000',
};

const staging = {
  EXPO_PUBLIC_EDIFY_ENV: 'staging',
  EXPO_PUBLIC_EDIFY_GATEWAY_URL: 'https://gateway.staging.example.org',
  EXPO_PUBLIC_EDIFY_IDENTITY_URL: 'https://app.staging.example.org',
};

describe('loadEnvironment', () => {
  test('accepts a local development configuration and trims the trailing slash', () => {
    expect(loadEnvironment(development)).toEqual({
      name: 'development',
      gatewayUrl: 'http://localhost:8090',
      identityUrl: 'http://10.0.2.2:8000',
    });
  });

  test('accepts an https staging configuration', () => {
    expect(loadEnvironment(staging).name).toBe('staging');
  });

  test.each(['production', '', 'prod'])('refuses the environment "%s"', (name) => {
    expect(() => loadEnvironment({ ...staging, EXPO_PUBLIC_EDIFY_ENV: name })).toThrow(EnvironmentError);
  });

  test.each([
    'https://edifyplanning.app',
    'https://www.edifyplanning.app',
    'https://EdifyPlanning.app',
    'https://api.edifyplanning.app',
  ])('refuses the production site %s in every environment', (url) => {
    for (const base of [development, staging]) {
      expect(() => loadEnvironment({ ...base, EXPO_PUBLIC_EDIFY_GATEWAY_URL: url })).toThrow(/production site/);
      expect(() => loadEnvironment({ ...base, EXPO_PUBLIC_EDIFY_IDENTITY_URL: url })).toThrow(/production site/);
    }
  });

  test('staging refuses plain http and local hosts', () => {
    expect(() =>
      loadEnvironment({ ...staging, EXPO_PUBLIC_EDIFY_GATEWAY_URL: 'http://gateway.staging.example.org' }),
    ).toThrow(/https staging host/);
    expect(() =>
      loadEnvironment({ ...staging, EXPO_PUBLIC_EDIFY_IDENTITY_URL: 'https://localhost' }),
    ).toThrow(/https staging host/);
  });

  test('development refuses plain http to a public host', () => {
    expect(() =>
      loadEnvironment({ ...development, EXPO_PUBLIC_EDIFY_GATEWAY_URL: 'http://example.org' }),
    ).toThrow(/plain http/);
  });

  test.each([undefined, '', 'localhost:8090', 'https://host/path', 'ftp://host'])(
    'refuses the malformed base URL %p',
    (url) => {
      expect(() => loadEnvironment({ ...development, EXPO_PUBLIC_EDIFY_GATEWAY_URL: url })).toThrow(
        /must be a base URL/,
      );
    },
  );
});
