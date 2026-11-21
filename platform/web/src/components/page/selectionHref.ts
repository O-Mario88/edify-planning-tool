import type { PageSelectionAction } from '@/gen/edify/screens/v1/page_pb';

export function selectionHref(pageHref: string, action: Pick<PageSelectionAction, 'href' | 'param' | 'joined'>, ids: readonly string[]) {
  const page = new URL(pageHref);
  const drawer = new URL(action.href, page.origin);
  if (action.joined) drawer.searchParams.set(action.param, ids.join(','));
  else ids.forEach((id) => drawer.searchParams.append(action.param, id));
  page.hash = new URLSearchParams({ selection: drawer.pathname + drawer.search }).toString();
  return page.href;
}
