import { getCurrentUser } from "@/lib/auth";
import { EdifySidebar, type EdifyRole } from "@/components/shell/EdifySidebar";
import { orgStaff } from "@/lib/org/supervision";
import { districtNameOf } from "@/lib/geography";

// Server-component wrapper that resolves the active user from the session
// cookie (lib/auth.ts) and renders the existing client-side EdifySidebar
// with the right role + identity. Pages just drop in <EdifySidebarServer />
// — no role hardcoding, no drift between roles and the actual logged-in
// user.
//
// Use the optional `roleOverride` to force a sidebar variant for a screen
// that's role-specific regardless of who's looking (e.g. the HR-only
// support-review tab). 99% of pages should pass nothing.

// The staff member's PRIMARY district. Runtime-created staff carry a real
// primaryDistrictId; this map covers the seeded demo logins so the sidebar
// profile shows a real home district rather than a blank.
const DEMO_PRIMARY_DISTRICT: Record<string, string> = {
  "STF-PC-001": "Mukono",  "STF-DM-014": "Wakiso",  "STF-AD-021": "Gulu",
  "STF-SO-007": "Kampala", "STF-EW-003": "Kampala", "STF-AW-019": "Kampala",
  "STF-MT-031": "Kampala", "STF-GA-042": "Kampala", "STF-GN-007": "Mbale",
  "STF-JO-022": "Wakiso",  "STF-PM-031": "Mbarara", "STF-AH-044": "Gulu",
  "STF-PM-052": "Soroti",  "STF-AD-001": "Kampala",
};

function primaryDistrict(staffId: string): string | undefined {
  const pid = orgStaff(staffId)?.primaryDistrictId;
  if (pid) return districtNameOf(pid);
  return DEMO_PRIMARY_DISTRICT[staffId];
}

// Stable per-user avatar colour (initials fallback when no headshot uploaded).
const AVATAR_COLORS = ["#10b981", "#2f5f7a", "#7c5cff", "#e0792b", "#0ea5e9", "#db2777", "#0d9488"];
function avatarColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

export async function EdifySidebarServer({
  roleOverride,
}: {
  roleOverride?: EdifyRole;
} = {}) {
  const user = await getCurrentUser();
  return (
    <EdifySidebar
      role={roleOverride ?? user.role}
      user={{
        staffId: user.staffId,
        name: user.name,
        initials: user.initials,
        color: avatarColor(user.staffId),
        district: primaryDistrict(user.staffId),
        online: true,
      }}
    />
  );
}
