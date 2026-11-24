/*
 * A card of rows (partials/todos/row.html and its kin: To-Do, the dashboard's
 * "Do next") and a form a page shows itself, as the app draws them
 * (mobile/src/ui/page/PageListView.tsx, PageFormView.tsx), at desktop width:
 * each row's tinted icon square, its bold title and the lines under it, its
 * pills and its buttons; an entry holding identical records opens onto
 * them. Each row carries its keys so the page's chips (FeedChips) can hide
 * the rows another chip excludes.
 */
import Link from 'next/link';

import type { PageAction, PageForm, PageList, PageListItem } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import { PageFormInline } from './PageFormInline';
import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '../blocks/buttons';

const TONE_SQUARE: Readonly<Record<string, string>> = {
  info: 'bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  brand: 'bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  good: 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)]',
  caution: 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  alert: 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)]',
};

function Bolt() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true" className="h-4 w-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" />
    </svg>
  );
}

function RowButtons({ actions, hrefOf }: { actions: readonly PageAction[]; hrefOf: (action: PageAction) => string }) {
  if (actions.length === 0) return null;
  return (
    <span className="flex shrink-0 flex-wrap items-center gap-2">
      {actions.map((action, index) => (
        <Link key={index} href={hrefOf(action)} className={`${index === 0 ? BUTTON_PRIMARY : BUTTON_OUTLINE} h-9 px-3 text-[13px]`}>
          {action.label}
        </Link>
      ))}
    </span>
  );
}

