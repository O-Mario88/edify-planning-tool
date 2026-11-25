package planningoversight

import (
	"strings"
	"testing"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// As the feed reads the risks: none sendable, the whole drawer and no
// button; one form, the form alone with the risk's action as its help;
// several, the whole drawer with each button's words and the first offered.
func TestWithRisksReadsAsTheFeedReadsTheSendForms(t *testing.T) {
	base := func() *screensv1.PageDrawer {
		return &screensv1.PageDrawer{Title: "School visit", Subtitle: "A school", Items: []*screensv1.DrawerItem{drawerHeading("Ownership")}}
	}
	overdue := risk{action: "Complete the activity or reschedule it", reason: "Planned for 1 Nov.", owner: "Paul N."}
	queue := risk{action: "Verify the submission", reason: "Waiting.", owner: "Impact Assessment", role: "ImpactAssessment"}

	if d := withRisks(base(), []risk{overdue}, false, true); d.GetCanSubmit() || d.GetItems()[0].GetHeading() != "Needs attention" ||
		d.GetItems()[1].GetText() != "Complete the activity or reschedule it Planned for 1 Nov. Owner: Paul N." {
		t.Fatalf("nothing sendable: %v", d)
	}
	one := withRisks(base(), []risk{overdue, queue}, true, false)
	if f := one.GetItems()[0].GetField(); len(one.GetItems()) != 1 || f.GetHelp() != "Verify the submission" || one.GetSubmitLabel() != "Send to Impact Assessment" {
		t.Fatalf("one form (the queue's, with no school): %v", one)
	}
	several := withRisks(base(), []risk{overdue, queue}, true, true)
	if !several.GetCanSubmit() || several.GetSubmitLabel() != "Send to Paul N." || !strings.HasSuffix(several.GetItems()[2].GetText(), " Send to Impact Assessment") {
		t.Fatalf("several forms: %v", several)
	}
}

// _partner_not_scheduled: due a week after the hand-over, late the day
// after; a warning for a week, high beyond; "1 day" and "N days".
func TestPartnerNotScheduledReadsAsTheDetector(t *testing.T) {
	today := *day("2026-11-25")
	if _, late := partnerNotScheduled("Room to Read", "Paul N.", day("2026-11-18"), today); late {
		t.Fatal("due today: not yet late")
	}
	r, late := partnerNotScheduled("Room to Read", "Paul N.", day("2026-11-17"), today)
	if !late || r.severity != "warning" || r.reason != "Room to Read has not scheduled this handover; it was due to be scheduled 1 day ago." ||
		r.due.Format("2006-01-02") != "2026-11-24" || r.owner != "Paul N." {
		t.Fatalf("a day late: %+v", r)
	}
	if r, _ := partnerNotScheduled("", "", day("2026-11-01"), today); r.severity != "high" || !strings.HasPrefix(r.reason, "The partner has not scheduled") {
		t.Fatalf("seventeen days late: %+v", r)
	}
}
