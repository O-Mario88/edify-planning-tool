/*
 * A card of rows as the app draws it (PageListView.tsx): each record's
 * coloured icon square, its bold title and the lines under it, its pills
 * and its buttons. A titled list carries its heading above the card. An
 * entry with records under it opens onto them (the web's <details> group).
 * Rows carry their chip keys (data-list-row) for the page's chips.
 */
import { ChevronRight, Zap } from 'lucide-react';

import type { PageAction, PageList, PageListItem } from '@/gen/edify/screens/v1/page_pb';

import { phoneTone } from './tone';

interface Links {
  readonly resolve: (href: string) => string;
  readonly hrefOf: (action: PageAction) => string;
}

function Row({ item, links }: { item: PageListItem; links: Links }) {
  const body = (
    <>
      <span data-ph="list-icon" data-ph-tone={phoneTone(item.tone || 'brand') ?? 'brand'} aria-hidden="true">
        <Zap size={15} />
      </span>
      <span data-ph="list-words">
        <span data-ph="list-title">{item.title}</span>
        {item.lines.map((line) => (
          <span key={line} data-ph="list-line">
            {line}
          </span>
        ))}
      </span>
    </>
  );
  const extras =
    item.badges.length > 0 || item.actions.length > 0 ? (
      <span data-ph="list-extras">
        {item.badges.map((badge) => (
          <span key={badge.text} data-ph="pill" data-ph-tone={badge.tone === 'plain' ? undefined : phoneTone(badge.tone)}>
            {badge.text}
          </span>
        ))}
        {item.actions.map((action) =>
          action.enabled ? (
            <a key={action.href + action.label} data-ph="list-action" href={links.hrefOf(action)} aria-label={`${action.label}: ${item.title}`}>
              {action.label}
            </a>
          ) : (
            <span key={action.href + action.label} data-ph="list-action" aria-disabled="true" title={action.reason || undefined}>
              {action.label}
            </span>
          ),
        )}
      </span>
    ) : null;
  return (
    <li data-ph="list-row" data-list-row={JSON.stringify(item.keys)}>
      {item.href ? (
        <a data-ph="list-main" href={links.resolve(item.href)}>
          {body}
        </a>
      ) : (
        <span data-ph="list-main">{body}</span>
      )}
      {extras}
    </li>
  );
}

function Group({ item, links }: { item: PageListItem; links: Links }) {
  return (
    <li data-ph="list-row" data-list-row={JSON.stringify(item.keys)}>
      <details data-ph="list-group">
        <summary data-ph="list-main" aria-label={`${item.title}, ${item.count}`}>
          <span data-ph="list-chevron" aria-hidden="true">
            <ChevronRight size={16} />
          </span>
          <span data-ph="list-words">
            <span data-ph="list-title">{item.title}</span>
            {item.lines.map((line) => (
              <span key={line} data-ph="list-line">
                {line}
              </span>
            ))}
          </span>
          <span data-ph="pill">{item.count}</span>
        </summary>
        <ul data-ph="list-children">
          {item.children.map((child, index) => (
            <Row key={`${child.title}-${index}`} item={child} links={links} />
          ))}
        </ul>
      </details>
    </li>
  );
}

export function PhoneList({ list, resolve, hrefOf }: { list: PageList } & Links) {
  const links = { resolve, hrefOf };
  return (
    <section data-ph="list-section" aria-label={list.title || undefined}>
      {list.title ? (
        <div data-ph="list-head">
          <h2 data-ph="table-title">{list.title}</h2>
          {list.count ? <span data-ph="list-count">{list.count}</span> : null}
        </div>
      ) : null}
      {list.items.length === 0 && list.empty ? (
        <div data-ph="card">
          <div data-ph="empty">
            <span>{list.empty}</span>
          </div>
        </div>
      ) : (
        <ul data-ph="list-card">
          {list.items.map((item, index) =>
            item.children.length > 0 ? (
              <Group key={`${item.title}-${index}`} item={item} links={links} />
            ) : (
              <Row key={`${item.title}-${index}`} item={item} links={links} />
            ),
          )}
        </ul>
      )}
    </section>
  );
}
