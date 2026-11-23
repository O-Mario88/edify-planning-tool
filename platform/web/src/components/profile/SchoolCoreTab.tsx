/*
 * The School Profile's Core School tab: the programme band with the school's
 * readiness and the Champion rule's checks, five figures, then its six cards.
 * No percentage or status is worked out here; a card Go does not send is not
 * drawn, and a button appears only where a real page stands behind it.
 */
import { Activity, BarChart3, CheckCircle2, Crown, Info, Layers, LifeBuoy, MinusCircle, Package, ShieldCheck, Target, TrendingUp, Users, XCircle } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageBlock, PagePanel } from '@/gen/edify/screens/v1/page_pb';
import { resolveHref } from '@/lib/feedPage';
import { championChecks, coreFigures, coreSchoolView } from '@/lib/schoolProfileView';
import type { ChampionCheck, InterventionRow } from '@/lib/schoolProfileView';

import { FeedBlocks } from '../page/FeedBlocks';
import { MetricTile, PanelLines, ProfileCard } from './parts';
import type { Accent } from './parts';

const FIGURE_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[Layers, 'blue'], [Package, 'blue'], [ShieldCheck, 'green'], [Users, 'blue'], [TrendingUp, 'green']];
const CHECK_ICONS: Readonly<Record<ChampionCheck['state'], LucideIcon>> = { met: CheckCircle2, not: XCircle, none: MinusCircle };

function CoreCard({ panel, title, icon, pagePath }: { panel: PagePanel | undefined; title?: string; icon: LucideIcon; pagePath: string }) {
  if (!panel) return null;
  return (
    <ProfileCard title={title ?? panel.title} icon={icon} block="core-card">
      <PanelLines panel={panel} pagePath={pagePath} />
    </ProfileCard>
  );
}

/** The links among a panel list, by the words Go gave them. */
function linkNamed(blocks: readonly PageBlock[], words: string): string {
  for (const block of blocks) {
    if (block.kind.case !== 'panel') continue;
    for (const item of block.kind.value.items) {
      if (item.kind.case !== 'links') continue;
      const found = item.kind.value.links.find((link) => link.text === words || link.text.startsWith(words));
      if (found) return found.href;
    }
  }
  return '';
}

function InsightsCard({ checks, panel, trajectory, pagePath }: { checks: readonly ChampionCheck[]; panel: PagePanel | undefined; trajectory: string; pagePath: string }) {
  if (!panel) return null;
  const notes = panel.items.flatMap((item) => (item.kind.case === 'text' ? [item.kind.value] : []));
  const doors = panel.items.flatMap((item) => (item.kind.case === 'links' ? item.kind.value.links.filter((link) => link.href) : []));
  return (
    <ProfileCard title="Core School Insights" icon={Target} block="core-insights">
      <ul data-pf="check-list">
        {trajectory ? (
          <li><TrendingUp className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" /><span>SSA trajectory: {trajectory}</span></li>
        ) : null}
        {checks.map((check) => {
          const CheckIcon = CHECK_ICONS[check.state];
          const word = check.state === 'met' ? 'Met' : check.state === 'not' ? 'Not met' : 'Not judged';
          return (
            <li key={check.text}>
              <CheckIcon data-state={check.state} className="h-4 w-4" aria-hidden="true" />
              <span><span className="sr-only">{word}: </span>{check.text}</span>
            </li>
          );
        })}
      </ul>
      {doors.map((door) => (
        <a key={door.text} href={resolveHref(pagePath, door.href)} className="mt-1 block text-[13px] font-semibold text-[var(--brand-primary)] hover:underline">{door.text}</a>
      ))}
      {notes.map((note) => <p key={note} data-pf="core-note">{note}</p>)}
    </ProfileCard>
  );
}

function InterventionsCard({ rows, year, ssaHref, pagePath }: { rows: readonly InterventionRow[]; year: string; ssaHref: string; pagePath: string }) {
  const href = ssaHref ? resolveHref(pagePath, ssaHref) : '';
  return (
    <ProfileCard title="Interventions & Implementation" icon={Activity} aside={year} block="core-interventions">
      {rows.length ? (
        <div id="core-intervention-table" data-pf="intervention-scroll" tabIndex={0} role="region" aria-label="Interventions, scrolls">
          <table data-pf="intervention-table">
            <thead>
              <tr>
                <th scope="col">Intervention</th>
                <th scope="col">Previous</th>
                <th scope="col">Current</th>
                <th scope="col">Change</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td>{row.name}</td>
                  <td className="tabular-nums">{row.previous}</td>
                  <td className="font-semibold tabular-nums">{row.current}</td>
                  <td className="font-semibold tabular-nums">{row.change}</td>
                  <td>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="py-5 text-center">
          <Package className="mx-auto h-9 w-9 text-[var(--edify-text-muted)]" aria-hidden="true" />
          <p className="mt-2 text-[13px] font-semibold text-[var(--edify-text)]">No interventions scored yet</p>
          <p className="text-[12px] text-[var(--edify-text-muted)]">A confirmed SSA shows each intervention here.</p>
        </div>
      )}
      {href ? <Link href={href} className="mt-2 inline-block text-[12px] font-semibold text-[var(--brand-primary)] hover:underline">Open the SSA tab</Link> : null}
    </ProfileCard>
  );
}

