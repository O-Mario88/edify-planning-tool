/** The five Edify dashboard pages, drawn from answers shaped as the Go gateway gives them. */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

import { CoreSchoolOversightView } from './CoreSchoolOversightView';
import { DecisionLogView } from './DecisionLogView';
import { EscalationsView } from './EscalationsView';
import { FieldDebriefView } from './FieldDebriefView';
import { PersonalTimeOffView } from './PersonalTimeOffView';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/x',
  useSearchParams: () => new URLSearchParams(),
}));

const D = 'http://django/x';
const page = (json: JsonValue) => fromJson(GetPageResponseSchema, json);

describe('Five Edify dashboard pages', () => {
  it('Escalations: hero, KPIs and empty state', () => {
    const html = renderToStaticMarkup(
      <EscalationsView
        pagePath="/escalations"
        drawerHref={D}
        answer={page({
          header: { eyebrow: 'Leadership', title: 'Escalations' },
          blocks: [
            { form: { title: 'Escalate to Programme Lead 1, your Programme Lead', text: 'Use this.', submitLabel: 'Send to Programme Lead' } },
            { section: 'Raised by you' },
            { empty: 'Nothing is currently escalated.' },
          ],
        })}
      />,
    );
    expect(html).toContain('Escalate to Programme Lead 1, your Programme Lead');
    expect(html).toContain('Open Escalations');
    expect(html).toContain('No escalations yet');
  });

  it('Core School Oversight: KPIs, SSA status, school link', () => {
    const cells = Array.from({ length: 21 }, (_, i) => ({ text: i === 6 ? '7.8' : i === 0 ? 'Central Division Primary' : 'x', href: i === 0 ? '/schools/1' : '' }));
    const html = renderToStaticMarkup(
      <CoreSchoolOversightView
        pagePath="/core-schools-oversight"
        drawerHref={D}
        answer={page({
          header: { eyebrow: 'Oversight', title: 'Core School Oversight' },
          blocks: [
            { strip: { metrics: [{ label: 'Core Schools', value: '142' }, { label: 'Current-Year SSA', value: '142 of 142' }, { label: 'Compared', value: '0 of 142' }, { label: 'Improved', value: '0' }] } },
            { linkTabs: { tabs: [{ label: 'Schools', href: '?tab=schools', active: true }] } },
            { table: { columns: cells.map((_, i) => ({ label: `C${i}` })), rows: [{ cells }] } },
          ],
        })}
      />,
    );
    expect(html).toContain('SSA Status');
    expect(html).toContain('Attention Summary');
    expect(html).toContain('href="/schools/1"');
  });

  it('Field Debrief: trend, action center and empty table', () => {
    const html = renderToStaticMarkup(
      <FieldDebriefView
        pagePath="/debriefs"
        drawerHref={D}
        answer={page({
          header: { eyebrow: 'My Work', title: 'Field Debrief Dashboard' },
          blocks: [
            { strip: { metrics: [{ label: 'Debriefs Submitted', value: '0' }] } },
            { chart: { title: 'Debrief Trend Over Time', categories: ['Oct 23', 'Oct 24'], series: [{ name: 'Submitted', values: [0, 0] }] } },
            { segments: { segments: [{ label: 'All Debriefs', active: true, blocks: [{ table: { columns: [{ label: 'Date' }, { label: 'Status' }], rows: [{ cells: [{ text: 'No Field Debriefs match these filters.' }] }] } }] }] } },
          ],
        })}
      />,
    );
    expect(html).toContain('Debrief Trend Over Time');
    expect(html).toContain('Action Center');
    expect(html).toContain('No Field Debriefs match these filters.');
  });

  it('Personal Time Off: portfolio, guidance and empty requests', () => {
    const html = renderToStaticMarkup(
      <PersonalTimeOffView
        pagePath="/personal-time-off"
        drawerHref={D}
        answer={page({
          header: { eyebrow: 'Reference', title: 'Personal Time Off' },
          blocks: [
            { linkTabs: { tabs: [{ label: 'My Leave', href: '?tab=my_leave', active: true }] } },
            { strip: { metrics: [{ label: 'Days Available', value: '21', helper: 'Used: 21 · Allocated: 42' }] } },
          ],
        })}
      />,
    );
    expect(html).toContain('Leave Balance Portfolio');
    expect(html).toContain('No leave requests yet');
  });

  it('Decision Log: context, KPIs and a decision row', () => {
    const html = renderToStaticMarkup(
      <DecisionLogView
        pagePath="/decision-log"
        answer={page({
          header: { eyebrow: 'Oversight', title: 'Decision Log' },
          blocks: [
            { table: { columns: [{ label: 'Date' }, { label: 'Decision' }, { label: 'Record' }, { label: 'Author' }], rows: [{ cells: [{ text: 'Nov 20' }, { text: 'Approve partner allocation' }, { text: 'Rwenzori' }, { text: 'Country Director' }] }] } },
          ],
        })}
      />,
    );
    expect(html).toContain('Total Decisions');
    expect(html).toContain('Approve partner allocation');
  });
});
