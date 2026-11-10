/**
 * Where a dropdown panel goes: always below its button (never flipped up
 * over it), lined up with the button, kept off the screen's edges and clear
 * of the bottom navigation. Pure, so it can be tested without a device.
 */

/** Where a dropdown's button sits on the screen. */
export interface Anchor {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface Screen {
  readonly width: number;
  readonly height: number;
  /** The safe-area inset at the foot (home indicator). */
  readonly bottomInset: number;
}

export interface PanelOptions {
  /**
   * `end` lines the panel's right edge up with the button's (row Actions,
   * More); `start` its left edge; `stretch` makes it the button's width.
   */
  readonly align: 'start' | 'end' | 'stretch';
  readonly width?: number;
  readonly minWidth?: number;
}

export interface Placement {
  readonly top: number;
  readonly maxHeight: number;
  readonly left?: number;
  readonly right?: number;
  readonly width?: number;
  readonly minWidth: number;
  readonly maxWidth: number;
}

/** Space between the button and the panel, as on the web (4–6px). */
export const GAP = 6;
/** The panel never touches the screen's side edges. */
const EDGE = 8;
/** The bottom navigation's height (sizes.bottomNav). */
const BOTTOM_NAV = 56;
/** Breathing room kept above the bottom navigation. */
const NAV_CLEARANCE = 8;
/** A panel is never squeezed shorter than this; it scrolls inside instead. */
const MIN_PANEL = 120;

function floorOf(screen: Screen): number {
  return screen.height - screen.bottomInset - BOTTOM_NAV;
}

export function placePanel(anchor: Anchor, screen: Screen, options: PanelOptions): Placement {
  const top = anchor.y + anchor.height + GAP;
  const maxHeight = Math.max(MIN_PANEL, floorOf(screen) - top);
  const minWidth = options.minWidth ?? 0;

  if (options.align === 'end') {
    const buttonRight = anchor.x + anchor.width;
    const widest = buttonRight - EDGE;
    return {
      top,
      maxHeight,
      right: screen.width - buttonRight,
      width: options.width === undefined ? undefined : Math.min(options.width, widest),
      minWidth: Math.min(minWidth, widest),
      maxWidth: widest,
    };
  }

  const left = Math.max(EDGE, anchor.x);
  const widest = screen.width - left - EDGE;
  const wanted = options.align === 'stretch' ? Math.max(anchor.width, minWidth) : options.width;
  return {
    top,
    maxHeight,
    left,
    width: wanted === undefined ? undefined : Math.min(wanted, widest),
    minWidth: Math.min(minWidth, widest),
    maxWidth: widest,
  };
}

/**
 * How far the page must scroll up for a panel of `panelHeight` to fit below
 * its button; 0 when it already fits. Capped at 60% of the screen, past which
 * the panel scrolls inside itself.
 */
export function roomToMake(anchor: Anchor, panelHeight: number, screen: Screen): number {
  const wanted = Math.min(panelHeight, screen.height * 0.6);
  const floor = floorOf(screen) - NAV_CLEARANCE;
  return Math.max(0, anchor.y + anchor.height + GAP + wanted - floor);
}
