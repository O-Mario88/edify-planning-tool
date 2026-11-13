/*
 * A KPI strip outside the page feed (the notification centre's figures):
 * drawn as every page's strip is (FeedStrip, components/context_metrics.html),
 * so one layout holds across the web. Figures are the gateway's; nothing is
 * counted here.
 */
import type { PageStrip } from '@/gen/edify/screens/v1/page_pb';

import { FeedStrip } from '../page/FeedStrip';

const asGiven = (href: string): string => href;

export function KpiStrip({ strip }: { strip: PageStrip }) {
  return <FeedStrip strip={strip} resolve={asGiven} />;
}
