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
import Link from 'next/link';
import { useState, useTransition } from 'react';

import { bulkAssignClusterAction, bulkAssignProjectAction } from '@/app/(app)/schools/actions';
import type { DirectorySchool } from '@/gen/edify/screens/v1/school_directory_pb';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { SsaDetailPanel, ssaModelFromDirectory } from '../blocks/SsaDetailPanel';
import { textTone } from '../blocks/tones';

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
    ? 'grid items-center gap-x-3 px-4 grid-cols-[76px_minmax(0,1fr)] xl:grid-cols-[84px_minmax(0,1.8fr)_minmax(0,1fr)_minmax(0,1fr)_140px]'
    : 'grid items-center gap-x-3 px-4 grid-cols-[20px_76px_minmax(0,1fr)_auto] xl:grid-cols-[20px_84px_minmax(0,1.8fr)_minmax(0,1fr)_minmax(0,1fr)_140px_92px]';
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
}: {
  school: DirectorySchool;
  props: DirectoryListProps;
  open: boolean;
  onToggle: () => void;
  picked: boolean;
  onPick: (checked: boolean) => void;
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
        className={`${rowGridClass(props.readOnly)} min-h-[40px] cursor-pointer py-2 transition-colors hover:bg-[color-mix(in_oklab,var(--edify-surface-muted)_55%,transparent)] focus-within:bg-[color-mix(in_oklab,var(--edify-surface-muted)_40%,transparent)] ${
          open ? 'bg-[color-mix(in_oklab,var(--edify-surface-muted)_45%,transparent)]' : ''
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

        <div className="min-w-0">
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
          <h2
            data-directory-name=""
            className="break-words text-[length:var(--edify-text-label-size)] font-semibold leading-[1.3] text-[var(--edify-text)]"
          >
            {schoolHref ? (
              <Link href={schoolHref} className="inline text-[var(--edify-text)] hover:underline">
                {school.name}
              </Link>
            ) : (
              <span>{school.name}</span>
            )}
          </h2>
        </div>

        <div className="hidden min-w-0 xl:block" data-fact="district">
          {districtHref ? (
            <Link
              href={districtHref}
              className="inline break-words text-[length:var(--edify-text-label-size)] font-medium text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]"
            >
              {school.district}
            </Link>
          ) : (
            <span className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text)]">{school.district}</span>
          )}
        </div>

        <div className="hidden min-w-0 xl:block" data-fact="cluster">
          {clusterHref ? (
            <Link
              href={clusterHref}
              className="inline break-words text-[length:var(--edify-text-label-size)] font-medium text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]"
            >
              {school.clusterName}
            </Link>
          ) : (
            <span className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{school.clusterName}</span>
          )}
        </div>

        <div className="hidden min-w-0 xl:block" data-fact="visit">
          <Badge tone={school.visitStatusTone}>{school.visitStatusLabel}</Badge>
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
          {schoolHref ? (
            <div>
              <Link href={schoolHref} className="inline text-[13px] font-bold text-[var(--edify-text)] hover:underline">
                Open {school.name} school profile
              </Link>
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
      <div className="flex min-h-[48px] flex-wrap items-center gap-3 bg-[color-mix(in_oklab,var(--edify-surface-muted)_64%,transparent)] px-4 py-2">
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
            role="row"
            aria-label="School Directory columns"
            className={`${rowGridClass(props.readOnly)} border-y border-[var(--edify-table-divider)] bg-[color-mix(in_oklab,var(--edify-surface-muted)_42%,transparent)] py-2 text-[11px] font-bold uppercase tracking-[0.04em] text-[var(--edify-text-muted)]`}
          >
            {!props.readOnly ? (
              <div role="columnheader" className="flex items-center justify-center">
                <label className="flex items-center justify-center">
                  <input
                    type="checkbox"
                    checked={allPicked}
                    aria-label="Select page"
                    onChange={(event) => toggleAll(event.target.checked)}
                    className="h-4 w-4 accent-[var(--brand-primary)]"
                  />
                  <span className="sr-only">Select page</span>
                </label>
              </div>
            ) : null}
            <div role="columnheader" className="min-w-0 truncate">
              School ID
            </div>
            <div role="columnheader" className="min-w-0 truncate">
              School Name
            </div>
            <div role="columnheader" className="hidden min-w-0 truncate xl:block">
              District
            </div>
            <div role="columnheader" className="hidden min-w-0 truncate xl:block">
              Cluster
            </div>
            <div role="columnheader" className="hidden min-w-0 truncate xl:block">
              Visit Status
            </div>
            {!props.readOnly ? (
              <div role="columnheader" className="text-right">
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
              />
            ))}
          </ul>
        </>
      ) : (
        <p className="border-t border-[var(--edify-table-divider)] px-4 py-10 text-center text-[14px] font-semibold text-[var(--edify-text-muted)]">
          {props.emptyMessage}
        </p>
      )}
    </div>
  );
}
