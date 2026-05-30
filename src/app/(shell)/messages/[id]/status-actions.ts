"use server";

// Per-recipient status server actions — wired into MessageActionBar.
//
// All five actions share one shape: they take a `messageId` from the
// form (the user is implied by the session), call
// `updateRecipientStatus`, then revalidate every path the inbox /
// detail page is rendered at so the change is reflected on the next
// render.
//
// Re-validation paths:
//   • /messages and /messages/[id]            (shell)
//   • /partner/messages and /partner/messages/[id]
//
// We revalidate both unconditionally because a message might be
// visible in either surface depending on the user's role. The cost
// is negligible (Next caches each route independently).

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { updateRecipientStatus } from "@/lib/messages-v2/mock";

async function applyStatus(
  messageId: string,
  status: "read" | "unread" | "acknowledged" | "resolved" | "archived",
  /** Skip revalidation — caller is inside render and Next.js 15
   *  disallows `revalidatePath` from a render path. The state change
   *  still lands in the mutable mock store; the next request renders
   *  fresh data anyway. */
  skipRevalidate = false,
): Promise<{ ok: boolean }> {
  if (!messageId) return { ok: false };
  const user = await getCurrentUser();
  const result = updateRecipientStatus(messageId, user.staffId, status);
  if (!skipRevalidate) {
    // Form-submission paths can safely revalidate — they run outside
    // render.  Mutates every surface the message could appear on so
    // the inbox badge clears immediately.
    revalidatePath("/messages");
    revalidatePath(`/messages/${messageId}`);
    revalidatePath("/partner/messages");
    revalidatePath(`/partner/messages/${messageId}`);
  }
  return { ok: result.ok };
}

export async function markReadAction(formData: FormData) {
  await applyStatus(String(formData.get("messageId") ?? ""), "read");
}

export async function markUnreadAction(formData: FormData) {
  await applyStatus(String(formData.get("messageId") ?? ""), "unread");
}

export async function acknowledgeAction(formData: FormData) {
  await applyStatus(String(formData.get("messageId") ?? ""), "acknowledged");
}

export async function markResolvedAction(formData: FormData) {
  await applyStatus(String(formData.get("messageId") ?? ""), "resolved");
}

export async function archiveAction(formData: FormData) {
  await applyStatus(String(formData.get("messageId") ?? ""), "archived");
}

/** Silent mark-as-read for the detail page. Server components call
 *  this once on render so opening a message updates the user's badge
 *  count without an explicit click. Idempotent — no-op for already-
 *  read recipients (the mutator handles it).
 *
 *  Skips revalidatePath because Next.js 15 throws when revalidation
 *  is triggered from inside a render. The mock state mutation is
 *  enough — the next time the user navigates to /messages the
 *  inbox renders the updated count. */
export async function markReadOnView(messageId: string): Promise<void> {
  if (!messageId) return;
  await applyStatus(messageId, "read", /* skipRevalidate */ true);
}
