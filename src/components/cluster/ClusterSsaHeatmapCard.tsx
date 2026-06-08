// Per-cluster SSA intervention heatmap — rows = clusters, cols = SSA
// interventions, cell = average score across the cluster's schools. Banded
// 0–4 critical / 5–6 needs support / 7–8 good / 9–10 strong.

import { clusterSsaHeatmap } from "@/lib/cluster/cluster-core";

function band(v: number | null): { cls: string; label: string } {
  if (v == null) return { cls: "bg-[var(--surface-2)] text-[var(--text-muted)]", label: "—" };
  if (v <= 4) return { cls: "bg-rose-100 text-rose-800", label: String(v) };
  if (v <= 6) return { cls: "bg-amber-100 text-amber-800", label: String(v) };
  if (v <= 8) return { cls: "bg-emerald-100 text-emerald-800", label: String(v) };
  return { cls: "bg-emerald-300 text-emerald-900", label: String(v) };
}

// Short column headers from the intervention names.
function abbr(name: string): string {
  return name.split(/[ /]/).filter(Boolean).map((w) => w[0]).join("").slice(0, 3).toUpperCase();
}

export function ClusterSsaHeatmapCard() {
  const { interventions, rows } = clusterSsaHeatmap();
  const withData = rows.filter((r) => r.schoolsWithSsa > 0);

  return (
    <section className="card rounded-2xl p-4">
      <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
        SSA performance by cluster
      </h2>
      <p className="muted text-[12px] mt-0.5">
        Average SSA score per intervention across each cluster&apos;s schools. Red = critical, amber = needs support, green = good/strong.
      </p>
      {withData.length === 0 ? (
        <p className="muted text-[12.5px] mt-3">No cluster SSA data yet — scores appear once member schools have uploaded SSAs.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="text-[11.5px] border-separate" style={{ borderSpacing: 3 }}>
            <thead>
              <tr>
                <th className="text-left muted font-semibold pr-2 sticky left-0">Cluster</th>
                {interventions.map((iv) => (
                  <th key={iv} className="px-1 font-semibold muted text-center" title={iv}>{abbr(iv)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {withData.map((r) => (
                <tr key={r.clusterId}>
                  <td className="pr-2 font-semibold text-[var(--color-edify-text)] whitespace-nowrap sticky left-0">
                    {r.clusterName}<span className="muted font-normal"> · {r.schoolsWithSsa}</span>
                  </td>
                  {r.cells.map((v, i) => {
                    const b = band(v);
                    return (
                      <td key={i} className="p-0">
                        <div className={`h-7 w-7 sm:h-8 sm:w-9 grid place-items-center rounded sm:rounded-md font-bold tabular ${b.cls}`}>{b.label}</div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted text-[10.5px] mt-2">Columns: {interventions.map((iv) => `${abbr(iv)} = ${iv}`).join(" · ")}</p>
        </div>
      )}
    </section>
  );
}
