/*
 * The school profile (School 360), drawn from SchoolProfileService, which Go
 * answers (docs/migration/13-school-profiles.md): the header with its badges
 * and doors, the tab strip, then the open tab's blocks. The engine tabs put
 * their insights rail beside the rest on a wide screen and under it on a
 * phone, as templates/pages/schools/detail.html does. A school the reader may
 * not open is the not-found page; a profile Go hands on (an acting reader, a
 * long Participation list) says so and opens the existing web.
 */
import { toJson } from '@bufbuild/protobuf';
import { cookies } from 'next/headers';
import { notFound, unstable_rethrow } from 'next/navigation';

import { SchoolCoreTab } from '@/components/profile/SchoolCoreTab';
import { SchoolHero } from '@/components/profile/SchoolHero';
import { SchoolOverview } from '@/components/profile/SchoolOverview';
import { LocationCard } from '@/components/route/LocationCard';
import { GetSchoolLocationResponseSchema, RoutePlannerService } from '@/gen/edify/routes/v1/routes_pb';
import type { PageAction, PageBlock } from '@/gen/edify/screens/v1/page_pb';
import { SchoolProfileService } from '@/gen/edify/screens/v1/school_profile_pb';
import type { GetSchoolProfileResponse } from '@/gen/edify/screens/v1/school_profile_pb';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { actionHref, drawerPageHref } from '@/lib/feedPage';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { ACCESS_COOKIE } from '@/lib/session';
import { requestView } from '@/lib/requestView';
import { profileAsk, profileTabs, profileYear, splitRail, trailingPanels } from '@/lib/schoolProfile';
import { honestSsa, schoolIdentity, trendPoints } from '@/lib/schoolProfileView';

import { TabRail } from '../blocks/TabRail';
import { PhoneBlocks } from '../phone/PhoneBlocks';
import { FeedBlocks } from './FeedBlocks';
import { NotMovedYet } from './NotMovedYet';
import { SelectionBar } from './SelectionBar';

async function ask(schoolId: string, tab: string, fy: string, period: string): Promise<GetSchoolProfileResponse | null> {
  return asReader(async (token) => {
    try {
      return await gatewayClient(SchoolProfileService, token).getSchoolProfile({ schoolId, tab, fy, period });
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return null;
      throw error;
    }
  });
}

/** A second tab's answer the page only draws part of: when it cannot be read, the page still opens without that part. */
async function askAlso(schoolId: string, tab: string, fy: string, period: string): Promise<GetSchoolProfileResponse | null> {
  try {
    return await ask(schoolId, tab, fy, period);
  } catch (error) {
    unstable_rethrow(error);
    return null;
  }
}

/** The header draws the school's facts and year, so the tabs do not repeat them. */
const underHero = (blocks: readonly PageBlock[]) => blocks.filter((block) => block.kind.case !== 'facts' && block.kind.case !== 'scopeLine');

interface BlocksProps {
  readonly blocks: readonly PageBlock[];
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
  readonly clearFilters: boolean;
}

/** The SSA tab sets its last cards (the change between assessments, the history) side by side, two to one. */
function Body({ blocks, pagePath, drawerHref, selectable, clearFilters, sideBySide }: BlocksProps & { sideBySide: boolean }) {
  const cut = sideBySide ? trailingPanels(blocks) : blocks.length;
  const draw = (part: readonly PageBlock[]) => <FeedBlocks blocks={part} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} clearFilters={clearFilters} />;
  if (cut >= blocks.length) return draw(blocks);
  return (
    <>
      {draw(blocks.slice(0, cut))}
      <div className="grid items-start gap-4 lg:grid-cols-[2fr_1fr]">{draw(blocks.slice(cut))}</div>
    </>
  );
}

