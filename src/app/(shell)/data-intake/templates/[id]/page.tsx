import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Download, FileSpreadsheet } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { isMockAllowed } from "@/lib/mock-policy";
import { getTemplate } from "@/lib/data-intake-mock";

export default async function TemplateDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!isMockAllowed()) return notFound();
  const t = getTemplate(id);
  if (!t) return notFound();

  return (
    <StubPage title={t.name} subtitle={`${t.dataType} · ${t.description}`}>
      <Link
        href="/data-intake/templates"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to template builder
      </Link>

      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <FileSpreadsheet size={14} className="text-[var(--color-edify-primary)]" />
            Schema
          </h2>
          <a
            href={`/api/templates/${t.id}/csv`}
            className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5 hover:brightness-110"
          >
            <Download size={13} />
            Download CSV template
          </a>
        </header>

        {/* Required columns */}
        <div>
          <h3 className="text-[12px] font-extrabold tracking-tight uppercase muted mb-2">Required columns</h3>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-[11.5px]">
            {t.requiredColumns.map((c) => (
              <li key={c} className="inline-flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                <span className="font-mono">{c}</span>
                {t.dropdownColumns[c] && (
                  <span className="text-[10px] muted">({t.dropdownColumns[c].length} allowed values)</span>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Optional columns */}
        {t.optionalColumns.length > 0 && (
          <div className="mt-4">
            <h3 className="text-[12px] font-extrabold tracking-tight uppercase muted mb-2">Optional columns</h3>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-[11.5px]">
              {t.optionalColumns.map((c) => (
                <li key={c} className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                  <span className="font-mono">{c}</span>
                  {t.dropdownColumns[c] && (
                    <span className="text-[10px] muted">({t.dropdownColumns[c].length} allowed values)</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Dropdowns */}
        {Object.keys(t.dropdownColumns).length > 0 && (
          <div className="mt-4">
            <h3 className="text-[12px] font-extrabold tracking-tight uppercase muted mb-2">Dropdown values</h3>
            <ul className="space-y-1.5 text-[11.5px]">
              {Object.entries(t.dropdownColumns).map(([col, values]) => (
                <li key={col}>
                  <span className="font-mono font-extrabold">{col}: </span>
                  <span className="muted">{values.join(" · ")}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Example rows */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Example row</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                {Object.keys(t.exampleRows[0] ?? {}).map((c) => (
                  <th key={c} className="py-2 px-2 whitespace-nowrap">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.exampleRows.map((row, i) => (
                <tr key={i} className="border-b border-[#eef2f4]">
                  {Object.values(row).map((v, j) => (
                    <td key={j} className="py-2 px-2 whitespace-nowrap font-mono">{String(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Validation rules */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Validation rules</h2>
        <ul className="space-y-1 text-[12px]">
          {t.validationRules.map((r, i) => (
            <li key={i} className="inline-flex items-start gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-3.5 text-[11.5px] muted">
        Created by <span className="font-extrabold text-[var(--color-edify-text)]">{t.createdBy}</span> ·
        Last updated <span className="font-extrabold text-[var(--color-edify-text)]">{t.updatedAt}</span>
      </section>
    </StubPage>
  );
}
