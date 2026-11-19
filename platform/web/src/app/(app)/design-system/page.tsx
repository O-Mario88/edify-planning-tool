/**
 * The design system's catalogue: every standard part of a page, drawn by the
 * components the pages use, with sample figures. It is the reference each
 * page is compared against: a page that looks different from this (or from
 * the live system) is off and gets beaten back into shape.
 */
import { create } from '@bufbuild/protobuf';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import {
  Badge,
  BUTTON_OUTLINE,
  BUTTON_PRIMARY,
  Caption,
  Card,
  CardTitle,
  Eyebrow,
  FeedChart,
  FeedTable,
  KpiStrip,
  Meter,
  MiniTile,
  PageHeader,
  PageTitle,
  Pager,
  SectionHeading,
  StandardCard,
  TabRail,
} from '@/components/ds';
import { PhonePage } from '@/components/phone/PhonePage';
import { PageChartSchema, PageHeaderSchema, PageLinkTabsSchema, PagePagerSchema, PageStripSchema, PageTableSchema } from '@/gen/edify/screens/v1/page_pb';
import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

export const metadata: Metadata = { title: 'Design system — Edify' };

const HERE = '/design-system';

const HEADER = create(PageHeaderSchema, {
  eyebrow: 'Schools & Field',
  title: 'Core Schools',
  description: 'Every Core school this year, who holds it and how its support stands.',
  actions: [
    { key: 'export', label: 'Export', enabled: true, href: `${HERE}#export`, download: true },
    { key: 'add', label: 'Add School', primary: true, enabled: true, href: `${HERE}#add` },
  ],
});

const STRIP = create(PageStripSchema, {
  metrics: [
    { label: 'Schools', value: '1,284', helper: 'this year' },
    { label: 'Visited', value: '742', helper: '58% of schools', tone: 'success' },
    { label: 'Planned', value: '311', helper: 'not yet done' },
    { label: 'Not planned', value: '231', helper: 'need a date', tone: 'warning' },
    { label: 'Overdue', value: '17', helper: 'past their date', tone: 'danger' },
  ],
});

const TABS = create(PageLinkTabsSchema, {
  label: 'Lens',
  tabs: [
    { label: 'All', href: HERE, active: true },
    { label: 'Client', href: `${HERE}?lens=client` },
    { label: 'Core', href: `${HERE}?lens=core` },
    { label: 'Partner', href: `${HERE}?lens=partner` },
  ],
});

const PAGER = create(PagePagerSchema, {
  summary: 'Showing 1–3 of 1,284',
  pages: [
    { label: '1', href: HERE, current: true },
    { label: '2', href: `${HERE}?page=2` },
    { label: '3', href: `${HERE}?page=3` },
    { label: 'Next', href: `${HERE}?page=2` },
  ],
});

const TABLE = create(PageTableSchema, {
  title: 'Schools',
  count: '1,284',
  columns: [{ label: 'School ID' }, { label: 'School' }, { label: 'District' }, { label: 'Status' }, { label: 'Visits', numeric: true }],
  rows: [
    { cells: [{ text: 'SCH-00412' }, { text: 'Bright Hope Primary', href: `${HERE}#school`, strong: true }, { text: 'Wakiso' }, { text: 'Visited', badge: true, tone: 'good' }, { text: '2' }] },
    { cells: [{ text: 'SCH-00977' }, { text: 'St. Kizito Nursery & Primary', href: `${HERE}#school`, strong: true }, { text: 'Mukono' }, { text: 'Planned', badge: true, tone: 'info' }, { text: '1' }] },
    { cells: [{ text: 'SCH-01530' }, { text: 'Kampala Junior Academy', href: `${HERE}#school`, strong: true }, { text: 'Kampala' }, { text: 'Overdue', badge: true, tone: 'alert' }, { text: '0' }] },
  ],
  pager: PAGER,
});

const EMPTY_TABLE = create(PageTableSchema, {
  title: 'Escalations',
  columns: [{ label: 'School' }, { label: 'Raised' }],
  emptyMessage: 'Nothing is waiting on you.',
});

const CHART = create(PageChartSchema, {
  title: 'Visits by month',
  subtitle: 'Done against planned',
  categories: ['Jul', 'Aug', 'Sep', 'Oct', 'Nov'],
  series: [
    { name: 'Done', values: [82, 120, 141, 166, 97] },
    { name: 'Planned', values: [110, 130, 150, 170, 180] },
  ],
  axisTitle: 'Visits',
});

const BAR_CHART = create(PageChartSchema, {
  title: 'Visits by district',
  horizontal: true,
  categories: ['Wakiso', 'Mukono', 'Kampala', 'Jinja'],
  series: [{ name: 'Visits', values: [214, 168, 131, 77] }],
});

