//go:build integration

package integration

import (
	"context"
	"strconv"
	"strings"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func portfolioOf(t *testing.T, email string, query map[string]string) *screensv1.GetPageResponse {
	t.Helper()
	borrowAccount(t, email)
	page, err := pageOf(sessionOf(t, email, seededPassword).GetAccessToken(), "/team-planning-oversight/", query)
	if err != nil {
		t.Fatalf("%s opening the portfolio: %v", email, err)
	}
	return page
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's: Admin reads every operating school in the country
// portfolio, under its lead and officer, and pages the officer's table on
// the officer's own parameter.
func TestThePortfolioListsEveryOperatingSchoolForAdmin(t *testing.T) {
	var operating int
	if err := admin.QueryRow(context.Background(),
		`SELECT count(*) FROM school WHERE deleted_at IS NULL AND operational_status IN ('active', 'reopened')`).Scan(&operating); err != nil {
		t.Fatal(err)
	}
	page := portfolioOf(t, "admin@edify.org", map[string]string{"view": "portfolio"})
	if !strings.HasPrefix(page.GetHeader().GetDescription(), "Every school in the country portfolio") {
		t.Fatalf("description %q", page.GetHeader().GetDescription())
	}
	var strip *screensv1.PageStrip
	tables, listed := 0, 0
	var pageParam string
	for _, b := range page.GetBlocks() {
		if s := b.GetStrip(); s != nil {
			strip = s
		}
		if tb := b.GetTable(); tb != nil {
			tables++
			listed += len(tb.GetRows()) - 1
		}
		for _, item := range b.GetPanel().GetItems() {
			for _, l := range item.GetLinks().GetLinks() {
				if l.GetText() == "2" {
					pageParam = strings.SplitN(strings.SplitN(l.GetHref(), "&", 2)[1], "=", 2)[0]
				}
			}
		}
	}
	if strip == nil || strings.ReplaceAll(strip.GetMetrics()[0].GetValue(), ",", "") != strconv.Itoa(operating) {
		t.Fatalf("Schools In Portfolio %v, want %d", strip.GetMetrics()[0], operating)
	}
	if operating > 0 && (tables == 0 || listed == 0) {
		t.Fatalf("%d tables, %d schools listed", tables, listed)
	}
	if pageParam == "" {
		t.Skip("one page of schools only: the pager is not drawn")
	}
	second := portfolioOf(t, "admin@edify.org", map[string]string{"view": "portfolio", pageParam: "2"})
	for _, b := range second.GetBlocks() {
		if items := b.GetPanel().GetItems(); len(items) > 0 && strings.HasPrefix(items[0].GetText(), "Showing 51–") {
			return
		}
	}
	t.Fatal("the second page of the officer's table was not shown")
}

func TestThePortfolioIsTheTeamsForAProgrammeLeadAndRefusedToACCEO(t *testing.T) {
	page := portfolioOf(t, "pl2@edify.org", map[string]string{"view": "portfolio"})
	if !strings.HasPrefix(page.GetHeader().GetDescription(), "Every school your team holds") {
		t.Fatalf("description %q", page.GetHeader().GetDescription())
	}
	borrowAccount(t, "cceo@edify.org")
	if _, err := pageOf(sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken(), "/team-planning-oversight/",
		map[string]string{"view": "portfolio"}); err == nil {
		t.Fatal("a CCEO opened Planning Oversight's portfolio")
	}
}
