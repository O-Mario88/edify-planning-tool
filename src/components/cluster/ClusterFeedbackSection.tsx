"use client";

// Cluster feedback — partner / staff / IA notes on how the cluster's activities
// are going. Shown on the cluster profile; anyone with cluster access can add.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { MessageSquare, Plus, Check, ThumbsUp, AlertTriangle, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { addClusterFeedbackAction } from "@/lib/actions/cluster-actions";

export type ClusterFeedbackVM = {
  id: string;
  label: string; // "Partner feedback" / "Staff feedback" / "IA verification feedback"
  by: string;
  date: string;
  whatWentWell?: string;
  challenges?: string;
  recommendations?: string;
  rating?: number;
};

export function ClusterFeedbackSection({ clusterId, feedback }: { clusterId: string; feedback: ClusterFeedbackVM[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [open, setOpen] = useState(false);
  const [well, setWell] = useState("");
  const [challenges, setChallenges] = useState("");
  const [recs, setRecs] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    if (!well.trim() && !challenges.trim() && !recs.trim()) { setError("Add at least one note."); return; }
    start(async () => {
      const res = await addClusterFeedbackAction(clusterId, {
        whatWentWell: well.trim() || undefined,
        challenges: challenges.trim() || undefined,
        recommendations: recs.trim() || undefined,
      });
      if (!res.ok) { setError(res.reason === "FORBIDDEN" ? "Not permitted for your role." : (res.reason === "FAILED" ? res.message ?? "Failed." : "Failed.")); return; }
      setOpen(false); setWell(""); setChallenges(""); setRecs("");
      router.refresh();
    });
  }

  return (
    <section className="card rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h2 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <MessageSquare size={14} className="text-[var(--color-edify-primary)]" /> Feedback
        </h2>
        {!open && (
          <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
            <Plus size={12} /> Add
          </button>
        )}
      </div>

      {open && (
        <div className="space-y-2 mb-3 rounded-lg border border-[var(--color-edify-border)] p-2.5">
          <Ta value={well} onChange={setWell} placeholder="What went well" />
          <Ta value={challenges} onChange={setChallenges} placeholder="Challenges" />
          <Ta value={recs} onChange={setRecs} placeholder="Recommendations" />
          <div className="flex items-center gap-2">
            <button type="button" disabled={pending} onClick={submit}
              className={cn("inline-flex items-center gap-1 h-8 px-2.5 rounded-md text-[11.5px] font-semibold text-white", pending ? "bg-slate-300" : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]")}>
              <Check size={12} /> Submit
            </button>
            <button type="button" onClick={() => { setOpen(false); setError(null); }} className="text-[11px] muted">Cancel</button>
            {error && <span className="text-[10.5px] text-rose-600">{error}</span>}
          </div>
        </div>
      )}

      {feedback.length === 0 ? (
        <p className="text-[12px] muted">No feedback yet.</p>
      ) : (
        <ul className="space-y-2">
          {feedback.map((f) => (
            <li key={f.id} className="rounded-lg border border-[var(--color-edify-divider)] p-2.5 text-[11.5px]">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-extrabold text-[12px]">{f.label}</span>
                <span className="muted">{f.by} · {f.date.slice(0, 10)}</span>
              </div>
              {f.whatWentWell && <p className="mt-1 inline-flex items-start gap-1"><ThumbsUp size={10} className="mt-0.5 text-emerald-600 shrink-0" /> {f.whatWentWell}</p>}
              {f.challenges && <p className="mt-0.5 inline-flex items-start gap-1"><AlertTriangle size={10} className="mt-0.5 text-amber-600 shrink-0" /> {f.challenges}</p>}
              {f.recommendations && <p className="mt-0.5 inline-flex items-start gap-1"><ArrowRight size={10} className="mt-0.5 text-[var(--color-edify-primary)] shrink-0" /> {f.recommendations}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Ta({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={2} placeholder={placeholder}
      className="w-full px-2 py-1.5 rounded-md border border-[var(--color-edify-border)] bg-[var(--surface-1,#fff)] text-[11.5px] resize-y" />
  );
}
