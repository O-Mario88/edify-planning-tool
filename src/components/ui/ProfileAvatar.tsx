"use client";

// ProfileAvatar — the one avatar that shows a user's uploaded headshot.
//
// Renders the staff member's photo (a framed circle) when they've uploaded one,
// otherwise a coloured initials disc. Subscribes to the photo store so the
// avatar updates live the moment a new headshot is saved — no reload. Used in
// the sidebar profile and on the profile page.

import { useEffect, useState } from "react";
import { getProfilePhoto, subscribeProfilePhoto } from "@/lib/profile-photo-store";
import { cn } from "@/lib/utils";

export function ProfileAvatar({
  staffId,
  name,
  initials,
  color = "#2f5f7a",
  size = 40,
  rounded = "full",
  ring = true,
  className,
}: {
  staffId: string;
  name: string;
  initials: string;
  color?: string;
  size?: number;
  rounded?: "full" | "xl" | "2xl";
  ring?: boolean;
  className?: string;
}) {
  // Start undefined on both server and first client render to avoid a hydration
  // mismatch; the effect fills it in (and on every later change).
  const [photo, setPhoto] = useState<string | undefined>(undefined);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhoto(getProfilePhoto(staffId));
    return subscribeProfilePhoto(() => setPhoto(getProfilePhoto(staffId)));
  }, [staffId]);

  const radius = rounded === "full" ? "rounded-full" : rounded === "2xl" ? "rounded-2xl" : "rounded-xl";
  const frame = ring ? "ring-2 ring-white/15 shadow-[0_1px_3px_rgba(0,0,0,0.25)]" : "";
  const dim = { width: size, height: size } as const;

  if (photo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- user data-URL upload, not a static asset
      <img
        src={photo}
        alt={name}
        style={dim}
        className={cn("object-cover select-none shrink-0", radius, frame, className)}
      />
    );
  }

  return (
    <span
      aria-label={name}
      style={{ ...dim, background: color, fontSize: Math.round(size * 0.36) }}
      className={cn("grid place-items-center text-white font-extrabold select-none shrink-0", radius, frame, className)}
    >
      {initials}
    </span>
  );
}
