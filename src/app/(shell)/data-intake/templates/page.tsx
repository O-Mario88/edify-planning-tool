import Link from "next/link";
import { FileSpreadsheet, Download, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { dataTemplates } from "@/lib/data-intake-mock";

export default function TemplateBuilderPage() {
  if (!isMockAllowed()) {
    return (
      <StubPage title="Template Builder" subtitle="Upload templates are not yet served from the backend.">
        <InsufficientData surface="the template builder" />
      </StubPage>
    );
  }
  return (
    <StubPage
      title="Template Builder"
      subtitle={`${dataTemplates.length} system-generated upload templates. Each includes required columns, optional columns, dropdown values, example rows, validation rules, and system field mappings. Users do not invent columns.`}
    >
      <section className="card p-3.5">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {dataTemplates.map((t) => (
            <li key={t.id} className="py-3 flex items-center gap-3">
              <span className="h-10 w-10 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <FileSpreadsheet size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <Link href={`/data-intake/templates/${t.id}`} className="text-[13px] font-extrabold tracking-tight hover:text-[var(--color-edify-primary)]">
                  {t.name}
                </Link>
                <div className="text-caption muted truncate">
                  {t.dataType} · {t.requiredColumns.length} required + {t.optionalColumns.length} optional columns
                </div>
                <div className="text-[11px] muted leading-snug mt-0.5 line-clamp-2">{t.description}</div>
              </div>
              <a
                href={`/api/templates/${t.id}/csv`}
                className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-[11.5px] font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 shrink-0"
              >
                <Download size={12} />
                CSV
              </a>
              <Link
                href={`/data-intake/templates/${t.id}`}
                className="h-9 w-9 rounded-xl border border-[var(--color-edify-border)] grid place-items-center hover:bg-[var(--color-edify-soft)]/40 shrink-0"
                aria-label={`Open ${t.name}`}
              >
                <ChevronRight size={13} className="text-[var(--color-edify-muted)]" />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </StubPage>
  );
}
