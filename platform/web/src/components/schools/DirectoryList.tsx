'use client';

/*
 * The directory's record list (partials/schools/table.html and
 * directory_row.html): a list bar (Select page, "N schools listed"), then one
 * row a school: tick box, opener, School ID, name and, on a wide screen, its
 * district, cluster and visit status beside it, and one Actions menu. An
 * opened row shows every fact and the SSA score groups. Every value is the
 * gateway's.
 */
import Link from 'next/link';
import { useState, useTransition } from 'react';

import { bulkAssignClusterAction, bulkAssignProjectAction } from '@/app/(app)/schools/actions';
import type { DirectorySchool } from '@/gen/edify/screens/v1/school_directory_pb';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { textTone } from '../blocks/tones';
import { Icon } from '../shell/icons';

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

function Fact({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{label}</dt>
      <dd className="truncate font-medium text-[var(--edify-text)]">{children}</dd>
    </div>
  );
}

function ssaText(school: DirectorySchool): string {
  return school.ssaAverage === undefined ? 'Not assessed' : `${school.ssaAverage}/10`;
}

function Row({ school, props, open, onToggle, picked, onPick }: {
  school: DirectorySchool;
  props: DirectoryListProps;
  open: boolean;
  onToggle: () => void;
  picked: boolean;
  onPick: (checked: boolean) => void;
}) {
  const detailsId = `school-directory-details-${school.id}`;
  const name = props.mayOpenProfile ? (
    <Link href={`/schools/${school.schoolId}`} className="hover:underline">{school.name}</Link>
  ) : (
    school.name
  );
  const actions = school.actions.map((action) => ({
    key: action.key,
    label: action.label,
    enabled: action.enabled,
    reason: action.reason,
    href: `/schools/${encodeURIComponent(school.schoolId)}`,
  }));
  return (
    <li className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-surface)] last:border-b-0" data-row={school.schoolId}>
      <div className="flex min-h-[37px] items-center gap-3 px-4 py-1.5" onClick={(event) => {
        if (!(event.target as HTMLElement).closest('a, button, input, label')) onToggle();
      }}>
        {!props.readOnly ? (
          <label className="flex shrink-0 items-center">
            <input type="checkbox" checked={picked} onChange={(event) => onPick(event.target.checked)} className="h-4 w-4 accent-[var(--brand-primary)]" />
            <span className="sr-only">Select {school.name}</span>
          </label>
        ) : null}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={detailsId}
          aria-label={open ? `Hide details for ${school.name}` : `Show details for ${school.name}`}
          className="-mx-1 hidden h-6 w-6 shrink-0 sm:grid place-items-center rounded text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
        >
          <Icon name="chevronRight" className={`h-4 w-4 transition-transform ${open ? 'rotate-90' : ''}`} />
        </button>
        <span title={`School ID ${school.schoolId}`} className="shrink-0 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-1.5 py-px text-[length:var(--edify-text-micro-size)] font-bold text-[var(--edify-text-muted)]">
          <span className="sr-only">School ID </span>
          {school.schoolId}
        </span>
        <h2 data-directory-name className="min-w-0 flex-1 break-words text-[length:var(--edify-text-label-size)] font-semibold leading-[1.3] text-[var(--edify-text)] xl:flex-none xl:basis-[24rem]">{name}</h2>
        <span className="hidden min-w-0 flex-1 truncate xl:block" data-fact="district">{school.district}</span>
        <span className="hidden min-w-0 flex-1 truncate xl:block" data-fact="cluster">{school.clusterName}</span>
        <span className="hidden shrink-0 xl:block" data-fact="visit">
          <Badge tone={school.visitStatusTone}>{school.visitStatusLabel}</Badge>
        </span>
        {!props.readOnly ? (
          <div className="ml-auto shrink-0 pl-4">
            <RowActions subject={school.name} actions={actions} />
          </div>
        ) : null}
      </div>
      {open ? (
        <div id={detailsId} className="border-t border-[var(--edify-table-divider)] bg-[var(--edify-card-surface)] px-4 py-3">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
            <Fact label="District:">{school.district}</Fact>
            <Fact label="Shipping Address:">{school.shippingAddress}</Fact>
            <Fact label="School Type:">{school.schoolType}</Fact>
            <Fact label="Cluster:">{school.clusterName}</Fact>
            <Fact label="Enrollment:">{school.enrolment}</Fact>
            <Fact label="Phone:">{school.phone}</Fact>
            <Fact label="Primary Contact:">{school.contact}</Fact>
            <Fact label="Staff Name:">{school.staffName}</Fact>
            <Fact label="SSA:"><span className={textTone(school.ssaTone)}>{ssaText(school)}</span></Fact>
            <Fact label="Visit status:">
              <Badge tone={school.visitStatusTone}>{school.visitStatusLabel}</Badge>
              {school.nextVisitDate ? <span className="ml-1 text-[var(--edify-text-muted)]">{school.nextVisitDate}</span> : null}
            </Fact>
            <Fact label="Cluster training:">
              <span className={textTone(school.clusterTrainingState)} title={school.clusterTrainingReason || undefined}>{school.clusterTrainingLabel}</span>
            </Fact>
            <Fact label="Visit:"><span className={textTone(school.visitCount ? 'positive' : 'attention')}>{school.visitCount}</span></Fact>
            <Fact label="Training:"><span className={textTone(school.trainingCount ? 'positive' : 'attention')}>{school.trainingCount}</span></Fact>
          </dl>
          {school.ssaGroups.length ? (
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              {school.ssaGroups.map((group) => (
                <section key={group.key} className="rounded-[var(--radius-control)] border border-[var(--edify-border)] p-3">
                  <h3 className={`text-[length:var(--edify-text-micro-size)] font-semibold ${textTone(group.tone)}`}>{group.title}</h3>
                  <ul className="mt-1.5 space-y-1">
                    {group.items.map((item) => (
                      <li key={item.label} className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="truncate">{item.label}</span>
                        <Badge tone={item.bandTone}>{`${item.score} · ${item.band}`}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          ) : null}
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

  return (
    <div data-block="table">
      <div className="flex min-h-[53px] flex-wrap items-center gap-3 bg-[color-mix(in_oklab,var(--edify-surface-muted)_64%,transparent)] px-4 py-2.5">
        {!props.readOnly ? (
          <label className="flex items-center gap-2 font-semibold text-[var(--edify-text)]">
            <input
              type="checkbox"
              checked={allPicked}
              onChange={(event) => setPicked(event.target.checked ? props.schools.map((school) => school.id) : [])}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
            <span>Select page</span>
          </label>
        ) : null}
        {picked.length ? (
          <>
            <span aria-live="polite" className="font-semibold">{picked.length} selected</span>
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
        <span className="ml-auto text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--edify-text-muted)]">{props.listed}</span>
      </div>
      {props.schools.length ? (
        <ul role="list" aria-label="Schools" className="border-t border-[var(--edify-table-divider)]">
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
      ) : (
        <p className="px-4 py-10 text-center text-[14px] font-semibold text-[var(--edify-text-muted)]">{props.emptyMessage}</p>
      )}
    </div>
  );
}
