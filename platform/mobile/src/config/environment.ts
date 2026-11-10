/**
 * Which backends this build of the app may talk to.
 *
 * The app is configured at build time through EXPO_PUBLIC_* variables. Until a
 * production release is approved, this module refuses the production site
 * outright: a development or staging build cannot be pointed at it, whatever
 * its configuration says.
 */

export type EdifyEnvironment = 'development' | 'staging';

export interface AppEnvironment {
  readonly name: EdifyEnvironment;
  /** The Go gateway: every business call goes here. */
  readonly gatewayUrl: string;
  /** The existing identity system of the same environment: sign-in only. */
  readonly identityUrl: string;
}

export class EnvironmentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EnvironmentError';
  }
}

/** Hosts of the production site. Never reachable from this build. */
const PRODUCTION_HOSTS: readonly string[] = ['edifyplanning.app', 'www.edifyplanning.app'];

/** Hosts a development build may reach over plain HTTP. */
const LOCAL_HOSTS: readonly string[] = ['localhost', '127.0.0.1', '10.0.2.2'];

const PRIVATE_NETWORK = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;
const URL_PATTERN = /^(https?):\/\/([^/:?#]+)(:\d+)?$/;

interface ParsedUrl {
  readonly scheme: string;
  readonly host: string;
}

function parseBaseUrl(label: string, raw: string | undefined): ParsedUrl & { url: string } {
  const url = (raw ?? '').trim().replace(/\/+$/, '');
  const match = URL_PATTERN.exec(url);
  if (!match) {
    throw new EnvironmentError(`${label} must be a base URL such as https://host:port (got "${url}")`);
  }
  return { url, scheme: match[1], host: match[2].toLowerCase() };
}

function assertAllowed(label: string, name: EdifyEnvironment, parsed: ParsedUrl): void {
  if (PRODUCTION_HOSTS.includes(parsed.host) || parsed.host.endsWith('.edifyplanning.app')) {
    throw new EnvironmentError(
      `${label} points at the production site (${parsed.host}); this build may not use it`,
    );
  }
  const local = LOCAL_HOSTS.includes(parsed.host) || PRIVATE_NETWORK.test(parsed.host);
  if (name === 'staging' && (parsed.scheme !== 'https' || local)) {
    throw new EnvironmentError(`${label} must be an https staging host (got ${parsed.host})`);
  }
  if (name === 'development' && parsed.scheme !== 'https' && !local) {
    throw new EnvironmentError(`${label} may use plain http only on this machine or network`);
  }
}

export function loadEnvironment(vars: Readonly<Record<string, string | undefined>>): AppEnvironment {
  const name = (vars.EXPO_PUBLIC_EDIFY_ENV ?? '').trim().toLowerCase();
  if (name !== 'development' && name !== 'staging') {
    throw new EnvironmentError(
      `EXPO_PUBLIC_EDIFY_ENV must be "development" or "staging" (got "${name}"); ` +
        'a production build needs an approved release',
    );
  }
  const gateway = parseBaseUrl('EXPO_PUBLIC_EDIFY_GATEWAY_URL', vars.EXPO_PUBLIC_EDIFY_GATEWAY_URL);
  const identity = parseBaseUrl('EXPO_PUBLIC_EDIFY_IDENTITY_URL', vars.EXPO_PUBLIC_EDIFY_IDENTITY_URL);
  assertAllowed('EXPO_PUBLIC_EDIFY_GATEWAY_URL', name, gateway);
  assertAllowed('EXPO_PUBLIC_EDIFY_IDENTITY_URL', name, identity);
  return { name, gatewayUrl: gateway.url, identityUrl: identity.url };
}
