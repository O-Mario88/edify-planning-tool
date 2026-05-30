import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { log, telemetry, setTelemetry, type Telemetry } from "@/lib/log";

// The logger doesn't have much logic — but the *fields* it emits are
// what production dashboards filter on. These tests pin the field
// shape so a careless rename doesn't break log indexing silently.

describe("log", () => {
  const spies = {
    log:   vi.spyOn(console, "log").mockImplementation(() => {}),
    warn:  vi.spyOn(console, "warn").mockImplementation(() => {}),
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
  };
  beforeEach(() => {
    for (const k of Object.keys(spies) as (keyof typeof spies)[]) spies[k].mockClear();
  });
  afterEach(() => {
    for (const k of Object.keys(spies) as (keyof typeof spies)[]) spies[k].mockClear();
  });

  it("info writes through console.log", () => {
    log.info("hello", { x: 1 });
    expect(spies.log).toHaveBeenCalledOnce();
    expect(spies.log.mock.calls[0]?.[0]).toContain("hello");
  });

  it("warn routes through console.warn", () => {
    log.warn("careful", { kind: "test" });
    expect(spies.warn).toHaveBeenCalledOnce();
  });

  it("error routes through console.error", () => {
    log.error("nope", { id: "abc" });
    expect(spies.error).toHaveBeenCalledOnce();
  });

  it("handler logs ok with route + durationMs on success", async () => {
    const wrapped = log.handler("test.route", async () => "value");
    const result = await wrapped(new Request("http://example.com/x"));
    expect(result).toBe("value");
    const line = String(spies.log.mock.calls.at(-1)?.[0] ?? "");
    expect(line).toContain("request.ok");
    expect(line).toContain("test.route");
    expect(line).toContain("durationMs");
  });

  it("handler logs error + re-throws on failure", async () => {
    const wrapped = log.handler("test.fail", async () => {
      throw new Error("boom");
    });
    await expect(wrapped(new Request("http://example.com/x"))).rejects.toThrow("boom");
    const line = String(spies.error.mock.calls.at(-1)?.[0] ?? "");
    expect(line).toContain("request.failed");
    expect(line).toContain("test.fail");
  });
});

describe("telemetry abstraction", () => {
  it("defaults to a no-op that doesn't throw", () => {
    expect(() => telemetry.track({ name: "test" })).not.toThrow();
    expect(() => telemetry.captureException(new Error("x"))).not.toThrow();
  });

  it("setTelemetry swaps the sink without changing the import surface", () => {
    const tracked: { name: string; props?: Record<string, unknown> }[] = [];
    const captured: { err: unknown; extra?: Record<string, unknown> }[] = [];
    const fake: Telemetry = {
      track: (e) => tracked.push({ name: e.name, props: e.props }),
      captureException: (err, extra) => captured.push({ err, extra }),
    };
    setTelemetry(fake);
    telemetry.track({ name: "ev.x", props: { k: 1 } });
    telemetry.captureException(new Error("fail"), { route: "/x" });
    expect(tracked).toEqual([{ name: "ev.x", props: { k: 1 } }]);
    expect(captured).toHaveLength(1);
    expect((captured[0].err as Error).message).toBe("fail");
  });
});
