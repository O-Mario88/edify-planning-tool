import { describe, it, expect } from "vitest";
import { cookieSecure } from "@/lib/cookie-security";

const req = (url: string, headers: Record<string, string> = {}): Request =>
  new Request(url, { headers });

describe("cookieSecure", () => {
  it("trusts x-forwarded-proto=https (behind a TLS proxy, e.g. Railway)", () => {
    // Internal hop is http, but the edge terminated TLS — cookie must be Secure.
    expect(cookieSecure(req("http://internal:3000/login", { "x-forwarded-proto": "https" }))).toBe(true);
  });

  it("reads the first value of a multi-hop x-forwarded-proto", () => {
    expect(cookieSecure(req("http://internal/login", { "x-forwarded-proto": "https, http" }))).toBe(true);
  });

  it("is not Secure when the proxy reports http", () => {
    expect(cookieSecure(req("http://internal/login", { "x-forwarded-proto": "http" }))).toBe(false);
  });

  it("is Secure for a direct https request", () => {
    expect(cookieSecure(req("https://edifyplanning.app/login"))).toBe(true);
  });

  it("is NOT Secure over http://localhost so the browser keeps the cookie (docker-compose)", () => {
    // This is the bug fix: NODE_ENV=production + http://localhost used to mark
    // the CSRF + session cookies Secure, which the browser dropped → "Missing
    // CSRF token" and dead sessions.
    expect(cookieSecure(req("http://localhost:3000/login"))).toBe(false);
    expect(cookieSecure(req("http://127.0.0.1:3000/login"))).toBe(false);
    expect(cookieSecure(req("http://0.0.0.0:3000/login"))).toBe(false);
  });
});
