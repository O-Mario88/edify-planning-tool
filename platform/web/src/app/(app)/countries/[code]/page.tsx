import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { Card } from '@/components/blocks/Card';
import { AdminOnly, CountryFrame, Note, accountNames, readReader } from '@/components/countries/CountryFrame';
import { SettingsRecorder } from '@/components/countries/SettingsRecorder';
import { FeedTable } from '@/components/page/FeedTable';
import { CountryService } from '@/gen/edify/countries/v1/countries_pb';
import { asReader } from '@/lib/auth';
import {
  COUNTRIES_PATH,
  canRecordSettings,
  countryPath,
  dayText,
  kampalaToday,
  membershipsPath,
  recordRefusal,
  settingsForm,
  stateOf,
  versionsTable,
} from '@/lib/countryAdmin';
import { gatewayClient, isNotFound } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Country Settings - Edify Command Center' };

type Params = Promise<{ code: string }>;

/*
 * One country (Edify Global, docs/migration/80 §11): its state, every
 * settings version ever recorded, and, while it is not yet Active, the form
 * that records the next one. Uganda's settings are read here and never
 * changed: an Active country's change needs an approved change.
 */
export default async function CountryPage({ params }: { params: Params }) {
  const { code: raw } = await params;
  const code = decodeURIComponent(raw).toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) notFound();
  const reader = await readReader();
  if (!reader.isAdmin) return <AdminOnly />;
  const answer = await asReader((token) => gatewayClient(CountryService, token).getCountryConfig({ countryCode: code })).catch((error: unknown) => {
    if (isNotFound(error)) notFound();
    throw error;
  });
  const country = answer.country;
  if (!country) notFound();
  const names = await accountNames(answer.versions.map((v) => v.changedBy));
  const state = stateOf(country.state);
  const inForce = country.config;
  const facts = [
    { label: 'Code', value: country.code },
    { label: 'State', value: state.label },
    { label: 'Active Since', value: dayText(country.activatedOn, 'Not yet') },
    { label: 'Settings in Force', value: inForce ? `Version ${inForce.version} from ${dayText(inForce.effectiveFrom)}` : 'None' },
  ];

  return (
    <CountryFrame
      header={{
        backLabel: 'Countries',
        backHref: COUNTRIES_PATH,
        title: country.name,
        description: `${country.code} · its settings, version by version`,
        badges: [{ text: state.label, tone: state.tone }],
      }}
    >
      <Card label="Country">
        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt className="text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--edify-text-muted)]">{fact.label}</dt>
              <dd className="text-[length:var(--edify-text-label-size)] font-bold">{fact.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-[length:var(--edify-text-label-size)]">
          <a className="font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]" href={membershipsPath('')}>
            Manage who works in {country.name}
          </a>
        </p>
      </Card>
      <FeedTable table={versionsTable(answer.versions, names)} pagePath={countryPath(country.code)} drawerHref="" selectable={false} />
      {canRecordSettings(country.state) ? (
        <SettingsRecorder
          countryCode={country.code}
          countryName={country.name}
          initial={settingsForm(inForce ?? answer.versions[0])}
          today={kampalaToday()}
          latestFrom={answer.versions[0]?.effectiveFrom ?? ''}
        />
      ) : (
        <Note title="Settings cannot be recorded here">{recordRefusal(country)}</Note>
      )}
    </CountryFrame>
  );
}
