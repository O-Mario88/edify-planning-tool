"use client";

// IA / Admin data-intake actions — Add School + Upload SSA performance.
//
// Two drawers backed by the intake server actions. Geography-driven dependent
// dropdowns (region → district → sub-county) from the geography source of
// truth. FY + quarter for an SSA upload are DERIVED from the SSA date and shown
// live so the user sees which cycle the scores land in before submitting.

import { useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, Upload, CheckCircle2, Lock, FileUp, AlertCircle, Download } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
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
import { createSchool, createSchoolsBulk, uploadSsaPerformance } from "@/lib/actions/intake-actions";
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
};

const SCHOOL_TYPES: SchoolType[] = ["Client", "Core", "Potential Core", "Other"];
const EMPTY_SCORES = Object.fromEntries(SSA_INTERVENTION_AREAS.map((a) => [a, ""])) as Record<SsaInterventionArea, string>;

export function IaIntakeActions({ schools, existingIds }: { schools: IntakeSchoolLite[]; existingIds: string[] }) {
  const [active, setActive] = useState<{ id: string; mode: "manual" | "csv" } | null>(null);
  const close = () => setActive(null);

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
            <ul className="divide-y divide-[var(--color-edify-divider)]">
              {schools.slice(0, 6).map((s) => (
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
                  {s.planningLocked ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700 whitespace-nowrap">
                      <Lock size={10} /> SSA pending
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 whitespace-nowrap">
                      <CheckCircle2 size={10} /> Planning open
                    </span>
                  )}
                </li>
              ))}
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
    </>
  );
}

// ─── Add School ────────────────────────────────────────────────────

function NewSchoolDrawer({ open, onClose, existingIds, initialMode = "manual" }: { open: boolean; onClose: () => void; existingIds: string[]; initialMode?: "manual" | "csv" }) {
  const router = useRouter();
  const [mode, setMode] = useState<"manual" | "csv">(initialMode);
  const [pending, start] = useTransition();

  // Manual form state
  const [form, setForm] = useState({
    schoolId: "", schoolName: "", region: "", district: "", subCounty: "",
    schoolType: "Client" as SchoolType, enrollment: "", assignedCceo: "", cluster: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverMsg, setServerMsg] = useState<string | null>(null);

  // CSV state
  const fileRef = useRef<HTMLInputElement>(null);
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState<string | null>(null);
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
        setForm({ schoolId: "", schoolName: "", region: "", district: "", subCounty: "", schoolType: "Client", enrollment: "", assignedCceo: "", cluster: "" });
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
    f.text().then(setCsvText);
  }

  function submitCsv() {
    if (!parsed || parsed.validCount === 0) return;
    setServerMsg(null);
    const valid = parsed.rows.filter((r) => r.valid).map((r) => r.input);
    start(async () => {
      const res = await createSchoolsBulk(valid);
      if (res.ok) {
        setServerMsg(`Imported ${res.created} school${res.created === 1 ? "" : "s"}${res.failed.length ? `, ${res.failed.length} skipped` : ""}.`);
        setCsvText(""); setCsvName(null);
        if (fileRef.current) fileRef.current.value = "";
        router.refresh();
        setTimeout(onClose, 1200);
      } else {
        setServerMsg("You don't have permission to add schools.");
      }
    });
  }

  const canSubmit = mode === "manual" ? !pending : !pending && (parsed?.validCount ?? 0) > 0;

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
                {pending ? "Importing…" : `Import ${parsed?.validCount ?? 0} school${(parsed?.validCount ?? 0) === 1 ? "" : "s"}`}
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Input label="School ID" placeholder={ID_FORMATS.school.example} helper={ID_FORMATS.school.hint}
            value={form.schoolId} error={errors.schoolId} onChange={(e) => set("schoolId", e.target.value)} />
          <Input label="School name" placeholder="St. Mary Primary" value={form.schoolName} error={errors.schoolName}
            onChange={(e) => set("schoolName", e.target.value)} />
          <Select label="Region" placeholder="Select region" value={form.region} error={errors.region}
            options={REGIONS.map((r) => ({ value: r.key, label: r.label }))}
            onChange={(e) => { set("region", e.target.value); set("district", ""); set("subCounty", ""); }} />
          <Select label="District" placeholder={form.region ? "Select district" : "Pick a region first"} value={form.district}
            error={errors.district} disabled={!form.region} options={districtOptions}
            onChange={(e) => { set("district", e.target.value); set("subCounty", ""); }} />
          <Select label="Sub-county (optional)" placeholder={form.district ? "Select sub-county" : "Pick a district first"}
            value={form.subCounty} disabled={!form.district} options={subCountyOptions}
            onChange={(e) => set("subCounty", e.target.value)} />
          <Select label="School type" value={form.schoolType}
            options={SCHOOL_TYPES.map((t) => ({ value: t, label: t }))}
            onChange={(e) => set("schoolType", e.target.value as SchoolType)} />
          <Input label="Enrollment (optional)" type="number" placeholder="320" value={form.enrollment} error={errors.enrollment}
            onChange={(e) => set("enrollment", e.target.value)} />
          <Input label="Assigned CCEO (optional)" placeholder="Aisha Dar" value={form.assignedCceo}
            onChange={(e) => set("assignedCceo", e.target.value)} />
          <Input label="Cluster (optional)" placeholder="Central Cluster 3" value={form.cluster}
            onChange={(e) => set("cluster", e.target.value)} />
        </div>
      ) : (
        <CsvUploadPanel
          fileRef={fileRef}
          csvName={csvName}
          csvText={csvText}
          parsed={parsed}
          onPickFile={onPickFile}
          onPasteText={setCsvText}
        />
      )}
    </Modal>
  );
}

function CsvUploadPanel({
  fileRef, csvName, csvText, parsed, onPickFile, onPasteText,
}: {
  fileRef: React.RefObject<HTMLInputElement | null>;
  csvName: string | null;
  csvText: string;
  parsed: SchoolCsvResult | null;
  onPickFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onPasteText: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-dashed border-[var(--color-edify-divider)] p-4 text-center">
        <FileUp size={20} className="mx-auto text-[var(--color-edify-muted)]" />
        <p className="text-[12px] font-extrabold mt-1.5">Upload the School Onboarding CSV</p>
        <p className="text-[11px] muted">Use the template headers. School ID must be {ID_FORMATS.school.hint}.</p>
        <div className="flex items-center justify-center gap-2 mt-2.5">
          <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onPickFile} />
          <Button variant="secondary" size="sm" Icon={FileUp} onClick={() => fileRef.current?.click()}>
            {csvName ? "Choose another file" : "Choose CSV file"}
          </Button>
          <a href="/api/templates/tpl-school-onboarding/csv"
            className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
            <Download size={13} /> Template
          </a>
        </div>
        {csvName && <p className="text-[11px] muted mt-2">{csvName}</p>}
      </div>

      <details className="text-[11.5px]">
        <summary className="cursor-pointer font-semibold text-[var(--color-edify-muted)]">…or paste CSV rows</summary>
        <textarea
          className="mt-2 w-full h-24 rounded-lg border border-[var(--color-edify-divider)] bg-transparent p-2 text-[11.5px] font-mono"
          placeholder="Account Owner,School ID,School Name,District,Current Partner Type,Enrolment,Last Date of Enrolment"
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
        <Input label="Date of SSA" type="date" value={ssaDate} error={errors.ssaDate}
          onChange={(e) => setSsaDate(e.target.value)} />
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
