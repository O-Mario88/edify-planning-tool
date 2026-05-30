import { describe, it, expect } from "vitest";
import { t, resolveLocale, DEFAULT_LOCALE, SUPPORTED_LOCALES } from "@/lib/i18n";

describe("t — string lookup", () => {
  it("returns the English string by default", () => {
    expect(t("cpl.hero.tagline")).toBe(
      "Coach the field. Close the gaps. Multiply the wins.",
    );
  });

  it("returns the Swahili translation when locale=sw and a translation exists", () => {
    expect(t("cpl.hero.greeting", { name: "Daniel" }, "sw")).toBe(
      "Habari za jioni, Daniel.",
    );
  });

  it("falls back to English when the Swahili bundle is missing the key", () => {
    // The Swahili stub doesn't translate "leadership.title".
    expect(t("cpl.leadership.title", undefined, "sw")).toBe(
      "Where your attention earns the most",
    );
  });

  it("returns the key itself when neither locale has it (visible, never blank)", () => {
    expect(t("does.not.exist", undefined, "fr")).toBe("does.not.exist");
  });

  it("interpolates {param} placeholders", () => {
    expect(t("cpl.hero.greeting", { name: "Sarah" })).toBe(
      "Good evening, Sarah.",
    );
  });

  it("leaves placeholders intact when a param is missing (visible bug, not silent)", () => {
    expect(t("cpl.hero.greeting")).toContain("{name}");
  });
});

describe("resolveLocale", () => {
  it("returns the default when the cookie is empty or unknown", () => {
    expect(resolveLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(resolveLocale("")).toBe(DEFAULT_LOCALE);
    expect(resolveLocale("klingon")).toBe(DEFAULT_LOCALE);
  });

  it("accepts every supported locale", () => {
    for (const loc of SUPPORTED_LOCALES) {
      expect(resolveLocale(loc)).toBe(loc);
    }
  });
});
