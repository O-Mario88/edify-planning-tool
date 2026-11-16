//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
)

// planningMonitorTables is what the monitor's golden files, in order, and
// the column each table's rows are found by.
var planningMonitorTables = [][2]string{
	{"school", "id"}, {"school_cluster_assignment", "school_id"}, {"staff_school_assignment", "id"}, {"project", "id"}, {"activity", "id"},
	{"cluster_activity_attendance", "activity_id"}, {"partner_assignment", "id"}, {"ssa_record", "id"},
	{"project_school_assignment", "id"},
}

// sameFigure is whether Go's figure is the existing service's: numbers by
// value (JSON reads them as floats), nothing as nothing.
func sameFigure(got, want any) bool {
	switch g := got.(type) {
	case *int:
		if g == nil {
			return want == nil
		}
		return sameFigure(*g, want)
	case int:
		w, ok := want.(float64)
		return ok && float64(g) == w
	}
	return fmt.Sprint(got) == fmt.Sprint(want)
}

func compareFigures(t *testing.T, where string, got map[string]any, want map[string]any) int {
	t.Helper()
	differing := 0
	names := make([]string, 0, len(want))
	for name := range want {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		g, ok := got[name]
		if !ok {
			differing++
			t.Errorf("%s: Go has no %s (existing %v)", where, name, want[name])
			continue
		}
		if !sameFigure(g, want[name]) {
			differing++
			t.Errorf("%s: %s is %v, existing %v", where, name, g, want[name])
		}
	}
	return differing
}

// sameJSON is whether got reads as want once written as JSON.
func sameJSON(t *testing.T, where string, got any, want any) int {
	t.Helper()
	raw, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	var back any
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatal(err)
	}
	g, _ := json.Marshal(back)
	w, _ := json.Marshal(want)
	if string(g) != string(w) {
		t.Errorf("%s differs:\n go:       %s\n existing: %s", where, g, w)
		return 1
	}
	return 0
}

// The existing service's Planning Monitor over schools an officer holds of
// every type, staff and Partner visits, a hand-over, trainings, an SSA and a
// project, figure by figure for every team, person and school. Skipped
// unless EDIFY_PLANNING_MONITOR_GOLDEN names a file
// internal/planningmonitor/testdata/golden.py wrote within the last half
// hour.
func TestThePlanningMonitorFiguresAreTheExistingServices(t *testing.T) {
	path := os.Getenv("EDIFY_PLANNING_MONITOR_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PLANNING_MONITOR_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	type person struct {
		Figures   map[string]any   `json:"figures"`
		Readiness any              `json:"readiness"`
		Schools   []map[string]any `json:"schools"`
		Outreach  []map[string]any `json:"outreach"`
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Monitor struct {
			Leads []struct {
				Key       string         `json:"key"`
				Figures   map[string]any `json:"figures"`
				Readiness any            `json:"readiness"`
				Officers  []person       `json:"officers"`
			} `json:"leads"`
			Total  any `json:"total"`
			Ledger any `json:"ledger"`
		} `json:"monitor"`
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(planningMonitorTables) - 1; i >= 0; i-- {
			table, column := planningMonitorTables[i][0], planningMonitorTables[i][1]
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE %s LIKE 'gpm%%'`, table, column)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, tc := range planningMonitorTables {
		for _, row := range golden.Rows[tc[0]] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, tc[0], tc[0])
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", tc[0], err)
			}
		}
	}
	m, err := planningmonitor.Read(ctx, gateway, snoozer(t, golden.Answers[0].Email), "2027", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Leads) != len(golden.Monitor.Leads) {
		t.Fatalf("%d teams, existing %d", len(m.Leads), len(golden.Monitor.Leads))
	}
	differing := 0
	for i, want := range golden.Monitor.Leads {
		lead := m.Leads[i]
		differing += compareFigures(t, "team "+want.Key, lead.Figures(), want.Figures)
		if len(lead.Officers) != len(want.Officers) {
			t.Fatalf("team %s: %d people, existing %d", want.Key, len(lead.Officers), len(want.Officers))
		}
		for j, wp := range want.Officers {
			o := lead.Officers[j]
			who := fmt.Sprint(wp.Figures["name"])
			differing += compareFigures(t, who, o.Figures(), wp.Figures)
			byID := map[string]*planningmonitor.School{}
			for _, sch := range o.Schools {
				byID[sch.ID] = sch
			}
			for _, ws := range wp.Schools {
				sch := byID[fmt.Sprint(ws["id"])]
				if sch == nil {
					differing++
					t.Errorf("%s: no school %v", who, ws["id"])
					continue
				}
				figures := sch.Figures()
				for k, v := range sch.SchoolChecks() {
					figures[k] = v
				}
				differing += compareFigures(t, who+" school "+fmt.Sprint(ws["id"]), figures, ws)
			}
			differing += sameJSON(t, who+" readiness", o.Readiness().AsDict(), wp.Readiness)
			if len(o.Schools) != len(wp.Schools) || len(o.Outreach) != len(wp.Outreach) {
				differing++
				t.Errorf("%s: %d schools and %d outreach, existing %d and %d", who, len(o.Schools), len(o.Outreach),
					len(wp.Schools), len(wp.Outreach))
			}
		}
	}
	for i, want := range golden.Monitor.Leads {
		differing += sameJSON(t, "team "+want.Key+" readiness", m.Leads[i].Readiness().AsDict(), want.Readiness)
	}
	differing += sameJSON(t, "the total's readiness", m.Readiness().AsDict(), golden.Monitor.Total)
	ledger, err := m.Ledger(ctx, gateway)
	if err != nil {
		t.Fatal(err)
	}
	differing += sameJSON(t, "the ledger", ledger, golden.Monitor.Ledger)
	t.Logf("the monitor compared, %d figures differing", differing)

	// The monitor as the lead's dashboard carries it: from its section to
	// the week's heading after it.
	want := &screensv1.GetPageResponse{}
	if err := protojson.Unmarshal(golden.Answers[0].Body, want); err != nil {
		t.Fatal(err)
	}
	from, to := -1, len(want.GetBlocks())
	for i, b := range want.GetBlocks() {
		if b.GetSection() == "Planning Monitor" && from < 0 {
			from = i
		}
		if from >= 0 && i > from && b.GetSection() == "" && strings.Contains(b.GetPanel().GetTitle(), " · ") {
			to = i
			break
		}
	}
	if from < 0 {
		t.Fatal("the existing dashboard carries no Planning Monitor")
	}
	got := &screensv1.GetPageResponse{Blocks: planningmonitor.Blocks(m, ledger)}
	existing := &screensv1.GetPageResponse{Blocks: want.GetBlocks()[from:to]}
	t.Logf("the monitor's %d blocks compared (Go drew %d)", len(existing.GetBlocks()), len(got.GetBlocks()))
	if !proto.Equal(got, existing) {
		g, w := protojson.Format(got), protojson.Format(existing)
		at := 0
		for at < len(g) && at < len(w) && g[at] == w[at] {
			at++
		}
		t.Errorf("the monitor's blocks differ at byte %d:\n go:       …%s\n existing: …%s", at,
			g[max(at-400, 0):min(at+300, len(g))], w[max(at-400, 0):min(at+300, len(w))])
	}
}
