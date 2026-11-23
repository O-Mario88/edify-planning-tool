package schoolprofile

import "testing"

func chartOf(t *testing.T, h clusterHistoryData, kind clusterChartKind) ([]string, []float64) {
	t.Helper()
	chart := h.chart(kind).GetChart()
	if chart == nil {
		t.Fatal("no chart")
	}
	return chart.GetCategories(), chart.GetSeries()[0].GetValues()
}

func TestClusterHistoryNeverDrawsAMissingYearAsZero(t *testing.T) {
	score := 4.5
	h := clusterHistoryData{schools: 4, years: []clusterYear{
		{fy: "2024"},
		{fy: "2025", inPlan: 4, done: 1, visited: 1},
		{fy: "2026", ssa: &score, assessed: 2, inPlan: 2},
	}}
	if years, _ := chartOf(t, h, chartSSATrend); len(years) != 1 {
		t.Fatalf("the SSA trend draws only the assessed year, got %v", years)
	}
	if years, values := chartOf(t, h, chartSSACoverage); len(years) != 1 || values[0] != 50 {
		t.Fatalf("SSA coverage is 2 of 4 in the assessed year only, got %v %v", years, values)
	}
	years, values := chartOf(t, h, chartVisitCoverage)
	if len(years) != 2 || values[0] != 25 || values[1] != 0 {
		t.Fatalf("visit coverage covers the years with planned work, got %v %v", years, values)
	}
	years, values = chartOf(t, h, chartActionClosure)
	if len(years) != 2 || values[0] != 25 || values[1] != 0 {
		t.Fatalf("action closure covers the years with planned work, got %v %v", years, values)
	}
}

func TestClusterSSARailSaysNotAssessedInsteadOfZero(t *testing.T) {
	pr := &scopeProfile{assessable: 3, cmp: comparison{rows: []ivRow{{key: "leadership", label: "Leadership"}}}}
	rail := clusterSSARail(pr, lens{fy: "2027", base: "/clusters/c1"}).GetRail()
	part := rail.GetParts()[0]
	if part.GetFigure() != clusterNotAssessed {
		t.Fatalf("figure = %q", part.GetFigure())
	}
	if part.GetTitle() != clusterNotCompared {
		t.Fatalf("change = %q", part.GetTitle())
	}
	if m := part.GetMeters()[0]; m.GetValue() != clusterNotAssessed || m.GetFraction() != 0 {
		t.Fatalf("meter = %q %v", m.GetValue(), m.GetFraction())
	}
}

func TestClusterSSARailAveragesTheAssessedOnly(t *testing.T) {
	now, was := 4.5, 4.0
	delta := 0.5
	pr := &scopeProfile{assessed: 2, assessable: 5, overall: change{delta: &delta},
		cmp: comparison{current: &now, previous: &was, rows: []ivRow{{key: "leadership", label: "Leadership", current: &now}}}}
	part := clusterSSARail(pr, lens{fy: "2027", base: "/clusters/c1"}).GetRail().GetParts()[0]
	if part.GetFigure() != "4.50" || part.GetFigureNote() != "2 of 5 schools assessed" {
		t.Fatalf("figure %q note %q", part.GetFigure(), part.GetFigureNote())
	}
	if part.GetTitle() != "+0.50 since FY 2025/26" {
		t.Fatalf("change = %q", part.GetTitle())
	}
}
