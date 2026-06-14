"use client";

import { useCallback, useMemo, useState } from "react";
import { RefreshCw, FileText, ChevronRight, X, ShieldCheck, AlertTriangle } from "lucide-react";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { csrfHeaders } from "@/lib/csrf-client";
import type { BeLeadershipBoards, BeLeadershipSnapshot, BeDecisionInsight, BeDecisionBoard } from "@/lib/api/surfaces";
import {
  DECISION_TYPE_LABEL, DECISION_TYPE_BLURB, riskToPill, confidenceToPill, confidenceLabel,
  statusLabel, statusToPill, toneDot, REVIEW_STATUSES,
} from "@/lib/decisions/leadership-format";

type Props = { snapshot: BeLeadershipSnapshot | null; initialBoards: BeLeadershipBoards; canRecompute: boolean };

const DATA_TAB = "__confidence__";

export function DecisionEngineClient({ snapshot, initialBoards, canRecompute }: Props) {
  const [boards, setBoards] = useState<BeDecisionBoard[]>(initialBoards.boards);
  const [snap, setSnap] = useState(snapshot);
  const [active, setActive] = useState<string>(initialBoards.boards[0]?.decisionType ?? DATA_TAB);
  const [risk, setRisk] = useState<string>("");
  const [conf, setConf] = useState<string>("");
  const [selected, setSelected] = useState<BeDecisionInsight | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const allInsights = useMemo(() => boards.flatMap((b) => b.insights), [boards]);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const [b, s] = await Promise.all([
        fetch(`/api/leadership/decision-engine`).then((r) => r.json()),
        fetch(`/api/leadership/decision-engine/snapshot`).then((r) => r.json()),
      ]);
      if (b?.boards) setBoards(b.boards);
      if (s?.fy) setSnap(s);
    } finally {
      setBusy(false);
    }
  }, []);

  const recompute = useCallback(async () => {
    setBusy(true);
    setToast("Recomputing leadership insights from current data…");
    try {
      await fetch(`/api/leadership/decision-engine/recompute`, { method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() }, body: "{}" });
      await refresh();
      setToast("Insights refreshed.");
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 2500);
    }
  }, [refresh]);

  const activeBoard = boards.find((b) => b.decisionType === active);
  const visibleInsights = (activeBoard?.insights ?? []).filter(
    (i) => (!risk || i.riskLevel === risk) && (!conf || i.confidenceLevel === conf),
  );

  return (
    <div className="space-y-5">
      {snap && <StrategicHero snap={snap} />}
      {snap && <SnapshotStrip snap={snap} />}

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-200 pb-2 dark:border-slate-800">
        {boards.map((b) => (
          <TabButton key={b.decisionType} active={active === b.decisionType} onClick={() => setActive(b.decisionType)}
            label={DECISION_TYPE_LABEL[b.decisionType] ?? b.decisionType} count={b.insights.length} />
        ))}
        <TabButton active={active === DATA_TAB} onClick={() => setActive(DATA_TAB)} label="Data Confidence" />
        <div className="ml-auto flex items-center gap-2">
          {canRecompute && (
            <Button size="sm" variant="secondary" onClick={recompute} disabled={busy}>
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> Recompute
            </Button>
          )}
        </div>
      </div>

      {active === DATA_TAB ? (
        <DataConfidenceTab insights={allInsights} onOpen={setSelected} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="muted">{DECISION_TYPE_BLURB[active]}</span>
            <span className="ml-auto" />
            <FilterSelect label="Risk" value={risk} onChange={setRisk} options={[["", "All risk"], ["critical", "Critical"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]]} />
            <FilterSelect label="Confidence" value={conf} onChange={setConf} options={[["", "All confidence"], ["high", "High"], ["medium", "Medium"], ["low", "Low"], ["insufficient", "Insufficient"]]} />
          </div>
          {visibleInsights.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {visibleInsights.map((i) => <DecisionCard key={i.id} insight={i} onOpen={() => setSelected(i)} />)}
            </div>
          )}
        </>
      )}

      {selected && (
        <DetailDrawer
          insight={selected}
          canReview={activeBoard?.canReview ?? false}
          onClose={() => setSelected(null)}
          onChanged={async () => { await refresh(); setSelected(null); }}
        />
      )}

      {toast && (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-xs font-medium text-white shadow-lg dark:bg-slate-100 dark:text-slate-900">
          {toast}
        </div>
      )}
    </div>
  );
}

function StrategicHero({ snap }: { snap: BeLeadershipSnapshot }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5 dark:border-slate-800 dark:from-slate-900/60 dark:to-slate-900/20">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide muted">
        <ShieldCheck className="h-3.5 w-3.5" /> Strategic Recommendation · FY {snap.fy}
      </div>
      <p className="mt-1.5 text-lg font-semibold leading-snug text-[var(--text-primary)]">{snap.strategicHeadline}</p>
      <p className="mt-1 text-xs muted">The engine recommends; leadership decides. No action is executed automatically.</p>
    </div>
  );
}

