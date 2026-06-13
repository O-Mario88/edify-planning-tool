"use client";

// System Health — Mock Data Status (spec §18). Surfaces the live mock-leakage
// scan + production-safety flags so leakage is measurable and tracked toward 0.

import { useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert, Database, FileWarning, CheckCircle2, XCircle } from "lucide-react";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";

type Resp = {
  report: {
    scannedAt: string;
    totals: { sourceFiles: number; mockLibFiles: number; filesImportingMock: number; pageRoutesWithMock: number; componentsWithMock: number };
    topDomains: { domain: string; count: number }[];
    pagesWithMock: { page: string; mocks: string[] }[];
  };
  policy: { mockAllowed: boolean; backendOn: boolean; productionSafe: boolean; nodeEnv: string };
};

export function MockLeakageCard() {
  const [data, setData] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/system-health/mock-audit", { credentials: "include" });
        if (!r.ok) { setErr(r.status === 403 ? "Admin only" : "Could not load"); return; }
        setData(await r.json());
      } catch { setErr("Could not reach the scanner"); }
    })();
  }, []);

  if (err) return <section className="card p-3.5"><p className="text-[12px] muted">Mock-data status: {err}</p></section>;
  if (!data) return <section className="card p-3.5"><p className="text-[12px] muted">Scanning frontend for mock leakage…</p></section>;

  const t = data.report.totals;
  const p = data.policy;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Database size={14} /> Mock-data status</h2>
        <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold border",
          p.productionSafe ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200")}>
          {p.productionSafe ? <ShieldCheck size={11} /> : <ShieldAlert size={11} />} {p.productionSafe ? "Production safe" : "Migration in progress"}
        </span>
      </header>

      <div className="mb-3">
        <MetricStrip
          bare
          columns="grid-cols-2 sm:grid-cols-4"
          metrics={[
            { key: "mockLib", label: "Mock lib files", value: t.mockLibFiles },
            { key: "filesImporting", label: "Files importing mock", value: t.filesImportingMock },
            { key: "pageRoutes", label: "Page routes leaking", value: t.pageRoutesWithMock, tone: t.pageRoutesWithMock ? "alert" : "good" },
            { key: "components", label: "Components leaking", value: t.componentsWithMock, tone: t.componentsWithMock ? "alert" : "good" },
          ]}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mb-3">
        <Flag ok={!p.mockAllowed} label="Frontend mock fallback disabled" />
        <Flag ok={p.backendOn} label="Backend bridge on" />
        <Flag ok={p.productionSafe} label="Production safety" />
        <Flag ok={p.nodeEnv !== "production" || !p.mockAllowed} label={`Env: ${p.nodeEnv}`} />
      </div>

      <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1 inline-flex items-center gap-1"><FileWarning size={11} /> Top mock domains</div>
      <div className="flex flex-wrap gap-1 mb-2">
        {data.report.topDomains.slice(0, 10).map((d) => (
          <span key={d.domain} className="text-[10px] font-semibold rounded-md bg-slate-100 text-slate-600 px-1.5 py-0.5">{d.domain} · {d.count}</span>
        ))}
      </div>
      <p className="text-[10.5px] muted">Goal: drive “page routes leaking” to 0. Run <span className="font-mono">node scripts/mock-audit.mjs --gate</span> in CI to block regressions.</p>
    </section>
  );
}

function Flag({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold">
      {ok ? <CheckCircle2 size={14} className="text-emerald-600" /> : <XCircle size={14} className="text-rose-500" />}
      <span className={ok ? "text-slate-700" : "text-rose-600"}>{label}</span>
    </div>
  );
}
