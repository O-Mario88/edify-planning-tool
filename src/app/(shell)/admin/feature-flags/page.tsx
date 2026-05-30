import { Flag } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";

type Flag = {
  key: string;
  name: string;
  description: string;
  audience: string;
  state: "on" | "off" | "partial";
};

const FLAGS: Flag[] = [
  { key: "ai_debrief_summary",       name: "AI summary on Daily Field Debrief",   description: "Generates a one-paragraph summary on submit.",      audience: "Pilot — 20% of CCEOs",   state: "partial" },
  { key: "smart_route_v2",           name: "Smart Route v2 (turn-by-turn)",       description: "Adds turn-by-turn export and weather aware reroute.", audience: "All CCEOs in Kenya",      state: "on" },
  { key: "humane_pip_review_v2",     name: "Support-Review v2 checklist",          description: "Expanded checklist with mid-year-only items.",       audience: "HR + Country Directors", state: "on" },
  { key: "core_school_october",      name: "October Core onboarding",              description: "Auto-recommend Core onboarding after SSA verify ≥7.5.", audience: "Uganda only",            state: "on" },
  { key: "salesforce_bulk_paste",    name: "Bulk Salesforce ID paste",             description: "Paste 50+ IDs at once on the verification queue.",   audience: "Impact Assessment",      state: "off" },
  { key: "command_palette",          name: "Cmd-K command palette",                description: "Power-user keyboard navigation.",                   audience: "Internal",                state: "off" },
];

const TONE: Record<Flag["state"], string> = {
  on:      "bg-emerald-100 text-emerald-700",
  off:     "bg-slate-100   text-slate-700",
  partial: "bg-amber-100   text-amber-700",
};

const LABEL: Record<Flag["state"], string> = {
  on:      "On",
  off:     "Off",
  partial: "Partial rollout",
};

export default function FeatureFlagsPage() {
  return (
    <StubPage
      title="Feature Flags"
      subtitle="Roll features by role, country, and individual. Production wires this to the same store the runtime reads — toggling here re-evaluates immediately."
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {FLAGS.map((f) => (
          <div key={f.key} className="flex items-start gap-3 px-4 py-3.5">
            <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
              <Flag size={15} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <div className="text-body font-extrabold tracking-tight">{f.name}</div>
                <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap ${TONE[f.state]}`}>
                  {LABEL[f.state]}
                </span>
              </div>
              <div className="text-[11px] muted">{f.description}</div>
              <div className="text-caption muted mt-0.5">Audience: <span className="font-semibold">{f.audience}</span> · key: <span className="font-mono">{f.key}</span></div>
            </div>
          </div>
        ))}
      </section>
    </StubPage>
  );
}
