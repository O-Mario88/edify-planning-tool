"use client";

// Central "New cluster" action — the single place clusters are created.
// Planning surfaces only attach schools to existing clusters; creation lives
// here on the Clusters page. Calls createEmptyClusterAction (server) so the new
// cluster persists and the workspace/analytics see it immediately.

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Plus, AlertTriangle, Network } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { SUBCOUNTIES, subCountiesOf, regionForDistrict } from "@/lib/geography";
import { createEmptyClusterAction } from "@/lib/actions/cluster-actions";

const DISTRICT_OPTIONS = Array.from(new Set(SUBCOUNTIES.map((s) => s.districtName)))
  .sort()
  .map((d) => ({ value: d, label: d }));

export function CreateClusterButton() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [district, setDistrict] = useState(DISTRICT_OPTIONS[0]?.value ?? "");
  const [subCounty, setSubCounty] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("Client");
  const [error, setError] = useState<string | null>(null);

  const subCountyOptions = subCountiesOf(district).map((s) => ({ value: s.name, label: s.name }));

  function reset() {
    setName("");
    setSubCounty("");
    setType("Client");
    setError(null);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) { setError("Give the cluster a name (e.g. ‘Kayunga North Cluster’)."); return; }
    if (!district) { setError("Pick the district the cluster sits in."); return; }
    if (!subCounty) { setError("Pick the sub-county where the cluster meets."); return; }
    setPending(true);
    const res = await createEmptyClusterAction({
      name: name.trim(),
      region: regionForDistrict(district) ?? district,
      district,
      subCounty,
      clusterType: type as "Client" | "Core" | "Mixed",
    });
    setPending(false);
    if (!res.ok) {
      setError(
        res.reason === "INVALID_INPUT"
          ? (Object.values(res.errors)[0] ?? "Invalid cluster.")
          : res.reason === "FORBIDDEN"
            ? "You don't have permission to create clusters."
            : "Could not create the cluster.",
      );
      return;
    }
    setOpen(false);
    reset();
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
        description="Clusters are created here, then schools are assigned to them from the Cluster Assignment Workspace."
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
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Select
              label="District"
              required
              value={district}
              onChange={(e) => { setDistrict(e.target.value); setSubCounty(""); }}
              options={DISTRICT_OPTIONS}
            />
            <Select
              label="Sub-county"
              required
              value={subCounty}
              onChange={(e) => setSubCounty(e.target.value)}
              options={subCountyOptions}
              placeholder="Pick a sub-county"
              helper={subCountyOptions.length === 0 ? "Pick a district first." : undefined}
              disabled={subCountyOptions.length === 0}
            />
          </div>
          <Input
            label="Cluster name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Kayunga North Cluster"
            helper="Use a short, geography-anchored name. It must be unique within the district / sub-county."
          />
          <Select
            label="Cluster type"
            value={type}
            onChange={(e) => setType(e.target.value)}
            options={[
              { value: "Client", label: "Client" },
              { value: "Core", label: "Core" },
              { value: "Mixed", label: "Mixed" },
            ]}
          />

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
