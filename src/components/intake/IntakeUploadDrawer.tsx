"use client";

// Generic intake upload drawer — Manual | CSV for ANY field-described template.
//
// One component renders both a manual form (inputs derived from the template's
// fields, with a school picker for the School ID link) and a CSV upload (file /
// paste → live preview → import only the valid rows). Used for visits,
// trainings, exam results, expenses, the activity tracker, and SSA-by-CSV.

import { useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { FileUp, Plus, AlertCircle, CheckCircle2, Download } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { type IntakeTemplate, type TemplateField, requiredColumns } from "@/lib/intake/intake-templates";
import { validateIntakeValues, mapIntakeCsv, type IntakeCsvResult } from "@/lib/intake/intake-validate";
import { submitIntakeRecords } from "@/lib/actions/intake-actions";
import { uploadSsaFile, type UploadSummary } from "@/lib/intake/upload-client";
import { UploadSummaryCard } from "./UploadSummaryCard";
import type { IntakeSchoolLite } from "./IaIntakeActions";

export function IntakeUploadDrawer({
  open, onClose, template, mode: initialMode, schools, existingIds,
}: {
  open: boolean;
  onClose: () => void;
  template: IntakeTemplate | null;
  mode: "manual" | "csv";
  schools: IntakeSchoolLite[];
  existingIds: string[];
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"manual" | "csv">(initialMode);
  const [pending, start] = useTransition();
  const [serverMsg, setServerMsg] = useState<string | null>(null);

  // Manual
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  // CSV
  const fileRef = useRef<HTMLInputElement>(null);
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadSummary | null>(null);
  const isSsa = template?.id === "tpl-ssa-performance";

  const idSet = useMemo(() => new Set(existingIds), [existingIds]);
  const parsed: IntakeCsvResult | null = useMemo(
    () => (template && csvText.trim() ? mapIntakeCsv(template, csvText, idSet) : null),
    [template, csvText, idSet],
  );

  if (!template) return null;

  function setVal(key: string, v: string) {
    setValues((prev) => ({ ...prev, [key]: v }));
  }

  function reset() {
    setValues({}); setErrors({}); setCsvText(""); setCsvName(null); setCsvFile(null); setUploadResult(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  function submitManual() {
    if (!template) return;
    setServerMsg(null);
    const errs = validateIntakeValues(template, values, idSet);
    if (Object.keys(errs).length > 0) { setErrors(errs); return; }
    setErrors({});
    start(async () => {
      const res = await submitIntakeRecords(template.id, [values]);
      if (res.ok) {
        setServerMsg(res.created > 0 ? `Saved — 1 ${template.name} record added.` : `Row rejected: ${Object.values(res.failed[0]?.errors ?? {}).join(" · ")}`);
        if (res.created > 0) { reset(); router.refresh(); setTimeout(onClose, 900); }
      } else {
        setServerMsg("You don't have permission to upload this data.");
      }
    });
  }

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setCsvName(f.name);
    setCsvFile(f);
    setUploadResult(null);
    f.text().then(setCsvText);
  }

  function submitCsv() {
    if (!template) return;
    setServerMsg(null);

    // SSA-by-CSV posts the RAW file to the backend (the single source of truth):
    // Django validates + saves each row and reports the truthful breakdown.
    if (isSsa) {
      const file = csvFile
        ?? (csvText.trim() ? new File([csvText], csvName ?? "ssa.csv", { type: "text/csv" }) : null);
      if (!file) return;
      setUploadResult(null);
      start(async () => {
        const res = await uploadSsaFile(file);
        if (!res.ok) { setServerMsg(res.error); return; }
        setUploadResult(res.summary);
        router.refresh();
      });
      return;
    }

    if (!parsed || parsed.validCount === 0) return;
    const rows = parsed.rows.filter((r) => r.valid).map((r) => r.values);
    start(async () => {
      const res = await submitIntakeRecords(template.id, rows);
      if (res.ok) {
        setServerMsg(`Imported ${res.created} record${res.created === 1 ? "" : "s"}${res.failed.length ? `, ${res.failed.length} skipped` : ""}.`);
        reset(); router.refresh(); setTimeout(onClose, 1200);
      } else {
        setServerMsg("You don't have permission to upload this data.");
      }
    });
  }

  const hasUploadSource = !!csvFile || csvText.trim().length > 0;
  const canSubmit = mode === "manual"
    ? !pending
    : !pending && (isSsa ? hasUploadSource : (parsed?.validCount ?? 0) > 0);
  const csvHref = `/api/templates/${template.id}/csv`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={template.name}
      description={template.description}
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-[11px] muted truncate">{serverMsg}</span>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>Cancel</Button>
            {mode === "manual" ? (
              <Button variant="primary" size="sm" onClick={submitManual} disabled={!canSubmit} Icon={Plus}>
                {pending ? "Saving…" : "Save record"}
              </Button>
            ) : (
              <Button variant="primary" size="sm" onClick={submitCsv} disabled={!canSubmit} Icon={FileUp}>
                {pending ? "Uploading…" : isSsa ? "Upload SSA file" : `Import ${parsed?.validCount ?? 0} record${(parsed?.validCount ?? 0) === 1 ? "" : "s"}`}
              </Button>
            )}
          </div>
        </div>
      }
    >
      <div className="inline-flex rounded-lg border border-[var(--color-edify-divider)] p-0.5 mb-3 text-[12px] font-extrabold">
        {(["manual", "csv"] as const).map((m) => (
          <button key={m} type="button" onClick={() => setMode(m)}
            className={cn(
              "px-3 py-1 rounded-md transition-colors",
              mode === m ? "bg-[var(--color-edify-primary)] text-white" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
            )}>
            {m === "manual" ? "Manual entry" : "CSV upload"}
          </button>
        ))}
      </div>

      {mode === "manual" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {template.fields.map((f) => (
            <ManualField key={f.key} field={f} value={values[f.key] ?? ""} error={errors[f.key]}
              schoolLinked={template.schoolLinked} schools={schools} onChange={(v) => setVal(f.key, v)} />
          ))}
        </div>
      ) : (
        <CsvPanel
          template={template} fileRef={fileRef} csvName={csvName} csvText={csvText}
          parsed={parsed} csvHref={csvHref} uploadResult={uploadResult} isSsa={isSsa}
          onPickFile={onPickFile}
          onPasteText={(v) => { setCsvText(v); setCsvFile(null); setUploadResult(null); }}
        />
      )}
    </Modal>
  );
}

