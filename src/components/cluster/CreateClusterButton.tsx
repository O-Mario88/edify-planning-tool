"use client";

// Central "New cluster" action — the single place clusters are created.
// Form: District → one or more Sub-counties (checkboxes) → Cluster Leader
// (a school leader from a school in the chosen area: name + phone). No cluster
// type — core and client schools sit in the same locations.

import { useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Plus, AlertTriangle, Network, UserCheck } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { SUBCOUNTIES, subCountiesOf } from "@/lib/geography";
import { candidateClusterLeaders } from "@/lib/cluster/cluster-core";
import { createEmptyClusterAction } from "@/lib/actions/cluster-actions";
import { notifyClustersUpdated } from "@/lib/cluster/cluster-events";
import { cn } from "@/lib/utils";

const DISTRICT_OPTIONS = Array.from(new Set(SUBCOUNTIES.map((s) => s.districtName)))
  .sort()
  .map((d) => ({ value: d, label: d }));

export function CreateClusterButton({ geoByDistrict }: { geoByDistrict?: Record<string, string[]> } = {}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);

  // Geography source. When the caller passes `geoByDistrict` (the School
  // Directory derives it from the BACKEND schools it manages), the district +
  // sub-county pickers offer ONLY real backend geography that's in the user's
  // scope — so the name→ID resolution always succeeds and the backend never
  // 403s on an out-of-scope district. Falls back to the static national
  // catalogue for callers without it (e.g. the country-scoped Clusters page).
  const useBackendGeo = !!geoByDistrict && Object.keys(geoByDistrict).length > 0;
  const districtOpts = useBackendGeo
    ? Object.keys(geoByDistrict!).sort().map((d) => ({ value: d, label: d }))
    : DISTRICT_OPTIONS;

  const [district, setDistrict] = useState(districtOpts[0]?.value ?? "");
  const [subCounties, setSubCounties] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [autoName, setAutoName] = useState(""); // last auto-suggested name (so manual edits stick)
  const [leaderName, setLeaderName] = useState("");
  const [leaderPhone, setLeaderPhone] = useState("");
  const [leaderSchoolId, setLeaderSchoolId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const subCountyChoices = useMemo(
    () => (useBackendGeo ? (geoByDistrict![district] ?? []) : subCountiesOf(district).map((s) => s.name)),
    [district, useBackendGeo, geoByDistrict],
  );
  // School leaders from schools in the chosen district + sub-counties.
  const leaderCandidates = useMemo(
    () => candidateClusterLeaders(district, subCounties),
    [district, subCounties],
  );

  function reset() {
    setSubCounties([]);
    setName("");
    setAutoName("");
    setLeaderName("");
    setLeaderPhone("");
    setLeaderSchoolId("");
    setError(null);
  }

  function suggestName(subs: string[]): string {
    if (subs.length === 1) return `${subs[0]} Cluster`;
    if (subs.length > 1) return `${district} Cluster`;
    return "";
  }

  function toggleSubCounty(sc: string) {
    setSubCounties((prev) => {
      const next = prev.includes(sc) ? prev.filter((x) => x !== sc) : [...prev, sc];
      // Keep the name in sync with the selection while the user hasn't typed a
      // custom one (name still equals the last suggestion or is empty).
      const suggestion = suggestName(next);
      if (name === "" || name === autoName) {
        setName(suggestion);
        setAutoName(suggestion);
      }
      return next;
    });
  }

  function pickLeader(schoolId: string) {
    setLeaderSchoolId(schoolId);
    const c = leaderCandidates.find((x) => x.schoolId === schoolId);
    if (c) {
      setLeaderName(c.leaderName);
      setLeaderPhone(c.phone ?? "");
    }
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (subCounties.length === 0) { setError("Select at least one sub-county."); return; }
    if (!name.trim()) { setError("Give the cluster a name."); return; }
    setPending(true);
    const res = await createEmptyClusterAction({
      name: name.trim(),
      district,
      subCounties,
      clusterLeaderName: leaderName.trim() || undefined,
      clusterLeaderPhone: leaderPhone.trim() || undefined,
      clusterLeaderSchoolId: leaderSchoolId || undefined,
    });
    setPending(false);
    if (!res.ok) {
      setError(
        res.reason === "INVALID_INPUT"
          ? (Object.values(res.errors)[0] ?? "Invalid cluster.")
          : res.reason === "FORBIDDEN"
            ? "You don't have permission to create clusters."
            : res.reason === "FAILED"
              ? res.message  // surface the real backend reason (e.g. "District outside your scope")
              : "Could not create the cluster.",
      );
      return;
    }
    setOpen(false);
    reset();
    notifyClustersUpdated();
    router.refresh();
  }

  return (
    <>
      <Button size="sm" Icon={Plus} onClick={() => { reset(); setOpen(true); }}>
        New cluster
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Create a new cluster"
        description="Pick the district and the sub-counties it covers, then name its leader (a school leader from one of the cluster's schools). Assign schools from the workspace afterwards."
        size="md"
        variant="sheet"
        footer={
          <div className="flex items-center justify-end gap-2 w-full">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button
              size="sm"
              Icon={Network}
              disabled={pending}
              onClick={() => {
                const form = document.getElementById("create-cluster-form") as HTMLFormElement | null;
                form?.requestSubmit();
              }}
            >
              {pending ? "Creating…" : "Create cluster"}
            </Button>
          </div>
        }
      >
        <form id="create-cluster-form" onSubmit={handleSubmit} className="space-y-4">
          <Select
            label="District"
            required
            value={district}
            onChange={(e) => { setDistrict(e.target.value); setSubCounties([]); setLeaderSchoolId(""); }}
            options={districtOpts}
          />

          {/* Sub-counties — multi-select via checkboxes (a cluster may span several). */}
          <div className="space-y-1">
            <label className="block text-[12px] font-semibold text-[var(--color-edify-text)]">
              Sub-counties <span className="text-rose-500">*</span>
              <span className="ml-1 font-normal muted">({subCounties.length} selected)</span>
            </label>
            <div className="max-h-40 overflow-y-auto rounded-lg border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)]">
              {subCountyChoices.length === 0 ? (
                <p className="px-3 py-3 text-[12px] muted">No sub-counties catalogued for this district.</p>
              ) : (
                subCountyChoices.map((sc) => {
                  const checked = subCounties.includes(sc);
                  return (
                    <label
                      key={sc}
                      className={cn(
                        "flex items-center gap-2.5 px-3 py-2 text-[12.5px] cursor-pointer transition-colors",
                        checked ? "bg-[var(--color-edify-primary)]/5 font-semibold" : "hover:bg-[var(--color-edify-soft)]/40",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSubCounty(sc)}
                        className="h-3.5 w-3.5 accent-[var(--color-edify-primary)]"
                      />
                      {sc}
                    </label>
                  );
                })
              )}
            </div>
          </div>

          <Input
            label="Cluster name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Mukono Central Cluster"
            helper="Auto-suggested from your selection — edit if you like. Must be unique within the district."
          />

          {/* Cluster leader — a school leader from one of the cluster's schools. */}
          <div className="space-y-2 rounded-lg border border-[var(--color-edify-border)] p-3">
            <div className="flex items-center gap-1.5 text-[12px] font-extrabold tracking-tight">
              <UserCheck size={13} className="text-[var(--color-edify-primary)]" />
              Cluster leader
            </div>
            {leaderCandidates.length > 0 ? (
              <Select
                label="Pick a school leader"
                value={leaderSchoolId}
                onChange={(e) => pickLeader(e.target.value)}
                options={leaderCandidates.map((c) => ({
                  value: c.schoolId,
                  label: `${c.leaderName} — ${c.schoolName}${c.subCounty ? ` (${c.subCounty})` : ""}`,
                }))}
                placeholder="Select from schools in this area…"
              />
            ) : (
              <p className="text-[11px] muted">
                No school leaders on file for the selected area yet — enter the leader’s details below.
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input
                label="Leader name"
                value={leaderName}
                onChange={(e) => { setLeaderName(e.target.value); setLeaderSchoolId(""); }}
                placeholder="e.g. Esther Naluwu"
              />
              <Input
                label="Leader phone"
                value={leaderPhone}
                onChange={(e) => setLeaderPhone(e.target.value)}
                placeholder="e.g. +256 772 000 000"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}
        </form>
      </Modal>
    </>
  );
}
