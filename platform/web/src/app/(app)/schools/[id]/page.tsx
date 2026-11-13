import type { Metadata } from 'next';

import { ProfilePage } from '@/components/page/ProfilePage';
import { pageQuery } from '@/lib/feedPage';

export const metadata: Metadata = { title: 'School Profile - Edify Command Center' };

type Params = Promise<{ id: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * A school's profile (School 360) by School ID or record id, drawn from the
 * gateway's GetSchoolProfile answer, which Go reads
 * (docs/migration/13-school-profiles.md).
 */
export default async function SchoolProfileRoute({ params, searchParams }: { params: Params; searchParams: Search }) {
  const { id } = await params;
  return <ProfilePage schoolId={id.slice(0, 64)} query={pageQuery(await searchParams)} />;
}
