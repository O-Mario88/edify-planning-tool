'use client';

/*
 * A record card (PageRecord: the Clusters page's cards, Core Schools Matrix,
 * Planning's Clusters tab): the inline name linking to its profile, its pills,
 * one Actions menu, and its facts in one flowing line of "Label: value".
 * Clicking any non-interactive part of the summary toggles details inline;
 * clicking inside the opened detail panel allows normal selection and nested
 * interactions without collapsing the parent card.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import Link from 'next/link';
import { useId, useState } from 'react';

import type { PageAction, PageRecord } from '@/gen/edify/screens/v1/page_pb';
import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';
import { isPagePart, pagePartUrl } from '@/lib/pagePart';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { recordFactTone } from '../blocks/tones';
import { FeedFacts } from './FeedFacts';
import { FeedPanel } from './FeedPanel';
import { FeedTable } from './FeedTable';
import { SelectionBar } from './SelectionBar';

type Part = { state: 'idle' | 'loading' } | { state: 'ready'; answer: GetPageResponse } | { state: 'failed'; message: string };

const PART_FAILURES: Readonly<Record<number, string>> = {
  404: 'This was not found, or it is not yours to view.',
  503: 'This list has not moved to the new web app yet. Open the cluster in the existing web app.',
};

const INTERACTIVE_SELECTOR = 'a, button, input, label, select, textarea, [role="menu"], [role="menuitem"], [data-row-actions]';

function isInteractive(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(INTERACTIVE_SELECTOR));
}

function profileLinkLabel(title: string, href: string): string {
  if (href.startsWith('/clusters/')) return `Open ${title} cluster profile`;
  if (href.startsWith('/schools/')) return `Open ${title} school profile`;
  return `Open ${title} profile`;
}

export interface FeedRecordProps {
  readonly record: PageRecord;
  readonly pagePath: string;
  readonly drawerHref: string;
}

function LoadedPart({ answer, drawerHref, scopeId }: { answer: GetPageResponse; drawerHref: string; scopeId: string }) {
  const pagePath = answer.webPath;
  const resolve = (href: string) => resolveHref(pagePath, href);
  const selectable = Boolean(answer.selection?.actions.length);
  return (
    <div id={scopeId} className="mt-3 space-y-3">
      {answer.blocks.map((block, index) => {
        const kind = block.kind;
        if (kind.case === 'panel') return <FeedPanel key={index} panel={kind.value} resolve={resolve} drawerHref={drawerHref} nested />;
        if (kind.case === 'table') return <FeedTable key={index} table={kind.value} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />;
        return null;
      })}
      {answer.selection && selectable ? <SelectionBar selection={answer.selection} pageHref={drawerHref} scopeId={scopeId} /> : null}
    </div>
  );
}

export function FeedRecord({ record, pagePath, drawerHref }: FeedRecordProps) {
  const [open, setOpen] = useState(false);
  const [part, setPart] = useState<Part>({ state: 'idle' });
  const reactId = useId();
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const href = resolve(record.href);
  const loads = isPagePart(record.detailsPath);
  const opens = record.details.length > 0 || loads;
  const stableSlug = (record.pickId || record.href || record.detailsPath || record.title).replace(/[^A-Za-z0-9_-]/g, '-');
  const detailsId = `record-details-${stableSlug}-${reactId}`;
  const scopeId = `record-part-${record.detailsPath.replace(/[^A-Za-z0-9_-]/g, '-')}`;

  async function load() {
    setPart({ state: 'loading' });
    try {
      const response = await fetch(pagePartUrl(record.detailsPath), { cache: 'no-store' });
      if (response.status === 401) {
        window.location.reload();
        return;
      }
      if (!response.ok) {
        setPart({ state: 'failed', message: PART_FAILURES[response.status] ?? 'This list could not be loaded. Try again.' });
        return;
      }
      setPart({ state: 'ready', answer: fromJson(GetPageResponseSchema, (await response.json()) as JsonValue) });
    } catch {
      setPart({ state: 'failed', message: 'This list could not be loaded. Try again.' });
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && loads && (part.state === 'idle' || part.state === 'failed')) void load();
  }

  return (
    <article
      data-block="record"
      data-record-id={record.pickId || record.href || record.detailsPath || record.title}
      data-open={open ? 'true' : undefined}
      className="card overflow-hidden p-0 shadow-[var(--edify-shadow-sm)]"
    >
      <div
        data-record-summary=""
        onClick={(event) => {
          if (!opens || isInteractive(event.target)) return;
          if (window.getSelection()?.toString()) return;
          toggle();
        }}
        className={`relative px-4 py-3 transition-colors ${
          opens
            ? 'cursor-pointer hover:bg-[color-mix(in_oklab,var(--edify-surface-muted)_55%,transparent)] focus-within:bg-[color-mix(in_oklab,var(--edify-surface-muted)_40%,transparent)]'
            : ''
        } ${open ? 'bg-[color-mix(in_oklab,var(--edify-surface-muted)_45%,transparent)]' : ''}`}
      >
        <header className="flex flex-wrap items-center gap-2">
          {opens ? (
            <button
              type="button"
              onClick={toggle}
              aria-expanded={open}
              aria-controls={detailsId}
              aria-label={open ? `Hide details for ${record.title}` : `Show details for ${record.title}`}
              className="sr-only focus:not-sr-only focus:inline-flex focus:items-center focus:rounded focus:bg-[var(--edify-surface)] focus:px-2 focus:py-0.5 focus:text-[12px] focus:font-semibold focus:text-[var(--brand-primary-text)] focus:outline focus:outline-2 focus:outline-[var(--edify-accent)]"
            >
              {open ? 'Hide details' : 'Show details'}
            </button>
          ) : null}
          {record.pickId ? (
            <input
              type="checkbox"
              data-pick={record.pickId}
              aria-label={record.pickLabel || `Select ${record.title}`}
              className="h-4 w-4 shrink-0 accent-[var(--brand-primary)]"
            />
          ) : null}
          <h2 className="min-w-0 text-[length:var(--edify-text-label-size)] font-bold">
            {href ? (
              <Link href={href} className="inline hover:underline">
                {record.title}
              </Link>
            ) : (
              record.title
            )}
          </h2>
          {record.badges.map((badge) => (
            <Badge key={badge.text} tone={badge.tone} title={badge.title}>
              {badge.text}
            </Badge>
          ))}
          {record.subtitle ? <span className="text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{record.subtitle}</span> : null}
          <div className="ml-auto">
            <RowActions
              subject={record.title}
              actions={record.actions.map((action) => ({
                key: `${action.key}:${action.label}`,
                label: action.label,
                enabled: action.enabled,
                reason: action.reason,
                href: hrefOf(action),
              }))}
            />
          </div>
        </header>
        {record.facts.length ? (
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--edify-text-label-size)]">
            {record.facts.map((fact) => {
              const factHref = resolve(fact.href);
              return (
                <div key={fact.label} className="flex min-w-0 gap-1">
                  <dt className="font-medium text-[var(--edify-text-muted)]">{fact.label}:</dt>
                  <dd className={`font-semibold ${recordFactTone(fact.tone)}`}>
                    {factHref ? (
                      <Link href={factHref} className="inline hover:underline">
                        {fact.value}
                      </Link>
                    ) : (
                      fact.value
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        ) : null}
      </div>
      {open ? (
        <div
          id={detailsId}
          className="space-y-3 border-t border-[var(--edify-table-divider)] bg-[var(--edify-surface)] px-4 py-3"
          data-record-open=""
          onClick={(event) => event.stopPropagation()}
        >
          {href ? (
            <div>
              <Link href={href} className="inline text-[13px] font-bold text-[var(--edify-text)] hover:underline">
                {profileLinkLabel(record.title, href)}
              </Link>
            </div>
          ) : null}
          {record.details.map((block, index) => {
            if (block.kind.case === 'facts') {
              return <FeedFacts key={index} facts={block.kind.value} resolve={resolve} />;
            }
            if (block.kind.case === 'panel') {
              return <FeedPanel key={index} panel={block.kind.value} resolve={resolve} drawerHref={drawerHref} nested />;
            }
            return null;
          })}
          {part.state === 'loading' ? (
            <p className="mt-3 text-[var(--edify-text-muted)]" role="status">
              Loading schools…
            </p>
          ) : null}
          {part.state === 'failed' ? (
            <p className="mt-3 text-[#be123c] dark:text-[var(--edify-danger)]" role="alert">
              {part.message}
            </p>
          ) : null}
          {part.state === 'ready' ? <LoadedPart answer={part.answer} drawerHref={drawerHref} scopeId={scopeId} /> : null}
        </div>
      ) : null}
    </article>
  );
}
