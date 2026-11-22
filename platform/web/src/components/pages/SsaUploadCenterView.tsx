'use client';

import Link from 'next/link';
import { useState, type ChangeEvent, type FormEvent } from 'react';
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Upload } from 'lucide-react';

import { EDIFY_BTN_OUTLINE, EDIFY_BTN_PRIMARY, PageHeroHeader } from './EdifyDashboardChrome';

type UploadTab = 'ssa' | 'planned-activities';

interface RowError {
  row: number;
  message: string;
}

interface ImportResult {
  imported_count: number;
  skipped_count: number;
  record_ids?: string[];
  errors?: RowError[];
  error?: string;
}

const SSA_COLUMNS: ReadonlyArray<readonly [string, string, string]> = [
  ['School ID', 'Must match an authoritative Edify School ID in your country', 'UG-0001'],
  ['Assessment Date', 'Date of the SSA assessment (YYYY-MM-DD)', '2026-11-22'],
  ['SSA Year', 'Operational FY ("last", "current", or 4-digit FY such as 2027)', '2027'],
  ['Christ-Centered Education (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['School Leadership (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['Teaching & Learning (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['Financial Sustainability (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['Education Technology (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['Enrolment (0-10)', 'SSA performance score (0–10; headcount belongs on School Profile)', '7.5'],
  ['Community Engagement (0-10)', 'SSA score from 0 to 10', '7.5'],
  ['Safeguarding (0-10)', 'SSA score from 0 to 10', '7.5'],
];

const ACTIVITY_COLUMNS: ReadonlyArray<readonly [string, string, string]> = [
  ['activity_id', 'Authoritative activity ID exported from the template', 'act_12345'],
  ['edify_school_id', 'Authoritative Edify School ID (reference column)', 'UG-0001'],
  ['completion_status', 'Target status: completed, submitted_to_pl, or cancelled (leave blank to skip)', 'completed'],
  ['completion_notes', 'Optional field completion notes saved with the record', 'Completed visit with head teacher'],
];

export function SsaUploadCenterView() {
  const [activeTab, setActiveTab] = useState<UploadTab>('ssa');
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [fatalError, setFatalError] = useState<string | null>(null);

  const isSSA = activeTab === 'ssa';
  const templateHref = isSSA ? '/ssa/upload/template' : '/api/uploads/planned-activities';
  const postEndpoint = isSSA ? '/api/uploads/ssa' : '/api/uploads/planned-activities';
  const columns = isSSA ? SSA_COLUMNS : ACTIVITY_COLUMNS;

  function handleTabChange(next: UploadTab) {
    setActiveTab(next);
    setFile(null);
    setResult(null);
    setFatalError(null);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setResult(null);
    setFatalError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setFatalError('Please choose a CSV file to upload.');
      return;
    }
    setSubmitting(true);
    setFatalError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(postEndpoint, {
        method: 'POST',
        body: formData,
      });
      const json = (await res.json().catch(() => ({}))) as ImportResult;
      if (!res.ok) {
        setFatalError(json.error || `Upload failed (HTTP ${res.status}).`);
      } else {
        setResult(json);
      }
    } catch {
      setFatalError('Network error while uploading file. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-5 px-4 pb-20 pt-5 sm:px-6 lg:pb-12">
      <PageHeroHeader
        eyebrow="Quality & Bulk Operations"
        title="Bulk Upload Center"
        description="Download official templates and import validated SSA scores or planned-activity completions directly into the Go operational ledger. Imported SSA scores wait for independent verification."
        icon={<Upload className="h-5 w-5" />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/ssa/upload/history/" className={EDIFY_BTN_OUTLINE}>
              <span>Upload History</span>
            </Link>
            <Link href="/ia/verification/" className={EDIFY_BTN_OUTLINE}>
              <span>Verification Queue</span>
            </Link>
            <a href={templateHref} download className={EDIFY_BTN_PRIMARY}>
              <Download className="h-4 w-4" aria-hidden="true" />
              <span>Download CSV Template</span>
            </a>
          </div>
        }
      />

      {/* Mode Switcher */}
      <div className="flex flex-wrap gap-2 border-b border-[var(--edify-border)] pb-2" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={isSSA}
          onClick={() => handleTabChange('ssa')}
          className={`rounded-[10px] px-4 py-2 text-[13px] font-semibold transition-colors ${
            isSSA
              ? 'bg-[var(--brand-primary)] text-white shadow-xs'
              : 'border border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text)] hover:border-[var(--brand-primary-border)]'
          }`}
        >
          Official SSA Scores CSV
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={!isSSA}
          onClick={() => handleTabChange('planned-activities')}
          className={`rounded-[10px] px-4 py-2 text-[13px] font-semibold transition-colors ${
            !isSSA
              ? 'bg-[var(--brand-primary)] text-white shadow-xs'
              : 'border border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text)] hover:border-[var(--brand-primary-border)]'
          }`}
        >
          Planned Activities Completion CSV
        </button>
      </div>

      {/* Upload Form Card */}
      <section className="rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-5 shadow-[var(--edify-shadow-xs)]">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                {isSSA ? 'Upload Official SSA Scores (.csv)' : 'Upload Planned Activities Completion Sheet (.csv)'}
              </h2>
              <p className="text-[13px] text-[var(--edify-text-muted)]">
                {isSSA
                  ? 'Every row is validated against your country’s School Directory and queued for independent verification.'
                  : 'Download your pre-populated planned activities template, fill completion_status, and re-import.'}
              </p>
            </div>
            <a href={templateHref} download className={EDIFY_BTN_OUTLINE}>
              <FileSpreadsheet className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
              <span>{isSSA ? 'SSA Template (.csv)' : 'Planned Activities Template (.csv)'}</span>
            </a>
          </div>

          <label className="flex cursor-pointer flex-col items-center justify-center rounded-[12px] border-2 border-dashed border-[var(--edify-border)] bg-[var(--edify-surface)] px-6 py-8 text-center transition-colors hover:border-[var(--brand-primary)]">
            <Upload className="mb-2 h-7 w-7 text-[var(--brand-primary)]" aria-hidden="true" />
            <span className="text-[14px] font-semibold text-[var(--edify-text)]">
              {file ? file.name : 'Choose a CSV file to upload'}
            </span>
            <span className="mt-1 text-[12px] text-[var(--edify-text-muted)]">
              {file ? `${(file.size / 1024).toFixed(1)} KB ready for validation` : 'Max 5 MB · UTF-8 CSV format'}
            </span>
            <input
              type="file"
              name="file"
              accept=".csv,text/csv"
              onChange={handleFileChange}
              className="sr-only"
            />
          </label>

          <div className="flex items-center justify-end gap-3">
            <button type="submit" disabled={submitting || !file} className={EDIFY_BTN_PRIMARY}>
              <Upload className="h-4 w-4" aria-hidden="true" />
              <span>{submitting ? 'Validating & Importing…' : 'Upload and Import'}</span>
            </button>
          </div>
        </form>

        {fatalError ? (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2.5 rounded-[10px] border border-[var(--edify-danger-border)] bg-[var(--edify-danger-light)] px-4 py-3 text-[13px] text-[var(--edify-danger-text)]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{fatalError}</span>
          </div>
        ) : null}

        {result ? (
          <div className="mt-4 space-y-3 rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-surface)] p-4">
            <div className="flex flex-wrap items-center gap-4 text-[13.5px] font-semibold">
              <span className="inline-flex items-center gap-1.5 text-[var(--edify-success-text)]">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                Imported: {result.imported_count}
              </span>
              <span className="text-[var(--edify-text-muted)]">Skipped / Errors: {result.skipped_count}</span>
            </div>
            {result.errors && result.errors.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-[12.5px]">
                  <thead>
                    <tr className="border-b border-[var(--edify-border)] text-[var(--edify-text-muted)]">
                      <th className="py-1.5 pr-4 font-semibold">CSV Row</th>
                      <th className="py-1.5 font-semibold">Validation Issue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((err, i) => (
                      <tr key={`${err.row}-${i}`} className="border-b border-[var(--edify-border)]/60">
                        <td className="py-1.5 pr-4 font-mono font-semibold">{err.row}</td>
                        <td className="py-1.5 text-[var(--edify-danger-text)]">{err.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Required Column Specification */}
      <section className="rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-5 shadow-[var(--edify-shadow-xs)]">
        <h3 className="mb-3 text-[14px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
          Required Column Format
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-[var(--edify-border)] text-[11.5px] uppercase tracking-[0.03em] text-[var(--edify-text-muted)]">
                <th className="py-2 pr-4">Column Header</th>
                <th className="py-2 pr-4">Description</th>
                <th className="py-2">Example</th>
              </tr>
            </thead>
            <tbody>
              {columns.map(([col, desc, ex]) => (
                <tr key={col} className="border-b border-[var(--edify-border)]/60">
                  <td className="py-2 pr-4 font-semibold text-[var(--edify-text)]">{col}</td>
                  <td className="py-2 pr-4 text-[var(--edify-text-muted)]">{desc}</td>
                  <td className="py-2 font-mono text-[12px] text-[var(--brand-primary-text)]">{ex}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
