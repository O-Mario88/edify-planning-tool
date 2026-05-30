"use client";

// InteractiveTile — clickable wrapper that turns any KPI/metric tile
// into a filter trigger. Renders a button (or a plain div if no
// onClick) and applies the selected/hover/disabled affordances per
// the design brief.
//
// Visuals are kept utility-driven so each call site keeps full control
// over its internal layout (the existing KpiTile / PackageTile bodies
// are unchanged). We only own the wrapping surface — border colour
// flips, lift on hover, active state border + halo, cursor pointer.

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
  disabled?: boolean;
  /** When true, render a non-interactive surface but keep visual parity. */
  asStatic?: boolean;
};

export const InteractiveTile = forwardRef<HTMLButtonElement, Props>(
  function InteractiveTile(
    { active = false, disabled = false, asStatic = false, className, children, ...rest },
    ref,
  ) {
    if (asStatic) {
      return (
        <div className={cn("tile-filter-tile", className)} aria-current={active ? "true" : undefined}>
          {children}
        </div>
      );
    }
    return (
      <button
        ref={ref}
        type="button"
        disabled={disabled}
        aria-pressed={active}
        className={cn(
          "tile-filter-tile tile-filter-tile-clickable text-left w-full",
          active && "tile-filter-tile-active",
          disabled && "tile-filter-tile-disabled",
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    );
  },
);
