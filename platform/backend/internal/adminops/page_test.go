package adminops

import (
	"strings"
	"testing"
	"time"
)

func tk(id, status, title string) ticket {
	return ticket{ID: id, Reference: "TCK-" + id, Title: title, Category: "other", Status: status, ReporterRole: "CCEO",
		Route: "/planning", CreatedAt: time.Date(2026, 11, 10, 21, 30, 0, 0, time.UTC)}
}

func TestTheQueueIsReadAsItsOneResolveFormOnlyWhenItHoldsOneAndLittleAroundIt(t *testing.T) {
	one := supportForm([]ticket{tk("a", "submitted", "First"), tk("b", "verification", "Second")})
	form := one.GetForm()
	if form == nil || form.GetKey() != "/admin-ops/tickets/b/resolve" || form.GetText() != "First" || form.GetSubmitLabel() != "Resolve" {
		t.Fatalf("one resolvable ticket: %v", one)
	}
	if f := form.GetItems()[0].GetField(); f.GetLabel() != "Resolution for TCK-b" || f.GetPlaceholder() != "What was fixed?" {
		t.Fatalf("the form's field: %v", f)
	}
	if supportForm([]ticket{tk("a", "fix_ready", "A"), tk("b", "verification", "B")}) != nil {
		t.Error("two forms are read as a form")
	}
	if supportForm([]ticket{tk("a", "submitted", "A")}) != nil {
		t.Error("no form is read as a form")
	}
	if supportForm([]ticket{tk("a", "verification", strings.Repeat("L", 380))}) != nil {
		t.Error("a card past the intro limit is read as its form")
	}
}

func TestTheIntroLimitCountsCharactersNotBytes(t *testing.T) {
	// "é" is two bytes: 190 of them is 380 bytes but 190 characters, and
	// with the reference, labels and line the card stays under 400.
	if supportForm([]ticket{tk("a", "verification", strings.Repeat("é", 190))}) == nil {
		t.Error("a short card of two-byte letters is not read as its form")
	}
}

func TestAMissingRoleAndPageAreWrittenAsTheQueueWritesThem(t *testing.T) {
	got := ticketLine(ticket{CreatedAt: time.Date(2026, 11, 10, 21, 30, 0, 0, time.UTC)})
	if got != "user · unknown page · 11 Nov 00:30" {
		t.Fatalf("line %q", got)
	}
}

func TestAnIncidentsSeverityPillCarriesItsTone(t *testing.T) {
	for severity, want := range map[string]string{"critical": "alert", "high": "caution", "medium": "plain", "low": "plain", "weird": "plain"} {
		if got := severityTone(severity); got != want {
			t.Errorf("%s: %q, want %q", severity, got, want)
		}
	}
}

func TestTheRepairCatalogueReadsAsTheFeedReadsIt(t *testing.T) {
	items := repairPage().GetBlocks()[0].GetList().GetItems()
	if len(items) != 3 {
		t.Fatalf("%d repairs", len(items))
	}
	first, last := items[0], items[2]
	if first.GetTitle() != "Notifications for incidents that are already resolved" || first.GetBadges()[0].GetTone() != "plain" ||
		first.GetActions()[0].GetHref() != "/data-repair?repair=stale_incident_notifications" || len(first.GetLines()) != 2 {
		t.Fatalf("first %v", first)
	}
	if last.GetBadges()[0].GetText() != "Referred" || last.GetBadges()[0].GetTone() != "caution" || len(last.GetLines()) != 3 {
		t.Fatalf("referred %v", last)
	}
}
