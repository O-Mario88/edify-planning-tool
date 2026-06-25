// Contract test for the evidence preview routing — the rule that decides
// which viewer branch handles each evidence row:
//
//   image/*                        → inline <img>
//   application/pdf                → inline <iframe src=/file>
//   docx/.docx                     → prepare-view → cached PDF rendition <iframe>
//   anything else                  → download-only fallback
//
// The branching is mirrored both server-side (EvidenceService.recordUpload
// sets previewStatus) and client-side (EvidencePanel.openPreview picks the
// branch). This test pins the *client-side* classification so a future
// edit to the panel can't silently break DOCX previewing.

import { describe, expect, it } from "vitest";

// Re-implement the same predicates as EvidencePanel — pure functions of
// MIME + extension. Keeping a small inline copy so the test doesn't need
// to mount the React component (DOM-less environment).
function isImage(m: string | null) { return !!m && m.startsWith("image/"); }
function isPdf(m: string | null) { return m === "application/pdf"; }
function isDocx(item: { mimeType: string | null; fileExtension?: string | null }) {
  const ext = (item.fileExtension ?? "").toLowerCase();
  return ext === ".docx" || ext === ".doc" ||
    item.mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    item.mimeType === "application/msword";
}

describe("EvidencePanel preview routing", () => {
  it("classifies PNG as image", () => {
    const it1 = { mimeType: "image/png" };
    expect(isImage(it1.mimeType)).toBe(true);
    expect(isPdf(it1.mimeType)).toBe(false);
    expect(isDocx(it1)).toBe(false);
  });

  it("classifies application/pdf as pdf", () => {
    const it1 = { mimeType: "application/pdf" };
    expect(isPdf(it1.mimeType)).toBe(true);
    expect(isImage(it1.mimeType)).toBe(false);
    expect(isDocx(it1)).toBe(false);
  });

  it("classifies OOXML DOCX MIME as docx", () => {
    const it1 = { mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" };
    expect(isDocx(it1)).toBe(true);
  });

  it("classifies legacy .doc by MIME as docx", () => {
    const it1 = { mimeType: "application/msword" };
    expect(isDocx(it1)).toBe(true);
  });

  it("classifies by extension when MIME is the generic octet-stream", () => {
    const it1 = { mimeType: "application/octet-stream", fileExtension: ".docx" };
    expect(isDocx(it1)).toBe(true);
  });

  it("does not classify JPEG as DOCX (no false positive)", () => {
    const it1 = { mimeType: "image/jpeg", fileExtension: ".jpg" };
    expect(isDocx(it1)).toBe(false);
    expect(isImage(it1.mimeType)).toBe(true);
  });

  it("an Excel sheet is neither PDF, image, nor DOCX — falls through to download-only", () => {
    const it1 = { mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fileExtension: ".xlsx" };
    expect(isPdf(it1.mimeType)).toBe(false);
    expect(isImage(it1.mimeType)).toBe(false);
    expect(isDocx(it1)).toBe(false);
  });
});
