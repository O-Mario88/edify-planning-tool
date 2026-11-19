'use client';

/*
 * A record card that opens in place, as the app draws it (PageRecordView.tsx):
 * its tick box for the page's bar, the record's name with its status pills
 * and one Actions menu, then its facts as "Label: value" pairs that wrap.
 * "Show details" opens what the card carries (panels) and the list it loads
 * once opened (a cluster's schools, asked of the gateway through /page-parts,
 * as the desktop card does).
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

import type { PageAction, PageRecord } from '@/gen/edify/screens/v1/page_pb';
import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { actionHref, resolveHref } from '@/lib/feedPage';
import { isPagePart, pagePartUrl } from '@/lib/pagePart';

import { RowActions } from '../blocks/RowActions';
import { SelectionBar } from '../page/SelectionBar';
import { PhonePanel } from './PhonePanel';
import { PhoneTable } from './PhoneTable';
import { phoneTone } from './tone';

type Part = { state: 'idle' | 'loading' } | { state: 'ready'; answer: GetPageResponse } | { state: 'failed'; message: string };

const PART_FAILURES: Readonly<Record<number, string>> = {
  404: 'This was not found, or it is not yours to view.',
  503: 'This list has not moved to the new web app yet. Open it in the existing web app.',
};

function LoadedPart({ answer, drawerHref, scopeId }: { answer: GetPageResponse; drawerHref: string; scopeId: string }) {
  const pagePath = answer.webPath;
  const selectable = Boolean(answer.selection?.actions.length);
  return (
    <div id={scopeId} data-ph="record-part">
      {answer.blocks.map((block, index) => {
        const kind = block.kind;
        if (kind.case === 'panel') return <PhonePanel key={index} panel={kind.value} resolve={(href) => resolveHref(pagePath, href)} />;
        if (kind.case === 'table') return <PhoneTable key={index} table={kind.value} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />;
        return null;
      })}
      {answer.selection && selectable ? <SelectionBar selection={answer.selection} pageHref={drawerHref} scopeId={scopeId} /> : null}
    </div>
  );
}

export interface PhoneRecordProps {
  readonly record: PageRecord;
  readonly pagePath: string;
  readonly drawerHref: string;
  /** The page has a bar for ticked rows. */
  readonly selectable: boolean;
}

export function PhoneRecord({ record, pagePath, drawerHref, selectable }: PhoneRecordProps) {
  const [open, setOpen] = useState(false);
  const [part, setPart] = useState<Part>({ state: 'idle' });
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const loads = isPagePart(record.detailsPath);
  const opens = record.details.length > 0 || loads;
  const scopeId = `ph-record-${record.detailsPath.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  const href = resolve(record.href);

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

  const Chevron = open ? ChevronUp : ChevronDown;
  return (
    <article data-ph="record" data-block="record" aria-label={record.title}>
      <div data-ph="record-head">
        {selectable && record.pickId ? <input type="checkbox" data-pick={record.pickId} aria-label={record.pickLabel || `Select ${record.title}`} /> : null}
        <div data-ph="record-title-row">
          {opens ? (
            <button type="button" data-ph="record-title" aria-expanded={open} onClick={toggle} aria-label={`${open ? 'Hide' : 'Show'} details for ${record.title}`}>
              {record.title}
            </button>
          ) : href ? (
            <a data-ph="record-title" href={href}>
              {record.title}
            </a>
          ) : (
            <span data-ph="record-title">{record.title}</span>
          )}
          {record.badges.map((badge) => (
            <span key={badge.text} data-ph="record-badge" data-ph-tone={phoneTone(badge.tone) ?? undefined} title={badge.title || undefined}>
              {badge.text}
            </span>
          ))}
        </div>
        {record.actions.length > 0 ? (
          <RowActions
            subject={record.title}
            actions={record.actions.map((action) => ({ key: `${action.key}:${action.label}`, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
          />
        ) : null}
      </div>
      {record.subtitle ? <p data-ph="record-subtitle">{record.subtitle}</p> : null}
      {record.facts.length > 0 ? (
        <div data-ph="details-facts">
          {record.facts.map((fact) => (
            <span key={fact.label} data-ph="details-fact" data-ph-tone={phoneTone(fact.tone) ?? undefined} data-plain={fact.href ? undefined : true}>
              {fact.label}: {fact.href ? <a href={resolve(fact.href)}><b>{fact.value}</b></a> : <b>{fact.value}</b>}
            </span>
          ))}
        </div>
      ) : null}
      {opens ? (
        <button type="button" data-ph="record-toggle" aria-expanded={open} onClick={toggle}>
          {open ? 'Hide details' : 'Show details'}
          <Chevron size={14} aria-hidden="true" />
        </button>
      ) : null}
      {open ? (
        <div data-ph="record-open" data-record-open>
          {href ? (
            <a data-ph="details-link" href={href}>
              Open {record.title} profile
            </a>
          ) : null}
          {record.details.map((block, index) => (block.kind.case === 'panel' ? <PhonePanel key={index} panel={block.kind.value} resolve={resolve} /> : null))}
          {part.state === 'loading' ? <p data-ph="record-status" role="status">Loading…</p> : null}
          {part.state === 'failed' ? <p data-ph="record-status" data-ph-tone="alert" role="alert">{part.message}</p> : null}
          {part.state === 'ready' ? <LoadedPart answer={part.answer} drawerHref={drawerHref} scopeId={scopeId} /> : null}
        </div>
      ) : null}
    </article>
  );
}
