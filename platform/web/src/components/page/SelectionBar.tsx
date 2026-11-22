'use client';

/*
 * The bar for ticked rows (activities/selection_bar.html): it shows once a
 * row is ticked, says how many, and offers native Go Preview -> Confirm for
 * activity bulk reschedule & cancel (Step 3D — zero Django handoff).
 */
import { useEffect, useState } from 'react';

import {
  confirmBulkActivitiesAction,
  previewBulkActivitiesAction,
  type BulkConfirmResult,
  type BulkPreviewResult,
} from '@/app/(app)/bulk/activities/actions';
import { bulkAssignClusterAction, bulkAssignProjectAction, type BulkSchoolActionResult } from '@/app/(app)/schools/actions';
import type { PageSelection, PageSelectionAction } from '@/gen/edify/screens/v1/page_pb';

import { selectionHref } from './selectionHref';

type NativeBulkKind = 'reschedule' | 'cancel' | 'assign_cluster' | 'assign_project';

function nativeBulkKind(action: PageSelectionAction): NativeBulkKind | null {
  const href = action.href.toLowerCase();
  if (href.includes('/activity-selection/reschedule')) return 'reschedule';
  if (href.includes('/activity-selection/cancel')) return 'cancel';
  if (href.includes('bulk-assign-cluster') || href.includes('assign-cluster')) return 'assign_cluster';
  if (href.includes('bulk-assign-project') || href.includes('assign-project')) return 'assign_project';
  return null;
}

