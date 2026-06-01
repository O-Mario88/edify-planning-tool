"use client";

// IA / Admin data-intake actions — Add School + Upload SSA performance.
//
// Two drawers backed by the intake server actions. Geography-driven dependent
// dropdowns (region → district → sub-county) from the geography source of
// truth. FY + quarter for an SSA upload are DERIVED from the SSA date and shown
// live so the user sees which cycle the scores land in before submitting.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, Upload, CheckCircle2, Lock } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
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
import { createSchool, uploadSsaPerformance } from "@/lib/actions/intake-actions";

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
  const [open, setOpen] = useState<"school" | "ssa" | null>(null);
  return (
    <>
      <section className="card p-3.5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h2 className="text-body-lg font-extrabold tracking-tight">Data intake actions</h2>
            <p className="text-[11.5px] muted">
              Add a new school to the planning engine, or upload an SSA performance assessment. A new school is
              planning-locked until its first SSA is uploaded.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="secondary" size="sm" Icon={Upload} onClick={() => setOpen("ssa")}>
              Upload SSA performance
            </Button>
            <Button variant="primary" size="sm" Icon={Plus} onClick={() => setOpen("school")}>
              Add school
            </Button>
          </div>
        </div>

        {schools.length > 0 && (
          <ul className="divide-y divide-[var(--color-edify-divider)] mt-3">
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
        )}
      </section>

      <NewSchoolDrawer open={open === "school"} onClose={() => setOpen(null)} existingIds={existingIds} />
      <SsaUploadDrawer open={open === "ssa"} onClose={() => setOpen(null)} schools={schools} />
    </>
  );
}

// ─── Add School ────────────────────────────────────────────────────

function NewSchoolDrawer({ open, onClose, existingIds }: { open: boolean; onClose: () => void; existingIds: string[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [form, setForm] = useState({
    schoolId: "", schoolName: "", region: "", district: "", subCounty: "",
    schoolType: "Client" as SchoolType, enrollment: "", assignedCceo: "", cluster: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverMsg, setServerMsg] = useState<string | null>(null);

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

  function submit() {
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

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add a school"
      description="New schools enter the planning engine active but planning-locked until their first SSA is uploaded."
      variant="drawer-right"
      size="md"
      footer={
        <div className="flex items-center justify-between gap-3 w-full">
          <span className="text-[11px] muted truncate">{serverMsg}</span>
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending} Icon={Plus}>
              {pending ? "Adding…" : "Add school"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Input label="School ID" placeholder="SCH-IA-2003" value={form.schoolId} error={errors.schoolId}
          onChange={(e) => set("schoolId", e.target.value)} />
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
