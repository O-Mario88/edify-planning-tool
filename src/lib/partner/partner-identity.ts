// Resolve the signed-in user to the partner organisation they belong to.
// Demo partner accounts map by email → PartnerUser → partnerId.

import { getCurrentUser } from "@/lib/auth";
import { partnerUserByEmail, partnerById } from "./partner-mock";
import type { Partner } from "./partner-types";

export async function getCurrentPartner(): Promise<Partner | null> {
  const user = await getCurrentUser();
  const pu = partnerUserByEmail(user.email);
  if (!pu) return null;
  return partnerById(pu.partnerId) ?? null;
}

export async function getPartnerIdForCurrentUser(): Promise<string | null> {
  return (await getCurrentPartner())?.id ?? null;
}
