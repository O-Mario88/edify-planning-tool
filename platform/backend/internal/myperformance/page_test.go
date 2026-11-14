package myperformance

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestTheStageIsNamedAsThePageNamesIt(t *testing.T) {
	for stage, want := range map[string]string{
		"signed_off": "Signed off", "priorities_draft": "Priorities draft", "MANAGER_assessment": "Manager assessment", "": "",
	} {
		if got := stageLabel(stage); got != want {
			t.Errorf("%q: %q, want %q", stage, got, want)
		}
	}
	if scope("Program Lead") != "You and your team" || scope("Admin") != "Country delivery" || scope("CCEO") != "Your delivery and monitored partners" {
		t.Error("scope")
	}
}

func TestAReaderWithNoPeopleRecordOrARefusedYearIsPassedOn(t *testing.T) {
	s := NewService(nil, time.Now)
	officer := func(staff string) auth.Principal {
		p := auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO"}}
		p.StaffProfileID = staff
		return p
	}
	for _, c := range []struct {
		p     auth.Principal
		query string
	}{
		{officer(""), ""},
		{officer("s"), "fy=1999"},
		{officer("s"), "fy=20x7"},
	} {
		q, _ := url.ParseQuery(c.query)
		resp, served, err := s.Build(context.Background(), c.p, Path, q)
		if resp != nil || served || err != nil {
			t.Errorf("%+v %s: got (%v, %v, %v), want it passed on", c.p, c.query, resp, served, err)
		}
	}
}
