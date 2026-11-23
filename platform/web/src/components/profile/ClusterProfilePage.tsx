/*
 * The Cluster Profile, drawn from the gateway's page answer for the cluster:
 * its band, its seven tabs, the year's figures, then the open tab. A reader
 * whose scope does not hold the cluster gets the not-found page from Go.
 */
import { LineChart } from 'lucide-react';

import { FeedBlocks } from '@/components/page/FeedBlocks';
import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { SelectionBar } from '@/components/page/SelectionBar';
import { PhoneBlocks } from '@/components/phone/PhoneBlocks';
import type { PageAction, PageMetric } from '@/gen/edify/screens/v1/page_pb';
import { chartPoints, clusterFactsOf, clusterView } from '@/lib/clusterProfileView';
import { environment } from '@/lib/environment';
import { actionHref, drawerPageHref } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

import { BarChart3, CalendarCheck, CheckCircle2, Clock, Flag, History, School } from './clusterIcons';
import type { IconFor } from './clusterIcons';
import { ClusterHero } from './ClusterHero';
import { ClusterMembers } from './ClusterMembers';
import { ClusterOverview } from './ClusterOverview';
import { CardFilters } from './CardFilters';
import { ProfileTabs } from './ProfileTabs';
import { MetricTile, ProfileCard } from './parts';
import type { Accent } from './parts';
import { SsaTrendChart } from './SsaTrendChart';

const KPI_LOOK: Readonly<Record<string, readonly [IconFor, Accent]>> = {
  'Member Schools': [School, 'blue'],
  'In Visit Plan': [CalendarCheck, 'blue'],
  Completed: [CheckCircle2, 'green'],
  Upcoming: [Clock, 'blue'],
  'Past Their Date': [History, 'violet'],
  'Outstanding Actions': [Flag, 'amber'],
  'Cluster SSA Score': [BarChart3, 'blue'],
};

function SummaryTiles({ metrics, pagePath }: { metrics: readonly PageMetric[]; pagePath: string }) {
  return (
    <div data-pf="cluster-kpis" data-block="cluster-kpis">
      {metrics.map((metric) => {
        const [icon, accent] = KPI_LOOK[metric.label] ?? ([BarChart3, 'blue'] as const);
        return <MetricTile key={metric.label} metric={metric} icon={icon} accent={accent} pagePath={pagePath} />;
      })}
    </div>
  );
}

export async function ClusterProfilePage({ clusterId, query }: { clusterId: string; query: Record<string, string> }) {
  const path = `/clusters/${encodeURIComponent(clusterId)}`;
  const existingWebUrl = environment().existingWebUrl;
  const answer = await askFirst([path], query, true);
  if (!answer) return <NotMovedYet href={drawerPageHref(existingWebUrl, path, query)} />;
  const pagePath = answer.webPath || path;
  const drawerHref = drawerPageHref(existingWebUrl, pagePath, query);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const view = clusterView(answer.blocks);
  const { place, people } = clusterFactsOf(answer.blocks);
  const activeTab = answer.tabs.find((tab) => tab.active)?.key ?? 'overview';
  const selectable = Boolean(answer.selection?.actions.length);
  const isPhone = (await requestView()) === 'phone';
  const feed = { pagePath, drawerHref, selectable, clearFilters: false };
  const isOverview = activeTab === 'overview' && Boolean(view.summary);
  // What a tab holds beyond the cards this page draws itself.
  const rest = isOverview ? [] : [...view.others];
  const filters = view.filters.flatMap((block) => (block.kind.case === 'filters' ? block.kind.value.filters : []));
  return (
    <div data-pf-page="" className="space-y-3 px-3 pb-24 pt-3 sm:px-6 lg:pb-8" data-page={pagePath} data-tab={activeTab}>
      {answer.header ? <ClusterHero header={answer.header} place={place} people={people} hrefOf={hrefOf} /> : null}
      {answer.tabs.length ? <ProfileTabs tabs={answer.tabs} pagePath={pagePath} year={query.fy || ''} label="Cluster sections" /> : null}
      {!isOverview && filters.length ? <div data-pf="tab-filters"><CardFilters filters={filters} /></div> : null}
      {view.summary ? <SummaryTiles metrics={view.summary.metrics} pagePath={pagePath} /> : null}
      {isOverview ? <ClusterOverview view={view} filters={filters} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} /> : null}
      {!isOverview && view.members ? <ClusterMembers table={view.members} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} /> : null}
      {!isOverview && view.charts.length ? (
        <div data-pf="cluster-charts">
          {view.charts.map((chart) => {
            const isShare = chart.max === 100;
            return (
              <ProfileCard key={chart.title} title={chart.title} icon={LineChart} block="cluster-chart">
                <SsaTrendChart points={chartPoints(chart)} scaleMax={isShare ? 100 : 10} suffix={isShare ? '%' : ''} label={chart.title} empty={`No ${chart.title.toLowerCase()} recorded yet.`} />
                <p className="mt-1 text-[12px] text-[var(--edify-text-muted)]">{chart.subtitle}</p>
              </ProfileCard>
            );
          })}
        </div>
      ) : null}
      {!isOverview && view.activities ? <SummaryTiles metrics={view.activities.metrics} pagePath={pagePath} /> : null}
      {!isOverview && view.attendance ? <SummaryTiles metrics={view.attendance.metrics} pagePath={pagePath} /> : null}
      {rest.length ? (
        isPhone ? (
          <div data-ph="page"><PhoneBlocks blocks={rest} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} /></div>
        ) : (
          <FeedBlocks blocks={rest} {...feed} />
        )
      ) : null}
      {answer.selection?.actions.length ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}
