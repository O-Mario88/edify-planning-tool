/**
 * The redesigned Today for any reader (docs/migration/177 stage D): the same
 * screen the CCEO's Home now draws (components/today/TodayScreen), from the
 * same Go answer, for a role whose Home is not rebuilt yet.
 */
import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';

import { NotMovedYet } from '@/components/page/NotMovedYet';
import { TodayScreen } from '@/components/today/TodayScreen';
import { environment } from '@/lib/environment';
import { askHome } from '@/lib/homeData';

export const metadata: Metadata = { title: 'Today (redesign) — Edify' };

export default async function TodayNextPage() {
  const answer = await askHome();
  if (answer.kind === 'elsewhere') redirect(answer.url);
  if (answer.kind === 'notMoved') return <NotMovedYet href={`${environment().existingWebUrl}/home`} />;
  if (answer.kind === 'appOnly') notFound();
  return <TodayScreen parts={answer.parts} note="Redesign preview, from your live queue." />;
}
