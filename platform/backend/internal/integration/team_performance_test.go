//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// teamPerformanceGoldenEnv names a file of the existing feed's answers over
// the synthetic year in testdata/team_performance_rows.sql
// (docs/migration/37-team-performance.md, 37.3 says how it is made, on the
// day it is compared). Without it the comparison is skipped.
const teamPerformanceGoldenEnv = "EDIFY_TEAM_PERFORMANCE_GOLDEN"

// fileTeamPerformanceRows writes the synthetic year and removes it when the
// test ends. Every row's id starts "tpg".
func fileTeamPerformanceRows(t *testing.T) {
	t.Helper()
	ctx := context.Background()
	var already int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school WHERE id LIKE 'tpg%'`).Scan(&already); err != nil {
		t.Fatal(err)
	}
	if already != 0 {
		t.Skipf("the test database already holds %d of the synthetic schools", already)
	}
	run := func(file string) error {
		raw, err := os.ReadFile("testdata/" + file)
		if err != nil {
			return err
		}
		_, err = admin.Exec(ctx, string(raw))
		return err
	}
	t.Cleanup(func() {
		if err := run("team_performance_rows_cleanup.sql"); err != nil {
			t.Errorf("removing the synthetic year: %v", err)
		}
	})
	if err := run("team_performance_rows.sql"); err != nil {
		t.Fatalf("filing the synthetic year: %v", err)
	}
}

func tablesOf(page *screensv1.GetPageResponse) []*screensv1.PageTable {
	out := []*screensv1.PageTable{}
	for _, block := range page.GetBlocks() {
		if t := block.GetTable(); t != nil {
			out = append(out, t)
		}
	}
	return out
}

func rowNamed(table *screensv1.PageTable, name string) []string {
	for _, row := range table.GetRows() {
		cells := row.GetCells()
		if len(cells) > 0 && cells[0].GetText() == name {
			out := []string{}
			for _, c := range cells {
				out = append(out, c.GetText())
			}
			return out
		}
	}
	return nil
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTeamPerformanceOpensForEachReadersReach(t *testing.T) {
	for _, c := range []struct {
		email, title, home string
	}{
		{"admin@edify.org", "Team Performance", "National Total"},
		{"pl1@edify.org", "Team Performance", "Your team"},
		{"cceo@edify.org", "My Performance", "Your portfolio"},
	} {
		borrowAccount(t, c.email)
		token := sessionOf(t, c.email, seededPassword).GetAccessToken()
		page, err := pageOf(token, "/team-performance/", nil)
		if err != nil {
			t.Fatalf("%s: %v", c.email, err)
		}
		if page.GetHeader().GetTitle() != c.title || page.GetHeader().GetEyebrow() != "Performance & Coaching" {
			t.Fatalf("%s: the header %v", c.email, page.GetHeader())
		}
		tabs := page.GetBlocks()[1].GetLinkTabs().GetTabs()
		if len(tabs) != 6 || !tabs[0].GetActive() || tabs[0].GetLabel() != "Executive Summary" {
			t.Fatalf("%s: the tabs %v", c.email, tabs)
		}
		if strip := page.GetBlocks()[2].GetStrip(); strip.GetMetrics()[0].GetLabel() != "Total Portfolio" {
			t.Fatalf("%s: the strip %v", c.email, strip)
		}
		tables := tablesOf(page)
		if len(tables) == 0 || !strings.Contains(fmt.Sprint(tables[0].GetColumns()), c.home) {
			t.Fatalf("%s: the summary's total is not %q", c.email, c.home)
		}
	}
}

func TestTeamPerformanceIsNotFoundOutsideTheRolesThatReadIt(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/team-performance/", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator: %v, want not found", err)
	}
	borrowAccount(t, "admin@edify.org")
	token = sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/team-performance/country-targets", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("the Country Targets editor through the feed: %v, want not found", err)
	}
	if _, err := pageOf(token, "/team-performance/", map[string]string{"charts": "Nowhere"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("an unknown section's charts: %v, want not found", err)
	}
}

func TestTeamPerformanceCountsACCEOsCorePackage(t *testing.T) {
	fileTeamPerformanceRows(t)
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/team-performance/", map[string]string{"tab": "core"})
	if err != nil {
		t.Fatal(err)
	}
	tables := tablesOf(page)
	if len(tables) != 1 {
		t.Fatalf("the Core tab's tables: %d", len(tables))
	}
	// Moses K. holds three Core schools (one by his user id, one closed);
	// Beta has two package visits done and one training slot filled on
	// 28 September, read on the year's first day.
	got := rowNamed(tables[0], "Moses K.")
	want := []string{"Moses K.", "Northern", "Program Lead 2", "3", "0", "1", "0", "0", "12", "2", "16.7%", "0", "0%",
		"1", "0", "0", "0", "12", "1", "8.3%", "0", "0%"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("Moses K.'s Core package:\n got  %v\n want %v", got, want)
	}
}

// With the existing feed's answers on file, Go's are compared with them
// field by field, over the same synthetic year.
func TestTeamPerformanceMatchesTheExistingFeedOverASyntheticYear(t *testing.T) {
	path := os.Getenv(teamPerformanceGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", teamPerformanceGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden []struct {
		Email  string            `json:"email"`
		Query  map[string]string `json:"query"`
		Status int               `json:"status"`
		Body   json.RawMessage   `json:"body"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	fileTeamPerformanceRows(t)
	clientFor := goldenSignInClients()
	tokens := map[string]string{}
	compared, differing := 0, 0
	for _, answer := range golden {
		token, ok := tokens[answer.Email]
		if !ok {
			borrowAccount(t, answer.Email)
			result, err := signIn(t, clientFor(len(tokens)+1), answer.Email, seededPassword)
			if err != nil || result.GetSession() == nil {
				t.Fatalf("signing in %s: %v", answer.Email, err)
			}
			token = result.GetSession().GetAccessToken()
			tokens[answer.Email] = token
		}
		compared++
		got, err := pageOf(token, "/team-performance/", answer.Query)
		if answer.Status == 404 {
			if connect.CodeOf(err) != connect.CodeNotFound {
				differing++
				t.Errorf("%s %v: %v, want not found", answer.Email, answer.Query, err)
			}
			continue
		}
		if err != nil {
			differing++
			t.Errorf("%s %v: %v", answer.Email, answer.Query, err)
			continue
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(answer.Body, want); err != nil {
			t.Fatalf("%s %v: reading the existing answer: %v", answer.Email, answer.Query, err)
		}
		if !proto.Equal(got, want) {
			differing++
			g, w := protojson.Format(got), protojson.Format(want)
			at := 0
			for at < len(g) && at < len(w) && g[at] == w[at] {
				at++
			}
			t.Errorf("%s %v differs at byte %d:\n go:       …%s\n existing: …%s", answer.Email, answer.Query, at,
				g[max(at-200, 0):min(at+200, len(g))], w[max(at-200, 0):min(at+200, len(w))])
		}
	}
	t.Logf("%d answers of %d accounts compared, %d differing", compared, len(tokens), differing)
}
