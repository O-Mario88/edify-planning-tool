/*
 * The school profile (School 360), drawn from SchoolProfileService, which Go
 * answers (docs/migration/13-school-profiles.md): the header with its badges
 * and doors, the tab strip, then the open tab's blocks. The engine tabs put
 * their insights rail beside the rest on a wide screen and under it on a
 * phone, as templates/pages/schools/detail.html does. A school the reader may
 * not open is the not-found page; a profile Go hands on (an acting reader, a
 * long Participation list) says so and opens the existing web.
 */
import { notFound } from 'next/navigation';

import type { PageAction, PageBlock } from '@/gen/edify/screens/v1/page_pb';
import { SchoolProfileService } from '@/gen/edify/screens/v1/school_profile_pb';
import type { GetSchoolProfileResponse } from '@/gen/edify/screens/v1/school_profile_pb';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { actionHref, drawerPageHref } from '@/lib/feedPage';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { profileAsk, profileTabs, profileYear, splitRail, trailingPanels } from '@/lib/schoolProfile';

import { PageHeader } from '../blocks/PageHeader';
import { TabRail } from '../blocks/TabRail';
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

interface BlocksProps {
  readonly blocks: readonly PageBlock[];
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

/** The SSA tab sets its last cards (the change between assessments, the history) side by side, two to one. */
function Body({ blocks, pagePath, drawerHref, selectable, sideBySide }: BlocksProps & { sideBySide: boolean }) {
  const cut = sideBySide ? trailingPanels(blocks) : blocks.length;
  const draw = (part: readonly PageBlock[]) => <FeedBlocks blocks={part} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />;
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
  const answer = await ask(schoolId, asked.tab, asked.fy, asked.period);
  if (!answer) return <NotMovedYet href={drawerPageHref(existingWebUrl, ownPath, query)} />;
  const pagePath = answer.webPath || ownPath;
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const selectable = Boolean(answer.selection?.actions.length);
  const activeTab = answer.tabs.find((tab) => tab.active)?.key ?? '';
  const { frame, main, rail } = splitRail(answer.blocks);
  const props = { pagePath, drawerHref, selectable };
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page={pagePath} data-tab={activeTab}>
      {answer.header ? <PageHeader header={answer.header} hrefOf={hrefOf} /> : null}
      {answer.tabs.length ? <TabRail rail={profileTabs(answer.tabs, pagePath, profileYear(answer.blocks, asked.fy))} /> : null}
      {rail.length ? (
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
        <Body blocks={answer.blocks} {...props} sideBySide={activeTab === 'ssa'} />
      )}
      {answer.selection?.actions.length ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}
