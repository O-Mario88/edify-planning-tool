//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dashboard"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
)

// plDashboardTables is what the lead's golden files, in the order it files them.
var plDashboardTables = []string{"activity", "leave", "notification", "leadership_escalation", "cd_flag", "target_catchup_plan"}

// weekSlice is the existing page's This Week and backlog: from the week's
// heading to the Staff Activity Log after it.
func weekSlice(blocks []*screensv1.PageBlock) []*screensv1.PageBlock {
	from, to := -1, len(blocks)
	for i, b := range blocks {
		title := b.GetPanel().GetTitle()
		if from < 0 && b.GetPanel() != nil && strings.Contains(title, " · ") &&
			(strings.HasPrefix(title, "This week") || strings.HasPrefix(title, "Week of") || strings.HasPrefix(title, "Coming week")) {
			from = i
		}
		if from >= 0 && title == "Staff Activity" {
			to = i
			break
		}
	}
	if from < 0 {
		return nil
	}
	return blocks[from:to]
}

// staffActivitySlice is the existing page's Staff Activity Log: from its
// head to the end.
func staffActivitySlice(blocks []*screensv1.PageBlock) []*screensv1.PageBlock {
	for i, b := range blocks {
		if b.GetPanel().GetTitle() == "Staff Activity" {
			return blocks[i:]
		}
	}
	return nil
}

// samePage is 0 when got is want, else 1 with the first place they part.
func samePage(t *testing.T, where string, got, want *screensv1.GetPageResponse) int {
	t.Helper()
	if proto.Equal(got, want) {
		return 0
	}
	g, w := protojson.Format(got), protojson.Format(want)
	at := 0
	for at < len(g) && at < len(w) && g[at] == w[at] {
		at++
	}
	t.Errorf("%s differs at byte %d:\n go:       …%s\n existing: …%s", where, at,
		g[max(at-300, 0):min(at+300, len(g))], w[max(at-300, 0):min(at+300, len(w))])
	return 1
}

// The existing feed's Programme Lead This Week and backlog over team work
// the seed lacks — past-due work of every state, a reminder already sent,
// the lead's own, this week's work asking each thing of the lead, an
// officer's leave — compared with Go's for each query Go draws. Skipped
// unless EDIFY_PL_DASHBOARD_GOLDEN names a file
// internal/dashboard/testdata/pl_golden.py wrote within the last half hour.
func TestTheLeadsWeekMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_PL_DASHBOARD_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_PL_DASHBOARD_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(plDashboardTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gpld%%'`, plDashboardTables[i])); err != nil {
				t.Errorf("clearing %s: %v", plDashboardTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range plDashboardTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	compared, differing := 0, 0
	for _, answer := range golden.Answers {
		query := url.Values{}
		for k, v := range answer.Query {
			query.Set(k, v)
		}
		blocks, served, err := dashboard.LeadWeekBlocks(ctx, gateway, snoozer(t, answer.Email), query, "2027", time.Now())
		if err != nil {
			t.Fatalf("%v: %v", answer.Query, err)
		}
		if !served {
			t.Logf("%v: handed on", answer.Query)
			continue
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(answer.Body, want); err != nil {
			t.Fatal(err)
		}
		compared++
		strip, header, err := dashboard.LeadPulse(ctx, gateway, snoozer(t, answer.Email), "2027", time.Now())
		if err != nil {
			t.Fatalf("%v: the team pulse: %v", answer.Query, err)
		}
		if existing := want.GetBlocks()[1]; !proto.Equal(strip, existing) {
			differing++
			t.Errorf("%v: the team pulse differs:\n go:       %s\n existing: %s", answer.Query,
				protojson.Format(strip), protojson.Format(existing))
		}
		if !proto.Equal(header, want.GetHeader()) {
			differing++
			t.Errorf("%v: the header differs:\n go:       %s\n existing: %s", answer.Query,
				protojson.Format(header), protojson.Format(want.GetHeader()))
		}
		embed, servedEmbed, err := staffactivity.NewService(gateway, time.Now).TeamEmbed(ctx, snoozer(t, answer.Email), url.Values{})
		if err != nil || !servedEmbed {
			t.Fatalf("%v: the Staff Activity Log: %v (drawn %v)", answer.Query, err, servedEmbed)
		}
		differing += samePage(t, fmt.Sprintf("%v: the Staff Activity Log", answer.Query),
			&screensv1.GetPageResponse{Blocks: embed}, &screensv1.GetPageResponse{Blocks: staffActivitySlice(want.GetBlocks())})
		differing += samePage(t, fmt.Sprintf("%v: the week", answer.Query),
			&screensv1.GetPageResponse{Blocks: blocks}, &screensv1.GetPageResponse{Blocks: weekSlice(want.GetBlocks())})
		page, servedPage, err := dashboard.NewService(gateway, time.Now).Build(ctx, snoozer(t, answer.Email), dashboard.Path, query)
		if err != nil || !servedPage {
			t.Fatalf("%v: the whole page: %v (drawn %v)", answer.Query, err, servedPage)
		}
		differing += samePage(t, fmt.Sprintf("%v: the whole page", answer.Query), page, want)
	}
	t.Logf("%d answers compared, %d differing", compared, differing)
	if compared == 0 {
		t.Fatal("Go drew none of the lead's weeks")
	}
}
