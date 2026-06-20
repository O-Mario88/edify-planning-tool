// Email handling for social sign-in.
//
// SECURITY: normalization is `trim` + `lowercase` ONLY. It deliberately does
// NOT strip a `+tag` or dots. The registered-email gate matches the normalized
// provider email against the canonical local email exactly, so:
//   • jane@edify.org      → matches jane@edify.org              ✓
//   • jane+test@edify.org → does NOT match jane@edify.org       ✗ (no plus bypass)
//   • Jane@Edify.ORG      → matches jane@edify.org (case-fold)  ✓
// A `+tag` address only works if it was onboarded under that exact address.
//
// Edge-safe: TextEncoder + Web Crypto only (the hash is used in audit logs).

export function normalizeEmail(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim().toLowerCase();
  // A usable email has a single @ with non-empty local + domain parts.
  if (trimmed.length < 3) return null;
  const at = trimmed.indexOf("@");
  if (at <= 0 || at !== trimmed.lastIndexOf("@") || at === trimmed.length - 1) return null;
  if (trimmed.includes(" ")) return null;
  return trimmed;
}

/** True when the local part carries a `+tag` (e.g. jane+test@edify.org). */
export function hasPlusTag(email: string): boolean {
  const at = email.indexOf("@");
  if (at < 0) return false;
  return email.slice(0, at).includes("+");
}

/** SHA-256 hex of the normalized email — logged instead of the raw email where
 *  the raw value isn't needed, so audit trails avoid unnecessary PII. */
export async function emailHash(email: string): Promise<string> {
  const data = new TextEncoder().encode(email.trim().toLowerCase());
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
