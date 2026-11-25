package activities

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// What the Add does not make is handed on before any record is read, and a
// responsible party that is neither staff nor partner is refused in the
// view's words.
func TestTheWorkPlanAddHandsOnBeforeAnyRead(t *testing.T) {
	s := &Service{kampala: time.UTC, now: func() time.Time { return time.Date(2026, 11, 25, 9, 0, 0, 0, time.UTC) }}
	officer := auth.Principal{Account: auth.Account{StaffProfileID: "s-me", ActiveRole: "CCEO"}}
	base := url.Values{"catalogue_item_id": {"PARTNER_MEETINGS_ADMIN"}, "scheduled_date": {"2026-11-27"},
		"planned_school_count": {"3"}, "expected_participants": {"12"}}
	for name, c := range map[string]struct {
		p      auth.Principal
		change func(url.Values)
	}{
		"acting":               {auth.Principal{Account: auth.Account{StaffProfileID: "s-me", ActiveRole: "CCEO", InActingAppointment: true}}, func(url.Values) {}},
		"a partner":            {officer, func(f url.Values) { f.Set("responsibility_type", "partner") }},
		"another officer":      {officer, func(f url.Values) { f.Set("responsible_staff_id", "s-other") }},
		"a project":            {officer, func(f url.Values) { f.Set("project_id", "p1") }},
		"a signed count":       {officer, func(f url.Values) { f.Set("expected_participants", "-2") }},
		"no date":              {officer, func(f url.Values) { f.Del("scheduled_date") }},
		"a date in a sentence": {officer, func(f url.Values) { f.Set("scheduled_date", "27 Nov 2026") }},
	} {
		form := url.Values{}
		for k, v := range base {
			form[k] = append([]string{}, v...)
		}
		c.change(form)
		if _, err := s.prepareProgramme(context.Background(), c.p, form, Origin{}); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
	form := url.Values{"responsibility_type": {"volunteer"}}
	var refusal *Refusal
	if _, err := s.prepareProgramme(context.Background(), officer, form, Origin{}); !errors.As(err, &refusal) ||
		refusal.Message != "Could not add the activity: Select Staff or Partner as the responsible party." {
		t.Errorf("a volunteer: %v", err)
	}
}

// The lines are written as the snapshot's breakdown keeps them: a missing
// unit is 0, and the total is their sum.
func TestAloneLinesAreTheBreakdown(t *testing.T) {
	unit := int64(40000)
	lines, total := aloneLines(costing.Cost{Lines: []costing.Line{
		{Key: "partner_meetings", Label: "Partner Meetings [Rate basis: per meeting]", Unit: &unit, Qty: 1, Amount: 40000},
		{Key: "lunch_per_day", Label: "Lunch", Qty: 2, Amount: 0},
	}})
	if total != 40000 || len(lines) != 2 || lines[0].Unit != 40000 || lines[1].Unit != 0 || lines[0].LineItemType == "" {
		t.Fatalf("%v %d", lines, total)
	}
}
