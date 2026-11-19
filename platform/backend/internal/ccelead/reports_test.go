package ccelead

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

func TestEachRoleReadsTheReportsItsRuleGivesIt(t *testing.T) {
	now := time.Now()
	for role, want := range map[string]string{
		adminRole: "TRUE", regionalLead: "r.author_id = $1", "CountryDirector": "FALSE", "ImpactAssessment": "FALSE",
	} {
		got, _, err := visible(context.Background(), nil, auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: role}}, now)
		if err != nil || got != want {
			t.Errorf("%s reads %q (%v), want %q", role, got, err, want)
		}
	}
}

func TestADayIsWrittenAsTheReportsWriteIt(t *testing.T) {
	at := time.Date(2026, 5, 12, 23, 30, 0, 0, time.UTC)
	if got := day(&at); got != "12 May 2026" {
		t.Errorf("day = %q", got)
	}
	if got := day(nil); got != "" {
		t.Errorf("no day = %q", got)
	}
}

func TestTheEmptyRegisterIsReadAsOneCell(t *testing.T) {
	reg := register{path: ReportsPath, title: "Regional CCE Reports", registerTitle: "Reports", emptyTitle: "No reports yet", emptyBody: "None."}
	page := render(reg, Role{Page: true}, url.Values{})
	table := page.GetBlocks()[len(page.GetBlocks())-1].GetTable()
	if table.GetEmptyMessage() != "No reports yet" || table.GetRows()[0].GetCells()[0].GetText() != "Regional CCE Reports No reports yet None." {
		t.Errorf("empty register: %v", table)
	}
}

func TestRolesWithoutTheRegisterAreRefused(t *testing.T) {
	s := NewService(nil, time.Now)
	for role, r := range rules.Pages[ReportsPath].Roles {
		if r.Page {
			continue
		}
		_, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{ActiveRole: role}}, ReportsPath, nil)
		if !served || !errors.Is(err, pagegate.ErrNotAvailable) {
			t.Errorf("%s: served %v, %v", role, served, err)
		}
	}
}

func TestARegionalLeadRowIsWordedAsTheQueueWordsIt(t *testing.T) {
	due := time.Date(2026, 11, 10, 0, 0, 0, 0, time.UTC)
	late := leadTodo("cce-report-due-2026-10", "Submit the October CCE report", "late", "critical", ReportsPath, "Open reports", "Monthly report", &due, true)
	if late.StatusLabel != "Overdue" || late.StatusTone != "danger" || late.DueLabel != "10 Nov" || late.DueTone != "danger" {
		t.Errorf("an overdue report: %+v", late)
	}
	draft := leadTodo("cce-feedback-draft-x", "Share training feedback", strings.Repeat("x", 200), "medium", EngagementsPath, "Open log", "Uganda", nil, false)
	if draft.StatusLabel != "Waiting on Me" || draft.StatusTone != "warning" || draft.DueLabel != "—" ||
		draft.DueTone != "neutral" || len(draft.Description) != todoDescriptionLength {
		t.Errorf("unshared feedback: %+v", draft)
	}
}
