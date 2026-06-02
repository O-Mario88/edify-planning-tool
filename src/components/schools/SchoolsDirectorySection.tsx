"use client";

import { useMemo, useState } from "react";
import {
  ListFilter,
  ChevronDown,
  Plus,
  Layers,
  MapPin,
} from "lucide-react";
import { SchoolsOverviewTable } from "./SchoolsOverviewTable";
import { ExportButton } from "@/components/ui/ExportButton";
import {
  applyFilters,
  groupSchools,
  distinctRegions,
  distinctDistricts,
  distinctShippingAddresses,
  type SchoolRow,
  type Region,
  type District,
  type ShippingAddress,
  type GroupBy,
} from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

// Client-side directory: filter + group + cluster from the visible school
// set. Visibility is enforced upstream by getVisibleSchools(); this layer
// only narrows what's already accessible to the current user.
//
// Clustering happens HERE (not in the Planning Tool). The Create Cluster
// button captures whatever is currently filtered as a saved cluster, which
// the Planning Tool consumes when scheduling visits or trainings.
export function SchoolsDirectorySection({
  schools,
  totalAssignedCount,
}: {
  schools: SchoolRow[];
  totalAssignedCount: number;
}) {
  const [region, setRegion] = useState<Region | "All">("All");
  const [district, setDistrict] = useState<District | "All">("All");
  const [shipping, setShipping] = useState<ShippingAddress | "All">("All");
  const [groupBy, setGroupBy] = useState<GroupBy>("none");

  const filtered = useMemo(
    () =>
      applyFilters(schools, {
        region,
        district,
        shippingAddress: shipping,
      }),
    [schools, region, district, shipping],
  );

  const groups = useMemo(() => groupSchools(filtered, groupBy), [filtered, groupBy]);

  const regionOpts = useMemo(() => distinctRegions(schools), [schools]);
  const districtOpts = useMemo(() => distinctDistricts(schools), [schools]);
  const shippingOpts = useMemo(() => distinctShippingAddresses(schools), [schools]);

  const filtersActive = region !== "All" || district !== "All" || shipping !== "All";

  const handleCreateCluster = () => {
    const dim = shipping !== "All" ? shipping : district !== "All" ? district : region !== "All" ? region : "Filtered set";
    // Mock action — the real backend call would persist this to the
    // Cluster table for the current CCEO.
    alert(
      `Create cluster from ${filtered.length} schools (${dim}).\n\n` +
        `Backend POST /api/clusters {\n  ownerCceoId,\n  schoolIds: [${filtered
          .slice(0, 5)
          .map((s) => s.schoolId)
          .join(", ")}${filtered.length > 5 ? ", …" : ""}],\n  region, district, shippingAddress\n}`,
    );
  };

  return (
    <SchoolsOverviewTable
      groups={groups}
      totalAssignedCount={totalAssignedCount}
      toolbar={
        <div className="flex items-center gap-2">
          <ExportButton
            rows={filtered.map((s) => ({
              School: s.schoolName, District: s.district, Region: s.region,
              Type: s.schoolType ?? s.segment ?? "", SSA_status: s.ssaStatus,
              SSA_score: s.ssaScore, CCEO: s.assignedCceoName ?? "",
            }))}
            filename="schools-directory"
          />
          <button
            type="button"
            onClick={handleCreateCluster}
            disabled={filtered.length === 0}
            className={cn(
              "btn btn-sm btn-primary",
              filtered.length === 0 && "opacity-55 cursor-not-allowed",
            )}
          >
            <Plus size={12} />
            Create Cluster
          </button>
        </div>
      }
      filterBar={
        <div className="mb-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3 py-2.5 flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[var(--color-edify-dark)] uppercase tracking-wide pr-2 border-r border-[var(--color-edify-border)] mr-1">
            <ListFilter size={11} />
            Cluster Filters
          </span>

          <Select
            label="Region"
            value={region}
            onChange={(v) => setRegion(v as Region | "All")}
            options={["All", ...regionOpts]}
          />
          <Select
            label="District"
            value={district}
            onChange={(v) => setDistrict(v as District | "All")}
            options={["All", ...districtOpts]}
          />
          <Select
            label="Shipping Address"
            value={shipping}
            onChange={(v) => setShipping(v as ShippingAddress | "All")}
            options={["All", ...shippingOpts]}
            Icon={MapPin}
          />

          <span className="ml-auto inline-flex items-center gap-2">
            <Select
              label="Group By"
              value={groupBy}
              onChange={(v) => setGroupBy(v as GroupBy)}
              options={["none", "shippingAddress", "district", "region"]}
              labelMap={{
                none: "None",
                shippingAddress: "Shipping Address",
                district: "District",
                region: "Region",
              }}
              Icon={Layers}
            />
            <span className="text-[11px] muted font-semibold">
              {filtered.length} school{filtered.length === 1 ? "" : "s"}
              {filtersActive ? " (filtered)" : ""}
            </span>
          </span>
        </div>
      }
    />
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  labelMap,
  Icon,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  labelMap?: Record<string, string>;
  Icon?: React.ComponentType<{ size?: number; className?: string }>;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold">
      <span className="muted">{label}:</span>
      <span className="relative inline-block">
        {Icon && (
          <Icon
            size={11}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-edify-primary)] pointer-events-none"
          />
        )}
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "h-8 pr-7 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 appearance-none",
            Icon ? "pl-7" : "pl-2.5",
          )}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {labelMap?.[o] ?? o}
            </option>
          ))}
        </select>
        <ChevronDown
          size={11}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none"
        />
      </span>
    </label>
  );
}
