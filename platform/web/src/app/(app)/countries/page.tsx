import type { Metadata } from 'next';

import { AdminOnly, CountryFrame, Note, readReader } from '@/components/countries/CountryFrame';
import { FeedTable } from '@/components/page/FeedTable';
import { CountryService } from '@/gen/edify/countries/v1/countries_pb';
import { asReader } from '@/lib/auth';
import { COUNTRIES_PATH, countriesTable } from '@/lib/countryAdmin';
import { gatewayClient, isUnavailable, messageOf } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Countries - Edify Command Center' };

const HEADER = {
  title: 'Countries',
  description: 'The countries Edify Global serves, each with its state and the settings in force today.',
};

/*
 * Countries (Edify Global, docs/migration/80 §11): every registered country
 * from the gateway's CountryService (Go). Only Uganda is Active; the others
 * are prepared here and serve no one until they are approved and activated.
 */
export default async function CountriesPage() {
  const reader = await readReader();
  if (!reader.isAdmin) return <AdminOnly />;
  let answer;
  let refused = '';
  try {
    answer = await asReader((token) => gatewayClient(CountryService, token).listCountries({}));
  } catch (error) {
    if (!isUnavailable(error)) throw error;
    refused = messageOf(error, 'The country registry cannot be reached just now.');
  }
  return (
    <CountryFrame header={HEADER} tab="countries">
      {answer ? <FeedTable table={countriesTable(answer.countries)} pagePath={COUNTRIES_PATH} drawerHref="" selectable={false} /> : <Note>{refused}</Note>}
      <Note>
        A country that is not Active serves no one: its settings and memberships are prepared here and take effect only once it is approved and
        activated. Uganda&apos;s settings change only through an approved change, which is not built yet.
      </Note>
    </CountryFrame>
  );
}
