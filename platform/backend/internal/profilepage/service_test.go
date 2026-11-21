package profilepage

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestOtherPathsAreNotClaimed(t *testing.T) {
	got, served, err := NewService(nil).Build(context.Background(), auth.Principal{}, "/settings", url.Values{})
	if got != nil || served || err != nil {
		t.Fatalf("got %v, %v, %v", got, served, err)
	}
}

func TestBuildPageMatchesExpectedStructure(t *testing.T) {
	d1 := time.Date(2026, time.April, 20, 0, 0, 0, 0, time.UTC)
	d2 := time.Date(2026, time.September, 1, 0, 0, 0, 0, time.UTC)
	p := auth.Principal{
		Account: auth.Account{
			UserID:     "u1",
			Name:       "Moses K.",
			Email:      "cceo1@edify.org",
			Roles:      []string{"CCEO", "Program Lead"},
			ActiveRole: "CCEO",
		},
	}
	page := buildPage(p, "0700123456", 3, 2, []recentActivity{
		{id: "a1", status: "completed", plannedDate: &d1, schoolID: "s1", schoolName: "Goma Primary"},
		{id: "a2", status: "scheduled", plannedDate: &d2},
		{id: "a3", status: "planned", plannedDate: nil},
	})
	if page.GetHeader().GetTitle() != "Moses K." || page.GetHeader().GetEyebrow() != "Account" {
		t.Fatalf("unexpected header: %+v", page.GetHeader())
	}
	if len(page.GetBlocks()) != 4 {
		t.Fatalf("got %d blocks, want 4", len(page.GetBlocks()))
	}
	metrics := page.GetBlocks()[0].GetStrip().GetMetrics()
	if metrics[0].GetValue() != "3" || metrics[1].GetValue() != "2" || metrics[2].GetValue() != "67%" {
		t.Fatalf("unexpected metrics: %+v", metrics)
	}
	links := page.GetBlocks()[2].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if links[0].GetText() != "Goma Primary" || links[0].GetHref() != "/schools/s1" || links[0].GetCaption() != "April 20, 2026 · completed" {
		t.Fatalf("unexpected link[0]: %+v", links[0])
	}
	if links[1].GetText() != "→" || links[1].GetHref() != "/my-plan/a2" || links[1].GetCaption() != "Sept. 1, 2026 · scheduled" {
		t.Fatalf("unexpected link[1]: %+v", links[1])
	}
	if links[2].GetCaption() != "No date · planned" {
		t.Fatalf("unexpected link[2]: %+v", links[2])
	}
	if page.GetBlocks()[3].GetPanel().GetTitle() != "Switch Active Role" {
		t.Fatalf("expected Switch Active Role panel, got %+v", page.GetBlocks()[3])
	}
}
