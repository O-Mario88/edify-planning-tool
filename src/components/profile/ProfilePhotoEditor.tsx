"use client";

// ProfilePhotoEditor — upload / replace / remove your headshot.
//
// Lives in the profile-edit section and works for EVERY role (the profile page
// is shared). Reads the chosen image as a data URL and stores it per-staffId via
// the profile-photo store, so the new headshot immediately replaces the initials
// avatar everywhere (sidebar profile, profile hero).

import { useEffect, useRef, useState } from "react";
import { Camera, Trash2 } from "lucide-react";
import { ProfileAvatar } from "@/components/ui/ProfileAvatar";
import { getProfilePhoto, setProfilePhoto, clearProfilePhoto } from "@/lib/profile-photo-store";

const MAX_BYTES = 3 * 1024 * 1024; // 3 MB

export function ProfilePhotoEditor({
  staffId,
  name,
  initials,
  color = "#2f5f7a",
}: {
  staffId: string;
  name: string;
  initials: string;
  color?: string;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [hasPhoto, setHasPhoto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Re-mount the avatar after a change so it re-reads the store immediately.
  const [bump, setBump] = useState(0);

  // Sync hasPhoto on mount (client-only store; avoids a hydration mismatch).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHasPhoto(!!getProfilePhoto(staffId));
  }, [staffId]);

  function pick() {
    setError(null);
    fileRef.current?.click();
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Please choose an image file (JPG, PNG, or WebP).");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Image is too large — keep it under 3 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setProfilePhoto(staffId, String(reader.result));
      setHasPhoto(true);
      setBump((b) => b + 1);
    };
    reader.onerror = () => setError("Couldn't read that image. Try another file.");
    reader.readAsDataURL(file);
  }

  function remove() {
    clearProfilePhoto(staffId);
    setHasPhoto(false);
    setBump((b) => b + 1);
    setError(null);
  }

  return (
    <div className="flex items-center gap-4">
      {/* The camera badge IS the upload control — click the avatar to pick a
          photo. No separate "Upload photo" button. */}
      <button
        type="button"
        onClick={pick}
        aria-label={hasPhoto ? "Replace your profile photo" : "Upload a profile photo"}
        title={hasPhoto ? "Replace photo" : "Upload photo"}
        className="relative group rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)] focus-visible:ring-offset-2"
      >
        <ProfileAvatar key={bump} staffId={staffId} name={name} initials={initials} color={color} size={64} rounded="full" ring />
        <span className="absolute -bottom-0.5 -right-0.5 h-6 w-6 rounded-full bg-[var(--color-edify-primary)] text-white grid place-items-center ring-2 ring-[var(--color-card)] shadow group-hover:scale-105 transition-transform">
          <Camera size={13} />
        </span>
      </button>

      <div className="min-w-0">
        <div className="text-body font-semibold">Profile photo</div>
        <div className="text-[11px] muted leading-snug">Tap the camera to {hasPhoto ? "replace" : "upload"} your headshot. JPG, PNG, or WebP · up to 3 MB.</div>
        {hasPhoto && (
          <button
            type="button"
            onClick={remove}
            className="mt-2 inline-flex items-center gap-1.5 text-[12px] font-semibold text-rose-600 hover:underline"
          >
            <Trash2 size={13} /> Remove photo
          </button>
        )}
        {error && <div className="mt-1.5 text-[11px] text-rose-600">{error}</div>}
      </div>

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onFile} />
    </div>
  );
}
