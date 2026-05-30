// Shared types for the system-wide interactive tile filter pattern.
//
// Every meaningful KPI tile, summary card, or status chip in the app can
// register a `TileFilterSpec` and become a clickable filter trigger. The
// page reads the active filter from the URL (`?tileFilter=<id>`) and
// renders a focused detail view showing exactly the records behind the
// tile.
//
// The model is intentionally tile-id driven (one stable string per
// meaningful tile) rather than splitting into many small URL params —
// this keeps the URL terse and lets each consumer encode whatever
// dimension shape it needs (visit number, training number, status enum).

export type TileFilterEntityType =
  | "school"
  | "cluster"
  | "activity"
  | "visit"
  | "training"
  | "ssa"
  | "evidence"
  | "payment"
  | "partner"
  | "staff"
  | "message"
  | "notification"
  | "approval"
  | "debrief"
  | "donor_metric"
  | "hr_case"
  | "reschedule"
  | "finance_record";

export type TileFilterAction = {
  label: string;
  href?: string;
  onClick?: () => void;
};

export type TileFilterSpec = {
  /** Stable id used in the URL (`?tileFilter=missing-second-visit`). */
  id: string;
  /** Display title shown in the active filter header. */
  label: string;
  /** One-line explanation shown under the header. */
  description: string;
  /** Type of records returned — drives the result list shape. */
  entityType: TileFilterEntityType;
  /** Optional primary action to surface in the result header. */
  primaryAction?: TileFilterAction;
};
