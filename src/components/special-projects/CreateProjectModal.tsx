"use client";

// Create New Project (spec §3). A project is a targeted initiative mapped to
// one or more SSA interventions — NOT a 9th intervention. The primary
// intervention is required so impact can later be measured against the gap
// the project was designed to close.

import { useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Plus, AlertTriangle, Sparkles } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  PROJECT_TYPES,
  PROJECT_INTERVENTIONS,
  type ProjectScopeKind,
} from "@/lib/special-projects-mock";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import { createProjectAction } from "@/lib/actions/special-project-actions";

const SCOPE_OPTIONS: { value: ProjectScopeKind; label: string }[] = [
  { value: "country",  label: "Country-wide" },
  { value: "region",   label: "Region-specific" },
  { value: "district", label: "District-specific" },
  { value: "project",  label: "Project-specific" },
  { value: "partner",  label: "Partner-specific" },
];

export function CreateProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [type, setType] = useState<string>("Targeted Intervention");
  const [primary, setPrimary] = useState<SsaInterventionArea | "">("");
  const [secondary, setSecondary] = useState<SsaInterventionArea[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [about, setAbout] = useState("");
  const [coordinatorName, setCoordinatorName] = useState("");
  const [scopeKind, setScopeKind] = useState<ProjectScopeKind>("country");

  function reset() {
    setName(""); setType("Targeted Intervention"); setPrimary(""); setSecondary([]);
    setStartDate(""); setEndDate(""); setAbout(""); setCoordinatorName("");
    setScopeKind("country"); setError(null);
  }

  function toggleSecondary(area: SsaInterventionArea) {
    setSecondary((prev) =>
      prev.includes(area) ? prev.filter((a) => a !== area) : [...prev, area],
    );
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) { setError("Project name is required."); return; }
    if (!primary) { setError("Pick a primary SSA intervention."); return; }
    if (!startDate || !endDate) { setError("Set a start and end date."); return; }

    startTransition(async () => {
      const res = await createProjectAction({
        projectName: name.trim(),
        projectType: type,
        primaryInterventionId: primary,
        secondaryInterventionIds: secondary.filter((a) => a !== primary),
        startDate,
        endDate,
        description: about.trim() || undefined,
        coordinatorName: coordinatorName.trim() || undefined,
        scopeKind,
        status: "Active",
      });
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "You don't have permission to create projects." : res.message);
        return;
      }
      reset();
      router.refresh();
      router.push(`/projects/${res.projectId}`);
      onClose();
    });
  }

  return (
    <Modal
      open={open}
      onClose={() => { reset(); onClose(); }}
      title="Create New Project"
      description="A targeted initiative mapped to one or more SSA interventions. The primary intervention is the gap this project sets out to close."
      size="md"
      variant="sheet"
    >
      <form onSubmit={submit} className="space-y-3.5">
        <Input label="Project name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Literacy & Numeracy" />

        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Project type" value={type} onChange={(e) => setType(e.target.value)}
            options={PROJECT_TYPES.map((t) => ({ value: t, label: t }))}
          />
          <Select
            label="Project scope" value={scopeKind} onChange={(e) => setScopeKind(e.target.value as ProjectScopeKind)}
            options={SCOPE_OPTIONS}
          />
        </div>

        <Select
          label="Primary SSA intervention" required placeholder="Choose the gap this project targets…"
          value={primary}
          onChange={(e) => setPrimary(e.target.value as SsaInterventionArea)}
          options={PROJECT_INTERVENTIONS.map((i) => ({ value: i, label: i }))}
        />

        <div className="space-y-1.5">
          <label className="text-[11.5px] font-semibold">Secondary interventions (optional)</label>
          <div className="flex flex-wrap gap-1.5">
            {PROJECT_INTERVENTIONS.filter((i) => i !== primary).map((area) => {
              const on = secondary.includes(area);
              return (
                <button
                  key={area} type="button" onClick={() => toggleSecondary(area)}
                  className={cn(
                    "px-2 py-[3px] rounded-md text-[11px] font-semibold border transition-colors inline-flex items-center gap-1",
                    on
                      ? "bg-[var(--color-edify-primary)]/10 border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]"
                      : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
                  )}
                >
                  {on && <Sparkles size={9} />} {area}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Input label="Start date" type="date" required value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <Input label="End date" type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>

        <Input label="Project owner / coordinator" value={coordinatorName} onChange={(e) => setCoordinatorName(e.target.value)} placeholder="e.g. Rachel Apio" />

        <div className="flex flex-col gap-1">
          <label htmlFor="project-about" className="text-[11.5px] font-semibold">About the project</label>
          <textarea
            id="project-about" value={about} onChange={(e) => setAbout(e.target.value)} rows={3}
            placeholder="What this initiative does and how it addresses the intervention gap…"
            className="px-3 py-2 text-[12.5px] rounded-lg bg-white border border-[var(--color-edify-border)] outline-none focus:outline-2 focus:outline-[var(--color-edify-primary)] resize-none"
          />
        </div>

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />{error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" size="sm" onClick={() => { reset(); onClose(); }}>Cancel</Button>
          <Button type="submit" size="sm" Icon={Plus} disabled={pending}>{pending ? "Creating…" : "Create project"}</Button>
        </div>
      </form>
    </Modal>
  );
}
