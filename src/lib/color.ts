// Tiny colour utilities — pick a readable ink colour for any background so
// labels printed on a coloured chip/segment/donut never disappear (e.g. white
// text on a light amber or slate segment). Pure & client-safe.

function parseHex(hex: string): [number, number, number] | null {
  const m = hex.trim().replace(/^#/, "");
  if (m.length === 3) {
    const r = parseInt(m[0] + m[0], 16), g = parseInt(m[1] + m[1], 16), b = parseInt(m[2] + m[2], 16);
    return [r, g, b];
  }
  if (m.length === 6) {
    return [parseInt(m.slice(0, 2), 16), parseInt(m.slice(2, 4), 16), parseInt(m.slice(4, 6), 16)];
  }
  return null;
}

/** Relative luminance (0–1) per WCAG. */
export function luminance(hex: string): number {
  const rgb = parseHex(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * The readable ink for text on `bg`: near-black on light backgrounds, white on
 * dark. Threshold 0.55 keeps mid-tones (amber, cyan) legible with dark ink.
 */
export function readableInk(bg: string, dark = "#0b1220", light = "#ffffff"): string {
  return luminance(bg) > 0.55 ? dark : light;
}
