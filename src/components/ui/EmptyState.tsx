import { type ReactNode } from "react";
import { Inbox, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// First-impression card for empty surfaces.
//
// Premium products treat first-run as a feature, not a side effect.
// This component gives every empty list / panel / category the same
// shape: soft tinted halo, leading icon tile, two-line story, and an
// optional primary action. Drop-in API matches the older minimal
// version (`Icon`, `title`, `body`, `action`) so existing call sites
// keep working — they just get a better look for free.

export type EmptyStateTone =
  | "neutral"
  | "violet"
  | "emerald"
  | "amber"
  | "rose"
  | "sky";

const TONE: Record<EmptyStateTone, { halo: string; iconBg: string; iconText: string }> = {
  neutral: { halo: "from-slate-50",   iconBg: "bg-slate-100",   iconText: "text-slate-500"   },
  violet:  { halo: "from-violet-50",  iconBg: "bg-violet-100",  iconText: "text-violet-600 dark:text-violet-300"  },
  emerald: { halo: "from-emerald-50", iconBg: "bg-emerald-100", iconText: "text-emerald-600 dark:text-emerald-300" },
  amber:   { halo: "from-amber-50",   iconBg: "bg-amber-100",   iconText: "text-amber-600 dark:text-amber-300"   },
  rose:    { halo: "from-rose-50",    iconBg: "bg-rose-100",    iconText: "text-rose-600 dark:text-rose-300"    },
  sky:     { halo: "from-sky-50",     iconBg: "bg-sky-100",     iconText: "text-sky-600 dark:text-sky-300"     },
};

export function EmptyState({
  Icon = Inbox,
  title,
  body,
  action,
  tone = "neutral",
  compact = false,
  bare = false,
  className,
}: {
  Icon?:     LucideIcon;
  title:     string;
  body?:     string;
  /** Pre-built action node (e.g. a custom button). Rendered below the body. */
  action?:   ReactNode;
  /** Halo + icon-tile tone. Picks the personality of the page (e.g.
   *  `violet` for partners, `sky` for resources). */
  tone?:     EmptyStateTone;
  /** Smaller padding + icon. Use inside dense cards / sections. */
  compact?:  boolean;
  /** Disable the card chrome (border + background) — for callers that
   *  embed the empty state inside an already-card-shaped container. */
  bare?:     boolean;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={cn(
        "relative overflow-hidden",
        !bare && "rounded-2xl border border-[var(--color-edify-divider)] bg-white",
        compact ? "px-5 py-6" : "px-6 py-10",
        className,
      )}
    >
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b to-transparent opacity-60",
          t.halo,
        )}
      />
      <div className="relative flex flex-col items-center text-center max-w-md mx-auto">
        <span
          className={cn(
            "rounded-2xl grid place-items-center shrink-0",
            t.iconBg, t.iconText,
            compact ? "h-12 w-12" : "h-14 w-14",
          )}
        >
          <Icon size={compact ? 20 : 24} />
        </span>
        <h3 className={cn("font-extrabold tracking-tight mt-3", compact ? "text-[13.5px]" : "text-[15px]")}>
          {title}
        </h3>
        {body && (
          <p className={cn("text-secondary mt-1.5 leading-snug", compact ? "text-[11.5px]" : "text-body")}>
            {body}
          </p>
        )}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}
