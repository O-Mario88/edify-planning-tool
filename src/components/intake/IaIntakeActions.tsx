"use client";

// IA / Admin data-intake actions — Add School + Upload SSA performance.
//
// Two drawers backed by the intake server actions. Geography-driven dependent
// dropdowns (region → district → sub-county) from the geography source of
// truth. FY + quarter for an SSA upload are DERIVED from the SSA date and shown
// live so the user sees which cycle the scores land in before submitting.

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, Upload, CheckCircle2, Lock, FileUp, AlertCircle, Download, Pencil } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { REGIONS, districtsInRegion, subCountiesOf, type UgandaRegion } from "@/lib/geography";
import {
  SSA_INTERVENTION_AREAS,
  deriveFyFromDate,
  deriveQuarterFromDate,
  ssaAverage,
  validateNewSchool,
  validateSsaUpload,
  type SchoolType,
  type SsaInterventionArea,
} from "@/lib/intake/intake-core";
import { ID_FORMATS } from "@/lib/intake/id-formats";
import { mapSchoolCsv, type SchoolCsvResult } from "@/lib/intake/school-csv";
import { getIntakeTemplate } from "@/lib/intake/intake-templates";
import { createSchool, uploadSsaPerformance, updateSchoolDetails } from "@/lib/actions/intake-actions";
import { uploadSchoolFile, type UploadSummary } from "@/lib/intake/upload-client";
import { UploadSummaryCard } from "./UploadSummaryCard";
import { IntakeUploadDrawer } from "./IntakeUploadDrawer";

type UploadKind = { id: string; name: string; sub: string };
const UPLOADS: UploadKind[] = [
  { id: "tpl-school-onboarding", name: "School Onboarding", sub: "Create schools (ID 32791)" },
  { id: "tpl-ssa-performance",   name: "SSA Performance",   sub: "8 area scores + enrolment" },
  { id: "tpl-activity-tracker",  name: "Activity & Engagement", sub: "Last training/visit/exam — FY cycle" },
  { id: "tpl-exam-results",      name: "Exam Results",      sub: "Scores & pass rates" },
];

export type IntakeSchoolLite = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  schoolType: string;
  ssaStatus: string;
  planningLocked: boolean;
  dateAdded: string;
  addedBy: string;
  // Optional detail fields (prefill the Edit-details drawer).
  subCounty?: string;
  enrollment?: number;
  assignedCceo?: string;
  cluster?: string;
  phone?: string;
  primaryContact?: string;
  shippingAddress?: string;
  lastEnrollmentDate?: string;
};

const SCHOOL_TYPES: SchoolType[] = ["Client", "Core", "Champion", "Potential Core", "Potential Champion", "Other"];
const EMPTY_SCORES = Object.fromEntries(SSA_INTERVENTION_AREAS.map((a) => [a, ""])) as Record<SsaInterventionArea, string>;