function ManualField({
  field, value, error, schoolLinked, schools, onChange,
}: {
  field: TemplateField;
  value: string;
  error?: string;
  schoolLinked: boolean;
  schools: IntakeSchoolLite[];
  onChange: (v: string) => void;
}) {
  const label = `${field.label}${field.required ? "" : " (optional)"}`;

  // The School ID link → a picker of onboarded schools (when linking, not creating).
  if (field.key === "School ID" && schoolLinked) {
    return (
      <Select label={label} placeholder="Select a school" value={value} error={error}
        options={schools.map((s) => ({ value: s.schoolId, label: `${s.schoolName} (${s.schoolId})` }))}
        onChange={(e) => onChange(e.target.value)} />
    );
  }
  if (field.type === "select") {
    return (
      <Select label={label} placeholder={`Select ${field.label.toLowerCase()}`} value={value} error={error}
        options={(field.options ?? []).map((o) => ({ value: o, label: o }))}
        onChange={(e) => onChange(e.target.value)} />
    );
  }
  const inputType = field.type === "date" ? "date" : field.type === "number" || field.type === "score" ? "number" : "text";
  return (
    <Input
      label={label}
      type={inputType}
      min={field.type === "score" ? 0 : field.min}
      max={field.type === "score" ? 10 : field.max}
      step={field.type === "score" ? "0.1" : undefined}
      placeholder={field.example !== undefined ? String(field.example) : field.placeholder}
      value={value}
      error={error}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function CsvPanel({
  template, fileRef, csvName, csvText, parsed, csvHref, uploadResult, isSsa, onPickFile, onPasteText,
}: {
  template: IntakeTemplate;
  fileRef: React.RefObject<HTMLInputElement | null>;
  csvName: string | null;
  csvText: string;
  parsed: IntakeCsvResult | null;
  csvHref: string;
  uploadResult: UploadSummary | null;
  isSsa: boolean;
  onPickFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onPasteText: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      {/* Truthful, backend-reported result (SSA file upload). */}
      {uploadResult && <UploadSummaryCard summary={uploadResult} fileName={csvName} />}

      <div className="rounded-lg border border-dashed border-[var(--color-edify-divider)] p-4 text-center">
        <FileUp size={20} className="mx-auto text-[var(--color-edify-muted)]" />
        <p className="text-[12px] font-extrabold mt-1.5">Upload the {template.name} {isSsa ? "CSV or XLSX" : "CSV"}</p>
        <p className="text-[11px] muted">
          {template.schoolLinked ? "Each row must carry a School ID for an onboarded school." : "Use the template headers."}
        </p>
        <div className="flex items-center justify-center gap-2 mt-2.5">
          <input ref={fileRef} type="file" accept={isSsa ? ".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : ".csv,text/csv"} className="hidden" onChange={onPickFile} />
          <Button variant="secondary" size="sm" Icon={FileUp} onClick={() => fileRef.current?.click()}>
            {csvName ? "Choose another file" : "Choose CSV file"}
          </Button>
          <a href={csvHref} className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
            <Download size={13} /> Template
          </a>
        </div>
        {csvName && <p className="text-[11px] muted mt-2">{csvName}</p>}
      </div>

      <details className="text-[11.5px]">
        <summary className="cursor-pointer font-semibold text-[var(--color-edify-muted)]">…or paste CSV rows</summary>
        <textarea
          className="mt-2 w-full h-24 rounded-lg border border-[var(--color-edify-divider)] bg-transparent p-2 text-[11.5px] font-mono"
          placeholder={requiredColumns(template).join(",")}
          value={csvText}
          onChange={(e) => onPasteText(e.target.value)}
        />
      </details>

      {parsed?.headerError && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11.5px] text-rose-700">
          <AlertCircle size={14} className="shrink-0 mt-0.5" /> {parsed.headerError}
        </div>
      )}

      {parsed && !parsed.headerError && parsed.rows.length > 0 && (
        <div className="rounded-lg border border-[var(--color-edify-divider)] overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-[var(--color-edify-soft)]/40 text-[11.5px] font-extrabold">
            <span>{parsed.rows.length} rows parsed</span>
            <span className={cn(parsed.validCount === parsed.rows.length ? "text-emerald-700" : "text-amber-700")}>
              {parsed.validCount} valid · {parsed.rows.length - parsed.validCount} with errors
            </span>
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)] max-h-64 overflow-auto">
            {parsed.rows.map((r) => {
              const idCol = template.ownIdField ? r.values[template.ownIdField] : r.values["School ID"];
              return (
                <li key={r.rowNumber} className="px-3 py-2 flex items-start gap-2.5">
                  <span className={cn(
                    "inline-flex items-center justify-center h-5 w-5 rounded-md text-[10px] font-extrabold shrink-0 mt-0.5",
                    r.valid ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700",
                  )}>
                    {r.valid ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-extrabold truncate">
                      Row {r.rowNumber} · {idCol || "(no id)"} · School {r.values["School ID"] || "—"}
                    </div>
                    {!r.valid && (
                      <div className="text-[10.5px] text-rose-700 mt-0.5">{Object.values(r.errors).join(" · ")}</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
