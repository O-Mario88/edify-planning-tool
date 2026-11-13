/*
 * The page header pattern (templates: .edify-page-header): eyebrow, title,
 * one-line description, and the header's buttons on the right.
 */
import type { PageAction, PageHeader as PageHeaderMessage } from '@/gen/edify/screens/v1/page_pb';

import { Icon } from '../shell/icons';
import type { IconName } from '../shell/icons';
import { BUTTON_OUTLINE, BUTTON_PRIMARY } from './buttons';

const ACTION_ICONS: Readonly<Record<string, IconName>> = { add_school: 'plus', export: 'download' };

export function HeaderAction({ action, href }: { action: PageAction; href: string }) {
  const icon = ACTION_ICONS[action.key];
  const className = action.primary ? BUTTON_PRIMARY : BUTTON_OUTLINE;
  const content = (
    <>
      {icon ? <Icon name={icon} className="h-[18px] w-[18px]" /> : null}
      <span>{action.label}</span>
    </>
  );
  if (!action.enabled) {
    return (
      <button type="button" disabled title={action.reason || undefined} className={`${className} cursor-not-allowed opacity-55`}>
        {content}
      </button>
    );
  }
  return (
    // An export downloads its file (PageAction.download); the rest open a page.
    <a href={href} className={className} data-action={action.key} download={action.download || undefined}>
      {content}
    </a>
  );
}

export function PageHeader({ header, hrefOf }: { header: PageHeaderMessage; hrefOf: (action: PageAction) => string }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between" data-block="header">
      <div className="min-w-0">
        {header.eyebrow ? (
          <p className="text-[length:var(--edify-text-label-size)] font-semibold uppercase text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">
            {header.eyebrow}
          </p>
        ) : null}
        <h1 className="text-[length:var(--edify-text-display-size)] font-bold leading-[1.15] text-[var(--edify-text)]">{header.title}</h1>
        {header.description ? (
          <p className="text-[length:var(--edify-text-label-size)] font-medium text-[var(--edify-text-muted)]">{header.description}</p>
        ) : null}
      </div>
      {header.actions.length ? (
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          {header.actions.map((action) => (
            <HeaderAction key={action.key} action={action} href={hrefOf(action)} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
