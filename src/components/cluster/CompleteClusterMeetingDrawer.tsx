"use client";

// Complete Cluster Meeting — the completion gate. A meeting isn't complete
// until attendance + evidence + typed minutes + resolutions + a valid TS- id
// are captured, and (for early meetings) the next meeting date is confirmed,
// which auto-schedules the next meeting. Submitting moves it to Awaiting IA.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Check, AlertTriangle, Upload, ShieldCheck } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/utils";
import { completeClusterMeetingAction } from "@/lib/actions/cluster-actions";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";

export type CompleteMeetingTarget = {
  id: string;
  label: string;
  date: string;
  organizer: "partner" | "edify";
  clusterName: string;
  district: string;
  subCounty?: string;
  nextRequired: boolean;
};

const TS_RE = /^TS-\d{3,}$/i;

export function CompleteClusterMeetingDrawer({
  open, target, onClose,
}: {
  open: boolean;
  target: CompleteMeetingTarget | null;
  onClose: (completed?: boolean, nextDate?: string) => void;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [ts, setTs] = useState("");
  const [teachers, setTeachers] = useState("");
  const [leaders, setLeaders] = useState("");
  const [other, setOther] = useState("");
  const [attendanceFile, setAttendanceFile] = useState("");
  const [minutes, setMinutes] = useState("");
  const [minutesFile, setMinutesFile] = useState("");
  const [resolutions, setResolutions] = useState("");
  const [resolutionsFile, setResolutionsFile] = useState("");
  const [nextDate, setNextDate] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!target) return null;

  const total = (Number(teachers) || 0) + (Number(leaders) || 0) + (Number(other) || 0);
  const tsValid = TS_RE.test(ts.trim());
  const canSubmit =
    tsValid && total > 0 && !!attendanceFile && !!minutes.trim() &&
    (!!resolutions.trim() || !!resolutionsFile) &&
    (!target.nextRequired || !!nextDate);

  function submit() {
    setError(null);
    if (!canSubmit) { setError("Complete all required fields."); return; }
    start(async () => {
      const res = await completeClusterMeetingAction(target!.id, {
        salesforceTrainingId: ts.trim(),
        teachersCount: Number(teachers) || 0,
        schoolLeadersCount: Number(leaders) || 0,
        otherCount: Number(other) || 0,
        attendanceFileName: attendanceFile,
        minutesText: minutes.trim(),
        minutesFileName: minutesFile || undefined,
        resolutionsText: resolutions.trim() || undefined,
        resolutionsFileName: resolutionsFile || undefined,
        nextMeetingDate: nextDate || undefined,
        notes: notes.trim() || undefined,
      });
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "Not permitted for your role." : res.reason === "FAILED" ? res.message : "Failed.");
        return;
      }
      router.refresh();
      onClose(true, res.nextScheduled);
    });
  }

  return (
    <Modal
      open={open}
      onClose={() => onClose(false)}
      title="Complete Cluster Meeting"
      description="Prove attendance, document minutes, capture resolutions, enter the Salesforce training id, and confirm the next meeting. Then it goes to IA for confirmation."
      size="lg"
      variant="sheet"
      footer={
        <div className="flex items-center justify-between gap-2 w-full">
          <span className="text-[11px] muted">Total attended: <span className="font-extrabold tabular text-[var(--color-edify-text)]">{total}</span></span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => onClose(false)} className="h-9 px-3 rounded-lg text-[12px] font-semibold text-[var(--color-edify-muted)]">Cancel</button>
            <button type="button" onClick={submit} disabled={pending || !canSubmit}
              className={cn("inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg text-[12px] font-extrabold",
                pending || !canSubmit ? "bg-slate-200 text-slate-400 cursor-not-allowed" : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]")}>
              <Check size={13} /> {pending ? "Submitting…" : "Complete & send to IA"}
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Summary */}
        <div className="rounded-lg border border-[var(--color-edify-border)] p-3 text-[11.5px]">
          <div className="flex items-center gap-2 flex-wrap">
            <CalendarDays size={13} className="text-[var(--color-edify-primary)]" />
            <span className="font-extrabold text-[12.5px]">{target.label}</span>
            <span className="muted">{target.date}</span>
            <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", target.organizer === "partner" ? "bg-violet-50 text-violet-700" : "bg-sky-50 text-sky-700")}>{target.organizer === "partner" ? "Partner-managed" : "Edify staff"}</span>
          </div>
          <div className="muted mt-1">{target.clusterName} · {target.district}{target.subCounty ? ` · ${target.subCounty}` : ""}</div>
        </div>

        {/* Salesforce training id */}
        <Field label="Salesforce Training ID" required hint="Cluster meetings are entered in Salesforce as trainings. IDs must start with TS-, e.g. TS-01234.">
          <input value={ts} onChange={(e) => setTs(e.target.value)} placeholder="Enter the SF ID here"
            className={cn(inp, ts && !tsValid && "border-rose-400")} />
          {ts && !tsValid && <p className="text-[10.5px] text-rose-600 mt-1">Must start with TS-, for example TS-01234.</p>}
        </Field>

        {/* Attendance */}
        <Field label="Actual attendance" required>
          <div className="grid grid-cols-3 gap-2">
            <NumIn value={teachers} onChange={setTeachers} placeholder="Teachers" />
            <NumIn value={leaders} onChange={setLeaders} placeholder="School leaders" />
            <NumIn value={other} onChange={setOther} placeholder="Other" />
          </div>
          <p className="text-[11px] muted mt-1">Total attended (auto): <span className="font-extrabold tabular">{total}</span></p>
        </Field>

        {/* Attendance evidence */}
        <FileField label="Attendance form (evidence)" required value={attendanceFile} onPick={setAttendanceFile} />

        {/* Minutes — typed (5000) + optional upload */}
        <Field label="Meeting minutes" required hint="Type the minutes (up to 5000 characters). You can also attach a scan/PDF.">
          <textarea value={minutes} onChange={(e) => setMinutes(e.target.value.slice(0, 5000))} rows={5} maxLength={5000}
            placeholder="Type the meeting minutes…"
            className={cn(inp, "resize-y leading-snug")} />
          <div className="flex items-center justify-between mt-1">
            <span className="text-[10.5px] muted tabular">{minutes.length}/5000</span>
          </div>
          <div className="mt-1"><FilePicker label="Attach minutes (optional)" value={minutesFile} onPick={setMinutesFile} /></div>
        </Field>

        {/* Resolutions — text or upload */}
        <Field label="Meeting resolutions" required hint="Capture resolutions as text or attach a document (at least one).">
          <textarea value={resolutions} onChange={(e) => setResolutions(e.target.value)} rows={3}
            placeholder="One resolution per line (responsible person, due date…)"
            className={cn(inp, "resize-y leading-snug")} />
          <div className="mt-1"><FilePicker label="Attach resolutions (optional)" value={resolutionsFile} onPick={setResolutionsFile} /></div>
        </Field>

        {/* Next meeting */}
        <Field label="Next meeting date" required={target.nextRequired}
          hint={target.nextRequired ? "Confirming this auto-schedules the next cluster meeting." : "Optional for this meeting — set it to schedule a follow-up."}>
          <GlassDatePicker value={nextDate} onChange={setNextDate} />
        </Field>

        {/* Notes */}
        <Field label="Notes (optional)">
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Anything worth flagging…" className={inp} />
        </Field>

        <p className="text-[11px] muted inline-flex items-start gap-1.5">
          <ShieldCheck size={12} className="mt-0.5 shrink-0 text-[var(--color-edify-primary)]" />
          On submit this goes to IA for Salesforce confirmation. {target.organizer === "partner" ? "After IA confirms, the accountant can clear partner payment." : "After IA confirms, accountability is recorded."}
        </p>

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {error}
          </div>
        )}
      </div>
    </Modal>
  );
}

const inp = "w-full h-9 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30";

function Field({ label, required, hint, children }: { label: string; required?: boolean; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-[12px] font-semibold text-[var(--color-edify-text)]">{label}{required && <span className="text-rose-500"> *</span>}</label>
      {hint && <p className="text-[10.5px] muted -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}

function NumIn({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return <input value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} placeholder={placeholder} className={cn(inp, "h-9 text-center")} />;
}

function FileField({ label, required, value, onPick }: { label: string; required?: boolean; value: string; onPick: (name: string) => void }) {
  return (
    <Field label={label} required={required}>
      <FilePicker label="Choose file" value={value} onPick={onPick} />
    </Field>
  );
}

function FilePicker({ label, value, onPick }: { label: string; value: string; onPick: (name: string) => void }) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer">
      <span className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
        <Upload size={12} className="text-[var(--color-edify-primary)]" /> {label}
      </span>
      {value && <span className="text-[11px] muted truncate max-w-[180px]">{value}</span>}
      <input type="file" className="hidden" onChange={(e) => onPick(e.target.files?.[0]?.name ?? "")} />
    </label>
  );
}
