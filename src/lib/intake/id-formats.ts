// Canonical ID formats — the shapes the platform accepts + validates on intake.
//
// These match the source systems the IA team enters from:
//   School   32791       — digits only
//   Visit    SVE-88273   — "SVE-" + digits
//   Training TS-50294    — "TS-"  + digits
//   Expense  6161        — digits only
//
// Pure & client-safe so both the drawers (inline validation) and the server
// actions (authoritative validation) share one definition.

export type IdKind = "school" | "visit" | "training" | "expense";

export const ID_FORMATS: Record<IdKind, { label: string; pattern: RegExp; example: string; hint: string }> = {
  school:   { label: "School ID",   pattern: /^\d{4,6}$/,     example: "32791",     hint: "digits only, e.g. 32791" },
  visit:    { label: "Visit ID",    pattern: /^SVE-\d{4,6}$/, example: "SVE-88273", hint: "SVE- followed by digits, e.g. SVE-88273" },
  training: { label: "Training ID", pattern: /^TS-\d{4,6}$/,  example: "TS-50294",  hint: "TS- followed by digits, e.g. TS-50294" },
  expense:  { label: "Expense ID",  pattern: /^\d{3,6}$/,     example: "6161",      hint: "digits only, e.g. 6161" },
};

/** True when `value` matches the canonical format for `kind`. */
export function isValidId(kind: IdKind, value: string | undefined | null): boolean {
  if (value == null) return false;
  return ID_FORMATS[kind].pattern.test(value.trim());
}

/** Returns a human error string when `value` is malformed, else null. */
export function idFormatError(kind: IdKind, value: string | undefined | null): string | null {
  const f = ID_FORMATS[kind];
  if (!value || !value.trim()) return `${f.label} is required.`;
  if (!f.pattern.test(value.trim())) return `${f.label} must be ${f.hint}.`;
  return null;
}
