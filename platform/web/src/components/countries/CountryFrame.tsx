/*
 * The frame every country Admin page shares: its header, the Countries /
 * Memberships tabs, and the refusal a reader who is not an Admin sees. The
 * gateway refuses every write that is not an Admin's anyway; the page only
 * says so before anything is drawn.
 */
import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import type { ReactNode } from 'react';

import { AccountAdminService } from '@/gen/edify/identity/v1/accounts_pb';
import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { PageHeaderSchema } from '@/gen/edify/screens/v1/page_pb';
import { asReader } from '@/lib/auth';
import { ADMIN_ROLE, countryTabs } from '@/lib/countryAdmin';
import { gatewayClient } from '@/lib/gateway';

import { Card } from '../blocks/Card';
import { PageHeader } from '../blocks/PageHeader';
import { TabRail } from '../blocks/TabRail';

export interface Reader {
  readonly userId: string;
  readonly name: string;
  readonly isAdmin: boolean;
}

/** The signed-in reader, and whether they are working as an Admin. */
export async function readReader(): Promise<Reader> {
  const answer = await asReader((token) => gatewayClient(IdentityService, token).getSession({}));
  const session = answer.session;
  return {
    userId: session?.userId ?? '',
    name: session?.name || session?.email || '',
    isAdmin: session?.activeRole === ADMIN_ROLE,
  };
}

/**
 * The names of the accounts that recorded, granted or revoked something, for
 * the tables (the registry keeps ids). An account that can no longer be read
 * keeps its id.
 */
export async function accountNames(ids: Iterable<string>): Promise<Map<string, string>> {
  const wanted = [...new Set(ids)].filter(Boolean);
  const names = await asReader((token) => {
    const client = gatewayClient(AccountAdminService, token);
    return Promise.all(
      wanted.map((userId) =>
        client.getAccount({ userId }).then(
          (answer) => [userId, answer.account?.name || answer.account?.email || userId] as const,
          () => [userId, userId] as const,
        ),
      ),
    );
  });
  return new Map(names);
}

interface FrameProps {
  readonly header: MessageInitShape<typeof PageHeaderSchema>;
  readonly tab?: 'countries' | 'memberships';
  readonly children: ReactNode;
}

export function CountryFrame({ header, tab, children }: FrameProps) {
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-5 pt-5 sm:px-6">
      <PageHeader header={create(PageHeaderSchema, { eyebrow: 'Edify Global', ...header })} hrefOf={() => ''} />
      {tab ? <TabRail rail={countryTabs(tab)} /> : null}
      {children}
    </div>
  );
}

/** A short note in a card (a refusal, or why a form is not offered). */
export function Note({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <Card>
      {title ? <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{title}</h2> : null}
      <div className={`text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)] ${title ? 'mt-1' : ''}`}>{children}</div>
    </Card>
  );
}

export function AdminOnly() {
  return (
    <CountryFrame header={{ title: 'Country Administration', description: 'Countries, their settings and who works in each.' }}>
      <Note title="This page is for Admins">
        Country administration is open to an account working as Admin. Switch to the Admin role if your account holds it.
      </Note>
    </CountryFrame>
  );
}
