package recentchanges

import (
	"testing"
	"time"
)

func TestTimesinceIsDjangos(t *testing.T) {
	now := time.Date(2026, 11, 24, 12, 0, 0, 0, time.UTC)
	cases := []struct {
		ago  time.Duration
		want string
	}{
		{30 * time.Second, "0 minutes"},
		{-time.Hour, "0 minutes"},
		{time.Minute, "1 minute"},
		{59 * time.Minute, "59 minutes"},
		{time.Hour + 5*time.Minute, "1 hour, 5 minutes"},
		{2 * time.Hour, "2 hours"},
		{35 * time.Hour, "1 day, 11 hours"},
		{48*time.Hour + 30*time.Minute, "2 days"},
		{7 * 24 * time.Hour, "1 week"},
		{8 * 24 * time.Hour, "1 week, 1 day"},
	}
	for _, c := range cases {
		if got := timesince(now.Add(-c.ago), now); got != c.want {
			t.Errorf("timesince(%v) = %q, want %q", c.ago, got, c.want)
		}
	}
}

func TestPartnerSummaryAndBlock(t *testing.T) {
	a := partnerRow{school: "Alpha", partner: "Literacy Uganda", item: "In-School Training", project: "CCSEL", status: "pending_scheduling"}
	if got := a.summary(); got != "Alpha assigned to Literacy Uganda — In-School Training (project: CCSEL)" {
		t.Errorf("summary = %q", got)
	}
	b := partnerRow{cluster: "Cluster A", expected: "school_visit", status: "assigned"}
	if got := b.summary(); got != "Cluster A cluster assigned to a partner — school visit" {
		t.Errorf("cluster summary = %q", got)
	}
	cases := []struct {
		row  partnerRow
		want string
	}{
		{partnerRow{partner: "P", status: "pending_scheduling"}, ""},
		{partnerRow{partner: "P", status: "returned_to_staff"}, "P no longer holds it — it was handed back or withdrawn."},
		{partnerRow{status: "partner_scheduled"}, "The partner has already scheduled it. Withdraw it from Partner Monitoring instead, so the activity and its cost are unwound."},
		{partnerRow{partner: "P", status: "assigned", scheduled: true}, "P has already scheduled it. Withdraw it from Partner Monitoring instead, so the activity and its cost are unwound."},
		{partnerRow{partner: "P", status: "assigned", withdrawal: true}, "A withdrawal is already open on it."},
		{partnerRow{partner: "P", status: "assigned", replaces: true}, "It replaced another partner's work. Withdraw it instead, so the school is not left without support."},
	}
	for _, c := range cases {
		if got := c.row.blocked(); got != c.want {
			t.Errorf("blocked(%+v) = %q, want %q", c.row, got, c.want)
		}
	}
}

func TestClusterSummaryNamesTheMove(t *testing.T) {
	if got := clusterSummary("Alpha", "Cluster B", ""); got != "Alpha added to Cluster B" {
		t.Errorf("added = %q", got)
	}
	if got := clusterSummary("Alpha", "Cluster B", "Cluster A"); got != "Alpha moved from Cluster A to Cluster B" {
		t.Errorf("moved = %q", got)
	}
	if got := clusterSummary("", "", ""); got != "A school added to a cluster" {
		t.Errorf("unnamed = %q", got)
	}
}

func TestDrawerDrawsEachChangeAsItsThreeLines(t *testing.T) {
	now := time.Date(2026, 11, 24, 12, 0, 0, 0, time.UTC)
	d := drawerFor([]Change{
		{Kind: "Project", MadeAt: now.Add(-2 * time.Minute), Summary: "Alpha added to CCSEL", Effect: "Takes the school out of CCSEL."},
		{Kind: "Partner", MadeAt: now.Add(-time.Hour), Summary: "Beta assigned to P", Blocked: "A withdrawal is already open on it."},
	}, now)
	if d.GetTitle() != "Recent changes" || d.GetSubtitle() != "Your partner, project and cluster changes from the last 7 days. Undo one made by mistake." || d.GetCanSubmit() {
		t.Fatalf("head = %+v", d)
	}
	items := d.GetItems()
	if len(items) != 6 || items[0].GetHeading() != "Alpha added to CCSEL" || items[1].GetText() != "Project · 2 minutes ago" || items[2].GetText() != "Takes the school out of CCSEL." {
		t.Fatalf("first change = %+v", items[:3])
	}
	if n := items[5].GetNote(); n.GetText() != "A withdrawal is already open on it." || n.GetTone() != "warning" {
		t.Errorf("blocked = %+v", n)
	}
	empty := drawerFor(nil, now)
	if n := empty.GetItems()[0].GetNote(); n.GetText() != "Nothing to undo. Schools you assign to a partner, add to a project or put in a cluster show here for a week." {
		t.Errorf("empty = %+v", n)
	}
}
