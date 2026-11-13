/*
 * A page's blocks in the order the page draws them (PageBlock). The kinds
 * Planning and My Plan answer with are drawn; any other kind the gateway may
 * add later is named as not drawn yet rather than silently dropped.
 */
import type { PageAction, PageBlock, PageLinkTabs } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';

import { BUTTON_PRIMARY } from '../blocks/buttons';
import { FilterBar } from '../blocks/FilterBar';
import { Pager } from '../blocks/Pager';
import { TabRail } from '../blocks/TabRail';
import { Icon } from '../shell/icons';
import { FeedPanel } from './FeedPanel';
import { FeedRecord } from './FeedRecord';
import { FeedStrip } from './FeedStrip';
import { FeedTable } from './FeedTable';

export interface FeedBlocksProps {
  readonly blocks: readonly PageBlock[];
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

function LinkTabsBlock({ rail, pagePath, hrefOf }: { rail: PageLinkTabs; pagePath: string; hrefOf: (action: PageAction) => string }) {
  const resolved = { ...rail, tabs: rail.tabs.map((tab) => ({ ...tab, href: resolveHref(pagePath, tab.href) })) };
  const beside = rail.beside;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <TabRail rail={resolved} />
      {beside ? (
        <a href={hrefOf(beside)} className={BUTTON_PRIMARY} data-action={beside.key}>
          <Icon name="calendar" className="h-[18px] w-[18px]" />
          <span>{beside.label}</span>
        </a>
      ) : null}
    </div>
  );
}

/** A pager strip that follows a table or a list's empty state is that card's foot, as on the page. */
function joinsPrevious(blocks: readonly PageBlock[], index: number): boolean {
  const before = blocks[index - 1]?.kind.case;
  return blocks[index]?.kind.case === 'pager' && (before === 'table' || before === 'panel');
}

export function FeedBlocks({ blocks, pagePath, drawerHref, selectable }: FeedBlocksProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const pagerOf = (block: PageBlock | undefined) =>
    block?.kind.case === 'pager' ? <Pager pager={{ ...block.kind.value, pages: block.kind.value.pages.map((page) => ({ ...page, href: resolve(page.href) })) }} /> : undefined;
  return (
    <>
      {blocks.map((block, index) => {
        const kind = block.kind;
        if (joinsPrevious(blocks, index)) return null;
        const footer = joinsPrevious(blocks, index + 1) ? pagerOf(blocks[index + 1]) : undefined;
        switch (kind.case) {
          case 'filters':
            return (
              <FilterBar
                key={index}
                action={pagePath}
                clearHref={pagePath}
                oneRow
                hidden={kind.value.hidden}
                filters={kind.value.filters.map((filter) => ({
                  name: filter.name,
                  label: filter.label,
                  caption: filter.caption,
                  value: filter.value,
                  options: filter.options.map(({ value, label }) => ({ value, label })),
                }))}
              />
            );
          case 'strip':
            return <FeedStrip key={index} strip={kind.value} resolve={resolve} />;
          case 'panel':
            return <FeedPanel key={index} panel={kind.value} resolve={resolve} drawerHref={drawerHref} footer={footer} />;
          case 'linkTabs':
            return <LinkTabsBlock key={index} rail={kind.value} pagePath={pagePath} hrefOf={hrefOf} />;
          case 'table':
            return <FeedTable key={index} table={kind.value} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} footer={footer} />;
          case 'record':
            return <FeedRecord key={index} record={kind.value} pagePath={pagePath} drawerHref={drawerHref} />;
          case 'pager':
            return (
              <div key={index} className="overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)]">
                {pagerOf(block)}
              </div>
            );
          case 'section':
            return <h2 key={index} className="pt-2 text-[length:var(--edify-text-title-size)] font-bold">{kind.value}</h2>;
          case 'empty':
          case 'scopeLine':
            return <p key={index} className="text-[length:var(--edify-text-label-size)] font-medium text-[var(--edify-text-muted)]">{kind.value}</p>;
          case undefined:
            return null;
          default:
            return (
              <p key={index} data-block="not-drawn" className="rounded-[10px] border border-dashed border-[var(--edify-border)] px-4 py-3 text-[var(--edify-text-muted)]">
                This part of the page is not drawn here yet.
              </p>
            );
        }
      })}
    </>
  );
}
