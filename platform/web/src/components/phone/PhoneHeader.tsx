/*
 * A page's header as the app draws it (screens/PageScreen.tsx and
 * PageHeaderParts.tsx): the back link, eyebrow, the title with Export beside
 * it, the description (a "Label: value" line set bold after its colon), then
 * the pills and the other buttons in one wrapping row.
 */
import { ChevronLeft, Download } from 'lucide-react';

import type { PageAction, PageHeader } from '@/gen/edify/screens/v1/page_pb';

import { phoneTone } from './tone';

function Description({ text }: { text: string }) {
  const at = text.indexOf(': ');
  return (
    <p data-ph="description">
      {at > 0 ? (
        <>
          {text.slice(0, at + 2)}
          <b>{text.slice(at + 2)}</b>
        </>
      ) : (
        text
      )}
    </p>
  );
}

export function PhoneHeader({ header, hrefOf, resolve }: { header: PageHeader; hrefOf: (action: PageAction) => string; resolve: (href: string) => string }) {
  const exportAction = header.actions.find((action) => action.key === 'export');
  const buttons = header.actions.filter((action) => action !== exportAction);
  return (
    <>
      {header.backLabel ? (
        <a data-ph="back" href={resolve(header.backHref)}>
          <ChevronLeft size={14} aria-hidden="true" />
          {header.backLabel}
        </a>
      ) : null}
      {header.eyebrow ? <p data-ph="eyebrow">{header.eyebrow}</p> : null}
      <div data-ph="title-row">
        <h1 data-ph="title">{header.title}</h1>
        {exportAction ? (
          <a data-ph="export" href={hrefOf(exportAction)} data-action="export">
            <Download size={14} aria-hidden="true" />
            {exportAction.label}
          </a>
        ) : null}
      </div>
      {header.description ? <Description text={header.description} /> : null}
      {header.badges.length > 0 || buttons.length > 0 ? (
        <div data-ph="controls">
          {header.badges.map((badge, index) => {
            const tone = badge.tone === 'plain' ? undefined : phoneTone(badge.tone);
            return (
              <span key={badge.text} data-ph="pill" data-ph-tone={tone} data-wide={(index === 0 && header.badges.length > 1) || undefined} title={badge.title || undefined}>
                {badge.text}
              </span>
            );
          })}
          {buttons.map((action) => (
            <a
              key={action.key + action.href}
              data-ph="action"
              data-primary={action.primary || undefined}
              data-action={action.key}
              href={action.enabled ? hrefOf(action) : undefined}
              aria-disabled={action.enabled ? undefined : true}
              title={action.enabled ? undefined : action.reason || undefined}
            >
              {action.label}
            </a>
          ))}
        </div>
      ) : null}
    </>
  );
}
