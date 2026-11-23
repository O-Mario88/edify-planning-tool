/*
 * The Cluster Profile's header band: the cluster's name and status, where it
 * is and who holds it, and the actions this reader may take (Go decides which).
 */
import { BarChart3, CalendarDays, ChevronLeft, Info, Layers, Pencil, Plus, Route, Trash2, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageAction, PageFact, PageHeader } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';

const ACTION_ICONS: Readonly<Record<string, LucideIcon>> = {
  profile: BarChart3,
  schedule_group_training: CalendarDays,
  schedule_cluster_meeting: Users,
  route: Route,
  add_schools: Plus,
  edit_details: Pencil,
  delete: Trash2,
};

/** The three buttons the design keeps on the band; every other action opens from its Actions menu. */
const ON_BAND = new Set(['profile', 'edit_details', 'delete']);

function BandArt() {
  return (
    <span data-pf="band-art" aria-hidden="true">
      <svg viewBox="0 0 640 120" preserveAspectRatio="xMaxYMax slice">
        <path d="M120 120 C210 62 290 84 360 58 C440 28 520 62 640 24 L640 120 Z" fill="rgb(255 255 255 / 0.07)" />
        <path d="M230 120 C320 82 390 98 470 72 C540 52 590 70 640 54 L640 120 Z" fill="rgb(255 255 255 / 0.09)" />
        <path d="M340 120 C430 100 500 108 560 92 C600 82 620 86 640 80 L640 120 Z" fill="rgb(255 255 255 / 0.11)" />
      </svg>
    </span>
  );
}

function BandAction({ action, href }: { action: PageAction; href: string }) {
  const ActionIcon = ACTION_ICONS[action.key] ?? Pencil;
  const tone = action.key === 'delete' ? 'danger' : undefined;
  const content = (
    <>
      <ActionIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{action.label}</span>
    </>
  );
  if (!action.enabled) {
    return (
      <button type="button" disabled title={action.reason || undefined} aria-label={action.reason ? `${action.label}: ${action.reason}` : action.label} data-pf="band-action" data-tone={tone}>
        {content}
      </button>
    );
  }
  return (
    <a href={href} data-action={action.key} data-pf="band-action" data-tone={tone}>
      {content}
    </a>
  );
}

function Fact({ fact }: { fact: PageFact }) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5 text-[13px]">
      <dt className="shrink-0">{fact.label}:</dt>
      <dd className="min-w-0 truncate font-semibold">{fact.href ? <Link href={fact.href} className="hover:underline">{fact.value}</Link> : fact.value}</dd>
    </div>
  );
}

interface ClusterHeroProps {
  readonly header: PageHeader;
  readonly place: readonly PageFact[];
  readonly people: readonly PageFact[];
  readonly hrefOf: (action: PageAction) => string;
}

export function ClusterHero({ header, place, people, hrefOf }: ClusterHeroProps) {
  const back = header.backHref.startsWith('/') && !header.backHref.startsWith('//') ? header.backHref : '';
  const onBand = header.actions.filter((action) => ON_BAND.has(action.key));
  const inMenu = header.actions.filter((action) => !ON_BAND.has(action.key));
  const facts = [...place, ...people];
  return (
    <header data-block="header" className="space-y-2">
      {back && header.backLabel ? (
        <Link href={back} className="inline-flex items-center gap-1 text-[13px] font-semibold text-[var(--brand-primary)] hover:underline">
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {header.backLabel}
        </Link>
      ) : null}
      <div data-pf="cluster-band">
        <BandArt />
        <div data-pf="band-head">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[10px] bg-white/15">
            <Layers className="h-6 w-6" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-bold leading-tight">{header.title}</h1>
              {header.badges.map((badge) => <Badge key={badge.text} tone={badge.tone}>{badge.text}</Badge>)}
            </div>
            <div data-pf="band-line">
              <p>{header.description}</p>
              {facts.length ? (
                <details data-pf="band-info">
                  <summary aria-label="More about this cluster" title="More about this cluster"><Info className="h-4 w-4" aria-hidden="true" /></summary>
                  <dl data-pf="band-facts">{facts.map((fact) => <Fact key={fact.label} fact={fact} />)}</dl>
                </details>
              ) : null}
            </div>
          </div>
        </div>
        {header.actions.length ? (
          <nav aria-label="Cluster actions" data-pf="band-actions">
            {onBand.map((action) => <BandAction key={action.key} action={action} href={hrefOf(action)} />)}
            {inMenu.length ? (
              <RowActions
                subject={header.title}
                actions={inMenu.map((action) => ({ key: action.key, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
              />
            ) : null}
          </nav>
        ) : null}
      </div>
    </header>
  );
}
