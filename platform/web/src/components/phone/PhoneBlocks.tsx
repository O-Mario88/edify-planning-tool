/*
 * A page's blocks on a phone, in the page's order, each drawn the way the
 * native app draws it (mobile/src/ui/page/PageBlocksView.tsx). A kind the
 * app's design has no web part for yet is drawn by the desktop block
 * (FeedBlocks), never dropped.
 */
import type { PageAction, PageBlock, PageFacts } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';

import { FeedBlocks } from '../page/FeedBlocks';
import { PhoneFilters } from './PhoneFilters';
import { PhoneLinkTabs } from './PhoneLinkTabs';
import { PhoneList } from './PhoneList';
import { PhonePanel } from './PhonePanel';
import { PhoneRecord } from './PhoneRecord';
import { PhoneSegments } from './PhoneSegments';
import { PhoneEmpty, PhonePager } from './PhoneParts';
import { PhoneTable } from './PhoneTable';
import { PhoneTiles } from './PhoneTiles';

export interface PhoneBlocksProps {
  readonly blocks: readonly PageBlock[];
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

/** A pager strip after a table is that table's foot, as on the page. */
function joinsTable(blocks: readonly PageBlock[], index: number): boolean {
  return blocks[index]?.kind.case === 'pager' && blocks[index - 1]?.kind.case === 'table';
}

function FactsCard({ facts, resolve }: { facts: PageFacts; resolve: (href: string) => string }) {
  return (
    <section data-ph="card" data-padded="" aria-label="Profile details">
      <div data-ph="facts">
        {facts.facts.map((fact) => (
          <span key={fact.label} data-ph="fact">
            {fact.label}: {fact.href ? <a href={resolve(fact.href)}>{fact.value}</a> : <b>{fact.value}</b>}
          </span>
        ))}
      </div>
    </section>
  );
}

export function PhoneBlocks({ blocks, pagePath, drawerHref, selectable }: PhoneBlocksProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const draw = (list: readonly PageBlock[], index: number, bare = false) => {
    const block = list[index] as PageBlock;
    const kind = block.kind;
    if (joinsTable(list, index)) return null;
    switch (kind.case) {
      case 'scopeLine':
        return (
          <p key={index} data-ph="scope">
            {kind.value}
          </p>
        );
      case 'section':
        return (
          <h2 key={index} data-ph="section">
            {kind.value}
          </h2>
        );
      case 'facts':
        return <FactsCard key={index} facts={kind.value} resolve={resolve} />;
      case 'filters':
        return <PhoneFilters key={index} filters={kind.value} action={pagePath} />;
      case 'linkTabs':
        return <PhoneLinkTabs key={index} tabs={kind.value} resolve={resolve} besideHref={kind.value.beside ? hrefOf(kind.value.beside) : undefined} />;
      case 'strip':
        return <PhoneTiles key={index} strip={kind.value} resolve={resolve} />;
      case 'table': {
        const next = list[index + 1];
        const footer = next?.kind.case === 'pager' ? <PhonePager pager={next.kind.value} resolve={resolve} /> : undefined;
        return <PhoneTable key={index} table={kind.value} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} bare={bare} footer={footer} />;
      }
      case 'pager':
        return (
          <section key={index} data-ph="card">
            <PhonePager pager={kind.value} resolve={resolve} alone />
          </section>
        );
      case 'panel':
        return <PhonePanel key={index} panel={kind.value} resolve={resolve} />;
      case 'list':
        return <PhoneList key={index} list={kind.value} resolve={resolve} hrefOf={hrefOf} />;
      case 'record':
        return <PhoneRecord key={index} record={kind.value} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />;
      case 'empty':
        return <PhoneEmpty key={index} message={kind.value} hrefOf={hrefOf} />;
      case 'segments':
        return (
          <PhoneSegments
            key={index}
            title={kind.value.title}
            subtitle={kind.value.subtitle}
            caption={kind.value.caption}
            segments={kind.value.segments.map((segment) => ({
              label: segment.label,
              count: segment.count,
              active: segment.active,
              body: <>{segment.blocks.map((_, innerIndex) => draw(segment.blocks, innerIndex, true))}</>,
            }))}
          />
        );
      case undefined:
        return null;
      default:
        return <FeedBlocks key={index} blocks={[block]} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />;
    }
  };
  return <div data-ph="blocks">{blocks.map((_, index) => draw(blocks, index))}</div>;
}
