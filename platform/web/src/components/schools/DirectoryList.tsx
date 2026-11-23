'use client';

/*
 * The School Directory record list:
 *   - One aligned, visible column header row sharing the exact same CSS Grid
 *     layout template as every summary row:
 *       Selection (when permitted), School ID, School Name,
 *       District (xl+), Cluster (xl+), Visit Status (xl+), Actions (when permitted).
 *   - No disclosure chevron: clicking any non-interactive part of a summary
 *     row (including whitespace immediately after entity names) toggles that
 *     row's details inline, keyed by stable school.id.
 *   - Only the displayed text of profiled entities (School Name, District,
 *     Cluster) is an inline native Link.
 *   - Expanded details show record metadata + the 3-column SSA intervention
 *     breakdown preserving real zero scores and empty states.
 */
import { LocateFixed } from 'lucide-react';
import Link from 'next/link';
import { useState, useTransition } from 'react';

import { bulkAssignClusterAction, bulkAssignProjectAction } from '@/app/(app)/schools/actions';
import type { DirectorySchool } from '@/gen/edify/screens/v1/school_directory_pb';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { SsaDetailPanel, ssaModelFromDirectory } from '../blocks/SsaDetailPanel';
import { textTone } from '../blocks/tones';
import { GpsCaptureModal } from '../route/GpsCaptureModal';

export interface DirectoryListProps {
  readonly schools: readonly DirectorySchool[];
  readonly readOnly: boolean;
  readonly mayOpenProfile: boolean;
  readonly listed: string;
  readonly emptyMessage: string;
  /** Where an action opens until its drawer moves here: the existing web. */
  readonly existingWebUrl: string;
  readonly fy: string;
}

const INTERACTIVE_SELECTOR = 'a, button, input, label, select, textarea, [role="menu"], [role="menuitem"], [data-row-actions]';

function isInteractive(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(INTERACTIVE_SELECTOR));
}

/** Shared grid definition so headings and data cells stay aligned across viewports, zoom, and read-only mode. */
function rowGridClass(readOnly: boolean): string {
  return readOnly
    ? 'grid items-center gap-x-2.5 px-4 grid-cols-[78px_minmax(0,1fr)] xl:grid-cols-[78px_minmax(0,2.4fr)_minmax(0,0.75fr)_60px_minmax(0,1.15fr)_130px_168px]'
    : 'grid items-center gap-x-2.5 px-4 grid-cols-[18px_78px_minmax(0,1fr)_auto] xl:grid-cols-[18px_78px_minmax(0,2.4fr)_minmax(0,0.75fr)_60px_minmax(0,1.15fr)_130px_168px_84px]';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;

function shortDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso.trim());
  if (!match) return iso;
  const monthIdx = Number(match[2]) - 1;
  const day = Number(match[3]);
  const month = MONTHS[monthIdx];
  if (!month || !day) return iso;
  return `${day} ${month} ${match[1]}`;
}

function districtHrefOf(school: DirectorySchool): string {
  if (!school.districtId || !school.district || school.district === '—') return '';
  return `/districts/${encodeURIComponent(school.districtId)}`;
}

function clusterHrefOf(school: DirectorySchool): string {
  if (!school.clusterId || !school.clusterName || school.clusterName === 'Not assigned' || school.clusterName === '—') return '';
  return `/clusters/${encodeURIComponent(school.clusterId)}`;
}

