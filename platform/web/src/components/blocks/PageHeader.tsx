/*
 * The page header pattern (templates: .edify-page-header): eyebrow, title,
 * one-line description, and the header's buttons on the right.
 */
import type { PageAction, PageHeader as PageHeaderMessage } from '@/gen/edify/screens/v1/page_pb';

import { Icon } from '../shell/icons';
import type { IconName } from '../shell/icons';
import { Badge } from './Badge';
import { BUTTON_OUTLINE, BUTTON_PRIMARY } from './buttons';

const ACTION_ICONS: Readonly<Record<string, IconName>> = {
  add_school: 'plus',
  export: 'download',
  create_cluster: 'plus',
  edit_details: 'edit',
  plan_field_event: 'plus',
  schedule_group_training: 'calendar',
  schedule_cluster_meeting: 'calendar',
  recent_changes: 'back',
};

export function HeaderAction({ action, href }: { action: PageAction; href: string }) {
  const icon = ACTION_ICONS[action.key];
  const className = action.primary ? BUTTON_PRIMARY : BUTTON_OUTLINE;
  const content = (
    <>
      {icon ? <Icon name={icon} className="h-4 w-4" /> : null}
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

function BackLink({ header }: { header: PageHeaderMessage }) {
  if (!header.backLabel || !header.backHref.startsWith('/') || header.backHref.startsWith('//')) return null;
  return (
    <a href={header.backHref} className="mb-1 inline-flex items-center gap-1 text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]">
      <Icon name="back" className="h-3.5 w-3.5" />
      <span>{header.backLabel}</span>
    </a>
  );
}

/**
 * A record's header (the school profile: templates/pages/schools/detail.html):
 * back link, name and ID, then its badges with the buttons on one wrapping row.
 */
function RecordHeader({ header, hrefOf }: { header: PageHeaderMessage; hrefOf: (action: PageAction) => string }) {
  return (
    <div className="flex flex-col gap-3" data-block="header">
      <div className="min-w-0">
        <BackLink header={header} />
        <h1 className="text-[length:var(--edify-text-display-size)] font-bold leading-[1.15] text-[var(--edify-text)]">{header.title}</h1>
        {header.description ? <p className="text-[length:var(--edify-text-label-size)] font-medium text-[var(--edify-text-muted)]">{header.description}</p> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {header.badges.map((badge) => (
          <Badge key={badge.text} tone={badge.tone} title={badge.title || undefined} icon={badge.icon}>{badge.text}</Badge>
        ))}
        {header.actions.map((action) => (
          <HeaderAction key={action.key} action={action} href={hrefOf(action)} />
        ))}
      </div>
    </div>
  );
}

export function PageHeader({ header, hrefOf }: { header: PageHeaderMessage; hrefOf: (action: PageAction) => string }) {
  if (header.badges.length || header.backLabel) return <RecordHeader header={header} hrefOf={hrefOf} />;
  // The canonical page header (templates/components/page_header.html).
  return (
    <header className="edify-page-header" data-block="header">
      <div className="edify-page-header__lead">
        {header.eyebrow ? <p className="edify-page-eyebrow">{header.eyebrow}</p> : null}
        <h1 className="edify-page-title edify-page-header__title">{header.title}</h1>
        {header.description ? <p className="edify-page-header__description">{header.description}</p> : null}
      </div>
      {header.actions.length ? (
        <div className="edify-page-header__controls">
          {header.actions.map((action) => (
            <HeaderAction key={action.key} action={action} href={hrefOf(action)} />
          ))}
        </div>
      ) : null}
    </header>
  );
}
