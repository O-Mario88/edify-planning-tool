"use client";

// Administration Budget section.
//
// CD-editable region underneath the program activity matrix. CD adds
// rent / airtime / internet / etc.; PL sees the items read-only.
// Items have a category, name, justification, quantity, unit cost,
// total, and a week assignment ("Monthly" if recurring all month).
//
// Local state only — when the real backend lands, swap `addItem` /
// `removeItem` to server actions that revalidate the page.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus, Trash2, Wallet, Loader2 } from "lucide-react";
import {
  ADMIN_BUDGET_LABEL,
  type AdminBudgetCategory,
  type MfrAdminItem,
} from "@/lib/funds/monthly-fund-request-types";
import { useDemoStore } from "@/components/demo/DemoStore";
import { addAdminItem, removeAdminItem } from "@/lib/actions/admin-item-actions";
import { cn } from "@/lib/utils";

const CATEGORIES = Object.keys(ADMIN_BUDGET_LABEL) as AdminBudgetCategory[];

export function AdminBudgetSection({
  fundRequestId,
  items,
  canEdit,
  cdName,
  onItemsChange,
}: {
  fundRequestId: string;
  items: MfrAdminItem[];
  canEdit: boolean;
  cdName: string;
  onItemsChange?: (next: MfrAdminItem[]) => void;
}) {
  const [draft, setDraft] = useState({
    category:    "Rent"      as AdminBudgetCategory,
    itemName:    "",
    quantity:    1,
    unitCost:    0,
    week:        "Monthly"   as MfrAdminItem["week"],
    justification: "",
  });
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const { pushToast } = useDemoStore();

  const subtotal = items.reduce((s, i) => s + i.totalCost, 0);

  // Persist to the server overlay (so the item survives reload + feeds the
  // budget rollup), then optimistically reflect it in the local view.
  const addItem = () => {
    if (!draft.itemName.trim() || draft.unitCost <= 0) return;
    startTransition(async () => {
      const res = await addAdminItem(fundRequestId, {
        category: draft.category,
        itemName: draft.itemName.trim(),
        quantity: draft.quantity,
        unitCost: draft.unitCost,
        week: draft.week,
        justification: draft.justification.trim() || undefined,
      });
      if (res.ok) {
        onItemsChange?.([...items, res.item]);
        setDraft({ category: "Rent", itemName: "", quantity: 1, unitCost: 0, week: "Monthly", justification: "" });
        router.refresh();
      } else {
        pushToast({
          tone: "warning",
          title: "Couldn't add item",
          body: res.reason === "FORBIDDEN" ? "Only the Country Director can add admin items." : "Check the name and unit cost.",
        });
      }
    });
  };

  const removeItem = (id: string) => {
    startTransition(async () => {
      const res = await removeAdminItem(id);
      if (res.ok) {
        onItemsChange?.(items.filter((i) => i.id !== id));
        router.refresh();
      } else {
        pushToast({
          tone: "warning",
          title: "Couldn't remove item",
          body: res.reason === "FORBIDDEN" ? "Only the Country Director can remove admin items." : "Item no longer exists — refresh.",
        });
      }
    });
  };

  return (
    <section className="card p-4 lg:p-5">
      <header className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <Building2 size={14} className="text-amber-600" />
            Administration Budget
          </h2>
          <p className="text-[12px] muted mt-0.5">
            CD-added admin items — separate from program activity costs but included in the grand total.
          </p>
        </div>
        <div className="text-right">
          <div className="text-[9.5px] muted font-bold uppercase tracking-wide">Admin Subtotal</div>
          <div className="text-[18px] font-extrabold tabular num-hero">
            UGX {subtotal.toLocaleString()}
          </div>
        </div>
      </header>

      {/* Items list */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-[9.5px] uppercase tracking-wide muted font-bold border-b border-[var(--color-edify-divider)]">
              <th className="text-left py-2 pl-1 pr-2">Category</th>
              <th className="text-left py-2 px-2">Item</th>
              <th className="text-right py-2 px-2">Qty</th>
              <th className="text-right py-2 px-2">Unit cost</th>
              <th className="text-right py-2 px-2">Total</th>
              <th className="text-left py-2 px-2">Week</th>
              <th className="text-left py-2 px-2 hidden md:table-cell">Justification</th>
              {canEdit && <th className="w-[36px]" />}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={canEdit ? 8 : 7} className="py-6 text-center text-[12px] muted italic">
                  No administration budget items yet.
                </td>
              </tr>
            )}
            {items.map((it) => (
              <tr key={it.id} className="border-b border-[var(--color-edify-divider)] last:border-b-0">
                <td className="py-2 pl-1 pr-2">
                  <span className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700">
                    {ADMIN_BUDGET_LABEL[it.category]}
                  </span>
                </td>
                <td className="py-2 px-2 font-semibold text-slate-800">{it.itemName}</td>
                <td className="py-2 px-2 text-right tabular muted">{it.quantity.toLocaleString()}</td>
                <td className="py-2 px-2 text-right tabular muted">{it.unitCost.toLocaleString()}</td>
                <td className="py-2 px-2 text-right tabular font-extrabold">{it.totalCost.toLocaleString()}</td>
                <td className="py-2 px-2 muted">{it.week === "Monthly" ? "Monthly" : `W${it.week}`}</td>
                <td className="py-2 px-2 hidden md:table-cell muted truncate max-w-[260px]">{it.justification ?? "—"}</td>
                {canEdit && (
                  <td className="py-2">
                    <button
                      type="button"
                      onClick={() => removeItem(it.id)}
                      title="Remove item"
                      aria-label={`Remove ${it.itemName}`}
                      className="inline-flex items-center justify-center w-7 h-7 rounded-md border border-[var(--color-edify-border)] text-slate-500 hover:text-rose-700 hover:border-rose-200 hover:bg-rose-50"
                    >
                      <Trash2 size={11} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Inline add — only visible to CD */}
      {canEdit && (
        <div className="mt-4 pt-3 border-t border-dashed border-[var(--color-edify-border)]">
          <h3 className="text-[12px] font-extrabold tracking-tight mb-2 inline-flex items-center gap-1.5">
            <Wallet size={11} className="text-amber-600" />
            Add admin item
          </h3>
          <div className="grid grid-cols-2 lg:grid-cols-12 gap-2">
            <div className="lg:col-span-2">
              <Label>Category</Label>
              <select
                value={draft.category}
                onChange={(e) => setDraft({ ...draft, category: e.target.value as AdminBudgetCategory })}
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-amber-300"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{ADMIN_BUDGET_LABEL[c]}</option>
                ))}
              </select>
            </div>
            <div className="lg:col-span-3">
              <Label>Item name</Label>
              <input
                type="text"
                value={draft.itemName}
                onChange={(e) => setDraft({ ...draft, itemName: e.target.value })}
                placeholder="e.g. April rent"
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>
            <div className="lg:col-span-1">
              <Label>Qty</Label>
              <input
                type="number"
                min={1}
                value={draft.quantity}
                onChange={(e) => setDraft({ ...draft, quantity: Number(e.target.value) })}
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>
            <div className="lg:col-span-2">
              <Label>Unit cost (UGX)</Label>
              <input
                type="number"
                min={0}
                value={draft.unitCost}
                onChange={(e) => setDraft({ ...draft, unitCost: Number(e.target.value) })}
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>
            <div className="lg:col-span-2">
              <Label>Week</Label>
              <select
                value={String(draft.week)}
                onChange={(e) => {
                  const v = e.target.value;
                  setDraft({ ...draft, week: v === "Monthly" ? "Monthly" : (Number(v) as 1 | 2 | 3 | 4 | 5) });
                }}
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-amber-300"
              >
                <option value="Monthly">Monthly</option>
                <option value="1">Week 1</option>
                <option value="2">Week 2</option>
                <option value="3">Week 3</option>
                <option value="4">Week 4</option>
                <option value="5">Week 5</option>
              </select>
            </div>
            <div className="lg:col-span-2">
              <Label>Justification</Label>
              <input
                type="text"
                value={draft.justification}
                onChange={(e) => setDraft({ ...draft, justification: e.target.value })}
                placeholder="Optional"
                className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-amber-300"
              />
            </div>
          </div>
          <div className="mt-2 flex items-center justify-end">
            <button
              type="button"
              onClick={addItem}
              disabled={!draft.itemName.trim() || draft.unitCost <= 0 || isPending}
              className={cn(
                "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-extrabold transition-colors",
                draft.itemName.trim() && draft.unitCost > 0 && !isPending
                  ? "bg-amber-600 hover:bg-amber-700 text-white shadow-[0_10px_28px_-12px_rgba(217,119,6,0.45)]"
                  : "bg-slate-100 text-slate-400 cursor-not-allowed",
              )}
            >
              {isPending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
              Add item
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-[10px] font-extrabold text-slate-700 uppercase tracking-wide mb-1">
      {children}
    </label>
  );
}