function Fact({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex min-w-0 items-baseline gap-1 ${className}`}>
      <dt className="shrink-0 font-medium text-[var(--edify-text-muted)]">{label}</dt>
      <dd className="min-w-0 break-words font-semibold text-[var(--edify-text)]">{children}</dd>
    </div>
  );
}

function ssaText(school: DirectorySchool): string {
  if (school.ssaAverage === undefined) return 'Not assessed';
  const fixed = school.ssaAverage.toFixed(1);
  const clean = fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed;
  return `${clean}/10`;
}

function Row({
  school,
  props,
  open,
  onToggle,
  picked,
  onPick,
  onOpenGps,
}: {
  school: DirectorySchool;
  props: DirectoryListProps;
  open: boolean;
  onToggle: () => void;
  picked: boolean;
  onPick: (checked: boolean) => void;
  onOpenGps: (school: DirectorySchool) => void;
}) {
  const detailsId = `school-directory-details-${school.id}`;
  const schoolHref = props.mayOpenProfile && school.schoolId ? `/schools/${encodeURIComponent(school.schoolId)}` : '';
  const districtHref = districtHrefOf(school);
  const clusterHref = clusterHrefOf(school);
  const hasAssessment = school.ssaAverage !== undefined || school.ssaGroups.some((group) => group.items.length > 0);

  const actions = school.actions.map((action) => ({
    key: action.key,
    label: action.label,
    enabled: action.enabled,
    reason: action.reason,
    href: `/schools/${encodeURIComponent(school.schoolId)}`,
  }));

  return (
    <li
      className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-surface)] last:border-b-0"
      data-row={school.schoolId}
      data-row-id={school.id}
      data-open={open ? 'true' : undefined}
    >
      <div
        data-directory-summary=""
        className={`${rowGridClass(props.readOnly)} min-h-[38px] cursor-pointer py-1.5 transition-colors hover:bg-[#edf5ff] focus-within:bg-[#edf5ff]/75 dark:hover:bg-[color-mix(in_oklab,var(--edify-surface-muted)_60%,transparent)] ${
          open ? 'bg-[#edf5ff]/80 dark:bg-[color-mix(in_oklab,var(--edify-surface-muted)_50%,transparent)]' : ''
        }`}
        onClick={(event) => {
          if (isInteractive(event.target)) return;
          if (window.getSelection()?.toString()) return;
          onToggle();
        }}
      >
        {!props.readOnly ? (
          <label className="flex items-center justify-center">
            <input
              type="checkbox"
              checked={picked}
              onChange={(event) => onPick(event.target.checked)}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
            <span className="sr-only">Select {school.name}</span>
          </label>
        ) : null}

        <div className="min-w-0">
          <span
            title={`School ID ${school.schoolId}`}
            className="inline-block max-w-full truncate rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-1.5 py-px text-[length:var(--edify-text-micro-size)] font-bold tabular-nums text-[var(--edify-text-muted)]"
          >
            <span className="sr-only">School ID </span>
            {school.schoolId}
          </span>
        </div>

        <div className="min-w-0 overflow-hidden">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-controls={detailsId}
            aria-label={open ? `Hide details for ${school.name}` : `Show details for ${school.name}`}
            className="sr-only focus:not-sr-only focus:mr-1.5 focus:inline-flex focus:items-center focus:rounded focus:bg-[var(--edify-surface)] focus:px-1.5 focus:py-0.5 focus:text-[11px] focus:font-semibold focus:text-[var(--brand-primary-text)] focus:outline focus:outline-2 focus:outline-[var(--edify-accent)]"
          >
            {open ? 'Hide details' : 'Show details'}
          </button>
          <div
            data-directory-name=""
            title={school.name}
            className="max-w-full overflow-hidden text-ellipsis text-[12.5px] font-semibold leading-[1.3] text-[var(--edify-text)] xl:whitespace-nowrap"
          >
            {schoolHref ? (
              <Link href={schoolHref} className="inline text-[var(--edify-text)] hover:underline">
                {school.name}
              </Link>
            ) : (
              <span>{school.name}</span>
            )}
          </div>
        </div>

        <div className="max-xl:hidden min-w-0 truncate text-[12px]" data-fact="district" title={school.district}>
          {districtHref ? (
            <Link
              href={districtHref}
              className="inline font-medium text-[var(--edify-text)] hover:text-[var(--brand-primary-text)] hover:underline dark:hover:text-[var(--edify-accent-text)]"
            >
              {school.district}
            </Link>
          ) : (
            <span className="text-[var(--edify-text-muted)]">{school.district || '—'}</span>
          )}
        </div>

        <div className="max-xl:hidden min-w-0 truncate text-[12px] text-[var(--edify-text)]" data-fact="type" title={school.schoolType}>
          {school.schoolType || '—'}
        </div>

        <div className="max-xl:hidden min-w-0 truncate text-[12px]" data-fact="cluster" title={school.clusterName}>
          {clusterHref ? (
            <Link
              href={clusterHref}
              className="inline font-medium text-[var(--edify-text)] hover:text-[var(--brand-primary-text)] hover:underline dark:hover:text-[var(--edify-accent-text)]"
            >
              {school.clusterName}
            </Link>
          ) : (
            <span className="text-[var(--edify-text-muted)]">{school.clusterName || 'Not assigned'}</span>
          )}
        </div>

        <div className="max-xl:hidden min-w-0 truncate text-[12px]" data-fact="ssa">
          <span className="text-[var(--edify-text-muted)]">SSA: </span>
          <span className={`font-semibold tabular-nums ${school.ssaAverage !== undefined ? textTone(school.ssaTone) : 'text-[var(--edify-text-muted)]'}`}>
            {ssaText(school)}
          </span>
        </div>

        <div className="max-xl:hidden flex min-w-0 items-center gap-1.5 overflow-hidden" data-fact="visit">
          <Badge tone={school.visitStatusTone}>{school.visitStatusLabel}</Badge>
          {school.nextVisitDate ? (
            <span className="min-w-0 truncate text-[11.5px] font-medium tabular-nums text-[var(--edify-text-muted)]">
              {shortDate(school.nextVisitDate)}
            </span>
          ) : null}
        </div>

        {!props.readOnly ? (
          <div className="flex justify-end">
            <RowActions subject={school.name} actions={actions} />
          </div>
        ) : null}
      </div>

      {open ? (
        <div
          id={detailsId}
          data-directory-details=""
          onClick={(event) => event.stopPropagation()}
          className="space-y-3 border-t border-[var(--edify-table-divider)] bg-[var(--edify-card-surface)] px-4 py-3"
        >
          {schoolHref || !props.readOnly ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              {schoolHref ? (
                <Link href={schoolHref} className="inline text-[13px] font-bold text-[var(--edify-text)] hover:underline">
                  Open {school.name} school profile
                </Link>
              ) : (
                <span />
              )}
              {!props.readOnly ? (
                <button
                  type="button"
                  data-action="directory-add-gps"
                  onClick={() => onOpenGps(school)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-[8px] border border-[var(--brand-primary)] bg-white px-2.5 text-[12px] font-semibold text-[var(--brand-primary)] hover:bg-blue-50"
                >
                  <LocateFixed className="h-3.5 w-3.5" aria-hidden="true" />
                  Add / Update School GPS
                </button>
              ) : null}
            </div>
          ) : null}

          <dl className="flex flex-wrap gap-x-5 gap-y-1.5 text-[length:var(--edify-text-label-size)]">
            <Fact label="District:">
              {districtHref ? (
                <Link href={districtHref} className="inline text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]">
                  {school.district}
                </Link>
              ) : (
                school.district
              )}
            </Fact>
            <Fact label="Shipping Address:">{school.shippingAddress}</Fact>
            <Fact label="School Type:">{school.schoolType}</Fact>
            <Fact label="Cluster:">
              {clusterHref ? (
                <Link href={clusterHref} className="inline text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]">
                  {school.clusterName}
                </Link>
              ) : (
                school.clusterName
              )}
            </Fact>
            <Fact label="Enrollment:">{school.enrolment}</Fact>
            <Fact label="Phone:">{school.phone}</Fact>
            <Fact label="Primary Contact:">{school.contact}</Fact>
            <Fact label="Staff Name:">{school.staffName}</Fact>
            <Fact label="SSA:">
              <span className={textTone(school.ssaTone)}>{ssaText(school)}</span>
            </Fact>
            <Fact label="Visit status:">
              <Badge tone={school.visitStatusTone}>{school.visitStatusLabel}</Badge>
              {school.nextVisitDate ? <span className="ml-1 text-[var(--edify-text-muted)]">{school.nextVisitDate}</span> : null}
            </Fact>
            <Fact label="Cluster training:">
              <span className={textTone(school.clusterTrainingState)} title={school.clusterTrainingReason || undefined}>
                {school.clusterTrainingLabel}
              </span>
            </Fact>
            <Fact label="Visit:">
              <span className={textTone(school.visitCount ? 'positive' : 'attention')}>{school.visitCount}</span>
            </Fact>
            <Fact label="Training:">
              <span className={textTone(school.trainingCount ? 'positive' : 'attention')}>{school.trainingCount}</span>
            </Fact>
          </dl>

          <SsaDetailPanel model={ssaModelFromDirectory(school.ssaGroups, props.fy, hasAssessment)} />
        </div>
      ) : null}
    </li>
  );
}

export function DirectoryList(props: DirectoryListProps) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [bulkMode, setBulkMode] = useState<'cluster' | 'project' | null>(null);
  const [bulkTarget, setBulkTarget] = useState('');
  const [bulkMsg, setBulkMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [gpsSchool, setGpsSchool] = useState<DirectorySchool | null>(null);
  const [pending, startTransition] = useTransition();
  const allPicked = props.schools.length > 0 && picked.length === props.schools.length;

  function applyBulk() {
    if (!bulkMode || !picked.length || !bulkTarget.trim()) return;
    setBulkMsg(null);
    startTransition(async () => {
      const res =
        bulkMode === 'cluster'
          ? await bulkAssignClusterAction({ schoolIds: picked, clusterId: bulkTarget })
          : await bulkAssignProjectAction({ schoolIds: picked, projectId: bulkTarget });
      setBulkMsg({ ok: res.ok, text: res.message });
      if (res.ok) {
        setBulkMode(null);
        setBulkTarget('');
        setPicked([]);
      }
    });
  }

  function toggleAll(checked: boolean) {
    setPicked(checked ? props.schools.map((school) => school.id) : []);
  }

  return (
    <div data-block="table">
      <div className="flex min-h-[42px] flex-wrap items-center gap-3 bg-[color-mix(in_oklab,var(--edify-surface-muted)_64%,transparent)] px-4 py-1.5">
        {!props.readOnly ? (
          <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] font-medium text-[var(--edify-text)]">
            <input
              type="checkbox"
              checked={allPicked}
              onChange={(event) => toggleAll(event.target.checked)}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
            <span>Select page</span>
          </label>
        ) : null}
        {!props.readOnly && picked.length > 0 ? (
          <>
            <span aria-live="polite" className="font-semibold">
              {picked.length} selected
            </span>
            <button
              type="button"
              onClick={() => {
                setBulkMode('cluster');
                setBulkMsg(null);
              }}
              className="inline-flex h-7 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2.5 text-[12px] font-semibold hover:bg-[var(--brand-primary-soft)]"
            >
              Assign to Cluster
            </button>
            <button
              type="button"
              onClick={() => {
                setBulkMode('project');
                setBulkMsg(null);
              }}
              className="inline-flex h-7 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2.5 text-[12px] font-semibold hover:bg-[var(--brand-primary-soft)]"
            >
              Add to Project
            </button>
          </>
        ) : null}
        {bulkMode && picked.length ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={bulkTarget}
              onChange={(e) => setBulkTarget(e.target.value)}
              placeholder={bulkMode === 'cluster' ? 'Cluster ID' : 'Project ID'}
              className="h-7 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2 text-[12px]"
            />
            <button
              type="button"
              disabled={pending}
              onClick={applyBulk}
              className="inline-flex h-7 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-2.5 text-[12px] font-semibold text-white"
            >
              {pending ? 'Saving…' : 'Confirm'}
            </button>
            <button
              type="button"
              onClick={() => {
                setBulkMode(null);
                setBulkTarget('');
              }}
              className="text-[12px] font-semibold text-[var(--edify-text-muted)]"
            >
              Cancel
            </button>
          </div>
        ) : null}
        {bulkMsg ? (
          <span
            role="status"
            className={`text-[12px] font-semibold ${bulkMsg.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}
          >
            {bulkMsg.text}
          </span>
        ) : null}
        <span className="ml-auto text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--edify-text-muted)]">
          {props.listed}
        </span>
      </div>

      {props.schools.length ? (
        <>
          <div
            data-directory-header=""
            role="group"
            aria-label="School Directory columns"
            className={`${rowGridClass(props.readOnly)} border-y border-[var(--edify-table-divider)] bg-[color-mix(in_oklab,var(--edify-surface-muted)_42%,transparent)] py-1.5 text-[11px] font-bold uppercase tracking-[0.04em] text-[var(--edify-text-muted)]`}
          >
            {!props.readOnly ? (
              <div aria-hidden="true" className="flex items-center justify-center" />
            ) : null}
            <div className="min-w-0 truncate">
              School ID
            </div>
            <div className="min-w-0 truncate">
              School Name
            </div>
            <div className="max-xl:hidden min-w-0 truncate">
              District
            </div>
            <div className="max-xl:hidden min-w-0 truncate">
              Type
            </div>
            <div className="max-xl:hidden min-w-0 truncate">
              Cluster
            </div>
            <div className="max-xl:hidden min-w-0 truncate">
              SSA
            </div>
            <div className="max-xl:hidden min-w-0 truncate">
              Visit Status
            </div>
            {!props.readOnly ? (
              <div className="text-right">
                Actions
              </div>
            ) : null}
          </div>

          <ul role="list" aria-label="Schools">
            {props.schools.map((school) => (
              <Row
                key={school.id}
                school={school}
                props={props}
                open={openId === school.id}
                onToggle={() => setOpenId(openId === school.id ? null : school.id)}
                picked={picked.includes(school.id)}
                onPick={(checked) => setPicked(checked ? [...picked, school.id] : picked.filter((id) => id !== school.id))}
                onOpenGps={(s) => setGpsSchool(s)}
              />
            ))}
          </ul>
        </>
      ) : (
        <p className="border-t border-[var(--edify-table-divider)] px-4 py-10 text-center text-[14px] font-semibold text-[var(--edify-text-muted)]">
          {props.emptyMessage}
        </p>
      )}
      {gpsSchool ? (
        <GpsCaptureModal
          schoolId={gpsSchool.id}
          schoolCode={gpsSchool.schoolId}
          schoolName={gpsSchool.name}
          onClose={() => setGpsSchool(null)}
          onSaved={(res) => {
            setGpsSchool(null);
            setBulkMsg({ ok: true, text: res.message });
          }}
        />
      ) : null}
    </div>
  );
}
