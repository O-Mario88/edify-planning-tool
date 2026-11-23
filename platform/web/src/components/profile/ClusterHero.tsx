/*
 * The Cluster Profile's header band: the cluster's name and status, where it
 * is and who holds it, and the actions this reader may take (Go decides which).
 */
import { BarChart3, CalendarDays, ChevronLeft, Layers, Pencil, Plus, Route, Trash2, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageAction, PageFact, PageHeader } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';

const ACTION_ICONS: Readonly<Record<string, LucideIcon>> = {
  profile: BarChart3,
  schedule_group_training: CalendarDays,
  schedule_cluster_meeting: Users,
  route: Route,
  add_schools: Plus,
  edit_details: Pencil,
  delete: Trash2,
};

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
  return (
    <header data-block="header" className="space-y-2">
      {back && header.backLabel ? (
        <Link href={back} className="inline-flex items-center gap-1 text-[13px] font-semibold text-[var(--brand-primary)] hover:underline">
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          {header.backLabel}
        </Link>
      ) : null}
      <div data-pf="cluster-band">
        <div data-pf="band-head">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[10px] bg-white/15">
            <Layers className="h-6 w-6" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[20px] font-bold leading-tight sm:text-[24px]">{header.title}</h1>
              {header.badges.map((badge) => <Badge key={badge.text} tone={badge.tone}>{badge.text}</Badge>)}
            </div>
            <p className="mt-0.5 text-[13px]" style={{ color: 'rgb(255 255 255 / 0.88)' }}>{header.description}</p>
          </div>
        </div>
        <dl data-pf="band-facts">
          {[...place, ...people].map((fact) => <Fact key={fact.label} fact={fact} />)}
        </dl>
        {header.actions.length ? (
          <nav aria-label="Cluster actions" data-pf="band-actions">
            {header.actions.map((action) => <BandAction key={action.key} action={action} href={hrefOf(action)} />)}
          </nav>
        ) : null}
      </div>
    </header>
  );
}