export function IaIntakeActions({ schools, existingIds }: { schools: IntakeSchoolLite[]; existingIds: string[] }) {
  const [active, setActive] = useState<{ id: string; mode: "manual" | "csv" } | null>(null);
  const close = () => setActive(null);
  const [editing, setEditing] = useState<IntakeSchoolLite | null>(null);

  return (
    <>
      <section className="card p-3.5">
        <div className="min-w-0 mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight">Data uploads</h2>
          <p className="text-[11.5px] muted">
            Every upload supports manual entry (one or two) and CSV (a long list). Data about a school must carry its
            School ID to link it. New schools are planning-locked until their first SSA.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {UPLOADS.map((u) => (
            <div key={u.id} className="rounded-lg border border-[var(--color-edify-divider)] p-3 flex flex-col gap-2">
              <div className="min-w-0">
                <div className="text-[12.5px] font-extrabold tracking-tight truncate">{u.name}</div>
                <div className="text-[10.5px] muted truncate">{u.sub}</div>
              </div>
              <div className="flex items-center gap-1.5">
                <Button variant="secondary" size="sm" Icon={Plus} onClick={() => setActive({ id: u.id, mode: "manual" })}>
                  Manual
                </Button>
                <Button variant="ghost" size="sm" Icon={FileUp} onClick={() => setActive({ id: u.id, mode: "csv" })}>
                  CSV
                </Button>
              </div>
            </div>
          ))}
        </div>

        {schools.length > 0 && (
          <>
            <h3 className="text-[12px] font-extrabold tracking-tight mt-4 mb-1">Recently added schools</h3>
            <p className="text-[10.5px] muted mb-1">Use <span className="font-extrabold">Edit details</span> to complete optional fields (owner, enrolment, contact, phone, address) any time after upload.</p>
            <ul className="divide-y divide-[var(--color-edify-divider)]">
              {schools.slice(0, 6).map((s) => {
                const missing = missingDetailCount(s);
                return (
                <li key={s.schoolId} className="py-2.5 flex items-center gap-3">
                  <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[10px] font-extrabold">
                    {s.schoolType.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight truncate">{s.schoolName}</div>
                    <div className="text-caption muted truncate">
                      {s.schoolId} · {s.district}, {s.region} · added {s.dateAdded} · {s.addedBy}
                    </div>
                  </div>
                  {missing > 0 && (
                    <span className="hidden sm:inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-slate-100 text-slate-600 whitespace-nowrap">
                      {missing} field{missing === 1 ? "" : "s"} to add
                    </span>
                  )}
                  {s.planningLocked ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700 whitespace-nowrap">
                      <Lock size={10} /> SSA pending
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 whitespace-nowrap">
                      <CheckCircle2 size={10} /> Planning open
                    </span>
                  )}
                  <Button variant="ghost" size="sm" Icon={Pencil} onClick={() => setEditing(s)}>
                    Edit details
                  </Button>
                </li>
                );
              })}
            </ul>
          </>
        )}
      </section>

      {/* School onboarding has its own geography-aware drawer (manual + CSV). */}
      <NewSchoolDrawer
        key={`school-${active?.id === "tpl-school-onboarding" ? active.mode : "m"}`}
        open={active?.id === "tpl-school-onboarding"}
        initialMode={active?.id === "tpl-school-onboarding" ? active.mode : "manual"}
        onClose={close}
        existingIds={existingIds}
      />
      {/* SSA manual uses the score-grid drawer with live FY/quarter derivation. */}
      <SsaUploadDrawer
        open={active?.id === "tpl-ssa-performance" && active.mode === "manual"}
        onClose={close}
        schools={schools}
      />
      {/* Everything else (incl. SSA-by-CSV) uses the generic engine. */}
      <IntakeUploadDrawer
        key={`gen-${active && !(active.id === "tpl-school-onboarding") && !(active.id === "tpl-ssa-performance" && active.mode === "manual") ? `${active.id}-${active.mode}` : "none"}`}
        open={!!active && !(active.id === "tpl-school-onboarding") && !(active.id === "tpl-ssa-performance" && active.mode === "manual")}
        mode={active?.mode ?? "manual"}
        template={active ? getIntakeTemplate(active.id) ?? null : null}
        schools={schools}
        existingIds={existingIds}
        onClose={close}
      />
      {/* Edit / complete optional details for an already-uploaded school. */}
      <EditSchoolDrawer
        key={`edit-${editing?.schoolId ?? "none"}`}
        school={editing}
        onClose={() => setEditing(null)}
      />
    </>
  );
}

// Count of the optional detail fields not yet filled (display hint only).
const DETAIL_FIELDS: (keyof IntakeSchoolLite)[] = [
  "assignedCceo", "enrollment", "subCounty", "cluster", "phone", "primaryContact", "shippingAddress",
];
function missingDetailCount(s: IntakeSchoolLite): number {
  return DETAIL_FIELDS.filter((k) => {
    const v = s[k];
    return v === undefined || v === null || v === "";
  }).length;
}

// ─── Add School ────────────────────────────────────────────────────

