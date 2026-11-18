import type { Metadata } from 'next';

import { Card } from '@/components/blocks/Card';
import { BUTTON_PRIMARY } from '@/components/blocks/buttons';
import { AdminOnly, CountryFrame, Note, accountNames, readReader } from '@/components/countries/CountryFrame';
import { FIELD } from '@/components/countries/fields';
import { MembershipManager } from '@/components/countries/MembershipManager';
import { FeedTable } from '@/components/page/FeedTable';
import { CountryService } from '@/gen/edify/countries/v1/countries_pb';
import { AccountAdminService } from '@/gen/edify/identity/v1/accounts_pb';
import { asReader } from '@/lib/auth';
import { MEMBERSHIPS_PATH, accountsTable, grantableCountries, kampalaToday, membershipsPath } from '@/lib/countryAdmin';
import { gatewayClient, isNotFound } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Country Memberships - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

const SEARCH_PAGE = 20;
const MAX_SEARCH = 100;

function one(value: string | string[] | undefined, max: number): string {
  return (Array.isArray(value) ? value[0] : value)?.trim().slice(0, max) ?? '';
}

/*
 * Country memberships (Edify Global, docs/migration/80 §11 and §12): find an
 * account, see every country membership it ever had, grant a country and
 * revoke one with its reason, and, in a country whose roles come from the
 * registry, assign and revoke the roles the account holds there. Accounts come from AccountAdminService, the
 * memberships from CountryService (both Go); only the gateway writes.
 */
export default async function MembershipsPage({ searchParams }: { searchParams: Search }) {
  const reader = await readReader();
  if (!reader.isAdmin) return <AdminOnly />;
  const query = await searchParams;
  const search = one(query.q, MAX_SEARCH);
  const userId = one(query.user, 30);

  const found = search
    ? await asReader((token) => gatewayClient(AccountAdminService, token).listAccounts({ search, page: { page: 1, pageSize: SEARCH_PAGE } }))
    : null;

  let selected = null;
  if (userId) {
    selected = await asReader(async (token) => {
      const accounts = gatewayClient(AccountAdminService, token);
      const countries = gatewayClient(CountryService, token);
      const account = await accounts.getAccount({ userId }).then(
        (answer) => answer.account,
        (error: unknown) => {
          if (isNotFound(error)) return undefined;
          throw error;
        },
      );
      if (!account) return { account: undefined, memberships: [], assignableRoles: [], regions: [], countries: [] };
      const [memberships, registry] = await Promise.all([countries.listMemberships({ userId }), countries.listCountries({})]);
      return {
        account,
        memberships: memberships.memberships,
        assignableRoles: memberships.assignableRoles,
        regions: memberships.regions,
        countries: grantableCountries(registry.countries),
      };
    });
  }
  const names = selected?.account
    ? await accountNames(selected.memberships.flatMap((m) => [m.grantedBy, m.revokedBy, ...m.roles.flatMap((r) => [r.grantedBy, r.revokedBy])]))
    : new Map<string, string>();

  return (
    <CountryFrame
      header={{ title: 'Country Memberships', description: 'Which countries each account works in, who granted each one and why.' }}
      tab="memberships"
    >
      <Card label="Find an account">
        <form action={MEMBERSHIPS_PATH} method="get" className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col text-[length:var(--edify-text-label-size)] font-semibold">
            Account
            <input className={FIELD} type="search" name="q" defaultValue={search} maxLength={MAX_SEARCH} placeholder="Name or email" />
          </label>
          {userId ? <input type="hidden" name="user" value={userId} /> : null}
          <button type="submit" className={BUTTON_PRIMARY}>
            Search
          </button>
        </form>
      </Card>
      {found ? (
        <FeedTable table={accountsTable(found.accounts, search, userId, Number(found.page?.total ?? found.accounts.length))} pagePath={MEMBERSHIPS_PATH} drawerHref="" selectable={false} />
      ) : null}
      {selected === null ? (
        search ? null : <Note>Search for an account by name or email to see and change its countries.</Note>
      ) : selected.account ? (
        <>
          <Card label="Account">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{selected.account.name || selected.account.email}</h2>
              <a className="text-[13px] font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]" href={membershipsPath('', search)}>
                Close
              </a>
            </div>
            <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
              {selected.account.email} · {selected.account.activeRole || 'No role'}
            </p>
          </Card>
          <MembershipManager
            key={selected.account.userId}
            account={{
              userId: selected.account.userId,
              name: selected.account.name || selected.account.email,
              email: selected.account.email,
              activeRole: selected.account.activeRole,
            }}
            memberships={selected.memberships}
            assignableRoles={selected.assignableRoles}
            regions={selected.regions}
            countries={selected.countries.map((c) => ({ code: c.code, name: c.name, state: c.state }))}
            names={Object.fromEntries(names)}
            reader={{ userId: reader.userId, name: reader.name }}
            today={kampalaToday()}
          />
        </>
      ) : (
        <Note title="Account not found">That account does not exist or has been removed. Search for it again.</Note>
      )}
    </CountryFrame>
  );
}
