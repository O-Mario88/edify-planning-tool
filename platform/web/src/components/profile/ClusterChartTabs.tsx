'use client';

/* Cluster Analytics on the Overview: one history at a time, switched by its tabs. */
import { LineChart } from 'lucide-react';
import { useState } from 'react';

import type { PageChart } from '@/gen/edify/screens/v1/page_pb';
import { chartPoints } from '@/lib/clusterProfileView';

import { ProfileCard } from './parts';
import { SsaTrendChart } from './SsaTrendChart';

/** The tabs' short words, so all four fit the card's width. */
const TAB_WORDS: Readonly<Record<string, string>> = {
  'SSA Trend': 'SSA',
  'Visit Coverage': 'Visits',
  'Training Coverage': 'Trainings',
  'Action Closure': 'Actions',
};

export function ClusterChartTabs({ charts }: { charts: readonly PageChart[] }) {
  const [active, setActive] = useState(0);
  const chart = charts[active] ?? charts[0];
  if (!chart) return null;
  const isShare = chart.max === 100;
  return (
    <ProfileCard title="Cluster Analytics" icon={LineChart} block="cluster-analytics" className="h-full">
      <div role="tablist" aria-label="Cluster histories" className="mb-2 flex overflow-x-auto rounded-[8px] bg-[var(--edify-surface-muted)]" tabIndex={0}>
        {charts.map((item, index) => (
          <button
            key={item.title}
            type="button"
            role="tab"
            aria-selected={index === active}
            aria-label={item.title}
            onClick={() => setActive(index)}
            className={`h-8 shrink-0 whitespace-nowrap px-3 text-[12px] first:rounded-l-[8px] last:rounded-r-[8px] ${index === active ? 'bg-[var(--edify-web-segment-active)] font-bold text-white' : 'font-semibold text-[var(--edify-text-muted)]'}`}
          >
            {TAB_WORDS[item.title] ?? item.title}
          </button>
        ))}
      </div>
      <SsaTrendChart
        points={chartPoints(chart)}
        scaleMax={isShare ? 100 : 10}
        suffix={isShare ? '%' : ''}
        label={chart.title}
        empty={`No ${chart.title.toLowerCase()} recorded yet.`}
      />
      <p className="mt-1 text-[12px] text-[var(--edify-text-muted)]">{chart.subtitle}</p>
    </ProfileCard>
  );
}
