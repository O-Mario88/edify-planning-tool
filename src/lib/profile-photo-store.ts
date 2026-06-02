"use client";

// Profile-photo store — per-staff headshots a user uploads for their avatar.
//
// Year-1 demo: photos live in localStorage as data URLs, keyed by staffId, so
// the uploaded headshot shows everywhere the avatar renders (sidebar profile,
// profile page) and survives reloads on this device. Year-2 swaps this single
// file for an upload endpoint + CDN URL — every reader goes through
// getProfilePhoto()/subscribeProfilePhoto(), so the UI doesn't change.

const KEY = "edify.profilePhotos.v1";

type PhotoMap = Record<string, string>; // staffId -> data URL

function readAll(): PhotoMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as PhotoMap) : {};
  } catch {
    return {};
  }
}

const subs = new Set<() => void>();
function emit() { subs.forEach((cb) => cb()); }

function writeAll(map: PhotoMap) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(map));
  } catch {
    // quota / serialization failure — ignore in the demo
  }
  emit();
}

export function getProfilePhoto(staffId: string): string | undefined {
  if (!staffId) return undefined;
  return readAll()[staffId];
}

export function setProfilePhoto(staffId: string, dataUrl: string) {
  if (!staffId) return;
  const map = readAll();
  map[staffId] = dataUrl;
  writeAll(map);
}

export function clearProfilePhoto(staffId: string) {
  const map = readAll();
  if (map[staffId]) {
    delete map[staffId];
    writeAll(map);
  }
}

/** Subscribe to photo changes (and cross-tab updates). Returns an unsubscribe. */
export function subscribeProfilePhoto(cb: () => void): () => void {
  subs.add(cb);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) cb(); };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    subs.delete(cb);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}
