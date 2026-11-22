/**
 * School Directory column headers, no disclosure chevrons, inline entity links,
 * and 3-column SSA intervention breakdown (including zero scores vs missing SSA).
 */
import { create } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import {
  DirectorySchoolSchema,
  DirectorySsaGroupSchema,
  DirectorySsaItemSchema,
} from '@/gen/edify/screens/v1/school_directory_pb';
import { SsaDetailPanel, ssaModelFromDirectory } from '../blocks/SsaDetailPanel';
import { DirectoryList } from './DirectoryList';

vi.mock('@/app/(app)/schools/actions', () => ({
  bulkAssignClusterAction: vi.fn(),
  bulkAssignProjectAction: vi.fn(),
}));

const SCHOOL_WITH_SSA = create(DirectorySchoolSchema, {
  id: 'sch-1',
  schoolId: '1001',
  name: 'Aduku Primary School',
  district: 'Kwania',
  districtId: 'dist-kwania',
  clusterId: 'clu-aduku',
  clusterName: 'Aduku Cluster',
  visitStatusLabel: 'No Visit Planned',
  visitStatusTone: 'warning',
  ssaAverage: 0,
  ssaTone: 'danger',
  ssaGroups: [
    create(DirectorySsaGroupSchema, {
      key: 'urgent',
      title: 'SSA interventions needing urgent attention',
      tone: 'danger',
      items: [create(DirectorySsaItemSchema, { label: 'Christlike Behaviour', score: 0, band: 'Critical', bandTone: 'danger' })],
    }),
    create(DirectorySsaGroupSchema, {
      key: 'performing-well',
      title: 'SSA interventions performing well',
      tone: 'success',
      items: [create(DirectorySsaItemSchema, { label: 'Leadership', score: 7.1, band: 'Improving', bandTone: 'lime' })],
    }),
    create(DirectorySsaGroupSchema, {
      key: 'warning',
      title: 'SSA interventions to watch',
      tone: 'warning',
      items: [create(DirectorySsaItemSchema, { label: "Teacher's Environment", score: 5.1, band: 'Warning', bandTone: 'warning' })],
    }),
  ],
});

const SCHOOL_NO_SSA = create(DirectorySchoolSchema, {
  id: 'sch-2',
  schoolId: '1002',
  name: 'Unassessed Community School',
  district: '—',
  districtId: '',
  clusterId: '',
  clusterName: 'Not assigned',
  visitStatusLabel: 'No Visit Planned',
  visitStatusTone: 'neutral',
  ssaAverage: undefined,
  ssaTone: 'neutral',
  ssaGroups: [],
});

describe('DirectoryList headers, inline links and disclosure', () => {
  it('renders an aligned visible header row in exact column order without disclosure chevrons', () => {
    const html = renderToStaticMarkup(
      <DirectoryList
        schools={[SCHOOL_WITH_SSA, SCHOOL_NO_SSA]}
        readOnly={false}
        mayOpenProfile={true}
        listed="2 schools listed"
        emptyMessage="No schools"
        existingWebUrl=""
        fy="2027"
      />,
    );
    expect(html).toContain('data-directory-header=""');
    const header = html.slice(html.indexOf('data-directory-header=""'), html.indexOf('<ul role="list"'));
    for (const label of ['Select page', 'School ID', 'School Name', 'District', 'Cluster', 'Visit Status', 'Actions']) {
      expect(header).toContain(label);
    }
    // No visible disclosure chevron in rows.
    expect(html).not.toContain('edify-detail-toggle');
    // Inline links for School, District, and Cluster when authorized/present; plain text when missing.
    expect(html).toContain('href="/schools/1001"');
    expect(html).toContain('href="/districts/dist-kwania"');
    expect(html).toContain('href="/clusters/clu-aduku"');
    // Accessible visually-hidden disclosure button with entity-specific label.
    expect(html).toContain('aria-label="Show details for Aduku Primary School"');
    expect(html).toContain('aria-expanded="false"');
  });

  it('omits selection and actions columns in read-only mode and renders plain text when mayOpenProfile is false', () => {
    const html = renderToStaticMarkup(
      <DirectoryList
        schools={[SCHOOL_WITH_SSA]}
        readOnly={true}
        mayOpenProfile={false}
        listed="1 school listed"
        emptyMessage="No schools"
        existingWebUrl=""
        fy="2027"
      />,
    );
    const header = html.slice(html.indexOf('data-directory-header=""'), html.indexOf('<ul role="list"'));
    expect(header).not.toContain('Select page');
    expect(header).not.toContain('Actions');
    expect(html).not.toContain('href="/schools/1001"');
    expect(html).toContain('aria-label="Show details for Aduku Primary School"');
  });

  it('preserves real zero scores and renders a distinct empty state when unassessed', () => {
    const withZero = renderToStaticMarkup(
      <SsaDetailPanel model={ssaModelFromDirectory(SCHOOL_WITH_SSA.ssaGroups, '2027', true)} />,
    );
    expect(withZero).toContain('SSA DETAIL');
    expect(withZero).toContain('Intervention scores');
    expect(withZero).toContain('Latest confirmed assessment · FY 2027');
    expect(withZero).toContain('Christlike Behaviour');
    expect(withZero).toContain('(0/10)');
    expect(withZero).toContain('Leadership');
    expect(withZero).toContain('(7.1/10)');
    expect(withZero).toContain('Teacher&#x27;s Environment');
    expect(withZero).toContain('(5.1/10)');

    const missing = renderToStaticMarkup(
      <SsaDetailPanel model={ssaModelFromDirectory(SCHOOL_NO_SSA.ssaGroups, '2027', false)} />,
    );
    expect(missing).toContain('data-ssa-empty=""');
    expect(missing).toContain('No confirmed SSA scores are available yet.');
  });
});
