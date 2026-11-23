/*
 * The School Profile's Core School tab: the programme banner with Champion
 * Readiness in Go's words, the tab's figures, then its cards. No percentage
 * or status is worked out here; a card Go does not send is not drawn.
 */
import { Activity, BarChart3, Crown, LifeBuoy, Package, ShieldCheck, TrendingUp, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { PageBlock, PagePanel } from '@/gen/edify/screens/v1/page_pb';
import { coreSchoolView } from '@/lib/schoolProfileView';

import { FeedBlocks } from '../page/FeedBlocks';
import { MetricTile, PanelLines, ProfileCard } from './parts';
import type { Accent } from './parts';

const FIGURE_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[TrendingUp, 'green'], [Package, 'blue'], [Users, 'violet'], [Activity, 'blue'], [ShieldCheck, 'amber']];

function CoreCard({ panel, title, icon, pagePath }: { panel: PagePanel | undefined; title?: string; icon: LucideIcon; pagePath: string }) {
  if (!panel) return null;
  return (
    <ProfileCard title={title ?? panel.title} icon={icon} block="core-card">
      <PanelLines panel={panel} pagePath={pagePath} />
    </ProfileCard>
  );
}

interface SchoolCoreTabProps {
  readonly blocks: readonly PageBlock[];
  readonly year: string;
  readonly pagePath: string;
  readonly drawerHref: string;
}

export function SchoolCoreTab({ blocks, year, pagePath, drawerHref }: SchoolCoreTabProps) {
  const view = coreSchoolView(blocks);
  return (
    <div className="space-y-4" data-layout="school-core">
      <section
        aria-label="Core School Programme"
        className="flex flex-col gap-3 rounded-[12px] bg-[color-mix(in_srgb,var(--brand-primary)_78%,#06162e)] px-5 py-4 text-white sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex min-w-0 items-center gap-3">
          <Crown className="h-8 w-8 shrink-0" style={{ color: '#fcd34d' }} aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="text-[20px] font-bold leading-tight" style={{ color: '#ffffff' }}>Core School Programme</h2>
            <p className="text-[13px]" style={{ color: 'rgb(255 255 255 / 0.88)' }}>Programme support, package, implementation progress and school readiness{year ? ` for ${year}` : ''}.</p>
          </div>
        </div>
        {view.readiness ? (
          <div className="shrink-0">
            <p className="text-[12px] font-medium" style={{ color: 'rgb(255 255 255 / 0.85)' }}>Champion Readiness</p>
            <p className="mt-0.5 inline-flex rounded-full bg-white px-3 py-1 text-[13px] font-bold text-[var(--brand-primary)]">{view.readiness}</p>
          </div>
        ) : null}
      </section>
      {view.metrics.length ? (
        <div data-pf="core-figures">
          {view.metrics.map((metric, index) => {
            const [icon, accent] = FIGURE_LOOK[index % FIGURE_LOOK.length]!;
            return <MetricTile key={metric.label} metric={metric} icon={icon} accent={accent} pagePath={pagePath} />;
          })}
        </div>
      ) : null}
      <div data-pf="core-cards">
        <CoreCard panel={view.package} title="Package & Support" icon={Package} pagePath={pagePath} />
        <CoreCard panel={view.participation} icon={Users} pagePath={pagePath} />
        <CoreCard panel={view.champion} icon={ShieldCheck} pagePath={pagePath} />
        <CoreCard panel={view.outcomes} icon={BarChart3} pagePath={pagePath} />
        <CoreCard panel={view.support} icon={LifeBuoy} pagePath={pagePath} />
      </div>
      {view.others.length ? <FeedBlocks blocks={view.others} pagePath={pagePath} drawerHref={drawerHref} selectable={false} clearFilters={false} /> : null}
    </div>
  );
}
