/*
 * A page on a phone, in the native app's design (mobile/src/screens/
 * PageScreen.tsx): the field-coloured page with its header, the profile tab
 * rail, then the phone reading's blocks and the bar for ticked rows.
 */
import './phone.css';

import type { ReactNode } from 'react';

import type { PageAction, PageLinkTab } from '@/gen/edify/screens/v1/page_pb';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';

import { SelectionBar } from '../page/SelectionBar';
import { PhoneBlocks } from './PhoneBlocks';
import { PhoneHeader } from './PhoneHeader';

/** What a phone page draws: a page's answer, or a school profile's, which has the same parts. */
export type PhoneAnswer = Pick<GetPageResponse, 'header' | 'tabs' | 'blocks' | 'selection'>;

export interface PhonePageProps {
  readonly answer: PhoneAnswer;
  readonly pagePath: string;
  readonly drawerHref: string;
  /** The tab rail's links, where the page builds its own (the profile keeps its year). */
  readonly tabLinks?: readonly PageLinkTab[];
  /** Drawn after the blocks (the profile's Location & Directions card). */
  readonly children?: ReactNode;
}

export function PhonePage({ answer, pagePath, drawerHref, tabLinks, children }: PhonePageProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const selectable = Boolean(answer.selection?.actions.length);
  const tabs = tabLinks ?? answer.tabs.map((tab) => ({ label: tab.label, active: tab.active, href: resolve(`?tab=${encodeURIComponent(tab.key)}`) }));
  return (
    <div data-ph="page" data-page={pagePath}>
      {answer.header ? <PhoneHeader header={answer.header} hrefOf={hrefOf} resolve={resolve} /> : null}
      {tabs.length > 0 ? (
        // The profile's tab rail: straight dividers, the open tab filled, scrolling sideways when long.
        <nav data-ph="switch" aria-label="Sections">
          {tabs.map((tab) => (
            <a key={tab.href} data-ph="seg" aria-current={tab.active ? 'page' : undefined} href={tab.href}>
              {tab.label}
            </a>
          ))}
        </nav>
      ) : null}
      <PhoneBlocks blocks={answer.blocks} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />
      {children}
      {answer.selection && selectable ? <SelectionBar selection={answer.selection} pageHref={drawerHref} /> : null}
    </div>
  );
}
