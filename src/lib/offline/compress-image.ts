"use client";

// Client-side image compression (spec layer #9). Evidence photos off a phone are
// often 3–8 MB — far too heavy for a weak rural uplink. This downsizes + re-
// encodes to JPEG in the browser before upload, cutting most photos to a few
// hundred KB. Returns the original untouched if it isn't a raster image or if
// anything goes wrong (never block an upload because compression failed).

export type CompressOptions = {
  /** Longest edge in px (default 1600 — plenty for attendance/evidence). */
  maxDim?: number;
  /** JPEG quality 0–1 (default 0.7). */
  quality?: number;
};

export async function compressImage(file: File, opts: CompressOptions = {}): Promise<File> {
  const { maxDim = 1600, quality = 0.7 } = opts;
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;

  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);

    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close?.();

    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/jpeg", quality),
    );
    if (!blob || blob.size >= file.size) return file; // no win — keep original

    const name = file.name.replace(/\.(png|webp|jpe?g|heic|heif)$/i, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  }
}
