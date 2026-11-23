/*
 * The School Profile's header: the photo (or a plain placeholder, since no
 * school photograph is stored), the school's badges, name and ID, its place
 * and people, the six header buttons and the Actions menu for the rest.
 */
import { BarChart3, CalendarDays, ChevronLeft, FolderPlus, MapPin, Pencil, School, Users, XCircle } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageAction, PageFact, PageHeader } from '@/gen/edify/screens/v1/page_pb';
import { splitHeroActions } from '@/lib/schoolProfileView';
import type { SchoolIdentity } from '@/lib/schoolProfileView';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';

const ACTION_ICONS: Readonly<Record<string, LucideIcon>> = {
  'Edit Details': Pencil,
  Schedule: CalendarDays,
  'Assign to Partner': Users,
  'Enter SSA Score': BarChart3,
  'Add to Project': FolderPlus,
  'Close School': XCircle,
};

function SchoolImage() {
  return (
    <div
      role="img"
      aria-label="No school photograph on record"
      data-school-photo="placeholder"
      data-pf="hero-photo"
      className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-1 rounded-[12px] border border-[var(--edify-border)] bg-[color-mix(in_srgb,var(--brand-primary)_6%,var(--edify-surface))] text-[var(--edify-text-muted)]"
    >
      <School className="h-8 w-8 text-[color-mix(in_srgb,var(--brand-primary)_55%,var(--edify-text-muted))] sm:h-11 sm:w-11" aria-hidden="true" />
      <span className="px-1 text-center text-[11px] font-medium leading-tight sm:text-[12px]">No photo on record</span>
    </div>
  );
}

function HeroButton({ action, href }: { action: PageAction; href: string }) {
  const ButtonIcon = ACTION_ICONS[action.label] ?? Pencil;
  const lead = action.label === 'Edit Details';
  const shape =
    'flex min-h-[60px] flex-col items-center justify-center gap-1 rounded-[10px] border px-1 py-1.5 text-center text-[11px] font-semibold leading-tight sm:h-9 sm:min-h-0 sm:flex-row sm:gap-2 sm:whitespace-nowrap sm:px-3 sm:text-[13px] ' +
    (lead
      ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]'
      : 'border-[var(--edify-border)] bg-[var(--edify-surface)] text-[var(--edify-text)] hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]');
  const content = (
    <>
      <ButtonIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{action.label}</span>
    </>
  );
  if (!action.enabled) {
    return (
      <button type="button" disabled title={action.reason || undefined} className={`${shape} cursor-not-allowed opacity-55`}>
        {content}
      </button>
    );
  }
  return (
    <a href={href} data-action={action.key} className={shape}>
      {content}
    </a>
  );
}

function FactRow({ fact }: { fact: PageFact }) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5">
      <dt className="shrink-0 text-[var(--edify-text-muted)]">{fact.label}:</dt>
      <dd className="min-w-0 truncate font-semibold text-[var(--edify-text)]">
        {fact.href ? <Link href={fact.href} className="hover:underline">{fact.value}</Link> : fact.value}
      </dd>
    </div>
  );
}

interface SchoolHeroProps {
  readonly header: PageHeader;
  readonly identity: SchoolIdentity;
  readonly hrefOf: (action: PageAction) => string;
}

export function SchoolHero({ header, identity, hrefOf }: SchoolHeroProps) {
  const { row, menu } = splitHeroActions(header.actions);
  const ssa = header.badges.filter((badge) => badge.text.startsWith('SSA'));
  const others = header.badges.filter((badge) => !badge.text.startsWith('SSA'));
  const back = header.backHref.startsWith('/') && !header.backHref.startsWith('//') ? header.backHref : '';
  return (
    <header data-block="header" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        {back && header.backLabel ? (
          <Link href={back} className="inline-flex items-center gap-1 text-[13px] font-semibold text-[var(--brand-primary)] hover:underline">
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            {header.backLabel}
          </Link>
        ) : <span />}
        <RowActions
          subject={header.title}
          actions={menu.map((action) => ({ key: action.key || action.label, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
        />
      </div>
      <div data-pf="hero">
        <SchoolImage />
        <div data-pf="hero-identity" className="min-w-0">
          <div data-pf="hero-main" className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              {identity.typeLabel ? <Badge tone="primary">{identity.typeLabel}</Badge> : null}
              {ssa.map((badge) => <Badge key={badge.text} tone={badge.tone} title={badge.title || undefined}>{badge.text}</Badge>)}
              {identity.status ? <Badge tone={identity.statusTone || (identity.status === 'Operating' ? 'good' : 'caution')}>{identity.status}</Badge> : null}
              {others.map((badge) => <Badge key={badge.text} tone={badge.tone} title={badge.title || undefined} icon={badge.icon}>{badge.text}</Badge>)}
            </div>
            <h1 className="mt-1.5 text-[19px] font-bold leading-[1.2] text-[var(--edify-text)] sm:text-[24px]">{header.title}</h1>
            <p className="mt-0.5 text-[13px] font-medium text-[var(--edify-text-muted)]">
              School ID: {identity.schoolId}
              {identity.cluster?.value ? (
                <>
                  {' · '}
                  {identity.cluster.href ? <Link href={identity.cluster.href} className="font-semibold text-[var(--brand-primary)] hover:underline">{identity.cluster.value}</Link> : identity.cluster.value}
                </>
              ) : null}
            </p>
            {identity.place.length ? (
              <p data-pf="hero-place" className="mt-1 text-[13px] text-[var(--edify-text)]">
                <MapPin className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
                {identity.place.map((fact) => fact.value).join(' · ')}
              </p>
            ) : null}
          </div>
          <dl data-pf="hero-facts" className="text-[13px]">
            {[0, 1, 2].flatMap((index) => [identity.place[index], identity.people[index]]).map((fact, index) =>
              fact ? <FactRow key={fact.label} fact={fact} /> : <span key={index} />,
            )}
          </dl>
        </div>
        <dl data-pf="hero-people" className="text-[13px]">
          {identity.people.map((fact) => <FactRow key={fact.label} fact={fact} />)}
        </dl>
        {row.length ? (
          <nav aria-label="School actions" data-pf="hero-actions">
            {row.map((action) => <HeroButton key={action.label} action={action} href={hrefOf(action)} />)}
          </nav>
        ) : null}
      </div>
    </header>
  );
}