export async function ProfilePage({ schoolId, query }: { schoolId: string; query: Record<string, string> }) {
  const existingWebUrl = environment().existingWebUrl;
  const asked = profileAsk(query);
  const ownPath = `/schools/${encodeURIComponent(schoolId)}`;
  // A list a figure opens (`what=…`) is not part of the profile request: the existing web draws it.
  if (asked.elsewhere) return <NotMovedYet href={drawerPageHref(existingWebUrl, ownPath, query)} />;
  // The Core School and Details tabs carry no school facts, so the header reads them from the Overview;
  // the Overview's trend is the SSA tab's yearly chart.
  const needsFacts = asked.tab === 'core' || asked.tab === 'details';
  const needsTrend = asked.tab === '' || asked.tab === 'overview';
  const [answer, factsAnswer, ssaAnswer] = await Promise.all([
    ask(schoolId, asked.tab, asked.fy, asked.period),
    needsFacts ? askAlso(schoolId, 'overview', asked.fy, asked.period) : null,
    needsTrend ? askAlso(schoolId, 'ssa', asked.fy, asked.period) : null,
  ]);
  if (!answer) return <NotMovedYet href={drawerPageHref(existingWebUrl, ownPath, query)} />;
  const pagePath = answer.webPath || ownPath;
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const selectable = Boolean(answer.selection?.actions.length);
  const activeTab = answer.tabs.find((tab) => tab.active)?.key ?? '';
  const isPhone = (await requestView()) === 'phone';
  const identity = schoolIdentity(answer.header, factsAnswer?.blocks ?? answer.blocks);
  const yearLabel = identity.people.find((fact) => fact.label === 'Fiscal Year')?.value ?? '';
  const blocks = underHero(answer.blocks);
  const { frame, main, rail } = splitRail(blocks);
  const props = { pagePath, drawerHref, selectable, clearFilters: false };
  const isOverview = activeTab === 'overview' || activeTab === '';
  const otherTab = isPhone ? (
    <div data-ph="page">
      <PhoneBlocks blocks={blocks} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />
    </div>
  ) : rail.length ? (
    <>
      <FeedBlocks blocks={frame} {...props} />
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0 space-y-4">
          <FeedBlocks blocks={main} {...props} />
        </div>
        <div className="space-y-4 lg:sticky lg:top-4">
          <FeedBlocks blocks={rail} {...props} />
        </div>
      </div>
    </>
  ) : (
    <Body blocks={blocks} {...props} sideBySide={activeTab === 'ssa'} />
  );
  return (
    <div className="mx-auto max-w-[1600px] space-y-3 px-4 pb-24 pt-4 sm:px-6 lg:pb-8" data-page={pagePath} data-tab={activeTab}>
      {answer.header ? <SchoolHero header={answer.header} identity={identity} hrefOf={hrefOf} /> : null}
      {answer.tabs.length ? <TabRail rail={profileTabs(answer.tabs, pagePath, profileYear(answer.blocks, asked.fy))} /> : null}
      {isOverview ? (
        <SchoolOverview
          blocks={honestSsa(answer.blocks)}
          trend={trendPoints(ssaAnswer?.blocks ?? [])}
          year={yearLabel}
          pagePath={pagePath}
          drawerHref={drawerHref}
          location={<SchoolLocation schoolId={schoolId} />}
        />
      ) : activeTab === 'core' ? (
        <SchoolCoreTab blocks={answer.blocks} year={yearLabel} pagePath={pagePath} drawerHref={drawerHref} />
      ) : (
        otherTab
      )}
      {answer.selection?.actions.length ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}

/** The Location & Directions card; a school whose location cannot be read shows the profile without it. */
async function SchoolLocation({ schoolId }: { schoolId: string }) {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return null;
  let json = null;
  let revision = '';
  try {
    const location = await gatewayClient(RoutePlannerService, token).getSchoolLocation({ schoolId });
    json = toJson(GetSchoolLocationResponseSchema, location);
    // A new reading on the server redraws the card from it (a refresh after another reader's capture).
    revision = `${location.version}:${location.school?.locationStatus ?? ''}:${location.verifiedAt}`;
  } catch {
    return null; // the profile is drawn without its location card
  }
  return <LocationCard key={revision} answer={json} variant="rail" />;
}