function Row({ item, resolve, hrefOf }: { item: PageListItem; resolve: (href: string) => string; hrefOf: (action: PageAction) => string }) {
  const href = resolve(item.href);
  const title = href ? (
    <Link href={href} className="hover:underline">
      {item.title}
    </Link>
  ) : (
    item.title
  );
  const body = (
    <span className="flex min-w-0 flex-1 items-start gap-3">
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-[10px] ${TONE_SQUARE[item.tone] ?? TONE_SQUARE.brand}`}>
        <Bolt />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-[var(--edify-text)]">{title}</span>
        {item.lines.map((line, index) => (
          <span key={index} className="block text-[13px] text-[var(--edify-text-muted)]">
            {line}
          </span>
        ))}
        {item.badges.length ? (
          <span className="mt-1 flex flex-wrap gap-1">
            {item.badges.map((badge, index) => (
              <Badge key={index} tone={badge.tone} title={badge.title || undefined}>
                {badge.text}
              </Badge>
            ))}
          </span>
        ) : null}
      </span>
    </span>
  );
  const keys = JSON.stringify(item.keys);
  if (item.children.length) {
    return (
      <li data-list-row={keys} className="border-b border-[var(--edify-border)] last:border-b-0">
        <details>
          <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3">
            {body}
            <span className="rounded-full bg-[var(--edify-surface-muted)] px-2 py-0.5 text-[12px] font-semibold">{item.count}</span>
          </summary>
          <ul className="pb-2 pl-8">
            {item.children.map((child, index) => (
              <Row key={index} item={child} resolve={resolve} hrefOf={hrefOf} />
            ))}
          </ul>
        </details>
      </li>
    );
  }
  return (
    <li data-list-row={keys} className="flex flex-wrap items-center gap-3 border-b border-[var(--edify-border)] px-4 py-3 last:border-b-0">
      {body}
      <RowButtons actions={item.actions} hrefOf={hrefOf} />
    </li>
  );
}

/** A badge tone as the Admin dashboard's .admin-status colour. */
const ADMIN_STATUS: Readonly<Record<string, string>> = { danger: 's-red', warning: 's-orange', info: 's-blue', success: 's-green' };

/**
 * A card of the Admin dashboard's own family (.admin-panel of
 * .admin-target-row rows, partials/dashboards/admin/_platform_operations.html):
 * each row its title (a link or a day), its figure, then its status, next
 * step or bar, drawn by the existing admin-dashboard stylesheet.
 */
function AdminPanel({ list, resolve }: { list: PageList; resolve: (href: string) => string }) {
  // A card of bars is the Sign-ins card, whose rows the stylesheet lays out
  // as day, figure and bar ([data-admin-logins]); a row without a bar keeps
  // its empty third cell, as the template writes it.
  const logins = list.items.some((item) => item.meter);
  return (
    // A card with a header is a structured surface (static/js/micro-ux.js), which consistency.css reads for its padding.
    <section className="admin-panel edify-structured-surface" aria-label={list.title || undefined} data-block="list" data-family="admin-panel" data-admin-logins={logins ? '' : undefined}>
      <header className="admin-panel__header">
        <h2>{list.title}</h2>
        {list.subtitle ? <span className="edify-text-caption">{list.subtitle}</span> : null}
      </header>
      {list.items.map((item, index) => {
        const href = resolve(item.href);
        return (
          <div key={index} className={`admin-target-row${item.tone === 'head' ? ' admin-target-row--head' : ''}`}>
            {href ? <Link href={href}>{item.title}</Link> : <span>{item.title}</span>}
            {item.count ? <strong>{item.count}</strong> : null}
            {item.badges.map((badge) => (
              <span key={badge.text} className={`admin-status ${ADMIN_STATUS[badge.tone] ?? ''}`}>
                {badge.text}
              </span>
            ))}
            {item.actions.map((action) => (
              <Link key={action.label} href={resolve(action.href)} className="admin-next-step">
                {action.label}
                <span aria-hidden="true"> →</span>
              </Link>
            ))}
            {item.meter ? (
              <span className="admin-presence-bar" aria-hidden="true">
                <i style={{ '--w': `${Math.round(item.meter.fraction * 100)}%` } as React.CSSProperties} />
              </span>
            ) : logins ? (
              <span />
            ) : null}
          </div>
        );
      })}
      {!list.items.length && list.empty ? <p className="admin-panel__empty">{list.empty}</p> : null}
    </section>
  );
}

export function FeedList({
  list,
  resolve,
  hrefOf,
}: {
  list: PageList;
  resolve: (href: string) => string;
  hrefOf: (action: PageAction) => string;
}) {
  if (list.family === 'admin-panel') return <AdminPanel list={list} resolve={resolve} />;
  return (
    <section aria-label={list.title || 'List'} data-block="list" className="space-y-2">
      {list.title ? (
        <header className="flex items-baseline justify-between gap-3">
          <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{list.title}</h2>
          {list.count ? <span className="text-[13px] font-semibold text-[var(--edify-accent-text)]">{list.count}</span> : null}
        </header>
      ) : null}
      {list.subtitle ? <p className="text-[13px] text-[var(--edify-text-muted)]">{list.subtitle}</p> : null}
      <ul className="overflow-hidden card">
        {list.items.map((item, index) => (
          <Row key={index} item={item} resolve={resolve} hrefOf={hrefOf} />
        ))}
      </ul>
    </section>
  );
}

/**
 * A form the page shows itself (Escalations' "Escalate to …"). When the
 * gateway saves it (`canSave`) it is drawn and saved here; otherwise its save
 * is the existing web's, so the card says what it is and opens it there,
 * rather than drawing fields that would not save.
 */
export function FeedForm({ form, drawerHref, pagePath }: { form: PageForm; drawerHref: string; pagePath?: string }) {
  if (form.canSave && pagePath) return <PageFormInline form={form} pagePath={pagePath} />;
  return (
    <section aria-label={form.title} data-block="form" className="card p-4 shadow-[var(--edify-shadow-sm)]">
      <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{form.title}</h2>
      {form.text ? <p className="mt-1 text-[var(--edify-text-muted)]">{form.text}</p> : null}
      <a href={drawerHref} className={`${BUTTON_PRIMARY} mt-3 h-10 px-4`}>
        {form.submitLabel || 'Open the form'}
      </a>
    </section>
  );
}
