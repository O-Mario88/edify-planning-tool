// Edify motion system.
//
// Motion encodes meaning, not decoration. Every animation in the app
// should pull from one of the tokens below. Two reasons:
//
//   1. Consistency. A KPI tile entrance, a leadership-attention row
//      reveal, and an approval-row hover should feel like the same
//      product even though they live in different files.
//   2. Calm. Users stare at these dashboards for hours. We default
//      to short, soft springs — never bouncy, never long.
//
// Token vocabulary:
//
//   • `easing.standard`     — the default ease for most fades / slides.
//                             Slightly faster out than in.
//   • `easing.emphasized`   — for outgoing items that should feel decisive
//                             (approval row leaving the queue).
//   • `spring.soft`         — KPI counters, donut fills, progress bars.
//                             Gentle settle, no overshoot.
//   • `spring.pop`          — Successful state changes (approved, saved).
//                             Light overshoot to telegraph success.
//   • `duration.*`          — Plain ms numbers for non-spring animations.
//   • `stagger.row` / `stagger.tile` — Per-child delays for list reveals.
//
// Respect for prefers-reduced-motion is handled at the component level
// via `useReducedMotion()` from framer-motion (`motion/react`). When
// that returns true, components should swap to instant transitions.

import type { Transition, Variants } from "motion/react";

// ────────── Easings ──────────

export const easing = {
  // Custom cubic-bezier curves. These are the same ones used by
  // top-tier design systems (Linear, Vercel) — fast start, soft settle.
  standard:   [0.2, 0.0, 0.0, 1.0] as const,
  emphasized: [0.3, 0.0, 0.0, 1.0] as const,
  enter:      [0.0, 0.0, 0.0, 1.0] as const,
  exit:       [0.4, 0.0, 1.0, 1.0] as const,
} satisfies Record<string, readonly [number, number, number, number]>;

// ────────── Durations (ms) ──────────

export const duration = {
  instant: 80,
  fast:    160,
  base:    220,
  slow:    320,
  slowest: 480,
} as const;

// ────────── Spring presets ──────────

export const spring = {
  // Soft settle, no overshoot. Default for any numeric value that
  // animates to a new target (donut percentage, progress bar fill,
  // KPI count-up).
  soft: {
    type: "spring",
    stiffness: 180,
    damping: 24,
    mass: 0.9,
  } satisfies Transition,

  // Tiny overshoot. Reserve for genuine "yes!" moments — a row
  // resolving into the Disbursed tray, a target hitting On Track.
  pop: {
    type: "spring",
    stiffness: 320,
    damping: 22,
    mass: 0.7,
  } satisfies Transition,

  // Snappy hover lift on interactive cards. No overshoot.
  hover: {
    type: "spring",
    stiffness: 400,
    damping: 30,
    mass: 0.6,
  } satisfies Transition,
} as const;

// ────────── Stagger delays ──────────

export const stagger = {
  // Row reveal (Leadership Attention, table rows): 40ms between rows.
  // Below 40 feels glitchy; above 80 feels slow.
  row:  0.04,
  // Tile reveal (KPI grid): 30ms between tiles. KPI grids have more
  // children, so we keep the cumulative reveal under ~250ms.
  tile: 0.03,
  // Small lists in a hero card (3-5 items): a bit more breathing room.
  hero: 0.06,
} as const;

// ────────── Reusable variants ──────────

// Fade-up — the workhorse. Used by KPI tiles, attention cards,
// section headers. Looks calm at any duration.
export const fadeUp: Variants = {
  hidden:  { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
};

// Fade-up with stronger lift, for hero-class content (the
// `WhatChangedHero`, the My Plan card).
export const heroFadeUp: Variants = {
  hidden:  { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
};

// Subtle scale-in for KPI numerals counting up alongside the tile fade.
export const numIn: Variants = {
  hidden:  { opacity: 0, scale: 0.96 },
  visible: { opacity: 1, scale: 1 },
};

// Soft glow used on alert cards when they first land. Pairs with
// fadeUp on the same element.
export const alertGlow: Variants = {
  hidden:  { boxShadow: "0 0 0 rgba(0,0,0,0)" },
  visible: { boxShadow: "0 8px 24px -12px rgba(15,23,32,0.12)" },
};

// ────────── Helpers ──────────

// Container variants that propagate stagger to children. Both params
// are typed as plain `number` so callers can pass any of `stagger.*`
// without TS narrowing the literal type.
export function staggerContainer(delayChildren: number = 0.05, staggerChildren: number = stagger.tile): Variants {
  return {
    hidden:  {},
    visible: {
      transition: { delayChildren, staggerChildren },
    },
  };
}

// Standard transition object you can spread into any `transition` prop.
export const tEnter: Transition = { duration: duration.base / 1000, ease: easing.enter };
export const tExit:  Transition = { duration: duration.fast / 1000, ease: easing.exit  };
export const tStandard: Transition = { duration: duration.base / 1000, ease: easing.standard };
