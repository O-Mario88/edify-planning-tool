// KpiStrip is the canonical system-wide metric strip; MetricStrip is a thin
// adapter over it. This locks the pure value/tone/sub-value mapping so the ~30
// existing MetricStrip call sites render correctly through KpiStrip.

import { describe, expect, it } from "vitest";
import { metricToKpiFields } from "@/components/ui/MetricStrip";

describe("metricToKpiFields — MetricCell → KpiStripItem", () => {
  it("carries id/label and formats a numeric value", () => {
    const f = metricToKpiFields({ key: "total", label: "Total Schools", value: 1234 });
    expect(f.id).toBe("total");
    expect(f.label).toBe("Total Schools");
    expect(f.value).toBe(1234);
    expect(f.tone).toBe("default");
  });

  it("maps legacy tones (alert→danger, good→success)", () => {
    expect(metricToKpiFields({ key: "u", label: "Unclustered", value: 50, tone: "alert" }).tone).toBe("danger");
    expect(metricToKpiFields({ key: "s", label: "SSA", value: 50, tone: "good" }).tone).toBe("success");
    expect(metricToKpiFields({ key: "d", label: "X", value: 1, tone: "default" }).tone).toBe("default");
  });

  it("uses caption as the sub-value with a muted sub-tone", () => {
    const f = metricToKpiFields({ key: "c", label: "Client", value: 466, caption: "66.6%" });
    expect(f.subValue).toBe("66.6%");
    expect(f.subTone).toBe("muted");
  });

  it("renders a delta as an arrowed sub-value with its own tone (independent of value tone)", () => {
    const up = metricToKpiFields({ key: "a", label: "A", value: 10, delta: { dir: "up", text: "+3 vs Q1" } });
    expect(up.subValue).toBe("↑ +3 vs Q1");
    expect(up.subTone).toBe("success");
    const down = metricToKpiFields({ key: "b", label: "B", value: 2, delta: { dir: "down", text: "-1" } });
    expect(down.subValue).toBe("↓ -1");
    expect(down.subTone).toBe("danger");
  });

  it("appends a unit (space for words, none for %)", () => {
    expect(metricToKpiFields({ key: "p", label: "P", value: 62, unit: "%" }).value).toBe("62%");
    expect(metricToKpiFields({ key: "s", label: "S", value: 5, unit: "schools" }).value).toBe("5 schools");
  });

  it("forwards href + active for filter/link cells", () => {
    const f = metricToKpiFields({ key: "x", label: "X", value: 1, href: "/schools?district=Gulu", active: true });
    expect(f.href).toBe("/schools?district=Gulu");
    expect(f.active).toBe(true);
  });
});