function SnapshotStrip({ snap }: { snap: BeLeadershipSnapshot }) {
  const cells: MetricCell[] = [
    { key: "expand", label: "Regions ready to expand", value: snap.regionsReadyToExpand.length, tone: "good" },
    { key: "pause", label: "Areas to pause recruitment", value: snap.regionsToPauseRecruitment.length, tone: snap.regionsToPauseRecruitment.length ? "alert" : "default" },
    { key: "staff", label: "Staff overload risks", value: snap.staffOverloadRisks, tone: snap.staffOverloadRisks ? "alert" : "default" },
    { key: "mou", label: "Partner MOU risks", value: snap.partnerMouRisks, tone: snap.partnerMouRisks ? "alert" : "default" },
    { key: "gap", label: "Partner capacity gaps", value: snap.partnerCapacityGaps, tone: snap.partnerCapacityGaps ? "alert" : "default" },
    { key: "conf", label: "Data confidence", value: snap.dataConfidence, unit: "/100", tone: snap.dataConfidence >= 80 ? "good" : snap.dataConfidence >= 60 ? "default" : "alert" },
  ];
  return <MetricStrip metrics={cells} />;
}

function TabButton({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return (
    <button onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${active ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
      {label}{typeof count === "number" && <span className={`ml-1.5 ${active ? "opacity-70" : "muted"}`}>{count}</span>}
    </button>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="flex items-center gap-1 text-[11px] muted">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-200 bg-transparent px-2 py-1 text-[11px] text-[var(--text-primary)] dark:border-slate-700">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function DecisionCard({ insight, onOpen }: { insight: BeDecisionInsight; onOpen: () => void }) {
  return (
    <button onClick={onOpen}
      className="group flex w-full flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 text-left transition hover:border-slate-300 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {insight.scopeName && <div className="truncate text-[11px] font-medium uppercase tracking-wide muted">{insight.scopeName}</div>}
          <div className="mt-0.5 font-semibold leading-snug text-[var(--text-primary)]">{insight.recommendation}</div>
        </div>
        <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 muted transition group-hover:translate-x-0.5" />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Pill tone={riskToPill(insight.riskLevel)} size="xs">{insight.riskLevel} risk</Pill>
        <Pill tone={confidenceToPill(insight.confidenceLevel)} size="xs">{confidenceLabel(insight.confidenceLevel, insight.confidenceScore)}</Pill>
        {insight.status !== "new" && <Pill tone={statusToPill(insight.status)} size="xs">{statusLabel(insight.status)}</Pill>}
      </div>
      <p className="line-clamp-2 text-xs muted">{insight.reason}</p>
      <div className="mt-0.5 flex flex-wrap gap-1.5">
        {insight.evidencePoints.slice(0, 3).map((e) => (
          <span key={e.id} className="inline-flex items-center gap-1 rounded-md bg-slate-50 px-1.5 py-0.5 text-[10px] muted dark:bg-slate-800/60">
            <span className={`h-1.5 w-1.5 rounded-full ${toneDot(e.tone)}`} />{e.metricName}: <span className="font-medium text-[var(--text-primary)]">{e.metricValue}</span>
          </span>
        ))}
      </div>
    </button>
  );
}

function DataConfidenceTab({ insights, onOpen }: { insights: BeDecisionInsight[]; onOpen: (i: BeDecisionInsight) => void }) {
  const by = (l: string) => insights.filter((i) => i.confidenceLevel === l);
  const cells: MetricCell[] = [
    { key: "h", label: "High confidence", value: by("high").length, tone: "good" },
    { key: "m", label: "Medium confidence", value: by("medium").length },
    { key: "l", label: "Low confidence", value: by("low").length, tone: "alert" },
    { key: "i", label: "Insufficient data", value: by("insufficient").length, tone: "alert" },
  ];
  const weak = insights.filter((i) => i.confidenceLevel === "insufficient" || i.confidenceLevel === "low");
  return (
    <div className="space-y-4">
      <MetricStrip metrics={cells} />
      <p className="text-xs muted">Recommendations are only as strong as their data. The engine will not make a strong call on weak data — these need data completion first.</p>
      {weak.length === 0 ? <EmptyState label="All current insights meet the medium+ confidence bar." /> : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{weak.map((i) => <DecisionCard key={i.id} insight={i} onOpen={() => onOpen(i)} />)}</div>
      )}
    </div>
  );
}

function EmptyState({ label }: { label?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm muted dark:border-slate-800">
      {label ?? "No decisions match these filters for this period."}
    </div>
  );
}

function DetailDrawer({ insight, canReview, onClose, onChanged }: { insight: BeDecisionInsight; canReview: boolean; onClose: () => void; onChanged: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const act = useCallback(async (status: string) => {
    setBusy(true);
    try {
      await fetch(`/api/leadership/decision-engine/insight/${insight.id}/review`, {
        method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ status, note: note || undefined }),
      });
      onChanged();
    } finally { setBusy(false); }
  }, [insight.id, note, onChanged]);

  const addNote = useCallback(async () => {
    if (!note.trim()) return;
    setBusy(true);
    try {
      await fetch(`/api/leadership/decision-engine/insight/${insight.id}/note`, {
        method: "POST", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ note }),
      });
      setNote("");
      onChanged();
    } finally { setBusy(false); }
  }, [insight.id, note, onChanged]);

  const exportMemo = useCallback(async () => {
    const memo = await fetch(`/api/leadership/decision-engine/insight/${insight.id}/memo`).then((r) => r.json());
    const blob = new Blob([JSON.stringify(memo, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `decision-memo-${insight.id}.json`; a.click();
    URL.revokeObjectURL(url);
  }, [insight.id]);

  const m = insight.metrics ?? {};
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-2xl dark:bg-slate-950" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            {insight.scopeName && <div className="text-[11px] font-medium uppercase tracking-wide muted">{insight.scopeName}</div>}
            <h2 className="text-base font-semibold text-[var(--text-primary)]">{insight.recommendation}</h2>
          </div>
          <button onClick={onClose} className="rounded-md p-1 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="h-4 w-4" /></button>
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5">
          <Pill tone={riskToPill(insight.riskLevel)} size="sm">{insight.riskLevel} risk</Pill>
          <Pill tone={confidenceToPill(insight.confidenceLevel)} size="sm">{confidenceLabel(insight.confidenceLevel, insight.confidenceScore)}</Pill>
          <Pill tone={statusToPill(insight.status)} size="sm">{statusLabel(insight.status)}</Pill>
        </div>

        <Section title="Why">
          <p className="text-sm text-[var(--text-primary)]">{insight.reason}</p>
        </Section>

        {insight.contextAdjustment && (
          <Section title="Context / Fairness adjustment">
            <p className="rounded-lg bg-amber-50 p-2.5 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{insight.contextAdjustment}</p>
          </Section>
        )}

        <Section title="Evidence">
          <ul className="space-y-1.5">
            {insight.evidencePoints.map((e) => (
              <li key={e.id} className="flex items-start gap-2 text-sm">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${toneDot(e.tone)}`} />
                <span><span className="muted">{e.metricName}:</span> <span className="font-medium text-[var(--text-primary)]">{e.metricValue}</span>
                  {e.comparisonValue && <span className="muted"> (of {e.comparisonValue})</span>}
                  {e.explanation && <span className="block text-xs muted">{e.explanation}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Section>

        {Object.keys(m).length > 0 && (
          <Section title="Metrics">
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(m).map(([k, v]) => (
                <div key={k} className="rounded-lg border border-slate-200 px-2 py-1.5 dark:border-slate-800">
                  <div className="muted">{labelize(k)}</div><div className="font-medium text-[var(--text-primary)]">{fmtMetric(v)}</div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {insight.financialImplication && (
          <Section title="Financial implication"><p className="text-sm text-[var(--text-primary)]">{insight.financialImplication}</p></Section>
        )}

        <Section title="Decision options">
          <div className="flex flex-wrap gap-1.5">
            {insight.alternatives.map((a) => <span key={a} className="rounded-md border border-slate-200 px-2 py-0.5 text-xs muted dark:border-slate-700">{a}</span>)}
          </div>
        </Section>

        <Section title="Recommended next leadership action">
          <p className="rounded-lg bg-slate-50 p-2.5 text-sm text-[var(--text-primary)] dark:bg-slate-800/50">{insight.suggestedAction}</p>
        </Section>

        {/* Human review */}
        <Section title={canReview ? "Human review" : "Leadership note"}>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Add a leadership note or review reason…"
            className="w-full rounded-lg border border-slate-200 bg-transparent p-2 text-sm text-[var(--text-primary)] dark:border-slate-700" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {canReview ? REVIEW_STATUSES.map((s) => (
              <Button key={s.value} size="sm" variant={s.value === "rejected" ? "danger" : "secondary"} disabled={busy} onClick={() => act(s.value)}>{s.label}</Button>
            )) : (
              <Button size="sm" variant="secondary" disabled={busy} onClick={addNote}>Add note</Button>
            )}
          </div>
          {!canReview && (
            <p className="mt-1.5 flex items-center gap-1 text-[11px] muted"><AlertTriangle className="h-3 w-3" /> Your role can view + note, but not decide on this board.</p>
          )}
        </Section>

        <div className="mt-4 flex items-center justify-between border-t border-slate-200 pt-3 dark:border-slate-800">
          <Button size="sm" variant="ghost" onClick={exportMemo}><FileText className="h-3.5 w-3.5" /> Export decision memo</Button>
          <span className="text-[11px] muted">Engine recommendation — human decision required.</span>
        </div>
      </div>
    </div>
  );
}

function fmtMetric(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  return String(v);
}
function labelize(k: string): string {
  return k.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase()).trim();
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide muted">{title}</h3>
      {children}
    </div>
  );
}
