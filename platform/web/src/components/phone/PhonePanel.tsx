/*
 * A titled card of record details as the app draws it (PagePanelView.tsx):
 * its title, badges and the line under it, then its parts in the page's
 * order: sub-headings, paragraphs, fields ("Label: value", one to a line),
 * data rows with their figures ruled right, linked lists and a meter.
 */
import type { CSSProperties } from 'react';

import type { PagePanel, PagePanelItem } from '@/gen/edify/screens/v1/page_pb';

import { phoneTone } from './tone';

function Item({ item, resolve }: { item: PagePanelItem; resolve: (href: string) => string }) {
  const kind = item.kind;
  switch (kind.case) {
    case 'heading':
      return <h3 data-ph="panel-heading">{kind.value}</h3>;
    case 'text':
      return (
        <p data-ph="panel-text" data-ph-tone={phoneTone(item.tone)}>
          {kind.value}
        </p>
      );
    case 'fields':
      return (
        <div>
          {kind.value.facts.map((field, index) => (
            <p key={`${field.label}-${index}`} data-ph="panel-field">
              {field.label}: {field.href ? <a href={resolve(field.href)}>{field.value}</a> : <b>{field.value}</b>}
            </p>
          ))}
        </div>
      );
    case 'rows':
      return (
        <div>
          {kind.value.rows.map((row, index) => (
            <div key={index} data-ph="data-row">
              <span data-ph="data-line">
                <span data-ph="data-label">{row.label}</span>
                <span data-ph="data-value" data-ph-tone={phoneTone(row.tone)}>
                  {row.value}
                </span>
              </span>
              {row.meta ? <span data-ph="data-meta">{row.meta}</span> : null}
            </div>
          ))}
        </div>
      );
    case 'links':
      return (
        <div data-ph="panel-links">
          {kind.value.links.map((link) => {
            const words = (
              <>
                <span data-ph="link-text">{link.text}</span>
                {link.caption ? <span data-ph="link-caption">{link.caption}</span> : null}
              </>
            );
            return link.href ? (
              <a key={`${link.text}-${link.caption}`} data-ph="panel-link" href={resolve(link.href)}>
                {words}
              </a>
            ) : (
              <span key={`${link.text}-${link.caption}`} data-ph="panel-link">
                {words}
              </span>
            );
          })}
        </div>
      );
    case 'meter':
      return (
        <div data-ph="panel-meter">
          <span data-ph="meter-figure">
            {kind.value.value} <span data-ph="link-caption">{kind.value.label}</span>
          </span>
          <span data-ph="meter-track" aria-hidden="true">
            <span data-ph="meter-fill" style={{ '--ph-fill': `${Math.min(100, Math.max(0, kind.value.fraction * 100))}%` } as CSSProperties} />
          </span>
        </div>
      );
    default:
      return null;
  }
}

export function PhonePanel({ panel, resolve }: { panel: PagePanel; resolve: (href: string) => string }) {
  const hasHead = panel.title !== '' || panel.badges.length > 0;
  return (
    <section data-ph="card" aria-label={panel.title || undefined}>
      {hasHead ? (
        <div data-ph="panel-head">
          <div data-ph="panel-title-line">
            <h2 data-ph="table-title">{panel.title}</h2>
            {panel.badges.map((badge) => (
              <span key={badge.text} data-ph="panel-badge">
                {badge.text}
              </span>
            ))}
          </div>
          {panel.subtitle ? <p data-ph="panel-subtitle">{panel.subtitle}</p> : null}
        </div>
      ) : null}
      <div data-ph="panel-body">
        {panel.items.map((item, index) => (
          <Item key={index} item={item} resolve={resolve} />
        ))}
      </div>
    </section>
  );
}