/** The same parts as a phone reads them, drawn in the native app's design. */
const PHONE = create(GetPageResponseSchema, {
  header: HEADER,
  blocks: [
    { kind: { case: 'linkTabs', value: { tabs: [...TABS.tabs, { label: 'Closed', href: `${HERE}?lens=closed` }], beside: { key: 'calendar', label: 'Open Calendar', enabled: true, href: `${HERE}#calendar` } } } },
    {
      kind: {
        case: 'filters',
        value: {
          filters: ['Fiscal year', 'Quarter', 'Month', 'District'].map((label) => ({ name: label.toLowerCase().replace(' ', '_'), label, value: 'all', options: [{ value: 'all', label: `All ${label.toLowerCase()}` }] })),
        },
      },
    },
    { kind: { case: 'strip', value: STRIP } },
    { kind: { case: 'table', value: TABLE } },
    {
      kind: {
        case: 'list',
        value: {
          title: 'Do next',
          count: '2 open',
          items: [
            { title: 'Chase Partner Delivery', lines: ['Kyampisi UMEA Primary School · partner'], tone: 'caution', actions: [{ label: 'Open', enabled: true, href: `${HERE}#open` }] },
            { title: 'Verify completion', lines: ['Bright Hope Primary · support visit'], tone: 'info', actions: [{ label: 'Verify', enabled: true, href: `${HERE}#verify` }] },
          ],
        },
      },
    },
    { kind: { case: 'chart', value: BAR_CHART } },
    { kind: { case: 'panel', value: { title: 'Details', items: [{ kind: { case: 'fields', value: { facts: [{ label: 'District', value: 'Wakiso' }, { label: 'Cluster', value: 'Kira North' }] } } }, { kind: { case: 'rows', value: { rows: [{ label: 'Visits this year', value: '2', tone: 'good' }, { label: 'Overdue', value: '1', tone: 'alert' }] } } }] } } },
  ],
});

const TONES = ['good', 'caution', 'alert', 'info', 'purple', 'plain'] as const;

function Entry({ name, note, children }: { name: string; note: string; children: ReactNode }) {
  return (
    <section className="space-y-3" aria-label={name}>
      <SectionHeading note={note}>{name}</SectionHeading>
      {children}
    </section>
  );
}

export default function DesignSystemPage() {
  return (
    <div className="mx-auto max-w-[1500px] space-y-8 px-4 pb-24 pt-5 sm:px-6 lg:pb-8">
      <PageHeader header={HEADER} hrefOf={(action) => action.href} />

      <Entry name="Typography" note="The existing type scale: eyebrow, page title, section heading, card title, body and caption.">
        <Card>
          <div className="space-y-3">
            <Eyebrow>Eyebrow · Schools &amp; Field</Eyebrow>
            <PageTitle>Page title</PageTitle>
            <SectionHeading>Section heading</SectionHeading>
            <CardTitle>Card title</CardTitle>
            <p className="edify-text">Body text: the size every table cell and paragraph uses.</p>
            <Caption>Caption: the line under a figure, a card note or a hint.</Caption>
          </div>
        </Card>
      </Entry>

      <Entry name="Buttons" note="One primary action per header; the rest outlined. Rows get one Actions menu instead.">
        <div className="flex flex-wrap items-center gap-2">
          <a href={`${HERE}#primary`} className={BUTTON_PRIMARY}>
            Primary
          </a>
          <a href={`${HERE}#secondary`} className={BUTTON_OUTLINE}>
            Secondary
          </a>
        </div>
      </Entry>

      <Entry name="Badges" note="Status words, toned by meaning, never by decoration.">
        <div className="flex flex-wrap items-center gap-2">
          {TONES.map((tone) => (
            <Badge key={tone} tone={tone}>
              {tone}
            </Badge>
          ))}
        </div>
      </Entry>

      <Entry name="Figure row" note="A page's figures: one row of context metrics under the header, not tiles.">
        <KpiStrip strip={STRIP} />
      </Entry>

      <Entry name="Small tiles" note="The dashboards' toned figure tiles.">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MiniTile label="Approved" value="42" helper="this week" tone="success" />
          <MiniTile label="Waiting" value="9" helper="for a PL" tone="warning" />
          <MiniTile label="Rejected" value="3" helper="need a fix" tone="danger" />
          <MiniTile label="Drafts" value="12" helper="not sent" />
        </div>
      </Entry>

      <Entry name="Cards and meters" note="The registered card: title, a View all link, its content and a foot link.">
        <div className="grid gap-4 lg:grid-cols-2">
          <StandardCard title="Support visits" id="visits" headLink={{ label: 'View all', href: `${HERE}#visits` }}>
            <Meter done={62} planned={81} value="62%" meta="742 done · 231 planned · of 1,284 schools" tone="success" label="Support visits 62% done" />
            <Meter done={18} planned={30} value="18%" meta="23 done · 15 planned · of 128 trainings" tone="warning" label="Trainings 18% done" />
          </StandardCard>
          <StandardCard title="Completion reviews" id="reviews" footLink={{ label: 'Open the register', href: `${HERE}#reviews` }}>
            <Caption>9 completions are waiting for a PL to verify.</Caption>
          </StandardCard>
        </div>
      </Entry>

      <Entry name="Tabs" note="Segments on one rail: straight dividers, curved ends, never pills, never wrapping.">
        <TabRail rail={TABS} />
      </Entry>

      <Entry name="Tables" note="A titled table card, 50 rows a page, with its pager under it; an empty table says why.">
        <FeedTable table={TABLE} pagePath={HERE} drawerHref={HERE} selectable={false} />
        <FeedTable table={EMPTY_TABLE} pagePath={HERE} drawerHref={HERE} selectable={false} />
      </Entry>

      <Entry name="Pager" note="Under a table: the count on the left, the pages on the right.">
        <Pager pager={PAGER} />
      </Entry>

      <Entry name="On a phone" note="Below 64rem every page is the native app's design: tiles, segment rail with More, three filters and More, record tables, lists and panels.">
        <div className="max-w-[390px] overflow-hidden rounded-[24px] border border-[var(--edify-border)]">
          <PhonePage answer={PHONE} pagePath={HERE} drawerHref={HERE} />
        </div>
      </Entry>

      <Entry name="Graphs" note="The chart standard: the series colours, one plot height, bars of a fixed thickness.">
        <div className="grid gap-4 lg:grid-cols-2">
          <FeedChart chart={CHART} />
          <FeedChart chart={BAR_CHART} />
        </div>
      </Entry>
    </div>
  );
}
