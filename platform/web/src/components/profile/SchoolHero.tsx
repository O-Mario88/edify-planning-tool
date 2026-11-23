/*
 * The School Profile's header: the school icon, the school's badges, name and
 * ID, its place and people, the six header buttons, and the Actions menu for
 * the rest.
 */
import { BarChart3, Building2, CalendarDays, ChevronLeft, Crown, FolderPlus, Layers, MapPin, Pencil, School, ShieldCheck, User, UserCog, Users, XCircle } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageAction, PageFact, PageHeader } from '@/gen/edify/screens/v1/page_pb';
import { splitHeroActions } from '@/lib/schoolProfileView';
import type { SchoolIdentity } from '@/lib/schoolProfileView';

import { RowActions } from '../blocks/RowActions';

const ACTION_ICONS: Readonly<Record<string, LucideIcon>> = {
  'Edit Details': Pencil,
  Schedule: CalendarDays,
  'Assign to Partner': Users,
  'Enter SSA Score': BarChart3,
  'Add to Project': FolderPlus,
  'Close School': XCircle,
};

const FACT_ICONS: Readonly<Record<string, LucideIcon>> = {
  District: ShieldCheck,
  'Sub-region': Layers,
  'Sub-county': Building2,
  CCEO: User,
  'Programme Lead': UserCog,
  'Fiscal Year': CalendarDays,
};

function HeroButton({ action, href }: { action: PageAction; href: string }) {
  const ButtonIcon = ACTION_ICONS[action.label] ?? Pencil;
  const content = (
    <>
      <ButtonIcon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
      <span>{action.label}</span>
    </>
  );
  const lead = action.label === 'Edit Details' ? '' : undefined;
  if (!action.enabled) {
    return (
      <button type="button" disabled title={action.reason || undefined} data-pf="hero-action" data-lead={lead}>
        {content}
      </button>
    );
  }
  return (
    <a href={href} data-action={action.key} data-pf="hero-action" data-lead={lead}>
      {content}
    </a>
  );
}

function FactRow({ fact }: { fact: PageFact }) {
  const FactIcon = FACT_ICONS[fact.label] ?? MapPin;
  return (
    <div data-pf="hero-fact">
      <FactIcon className="h-[18px] w-[18px] shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" />
      <dt>{fact.label}:</dt>
      <dd>{fact.href ? <Link href={fact.href} className="hover:underline">{fact.value}</Link> : fact.value}</dd>
    </div>
  );
}

/** "SSA FY2027: 4.5", the year dropped on a phone as the design draws it. */
function SsaWords({ text }: { text: string }) {
  const parts = /^SSA( FY\d+)(: .*)$/.exec(text);
  if (!parts) return <>{text}</>;
  return <span>SSA<span data-pf="ssa-year">{parts[1]}</span>{parts[2]}</span>;
}

interface SchoolHeroProps {
  readonly header: PageHeader;
  readonly identity: SchoolIdentity;
  readonly hrefOf: (action: PageAction) => string;
}

export function SchoolHero({ header, identity, hrefOf }: SchoolHeroProps) {
  const { row, menu } = splitHeroActions(header.actions);
  // The designs always carry the Actions menu: the page's other actions, or these six when it has no others.
  const menuActions = menu.length ? menu : row;
  const ssa = header.badges.filter((badge) => badge.text.startsWith('SSA') || badge.text.startsWith('No FY'));
  const readiness = header.badges.filter((badge) => badge.text.startsWith('Readiness'));
  const others = header.badges.filter((badge) => !ssa.includes(badge) && !readiness.includes(badge));
  const back = header.backHref.startsWith('/') && !header.backHref.startsWith('//') ? header.backHref : '';
  const isOperating = identity.status === 'Operating';
  return (
    <header data-block="header" data-pf="school-head">
      {back && header.backLabel ? (
        <Link href={back} data-pf="back">
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {header.backLabel}
        </Link>
      ) : null}
      {menuActions.length ? (
        <div data-pf="hero-menu">
          <RowActions
            subject={header.title}
            actions={menuActions.map((action) => ({ key: action.key || action.label, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
          />
        </div>
      ) : null}
      <div data-pf="hero">
        <div role="img" aria-label={`${identity.typeLabel || 'School'} icon`} data-school-icon="" data-pf="hero-photo">
          <School aria-hidden="true" strokeWidth={1.5} />
        </div>
        <div data-pf="hero-identity">
          <div data-pf="hero-main">
            <div data-pf="hero-badges">
              {identity.typeLabel ? (
                <span data-pf="badge" data-tone="brand">
                  {identity.typeLabel.startsWith('Core') ? <Crown className="h-3.5 w-3.5" aria-hidden="true" /> : <School className="h-3.5 w-3.5" aria-hidden="true" />}
                  {identity.typeLabel}
                </span>
              ) : null}
              {ssa.map((badge) => <span key={badge.text} data-pf="badge" data-tone={badge.text.startsWith('SSA') ? 'good' : 'plain'} title={badge.title || undefined}><SsaWords text={badge.text} /></span>)}
              {identity.status ? (
                <span data-pf="badge" data-tone="plain">
                  <span data-pf="dot" data-on={isOperating || undefined} aria-hidden="true" />
                  {identity.status}
                </span>
              ) : null}
              {others.map((badge) => <span key={badge.text} data-pf="badge" data-tone="plain" title={badge.title || undefined}>{badge.text}</span>)}
            </div>
            <h1>{header.title}</h1>
            <p data-pf="hero-id">
              School ID: {identity.schoolId}
              {identity.cluster?.value ? (
                <>
                  {' · '}
                  {identity.cluster.href ? <Link href={identity.cluster.href} className="underline">{identity.cluster.value}</Link> : identity.cluster.value}
                </>
              ) : null}
              {readiness.map((badge) => <span key={badge.text} data-pf="hero-readiness" title={badge.title || undefined}> · {badge.text.replace('Readiness: ', '')}</span>)}
            </p>
            {identity.place.length ? (
              <p data-pf="hero-place">
                <MapPin className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                {identity.place.map((fact, index) => <span key={fact.label} data-first={index === 0 || undefined}>{fact.value}</span>)}
              </p>
            ) : null}
          </div>
          <dl data-pf="hero-facts">
            {[0, 1, 2].flatMap((index) => [identity.place[index], identity.people[index]]).map((fact, index) =>
              fact ? <FactRow key={fact.label} fact={fact} /> : <span key={index} />,
            )}
          </dl>
        </div>
        {row.length ? (
          <nav aria-label="School actions" data-pf="hero-actions">
            {row.map((action) => <HeroButton key={action.label} action={action} href={hrefOf(action)} />)}
          </nav>
        ) : null}
      </div>
    </header>
  );
}
