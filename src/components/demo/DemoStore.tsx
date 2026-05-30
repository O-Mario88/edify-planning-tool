"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";

// Client-side overlay store for demo interactivity. Server pages render the
// base data; this layer applies live status / audit / toast changes that
// persist across navigations via localStorage. Production swaps this for
// real server actions + DB writes.

const STORAGE_KEY = "edify-demo-store-v1";

// ────────── Types ──────────

export type DemoApprovalAction =
  | "PL_APPROVE"
  | "PL_RETURN"
  | "CD_APPROVE"
  | "CD_AMEND"
  | "CD_RETURN"
  | "CD_SUBMIT_TO_RVP"
  | "RVP_FINAL_APPROVE"
  | "RVP_RETURN"
  | "ACTIVATE"
  | "DISBURSE";

export type SubmissionOverlay = {
  status?:         string;
  amendedBudget?:  number;
  amendments?:     { id: string; amount: number; reason: string; comment: string; at: string; by: string }[];
  auditAppend?:    { at: string; actor: string; role: string; action: string; comment?: string; previousStatus?: string; newStatus?: string }[];
  lastUpdatedAt?:  string;
};

export type DemoState = {
  submissions: Record<string, SubmissionOverlay>;
};

export type Toast = {
  id:      string;
  tone:    "success" | "warning" | "error" | "info";
  title:   string;
  body?:   string;
  ttl?:    number; // ms
};

type Ctx = {
  state:        DemoState;
  applyAction:  (submissionId: string, action: DemoApprovalAction, payload?: { amount?: number; reason?: string; comment?: string }) => void;
  reset:        () => void;
  toasts:       Toast[];
  pushToast:    (t: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
};

const DemoStoreCtx = createContext<Ctx | null>(null);

// ────────── Default → next status mapping ──────────

const NEXT_STATUS: Record<DemoApprovalAction, string> = {
  PL_APPROVE:        "Approved by Program Lead",
  PL_RETURN:         "Returned by Program Lead",
  CD_APPROVE:        "Approved by Country Director",
  CD_AMEND:          "Amended by Country Director",
  CD_RETURN:         "Returned by Country Director",
  CD_SUBMIT_TO_RVP:  "Submitted to RVP",
  RVP_FINAL_APPROVE: "Final Approved",
  RVP_RETURN:        "Returned by RVP",
  ACTIVATE:          "Active Funding Plan",
  DISBURSE:          "Disbursed",
};

const ACTION_LABEL: Record<DemoApprovalAction, string> = {
  PL_APPROVE:        "Program Lead approved",
  PL_RETURN:         "Program Lead returned",
  CD_APPROVE:        "Country Director approved",
  CD_AMEND:          "Country Director amended budget",
  CD_RETURN:         "Country Director returned",
  CD_SUBMIT_TO_RVP:  "Submitted to RVP",
  RVP_FINAL_APPROVE: "RVP final-approved",
  RVP_RETURN:        "RVP returned",
  ACTIVATE:          "Funding plan activated",
  DISBURSE:          "Funds disbursed",
};

// ────────── Provider ──────────

function readPersistedState(): DemoState {
  if (typeof window === "undefined") return { submissions: {} };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { submissions: {} };
    return JSON.parse(raw) as DemoState;
  } catch {
    return { submissions: {} };
  }
}

export function DemoStoreProvider({ children }: { children: ReactNode }) {
  // Lazy initialiser reads localStorage once on mount — avoids the
  // React-compiler error about setState inside a useEffect.
  const [state, setState] = useState<DemoState>(readPersistedState);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // Persist on every change.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch { /* quota or private-mode — fine */ }
  }, [state]);

  const pushToast = useCallback((t: Omit<Toast, "id">) => {
    const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev, { id, ttl: 4500, ...t }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const applyAction = useCallback((
    submissionId: string,
    action: DemoApprovalAction,
    payload?: { amount?: number; reason?: string; comment?: string },
  ) => {
    const at = new Date().toISOString().replace("T", " · ").slice(0, 19);
    const newStatus = NEXT_STATUS[action];
    const label = ACTION_LABEL[action];

    setState((prev) => {
      const existing = prev.submissions[submissionId] ?? {};
      const auditAppend = [
        ...(existing.auditAppend ?? []),
        {
          at,
          actor: "Demo session",
          role:  inferRoleFromAction(action),
          action: actionVerb(action),
          comment: payload?.comment ?? payload?.reason,
          previousStatus: existing.status,
          newStatus,
        },
      ];
      const amendments = action === "CD_AMEND" && payload?.amount != null && payload?.reason
        ? [
            ...(existing.amendments ?? []),
            {
              id: `am-${Date.now()}`,
              amount: payload.amount,
              reason: payload.reason,
              comment: payload.comment ?? "",
              at,
              by: "Demo session",
            },
          ]
        : existing.amendments;

      return {
        ...prev,
        submissions: {
          ...prev.submissions,
          [submissionId]: {
            ...existing,
            status: newStatus,
            amendedBudget: action === "CD_AMEND" && payload?.amount != null
              ? payload.amount
              : existing.amendedBudget,
            amendments,
            auditAppend,
            lastUpdatedAt: at,
          },
        },
      };
    });

    pushToast({
      tone: action.includes("RETURN") ? "warning" : action.includes("AMEND") ? "info" : "success",
      title: label,
      body:  payload?.reason ?? payload?.comment ?? `Status → ${newStatus}`,
    });
  }, [pushToast]);

  const reset = useCallback(() => {
    setState({ submissions: {} });
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    pushToast({ tone: "info", title: "Demo state reset", body: "All overlays cleared. Server data is unchanged." });
  }, [pushToast]);

  return (
    <DemoStoreCtx.Provider value={{ state, applyAction, reset, toasts, pushToast, dismissToast }}>
      {children}
    </DemoStoreCtx.Provider>
  );
}

export function useDemoStore(): Ctx {
  const ctx = useContext(DemoStoreCtx);
  if (!ctx) throw new Error("useDemoStore must be used inside DemoStoreProvider");
  return ctx;
}

function inferRoleFromAction(a: DemoApprovalAction): string {
  if (a.startsWith("PL_"))   return "Program Lead";
  if (a.startsWith("CD_"))   return "Country Director";
  if (a.startsWith("RVP_"))  return "RVP";
  return "Program Accountant";
}

function actionVerb(a: DemoApprovalAction): "Approved" | "Returned" | "Amended" | "Submitted to RVP" | "Activated" | "Disbursed" {
  if (a === "PL_APPROVE" || a === "CD_APPROVE" || a === "RVP_FINAL_APPROVE") return "Approved";
  if (a === "PL_RETURN" || a === "CD_RETURN" || a === "RVP_RETURN")            return "Returned";
  if (a === "CD_AMEND")                                                        return "Amended";
  if (a === "CD_SUBMIT_TO_RVP")                                                return "Submitted to RVP";
  if (a === "ACTIVATE")                                                        return "Activated";
  return "Disbursed";
}
