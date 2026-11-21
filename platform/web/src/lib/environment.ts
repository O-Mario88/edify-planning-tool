/**
 * Which backends this web build may reach.
 *
 * A build is `development` or `staging`. It refuses to start as anything else
 * and refuses any edifyplanning.app host until a production release is
 * approved: the same rule as the app's src/config/environment.ts.
 */
export type EdifyEnvironment = 'development' | 'staging';

export interface WebEnvironment {
  readonly name: EdifyEnvironment;
  /** The Go gateway: every answer the pages show comes from here. */
  readonly gatewayUrl: string;
  /** The existing web, for the pages not yet moved here. */
  readonly existingWebUrl: string;
}

export class EnvironmentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EnvironmentError';
  }
}

const PRODUCTION_HOSTS: readonly string[] = ['edifyplanning.app', 'www.edifyplanning.app'];
const LOCAL_HOSTS: readonly string[] = ['localhost', '127.0.0.1', '[::1]'];
const PRIVATE_NETWORK = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;
const URL_PATTERN = /^(https?):\/\/([^/:?#]+|\[::1\])(:\d+)?$/;

interface ParsedUrl {
  readonly url: string;
  readonly scheme: string;
  readonly host: string;
}

function parseBaseUrl(label: string, raw: string | undefined): ParsedUrl {
  const url = (raw ?? '').trim().replace(/\/+$/, '');
  const match = URL_PATTERN.exec(url);
  if (!match || !match[1] || !match[2]) {
    throw new EnvironmentError(`${label} must be a base URL such as https://host:port (got "${url}")`);
  }
  return { url, scheme: match[1], host: match[2].toLowerCase() };
}

/** True for a production host of Edify. */
export function isProductionHost(host: string): boolean {
  const bare = host.toLowerCase().replace(/\.$/, '');
  return PRODUCTION_HOSTS.includes(bare) || bare.endsWith('.edifyplanning.app');
}

function assertAllowed(label: string, name: EdifyEnvironment, parsed: ParsedUrl): void {
  if (isProductionHost(parsed.host)) {
    throw new EnvironmentError(`${label} points at the production site (${parsed.host}); this build may not use it`);
  }
  const local = LOCAL_HOSTS.includes(parsed.host) || PRIVATE_NETWORK.test(parsed.host);
  if (name === 'staging' && (parsed.scheme !== 'https' || local)) {
    throw new EnvironmentError(`${label} must be an https staging host (got ${parsed.host})`);
  }
  if (name === 'development' && parsed.scheme !== 'https' && !local) {
    throw new EnvironmentError(`${label} may use plain http only on this machine or network`);
  }
}

export function loadEnvironment(vars: Readonly<Record<string, string | undefined>>): WebEnvironment {
  const name = (vars.EDIFY_ENV ?? '').trim().toLowerCase();
  if (name !== 'development' && name !== 'staging') {
    throw new EnvironmentError(
      `EDIFY_ENV must be "development" or "staging" (got "${name}"); a production build needs an approved release`,
    );
  }
  const gateway = parseBaseUrl('EDIFY_GATEWAY_URL', vars.EDIFY_GATEWAY_URL);
  assertAllowed('EDIFY_GATEWAY_URL', name, gateway);
  // EDIFY_EXISTING_WEB_URL is optional in Django-absent cutover deployments.
  const rawExisting = (vars.EDIFY_EXISTING_WEB_URL ?? '').trim();
  let existingWebUrl = '';
  if (rawExisting !== '') {
    const existing = parseBaseUrl('EDIFY_EXISTING_WEB_URL', rawExisting);
    assertAllowed('EDIFY_EXISTING_WEB_URL', name, existing);
    existingWebUrl = existing.url;
  }
  return { name, gatewayUrl: gateway.url, existingWebUrl };
}

let cached: WebEnvironment | undefined;

/** The server's environment, read once. */
export function environment(): WebEnvironment {
  cached ??= loadEnvironment(process.env);
  return cached;
}