function SupportCard({ panel, oversightHref, pagePath }: { panel: PagePanel | undefined; oversightHref: string; pagePath: string }) {
  if (!panel) return null;
  const href = oversightHref ? resolveHref(pagePath, oversightHref) : '';
  return (
    <ProfileCard title="Recommended Support" icon={LifeBuoy} block="core-support">
      <div data-pf="support-box">
        <Info className="h-4 w-4" aria-hidden="true" />
        <div className="min-w-0 flex-1"><PanelLines panel={panel} pagePath={pagePath} /></div>
      </div>
      {href ? (
        <Link href={href} data-pf="support-action">
          <Package className="h-4 w-4" aria-hidden="true" /> Open Core School Oversight
        </Link>
      ) : null}
    </ProfileCard>
  );
}

interface SchoolCoreTabProps {
  readonly blocks: readonly PageBlock[];
  readonly interventions: readonly InterventionRow[];
  /** The school's planning readiness, from its header. */
  readonly planningReadiness: string;
  readonly year: string;
  readonly pagePath: string;
  readonly drawerHref: string;
}

export function SchoolCoreTab({ blocks, interventions, planningReadiness, year, pagePath, drawerHref }: SchoolCoreTabProps) {
  const view = coreSchoolView(blocks);
  const figures = coreFigures(view, year, interventions);
  const checks = championChecks(view.champion);
  const met = checks.filter((check) => check.state === 'met').length;
  const judged = checks.some((check) => check.state !== 'none');
  const trajectory = view.metrics.find((metric) => metric.label === 'SSA Trajectory')?.value ?? '';
  const ssaHref = linkNamed(view.others, "Each intervention's scores");
  const oversightHref = linkNamed(view.others, 'Core School Oversight');
  const placedLinks = new Set([ssaHref, oversightHref]);
  const rest = view.others.filter((block) => {
    if (block.kind.case !== 'panel' || block.kind.value.title) return true;
    const hrefs = block.kind.value.items.flatMap((item) => (item.kind.case === 'links' ? item.kind.value.links.map((link) => link.href) : ['']));
    return !hrefs.every((href) => placedLinks.has(href));
  });
  return (
    <div className="space-y-3" data-layout="school-core">
      <section aria-label="Core School Programme" data-pf="core-band">
        <div>
          <Crown className="h-8 w-8 shrink-0" style={{ color: '#fcd34d' }} aria-hidden="true" />
          <div className="min-w-0">
            <h2>Core School Programme</h2>
            <p className="text-[13px]">Programme support, package, implementation progress and school readiness{year ? ` for ${year}` : ''}.</p>
          </div>
        </div>
        <div data-pf="core-band-side">
          {planningReadiness ? (
            <div>
              <p data-pf="core-band-label">Readiness Status</p>
              <p data-pf="core-band-pill">{planningReadiness}</p>
            </div>
          ) : null}
          {view.readiness ? (
            <div>
              <p data-pf="core-band-label">Champion Readiness</p>
              {checks.length ? (
                <>
                  <div data-pf="check-bar" role="img" aria-label={judged ? `${met} of ${checks.length} Champion checks met` : 'Champion checks not judged yet'}>
                    {checks.map((check) => <i key={check.text} data-state={check.state} />)}
                  </div>
                  <p data-pf="check-words">{judged ? `${met} of ${checks.length} checks met` : 'Not judged yet'} · {view.readiness}</p>
                </>
              ) : (
                <p data-pf="core-band-pill">{view.readiness}</p>
              )}
            </div>
          ) : null}
        </div>
      </section>
      <div data-pf="core-figures">
        {figures.map((metric, index) => {
          const [icon, accent] = FIGURE_LOOK[index % FIGURE_LOOK.length]!;
          return <MetricTile key={metric.label} metric={metric} icon={icon} accent={accent} pagePath={pagePath} />;
        })}
      </div>
      <div data-pf="core-cards">
        <CoreCard panel={view.package} title="Package & Support" icon={Package} pagePath={pagePath} />
        <CoreCard panel={view.participation} icon={Users} pagePath={pagePath} />
        <InsightsCard checks={checks} panel={view.champion} trajectory={trajectory} pagePath={pagePath} />
        <InterventionsCard rows={interventions} year={year} ssaHref={ssaHref} pagePath={pagePath} />
        <CoreCard panel={view.outcomes} icon={BarChart3} pagePath={pagePath} />
        <SupportCard panel={view.support} oversightHref={oversightHref} pagePath={pagePath} />
      </div>
      {rest.length ? <FeedBlocks blocks={rest} pagePath={pagePath} drawerHref={drawerHref} selectable={false} clearFilters={false} /> : null}
    </div>
  );
}
