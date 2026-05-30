import Image from "next/image";
import {
  CalendarDays,
  MapPin,
  CloudUpload,
  Star,
  Users,
  ArrowUpRight,
} from "lucide-react";
import { formatMetricNumber, type LoginHeroMetrics } from "@/lib/auth-metrics";

// Server component. Renders the full left-side hero, including the
// floating stats which receive their values from the server-fetched
// LoginHeroMetrics — never hardcoded.
export function LoginHeroSection({ metrics }: { metrics: LoginHeroMetrics }) {
  return (
    <section className="relative min-h-screen md:h-screen overflow-hidden text-white isolate bg-[#0a1623]">
      {/* Real Edify field photo as the hero backdrop. The next/image fill
          variant lets it cover at any viewport size; the layered gradients
          above keep the white headline + glass cards legible.
          NOTE: no negative z-index here — that would push the photo behind
          the page's light body background (#f4f6f8) and the hero would
          render white. `isolate` on the section keeps stacking local. */}
      <div className="absolute inset-0">
        <Image
          src="/hero-classroom.jpg"
          alt="Edify community gathering — teachers and headteachers in a school library"
          fill
          priority
          quality={85}
          sizes="(max-width: 1024px) 100vw, 55vw"
          className="object-cover object-center"
        />
        {/* Dark navy gradient overlay — strongest at the top so the headline
            and pill remain crisp, lighter at the bottom so the photo's
            faces and warmth still come through behind the floating stats. */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: [
              "linear-gradient(180deg, rgba(10,22,35,0.86) 0%, rgba(12,26,40,0.66) 45%, rgba(15,30,46,0.55) 100%)",
              "linear-gradient(90deg, rgba(10,22,35,0.55) 0%, rgba(10,22,35,0.20) 60%, transparent 100%)",
              "radial-gradient(700px 260px at 30% 12%, rgba(82,112,131,0.28), transparent 70%)",
            ].join(", "),
          }}
        />
        {/* Faint data-viz dot orbits — kept subtle on top of the photo. */}
        <svg
          viewBox="0 0 1400 900"
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full opacity-15 pointer-events-none"
          aria-hidden
        >
          <ellipse cx="700" cy="780" rx="640" ry="180" fill="none" stroke="#7ba3b8" strokeWidth="0.7" />
          <ellipse cx="700" cy="780" rx="520" ry="140" fill="none" stroke="#7ba3b8" strokeWidth="0.5" />
          <ellipse cx="700" cy="780" rx="380" ry="100" fill="none" stroke="#7ba3b8" strokeWidth="0.4" />
        </svg>
      </div>

      <div className="relative h-full flex flex-col px-6 py-8 md:px-12 md:py-10">
        {/* Top: brand + pill */}
        <div className="flex flex-col items-start gap-6">
          <div className="inline-flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-white/95 grid place-items-center shadow-lg shadow-black/20">
              <Image src="/edify-logo.png" alt="Edify" width={36} height={15} className="object-contain" style={{ width: "auto", height: "auto" }} priority />
            </div>
            <div className="text-[44px] font-extrabold tracking-tight leading-none">edify</div>
          </div>

          <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[.07] px-3 py-1.5 text-[12px] font-semibold text-white/90">
            <Users size={13} className="text-white/80" />
            Smarter planning. Stronger schools. Greater impact.
          </div>
        </div>

        {/* Headline */}
        <div className="mt-8 md:mt-10 max-w-[560px]">
          <h1 className="text-[30px] sm:text-[36px] md:text-[44px] leading-[1.1] md:leading-[1.05] font-extrabold tracking-tight">
            Welcome Back to{" "}
            <span className="text-[var(--color-edify-primary)]">Edify</span>{" "}
            Planning and Monitoring Tool.
          </h1>
          <p className="mt-4 text-body-lg text-white/75 leading-relaxed max-w-[480px]">
            Plan smarter, serve schools better, and stay on top of your monthly targets.
          </p>
        </div>

        {/* Glass feature card */}
        <div className="mt-8">
          <GlassFeatureCard />
        </div>

        {/* Floating stats — DATABASE-DRIVEN */}
        <div className="mt-8 md:mt-auto relative">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-6 items-end">
            <HeroStatCard
              icon={<Users size={16} />}
              label="Schools Reached"
              value={formatMetricNumber(metrics.schoolsReached.value)}
              trend={`${metrics.schoolsReached.trendPercent >= 0 ? "+" : ""}${metrics.schoolsReached.trendPercent}% ${metrics.schoolsReached.comparisonLabel}`}
              positive={metrics.schoolsReached.trendPercent >= 0}
            />

            {/* Decorative bar chart silhouette in the middle column */}
            <div className="hidden md:flex items-end justify-center gap-1.5 h-[120px] opacity-90">
              {[24, 38, 56, 78, 92, 86, 74, 60, 46].map((h, i) => (
                <span
                  key={i}
                  className="w-3 rounded-sm"
                  style={{
                    height: `${h}%`,
                    background:
                      "linear-gradient(180deg, rgba(125,170,200,0.85) 0%, rgba(82,112,131,0.55) 60%, rgba(40,70,95,0.2) 100%)",
                  }}
                />
              ))}
            </div>

            <HeroStatCard
              icon={<Star size={16} />}
              label="Target Progress"
              value={`${metrics.targetProgress.value}%`}
              trend={`${metrics.targetProgress.trendPercent >= 0 ? "+" : ""}${metrics.targetProgress.trendPercent}% ${metrics.targetProgress.comparisonLabel}`}
              positive={metrics.targetProgress.trendPercent >= 0}
              ring={metrics.targetProgress.value}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

// ────────── Inline feature panel ──────────

function GlassFeatureCard() {
  const features = [
    {
      key: "plan",
      icon: <CalendarDays size={18} />,
      title: "Plan with clarity",
      body: "Build monthly plans driven by real data and priorities.",
    },
    {
      key: "track",
      icon: <MapPin size={18} />,
      title: "Track field work",
      body: "Monitor visits, activities, and outcomes in real time.",
    },
    {
      key: "close",
      icon: <CloudUpload size={18} />,
      title: "Close tasks with Salesforce",
      body: "Seamlessly update, collaborate, and drive completion.",
    },
    {
      key: "lead",
      icon: <Star size={18} />,
      title: "Lead with confidence",
      body: "Get insights, set fast, and deliver measurable impact.",
    },
  ];
  return (
    <div className="rounded-2xl border border-white/15 bg-white/[.06] backdrop-blur-md p-5">
      <div className="grid grid-cols-1 md:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-white/10">
        {features.map((f, i) => (
          <div key={f.key} className={`px-2 ${i === 0 ? "md:pl-0" : "md:pl-4"} ${i === features.length - 1 ? "md:pr-0" : "md:pr-4"} py-3 md:py-0`}>
            <div className="w-9 h-9 rounded-full bg-white/[.10] border border-white/15 grid place-items-center text-white">
              {f.icon}
            </div>
            <div className="mt-3">
              <div className="text-[13px] font-bold leading-tight">{f.title}</div>
              <div className="text-[11.5px] text-white/65 leading-snug mt-1.5">{f.body}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ────────── Floating stat card ──────────

function HeroStatCard({
  icon,
  label,
  value,
  trend,
  positive,
  ring,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  trend: string;
  positive: boolean;
  ring?: number; // 0–100 — when present, shows a circular progress
}) {
  return (
    <div className="rounded-2xl border border-white/15 bg-white/[.10] backdrop-blur-md p-3.5 shadow-2xl shadow-black/30 overflow-hidden">
      <div className="flex items-center gap-3">
        {ring !== undefined ? (
          <RingMini pct={ring} />
        ) : (
          <span className="w-9 h-9 rounded-full bg-white/[.12] border border-white/15 grid place-items-center text-white">
            {icon}
          </span>
        )}
        <div className="leading-tight min-w-0 flex-1">
          <div className="text-caption uppercase tracking-wide text-white/65 font-semibold">
            {label}
          </div>
          <div className="text-[24px] font-extrabold tabular leading-none mt-1 truncate">
            {value}
          </div>
          <div
            className={`text-caption font-semibold mt-1 inline-flex items-center gap-1 truncate ${positive ? "text-emerald-300" : "text-rose-300"}`}
          >
            <ArrowUpRight size={10} className="shrink-0" />
            {trend}
          </div>
        </div>
      </div>
    </div>
  );
}

function RingMini({ pct }: { pct: number }) {
  const size = 44;
  const stroke = 5;
  const r = size / 2 - stroke;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return (
    <span className="relative inline-block shrink-0" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#7ba3b8"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={off}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-[10px] font-extrabold tabular text-white">
        {pct}%
      </span>
    </span>
  );
}
