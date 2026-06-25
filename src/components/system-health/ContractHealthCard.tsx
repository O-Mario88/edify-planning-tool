// Data-contract health surface. Server component — shows live/dashboard
// surfaces whose backend payload failed schema validation (a `live: true`
// response carrying off-spec or undefined-array data). These are downgraded to
// section-level failures before they can reach a component's .map(); this card
// makes the underlying contract problem visible instead of hidden.

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { getContractViolations } from "@/lib/api/contract";

export function ContractHealthCard() {
  const violations = getContractViolations();
  const healthy = violations.length === 0;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Data Contract Health</h2>
          <p className="text-xs text-slate-500">
            Live surfaces validated against their schema — <code>live: true</code> must mean valid data.
          </p>
        </div>
        <span
          className={
            healthy
              ? "inline-flex items-center gap-1 text-xs font-semibold text-emerald-600"
              : "inline-flex items-center gap-1 text-xs font-semibold text-rose-600"
          }
        >
          {healthy ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
          {healthy ? "No violations" : `${violations.length} surface${violations.length === 1 ? "" : "s"}`}
        </span>
      </header>

      {healthy ? (
        <p className="text-xs text-slate-500">
          Every validated surface returned a conformant payload this session. Contract violations are
          recorded here (and in the server logs) the moment a backend response breaks its schema.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {violations.map((v) => (
            <li key={`${v.endpoint}:${v.missingFieldPath ?? "-"}`} className="flex items-start gap-3 py-2">
              <span className="mt-0.5 text-rose-500">
                <ShieldAlert size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  <span className="font-mono text-[12px]">{v.endpoint}</span>
                  {v.component && <span className="text-slate-400"> · {v.component}</span>}
                </p>
                <p className="text-[11px] text-slate-500">
                  {v.errorType} — field <span className="font-mono">{v.missingFieldPath ?? "(root)"}</span>
                  {v.expectedType && (
                    <>
                      {" "}expected <span className="font-mono">{v.expectedType}</span>, got{" "}
                      <span className="font-mono">{v.receivedType}</span>
                    </>
                  )}
                </p>
                {v.sampleError && <p className="mt-0.5 font-mono text-[11px] text-slate-400">{v.sampleError}</p>}
                <p className="mt-0.5 text-[10.5px] text-slate-400">
                  {v.role ? `role: ${v.role} · ` : ""}seen {v.count}× · last {new Date(v.lastSeen).toLocaleString()}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
