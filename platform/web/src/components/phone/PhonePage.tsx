/*
 * A page on a phone, in the native app's design (mobile/src/screens/
 * PageScreen.tsx): the field-coloured page with its header, the profile tab
 * rail, then the phone reading's blocks and the bar for ticked rows.
 */
import './phone.css';

import type { PageAction } from '@/gen/edify/screens/v1/page_pb';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';

import { SelectionBar } from '../page/SelectionBar';
import { PhoneBlocks } from './PhoneBlocks';
import { PhoneHeader } from './PhoneHeader';

export function PhonePage({ answer, pagePath, drawerHref }: { answer: GetPageResponse; pagePath: string; drawerHref: string }) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const selectable = Boolean(answer.selection?.actions.length);
  return (
    <div data-ph="page" data-page={pagePath}>
      {answer.header ? <PhoneHeader header={answer.header} hrefOf={hrefOf} resolve={resolve} /> : null}
      {answer.tabs.length > 0 ? (
        <nav data-ph="switch" aria-label="Sections">
          {answer.tabs.map((tab) => (
            <a key={tab.key} data-ph="seg" aria-current={tab.active ? 'page' : undefined} href={resolve(`?tab=${encodeURIComponent(tab.key)}`)}>
              {tab.label}
            </a>
          ))}
        </nav>
      ) : null}
      <PhoneBlocks blocks={answer.blocks} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />
      {answer.selection && selectable ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}
