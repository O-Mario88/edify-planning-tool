import { NotMovedYet as NotMovedYetCard } from '@/components/page/NotMovedYet';
import { currentPath } from '@/lib/auth';
import { environment } from '@/lib/environment';

/*
 * A page that has not moved to this web app yet says so and opens the same
 * page of the existing web, rather than drawing something that looks
 * finished and is not.
 */
export default async function NotMovedYet() {
  const path = await currentPath();
  return <NotMovedYetCard href={`${environment().existingWebUrl}${path}`} />;
}
