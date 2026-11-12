import { describe, expect, it } from 'vitest';

import { EnvironmentError, isProductionHost, loadEnvironment } from './environment';

const DEV = { EDIFY_ENV: 'development', EDIFY_GATEWAY_URL: 'http://127.0.0.1:8090', EDIFY_EXISTING_WEB_URL: 'http://localhost:8010' };

describe('loadEnvironment', () => {
  it('accepts a development build on this machine', () => {
    expect(loadEnvironment(DEV)).toEqual({ name: 'development', gatewayUrl: 'http://127.0.0.1:8090', existingWebUrl: 'http://localhost:8010' });
  });

  it('refuses a build that is neither development nor staging', () => {
    expect(() => loadEnvironment({ ...DEV, EDIFY_ENV: 'production' })).toThrow(EnvironmentError);
    expect(() => loadEnvironment({ ...DEV, EDIFY_ENV: '' })).toThrow(EnvironmentError);
  });

  it.each(['https://edifyplanning.app', 'https://www.edifyplanning.app', 'https://api.edifyplanning.app', 'https://EDIFYPLANNING.APP'])(
    'refuses the production host %s',
    (url) => {
      expect(() => loadEnvironment({ ...DEV, EDIFY_GATEWAY_URL: url })).toThrow(/production/);
      expect(() => loadEnvironment({ ...DEV, EDIFY_EXISTING_WEB_URL: url })).toThrow(/production/);
    },
  );

  it('refuses plain http away from this machine, and a staging build on http', () => {
    expect(() => loadEnvironment({ ...DEV, EDIFY_GATEWAY_URL: 'http://gateway.example.com' })).toThrow(EnvironmentError);
    expect(() => loadEnvironment({ ...DEV, EDIFY_ENV: 'staging' })).toThrow(/https staging/);
  });

  it('refuses a URL with a path or no scheme', () => {
    expect(() => loadEnvironment({ ...DEV, EDIFY_GATEWAY_URL: 'http://localhost:8090/api' })).toThrow(EnvironmentError);
    expect(() => loadEnvironment({ ...DEV, EDIFY_GATEWAY_URL: 'localhost:8090' })).toThrow(EnvironmentError);
  });

  it('names production hosts', () => {
    expect(isProductionHost('edifyplanning.app.')).toBe(true);
    expect(isProductionHost('staging.edify.example')).toBe(false);
  });
});