function NewSchoolDrawer({ open, onClose, existingIds, initialMode = "manual" }: { open: boolean; onClose: () => void; existingIds: string[]; initialMode?: "manual" | "csv" }) {
  const router = useRouter();
  const [mode, setMode] = useState<"manual" | "csv">(initialMode);
  const [pending, start] = useTransition();

  // Manual form state
  const [form, setForm] = useState({
    schoolId: "", schoolName: "", region: "", district: "", subCounty: "", parish: "",
    schoolType: "Client" as SchoolType, enrollment: "", assignedCceo: "", cluster: "",
  });
  // Parish options (admin4, UG-AU-DS-2022) — loaded from the backend for the
  // chosen district + sub-county. Empty until a sub-county the dataset covers
  // is selected.
  const [parishOptions, setParishOptions] = useState<{ value: string; label: string }[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverMsg, setServerMsg] = useState<string | null>(null);

  // CSV state
  const fileRef = useRef<HTMLInputElement>(null);
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [updateExisting, setUpdateExisting] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadSummary | null>(null);
  const parsed: SchoolCsvResult | null = useMemo(
    () => (csvText.trim() ? mapSchoolCsv(csvText, new Set(existingIds)) : null),
    [csvText, existingIds],
  );

  const districtOptions = useMemo(
    () => (form.region ? districtsInRegion(form.region as UgandaRegion).map((d) => ({ value: d, label: d })) : []),
    [form.region],
  );
  const subCountyOptions = useMemo(
    () => (form.district ? subCountiesOf(form.district).map((s) => ({ value: s.name, label: s.name })) : []),
    [form.district],
  );

  // Load backend parishes whenever the district + sub-county are both chosen.
  useEffect(() => {
    if (!form.district || !form.subCounty) { setParishOptions([]); return; }
    let cancelled = false;
    const qs = new URLSearchParams({ district: form.district, subCounty: form.subCounty });
    fetch(`/api/geography/parishes?${qs}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setParishOptions((d.parishes ?? []).map((p: { name: string }) => ({ value: p.name, label: p.name }))); })
      .catch(() => { if (!cancelled) setParishOptions([]); });
    return () => { cancelled = true; };
  }, [form.district, form.subCounty]);

  function set<K extends keyof typeof form>(k: K, v: (typeof form)[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function submitManual() {
    setServerMsg(null);
    const v = validateNewSchool(form, new Set(existingIds));
    if (!v.ok) { setErrors(v.errors); return; }
    setErrors({});
    start(async () => {
      const res = await createSchool(form);
      if (res.ok) {
        setServerMsg(`School ${res.id} added — planning-locked until its first SSA upload.`);
        setForm({ schoolId: "", schoolName: "", region: "", district: "", subCounty: "", parish: "", schoolType: "Client", enrollment: "", assignedCceo: "", cluster: "" });
        router.refresh();
        setTimeout(onClose, 900);
      } else if (res.reason === "INVALID_INPUT") {
        setErrors(res.errors);
      } else {
        setServerMsg("You don't have permission to add schools.");
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

  // Submit the RAW file to the backend (the single source of truth). The backend
  // parses, validates, and SAVES the rows in Postgres, then reports the truthful
  // breakdown — no client-side mock fallback. The preview above is informational.
  function submitCsv() {
    setServerMsg(null);
    setUploadResult(null);
    // Prefer the picked file; otherwise build one from pasted CSV text.
    const file = csvFile
      ?? (csvText.trim() ? new File([csvText], csvName ?? "schools.csv", { type: "text/csv" }) : null);
    if (!file) return;
    start(async () => {
      const res = await uploadSchoolFile(file, updateExisting);
      if (!res.ok) {
        setServerMsg(res.error);
        return;
      }
      setUploadResult(res.summary);
      // Refetch the directory + intake surfaces so the uploaded rows show live.
      router.refresh();
      if (res.summary.success) {
        setServerMsg(null);
      }
    });
  }

  const hasUploadSource = !!csvFile || csvText.trim().length > 0;
  const canSubmit = mode === "manual" ? !pending : !pending && hasUploadSource;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add schools"
      description="One or two schools? Type them. A long list? Upload the CSV. New schools are planning-locked until their first SSA."
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-[11px] muted truncate">{serverMsg}</span>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>Cancel</Button>
            {mode === "manual" ? (
              <Button variant="primary" size="sm" onClick={submitManual} disabled={!canSubmit} Icon={Plus}>
                {pending ? "Adding…" : "Add school"}
              </Button>
            ) : (
              <Button variant="primary" size="sm" onClick={submitCsv} disabled={!canSubmit} Icon={FileUp}>
                {pending ? "Uploading…" : "Upload to directory"}
              </Button>
            )}
          </div>
        </div>
      }
    >
      {/* Mode toggle */}
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
        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-3 py-2 text-[11px] leading-snug">
            <span className="font-extrabold text-[var(--color-edify-text)]">Only 4 fields are required</span> to create a school —
            School ID, School Name, District, and Partner Type. Everything else (owner, enrolment, contact, address) can be
            <span className="font-extrabold text-[var(--color-edify-text)]"> added later by IA or staff</span>.
          </div>

          {/* Required */}
          <div>
            <h4 className="text-[10.5px] font-extrabold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] mb-2">Required</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="School ID *" placeholder={ID_FORMATS.school.example} helper={ID_FORMATS.school.hint}
                value={form.schoolId} error={errors.schoolId} onChange={(e) => set("schoolId", e.target.value)} />
              <Input label="School name *" placeholder="St. Mary Primary" value={form.schoolName} error={errors.schoolName}
                onChange={(e) => set("schoolName", e.target.value)} />
              <Select label="Region *" placeholder="Select region" value={form.region} error={errors.region}
                options={REGIONS.map((r) => ({ value: r.key, label: r.label }))}
                onChange={(e) => { set("region", e.target.value); set("district", ""); set("subCounty", ""); set("parish", ""); }} />
              <Select label="District *" placeholder={form.region ? "Select district" : "Pick a region first"} value={form.district}
                error={errors.district} disabled={!form.region} options={districtOptions}
                onChange={(e) => { set("district", e.target.value); set("subCounty", ""); set("parish", ""); }} />
              <Select label="School type *" value={form.schoolType}
                options={SCHOOL_TYPES.map((t) => ({ value: t, label: t }))}
                onChange={(e) => set("schoolType", e.target.value as SchoolType)} />
            </div>
          </div>

          {/* Optional — add now or later */}
          <div>
            <h4 className="text-[10.5px] font-extrabold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] mb-2">
              Optional — add now or later
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="Enrolment" type="number" placeholder="320" value={form.enrollment} error={errors.enrollment}
                helper="Or it arrives with the first SSA upload." onChange={(e) => set("enrollment", e.target.value)} />
              <Input label="Staff Name (CCEO/PL)" placeholder="Aisha Dar" value={form.assignedCceo}
                helper="The CCEO/PL attached to the school. Unmatched names queue for Admin setup." onChange={(e) => set("assignedCceo", e.target.value)} />
              <Select label="Sub-county" placeholder={form.district ? "Select sub-county" : "Pick a district first"}
                value={form.subCounty} disabled={!form.district} options={subCountyOptions}
                onChange={(e) => { set("subCounty", e.target.value); set("parish", ""); }} />
              <Select label="Parish"
                placeholder={!form.subCounty ? "Pick a sub-county first" : parishOptions.length ? "Select parish" : "No parishes on file"}
                value={form.parish} disabled={!form.subCounty || parishOptions.length === 0} options={parishOptions}
                onChange={(e) => set("parish", e.target.value)} />
              <Input label="Cluster" placeholder="Central Cluster 3" value={form.cluster}
                onChange={(e) => set("cluster", e.target.value)} />
            </div>
            <p className="text-[10.5px] muted mt-2">
              Phone, primary contact, and shipping address are also optional — include them in the CSV when available, or leave blank.
            </p>
          </div>
        </div>
      ) : (
        <CsvUploadPanel
          fileRef={fileRef}
          csvName={csvName}
          csvText={csvText}
          parsed={parsed}
          uploadResult={uploadResult}
          updateExisting={updateExisting}
          onToggleUpdateExisting={setUpdateExisting}
          onPickFile={onPickFile}
          onPasteText={(v) => { setCsvText(v); setCsvFile(null); setUploadResult(null); }}
        />
      )}
    </Modal>
  );
}

function CsvUploadPanel({
  fileRef, csvName, csvText, parsed, uploadResult, updateExisting, onToggleUpdateExisting, onPickFile, onPasteText,
}: {
  fileRef: React.RefObject<HTMLInputElement | null>;
  csvName: string | null;
  csvText: string;
  parsed: SchoolCsvResult | null;
  uploadResult: UploadSummary | null;
  updateExisting: boolean;
  onToggleUpdateExisting: (v: boolean) => void;
  onPickFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onPasteText: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      {/* Truthful, backend-reported result (shown after upload). */}
      {uploadResult && <UploadSummaryCard summary={uploadResult} fileName={csvName} />}

      <div className="rounded-lg border border-dashed border-[var(--color-edify-divider)] p-4 text-center">
        <FileUp size={20} className="mx-auto text-[var(--color-edify-muted)]" />
        <p className="text-[12px] font-extrabold mt-1.5">Upload the School Onboarding CSV or XLSX</p>
        <p className="text-[11px] muted">
          Required columns: <span className="font-extrabold text-[var(--color-edify-text)]">School ID, School Name, District</span>.
          Partner Type, owner, enrolment, contact &amp; address are optional — leave blank if unknown. School ID must be {ID_FORMATS.school.hint}.
        </p>
        <div className="flex items-center justify-center gap-2 mt-2.5">
          <input ref={fileRef} type="file" accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden" onChange={onPickFile} />
          <Button variant="secondary" size="sm" Icon={FileUp} onClick={() => fileRef.current?.click()}>
            {csvName ? "Choose another file" : "Choose CSV / XLSX file"}
          </Button>
          <a href="/api/templates/tpl-school-onboarding/csv"
            className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
            <Download size={13} /> Template
          </a>
        </div>
        {csvName && <p className="text-[11px] muted mt-2">{csvName}</p>}
      </div>

      <label className="flex items-center gap-2 text-[11.5px] font-semibold text-[var(--color-edify-text)]">
        <input type="checkbox" checked={updateExisting} onChange={(e) => onToggleUpdateExisting(e.target.checked)} />
        Update existing schools (overwrite rows whose School ID already exists)
      </label>

      <details className="text-[11.5px]">
        <summary className="cursor-pointer font-semibold text-[var(--color-edify-muted)]">…or paste CSV rows</summary>
        <textarea
          className="mt-2 w-full h-24 rounded-lg border border-[var(--color-edify-divider)] bg-transparent p-2 text-[11.5px] font-mono"
          placeholder="Staff Name,School ID,School Name,District,Current Partner Type,Enrolment,Last Date of Enrolment"
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
            {parsed.rows.map((r) => (
              <li key={r.rowNumber} className="px-3 py-2 flex items-start gap-2.5">
                <span className={cn(
                  "inline-flex items-center justify-center h-5 w-5 rounded-md text-[10px] font-extrabold shrink-0 mt-0.5",
                  r.valid ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700",
                )}>
                  {r.valid ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-extrabold truncate">
                    {r.input.schoolName || "(no name)"} · {r.input.schoolId || "(no id)"}
                  </div>
                  <div className="text-[10.5px] muted truncate">
                    {r.input.district || "—"} · {r.input.schoolType}
                    {r.input.assignedCceo ? ` · ${r.input.assignedCceo}` : ""}
                  </div>
                  {!r.valid && (
                    <div className="text-[10.5px] text-rose-700 mt-0.5">
                      {Object.values(r.errors).join(" · ")}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── Edit / complete school details ────────────────────────────────
//
// A school is created with only the 4 required fields. Here IA/staff fill the
// optional ones (owner, enrolment, sub-county, cluster, contact, phone, address)
// any time later. Nothing here is required — Save patches only what changed.

function EditSchoolDrawer({ school, onClose }: { school: IntakeSchoolLite | null; onClose: () => void }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [form, setForm] = useState({
    assignedCceo: school?.assignedCceo ?? "",
    enrollment: school?.enrollment != null ? String(school.enrollment) : "",
    lastEnrollmentDate: school?.lastEnrollmentDate ?? "",
    subCounty: school?.subCounty ?? "",
    cluster: school?.cluster ?? "",
    primaryContact: school?.primaryContact ?? "",
    phone: school?.phone ?? "",
    shippingAddress: school?.shippingAddress ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverMsg, setServerMsg] = useState<string | null>(null);

  const district = school?.district;
  const subCountyOptions = useMemo(
    () => (district ? subCountiesOf(district).map((s) => ({ value: s.name, label: s.name })) : []),
    [district],
  );

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function submit() {
    if (!school) return;
    setServerMsg(null);
    setErrors({});
    const patch = {
      assignedCceo: form.assignedCceo.trim() || undefined,
      enrollment: form.enrollment.trim() === "" ? undefined : Number(form.enrollment),
      lastEnrollmentDate: form.lastEnrollmentDate.trim() || undefined,
      subCounty: form.subCounty.trim() || undefined,
      cluster: form.cluster.trim() || undefined,
      primaryContact: form.primaryContact.trim() || undefined,
      phone: form.phone.trim() || undefined,
      shippingAddress: form.shippingAddress.trim() || undefined,
    };
    if (patch.enrollment !== undefined && (!Number.isFinite(patch.enrollment) || patch.enrollment < 0)) {
      setErrors({ enrollment: "Enter a valid number." });
      return;
    }
    start(async () => {
      const res = await updateSchoolDetails(school.schoolId, patch);
      if (res.ok) {
        setServerMsg("Details saved.");
        router.refresh();
        setTimeout(onClose, 800);
      } else if (res.reason === "INVALID_INPUT") {
        setErrors({ [res.field ?? "enrollment"]: "Invalid value." });
      } else if (res.reason === "NOT_FOUND") {
        setServerMsg("That school no longer exists.");
      } else {
        setServerMsg("You don't have permission to edit school details.");
      }
    });
  }

  return (
    <Modal
      open={!!school}
      onClose={onClose}
      title={school ? `Edit details · ${school.schoolName}` : "Edit details"}
      description="Complete the optional fields for this school. Everything here can be filled now or later — nothing is required."
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-[11px] muted truncate">{serverMsg}</span>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending} Icon={CheckCircle2}>
              {pending ? "Saving…" : "Save details"}
            </Button>
          </div>
        </div>
      }
    >
      {school && (
        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-3 py-2 text-[11px] leading-snug">
            <span className="font-extrabold text-[var(--color-edify-text)]">{school.schoolId}</span> · {school.district}, {school.region} · {school.schoolType}
          </div>

          <div>
            <h4 className="text-[10.5px] font-extrabold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] mb-2">Ownership &amp; enrolment</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="Staff Name (CCEO/PL)" placeholder="Aisha Dar" value={form.assignedCceo}
                helper="Who this school's portfolio belongs to." onChange={(e) => set("assignedCceo", e.target.value)} />
              <Input label="Enrolment" type="number" placeholder="320" value={form.enrollment} error={errors.enrollment}
                onChange={(e) => set("enrollment", e.target.value)} />
              <div className="space-y-1">
                <label className="block text-[12px] font-semibold text-[var(--color-edify-text)]">Last date of enrolment</label>
                <GlassDatePicker value={form.lastEnrollmentDate} onChange={(iso) => set("lastEnrollmentDate", iso)} />
              </div>
            </div>
          </div>

          <div>
            <h4 className="text-[10.5px] font-extrabold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] mb-2">Location</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Select label="Sub-county" placeholder="Select sub-county" value={form.subCounty} options={subCountyOptions}
                onChange={(e) => set("subCounty", e.target.value)} />
              <Input label="Cluster" placeholder="Central Cluster 3" value={form.cluster}
                onChange={(e) => set("cluster", e.target.value)} />
            </div>
          </div>

          <div>
            <h4 className="text-[10.5px] font-extrabold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] mb-2">Contact &amp; delivery</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="Primary contact" placeholder="Head teacher name" value={form.primaryContact}
                onChange={(e) => set("primaryContact", e.target.value)} />
              <Input label="Phone" placeholder="+256 7xx xxx xxx" value={form.phone}
                onChange={(e) => set("phone", e.target.value)} />
            </div>
            <div className="mt-3">
              <Input label="School shipping address" placeholder="P.O. Box / physical address" value={form.shippingAddress}
                onChange={(e) => set("shippingAddress", e.target.value)} />
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ─── Upload SSA performance ────────────────────────────────────────

function SsaUploadDrawer({ open, onClose, schools }: { open: boolean; onClose: () => void; schools: IntakeSchoolLite[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [schoolId, setSchoolId] = useState("");
  const [ssaDate, setSsaDate] = useState("");
  const [newEnrollment, setNewEnrollment] = useState("");
  const [scores, setScores] = useState<Record<SsaInterventionArea, string>>({ ...EMPTY_SCORES });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverMsg, setServerMsg] = useState<string | null>(null);

  const derived = useMemo(() => {
    if (!ssaDate) return null;
    return { fy: deriveFyFromDate(ssaDate), quarter: deriveQuarterFromDate(ssaDate) };
  }, [ssaDate]);
  const avg = useMemo(() => ssaAverage(scores), [scores]);

  function reset() {
    setSchoolId(""); setSsaDate(""); setNewEnrollment(""); setScores({ ...EMPTY_SCORES }); setErrors({});
  }

  function submit() {
    setServerMsg(null);
    const v = validateSsaUpload({ schoolId, ssaDate, newEnrollment, scores });
    if (!v.ok) { setErrors(v.errors); return; }
    setErrors({});
    start(async () => {
      const res = await uploadSsaPerformance({ schoolId, ssaDate, newEnrollment, scores });
      if (res.ok) {
        setServerMsg(`SSA recorded — avg ${res.averageScore}/10, ${res.quarter} FY ${res.fy}. Planning unlocked.`);
        reset();
        router.refresh();
        setTimeout(onClose, 1000);
      } else if (res.reason === "INVALID_INPUT") {
        setErrors(res.errors);
      } else {
        setServerMsg("You don't have permission to upload SSA performance.");
      }
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Upload SSA performance"
      description="Score the 8 intervention areas (0–10). The fiscal year and quarter are derived from the SSA date."
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-[11px] muted truncate">{serverMsg}</span>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending} Icon={Upload}>
              {pending ? "Uploading…" : "Upload SSA"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Select label="School" placeholder="Select a school" value={schoolId} error={errors.schoolId}
          options={schools.map((s) => ({ value: s.schoolId, label: `${s.schoolName} (${s.schoolId})` }))}
          onChange={(e) => setSchoolId(e.target.value)} />
        <div className="space-y-1">
          <label className="block text-[12px] font-semibold text-[var(--color-edify-text)]">Date of SSA</label>
          <GlassDatePicker value={ssaDate} onChange={setSsaDate} />
          {errors.ssaDate && <p className="text-[11px] text-[var(--color-edify-danger)]">{errors.ssaDate}</p>}
        </div>
      </div>

      {derived && (
        <div className="mt-2 flex items-center gap-2 text-[11px]">
          <span className="inline-flex items-center px-2 py-[2px] rounded-md font-extrabold bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
            {derived.quarter} · FY {derived.fy}
          </span>
          <span className="muted">derived from the SSA date</span>
        </div>
      )}

      <div className="mt-4">
        <h3 className="text-[12px] font-extrabold tracking-tight mb-2 flex items-center justify-between">
          <span>Intervention scores (0–10)</span>
          <span className="muted font-semibold">Avg {avg}/10</span>
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SSA_INTERVENTION_AREAS.map((area) => (
            <Input key={area} label={area} type="number" min={0} max={10} step="0.1" placeholder="0–10"
              value={scores[area]} error={errors[area]}
              onChange={(e) => setScores((s) => ({ ...s, [area]: e.target.value }))} />
          ))}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Input label="Updated enrollment (optional)" type="number" placeholder="335" value={newEnrollment}
          error={errors.newEnrollment} onChange={(e) => setNewEnrollment(e.target.value)} />
      </div>
    </Modal>
  );
}