export function SelectionBar({ selection, pageHref, scopeId }: { selection: PageSelection; pageHref: string; scopeId?: string }) {
  const [ids, setIds] = useState<readonly string[]>([]);
  const [activeKind, setActiveKind] = useState<NativeBulkKind | null>(null);
  const [date, setDate] = useState('');
  const [reason, setReason] = useState('');
  const [targetId, setTargetId] = useState('');
  const [preview, setPreview] = useState<BulkPreviewResult | null>(null);
  const [confirmResult, setConfirmResult] = useState<BulkConfirmResult | null>(null);
  const [schoolResult, setSchoolResult] = useState<BulkSchoolActionResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const read = () => {
      const root = scopeId ? document.getElementById(scopeId) : document;
      const ticked = root ? Array.from(root.querySelectorAll<HTMLInputElement>('input[data-pick]:checked')) : [];
      const boxes = scopeId ? ticked : ticked.filter((box) => !box.closest('[data-record-open]'));
      setIds([...new Set(boxes.map((box) => box.dataset.pick ?? '').filter(Boolean))]);
    };
    document.addEventListener('change', read);
    return () => document.removeEventListener('change', read);
  }, [scopeId]);

  if (!ids.length && !activeKind && !confirmResult && !schoolResult) return null;

  const resetModal = () => {
    setActiveKind(null);
    setTargetId('');
    setPreview(null);
    setConfirmResult(null);
    setSchoolResult(null);
    setError('');
    setBusy(false);
  };

  const runPreview = async () => {
    if (activeKind !== 'reschedule' && activeKind !== 'cancel') return;
    setError('');
    setBusy(true);
    const res = await previewBulkActivitiesAction({ kind: activeKind, activityIds: ids, date, reason });
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setPreview(res.data);
  };

  const runConfirm = async () => {
    if ((activeKind !== 'reschedule' && activeKind !== 'cancel') || !preview || busy) return;
    if (!reason.trim()) {
      setError(activeKind === 'reschedule' ? 'Give the reason these activities are moving.' : 'Give the reason these activities are being cancelled.');
      return;
    }
    if (activeKind === 'reschedule' && !date.trim()) {
      setError('Choose the date these activities move to.');
      return;
    }
    setError('');
    setBusy(true);
    const res = await confirmBulkActivitiesAction({
      kind: activeKind,
      activityIds: ids,
      date,
      reason,
      idempotencyKey: preview.previewToken,
    });
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setConfirmResult(res.data);
    setPreview(null);
  };

  const runSchoolBulk = async () => {
    if ((activeKind !== 'assign_cluster' && activeKind !== 'assign_project') || busy) return;
    if (!targetId.trim()) {
      setError(activeKind === 'assign_cluster' ? 'Enter the destination Cluster ID.' : 'Enter the destination Project ID.');
      return;
    }
    setError('');
    setBusy(true);
    const res =
      activeKind === 'assign_cluster'
        ? await bulkAssignClusterAction({ schoolIds: ids, clusterId: targetId })
        : await bulkAssignProjectAction({ schoolIds: ids, projectId: targetId });
    setBusy(false);
    if (!res.ok) {
      setError(res.message);
      return;
    }
    setSchoolResult(res);
  };

  const place = scopeId
    ? 'flex rounded-[10px]'
    : 'fixed inset-x-4 bottom-24 z-40 mx-auto flex max-w-[40rem] rounded-[10px] shadow-lg lg:bottom-6';

  return (
    <>
      {ids.length > 0 ? (
        <div role="region" aria-label="Selected rows" data-block="selection" className={`${place} flex-wrap items-center gap-3 border border-[var(--brand-primary-border)] bg-[var(--edify-surface)] px-4 py-2.5`}>
          <span className="font-semibold">
            {ids.length} {selection.noun}
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            {selection.actions.map((action) => {
              const kind = nativeBulkKind(action);
              if (kind) {
                return (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => {
                      setActiveKind(kind);
                      setPreview(null);
                      setConfirmResult(null);
                      setError('');
                    }}
                    className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-label-size)] font-semibold hover:bg-[var(--brand-primary-soft)]"
                  >
                    {action.label}
                  </button>
                );
              }
              return (
                <a
                  key={action.label}
                  href={selectionHref(pageHref, action, ids)}
                  className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-label-size)] font-semibold hover:bg-[var(--brand-primary-soft)]"
                >
                  {action.label}
                </a>
              );
            })}
          </div>
        </div>
      ) : null}

      {activeKind || confirmResult || schoolResult ? (
        <div role="dialog" aria-modal="true" aria-label="Bulk action" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4">
          <div className="w-full max-w-lg space-y-4 rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-bold text-[var(--edify-text)]">
                {activeKind === 'reschedule'
                  ? 'Bulk Reschedule Activities'
                  : activeKind === 'cancel'
                    ? 'Bulk Cancel Activities'
                    : activeKind === 'assign_cluster'
                      ? 'Assign Schools to Cluster'
                      : 'Enroll Schools in Project'}
              </h2>
              <button type="button" onClick={resetModal} className="text-[12px] font-bold text-[var(--edify-text-muted)]">
                Close
              </button>
            </div>

            {error ? (
              <p role="alert" className="rounded-[var(--radius-control)] border border-[#fecdd3] bg-[#fff1f2] px-3 py-2 text-[12px] font-semibold text-[#be123c]">
                {error}
              </p>
            ) : null}

            {confirmResult || schoolResult ? (
              <div className="space-y-3">
                <p role="status" className="rounded-[var(--radius-control)] border border-[#a7f3d0] bg-[#ecfdf5] px-3 py-2 text-[13px] font-semibold text-[#047857]">
                  {confirmResult?.message || confirmResult?.outcome || schoolResult?.message || 'Bulk action completed.'}
                </p>
                {schoolResult?.warnings.length ? (
                  <ul className="space-y-1 text-[12px] text-[var(--edify-text-muted)]">
                    {schoolResult.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                ) : null}
                <button
                  type="button"
                  onClick={resetModal}
                  className="inline-flex h-9 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[13px] font-bold text-white"
                >
                  Done
                </button>
              </div>
            ) : activeKind === 'assign_cluster' || activeKind === 'assign_project' ? (
              <div className="space-y-3">
                <div className="space-y-1">
                  <label htmlFor="bulk-target-id" className="block text-[12px] font-bold text-[var(--edify-text)]">
                    {activeKind === 'assign_cluster' ? 'Cluster ID' : 'Project ID'}
                  </label>
                  <input
                    id="bulk-target-id"
                    type="text"
                    value={targetId}
                    onChange={(e) => setTargetId(e.target.value)}
                    placeholder={activeKind === 'assign_cluster' ? 'Enter cluster ID…' : 'Enter project ID…'}
                    className="h-9 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
                  />
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={runSchoolBulk}
                  className="inline-flex h-9 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[13px] font-bold text-white"
                >
                  {busy ? 'Applying…' : `Apply to ${ids.length} school(s)`}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {activeKind === 'reschedule' ? (
                  <div className="space-y-1">
                    <label htmlFor="bulk-date" className="block text-[12px] font-bold text-[var(--edify-text)]">
                      New Date
                    </label>
                    <input
                      id="bulk-date"
                      type="date"
                      value={date}
                      onChange={(e) => {
                        setDate(e.target.value);
                        setPreview(null);
                      }}
                      className="h-9 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px]"
                    />
                  </div>
                ) : null}
                <div className="space-y-1">
                  <label htmlFor="bulk-reason" className="block text-[12px] font-bold text-[var(--edify-text)]">
                    Reason
                  </label>
                  <textarea
                    id="bulk-reason"
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Explain why these activities are changing…"
                    className="w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-2.5 text-[13px]"
                  />
                </div>

                {preview ? (
                  <div className="space-y-2 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)]/40 p-3 text-[12px]">
                    <p className="font-bold text-[var(--edify-text)]">
                      Preview (no changes saved yet): {preview.eligible.length} eligible, {preview.excluded.length} excluded
                    </p>
                    {preview.excluded.length > 0 ? (
                      <ul className="space-y-1 text-[#b91c1c]">
                        {preview.excluded.map((ex) => (
                          <li key={ex.id}>
                            <strong>{ex.title || ex.id}</strong>: {ex.reason}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}

                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={runPreview}
                    className="inline-flex h-9 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-4 text-[13px] font-bold"
                  >
                    {busy && !preview ? 'Checking…' : 'Preview Changes'}
                  </button>
                  {preview && preview.eligible.length > 0 ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={runConfirm}
                      className="inline-flex h-9 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[13px] font-bold text-white"
                    >
                      {busy ? 'Applying…' : `Confirm (${preview.eligible.length})`}
                    </button>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
