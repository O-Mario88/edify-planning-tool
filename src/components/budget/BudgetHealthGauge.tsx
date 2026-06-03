// Semicircle budget-health gauge (score 0–100) with an On Track / At Risk /
// Critical legend. Pure SVG — no chart lib needed.

const TONES = [
  { stop: 0.5, color: "#dc2626" },   // 0–50 critical (red)
  { stop: 0.75, color: "#f59e0b" },  // 50–75 at risk (amber)
  { stop: 1, color: "#0f8a5f" },     // 75–100 healthy (green)
];

function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number): string {
  const rad = (d: number) => (d * Math.PI) / 180;
  const x1 = cx + r * Math.cos(rad(startDeg));
  const y1 = cy + r * Math.sin(rad(startDeg));
  const x2 = cx + r * Math.cos(rad(endDeg));
  const y2 = cy + r * Math.sin(rad(endDeg));
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

export function BudgetHealthGauge({
  score,
  split,
  label = "Healthy",
}: {
  score: number;
  split?: { onTrack: number; atRisk: number; critical: number };
  label?: string;
}) {
  const W = 220, H = 130, cx = 110, cy = 116, r = 90, stroke = 16;
  // 180° (left) → 360° (right). Three coloured bands.
  const bandStart = 180;
  const bands = [
    { from: 0, to: 0.5, color: "#fecaca" },
    { from: 0.5, to: 0.75, color: "#fde68a" },
    { from: 0.75, to: 1, color: "#a7f3d0" },
  ];
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const needleDeg = bandStart + pct * 180;

  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Budget health ${score} of 100`}
        style={{ width: "100%", maxWidth: W, height: "auto" }}>
        {bands.map((b, i) => (
          <path
            key={i}
            d={arcPath(cx, cy, r, bandStart + b.from * 180, bandStart + b.to * 180)}
            fill="none"
            stroke={b.color}
            strokeWidth={stroke}
            strokeLinecap="round"
          />
        ))}
        {/* progress arc up to score */}
        <path
          d={arcPath(cx, cy, r, bandStart, needleDeg)}
          fill="none"
          stroke={pct >= 0.75 ? TONES[2].color : pct >= 0.5 ? TONES[1].color : TONES[0].color}
          strokeWidth={stroke}
          strokeLinecap="round"
          opacity={0.9}
        />
        <text x={cx} y={cy - 18} textAnchor="middle" className="fill-[var(--color-edify-text)]" style={{ fontSize: 30, fontWeight: 800 }}>
          {Math.round(score)}<tspan style={{ fontSize: 14, fontWeight: 700 }} className="fill-[var(--color-edify-muted)]"> /100</tspan>
        </text>
        <text x={cx} y={cy} textAnchor="middle" className="fill-[var(--color-edify-muted)]" style={{ fontSize: 12, fontWeight: 700 }}>{label}</text>
      </svg>
      {split && (
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10.5px] mt-1">
          <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" /> On Track <b>{split.onTrack}%</b></span>
          <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500" /> At Risk <b>{split.atRisk}%</b></span>
          <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-rose-500" /> Critical <b>{split.critical}%</b></span>
        </div>
      )}
    </div>
  );
}
