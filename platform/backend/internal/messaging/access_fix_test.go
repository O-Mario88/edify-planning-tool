package messaging

import (
	"testing"
)

// Owner, 2026-11-13: "Can you fix those from the go side" (agent 32's
// findings in the existing Messages page).

// A thread with no record is never listed, yet the existing page opened it
// for a participant by ?thread=. Go refuses it as the list does.
func TestAThreadWithNoRecordIsNotOpened(t *testing.T) {
	if openWithoutRecord() {
		t.Fatal("a thread with no record was opened")
	}
}

// "evidence" threads have no label in the existing page, so its gate refused
// them to everyone but the Admin. Go labels them as an evidence upload's.
func TestEvidenceThreadsHaveTheirLabel(t *testing.T) {
	if got := contextLabel("evidence"); got != "Evidence" {
		t.Fatalf("label %q", got)
	}
	if got := contextLabel("evidence_upload"); got != rules.ContextLabels["evidence_upload"] {
		t.Fatalf("the existing labels are kept: %q", got)
	}
	if _, decided := roleGate("ia", "evidence"); decided {
		t.Fatal("an evidence thread is refused before its record is read")
	}
}

// The existing pager drew the gap only before page 4: page 5 of 9 read
// "1 2 3 4 [5] 6 9" with no gap before 9. Go draws a gap for every run of
// hidden pages.
func TestThePagerDrawsAGapForEveryHiddenRun(t *testing.T) {
	labels := func(page, pages int) []string {
		out := []string{}
		for _, l := range pager(page, pages, pages*20, (page-1)*20, "all", "newest", "").GetLinks() {
			out = append(out, l.GetLabel())
		}
		return out
	}
	cases := map[[2]int]string{
		{5, 9}:  "1 2 3 4 5 6 … 9",
		{7, 12}: "1 2 3 … 6 7 8 … 12",
		{1, 9}:  "1 2 3 … 9",
		{9, 9}:  "1 2 3 … 8 9",
		{3, 5}:  "1 2 3 4 5",
	}
	for c, want := range cases {
		got := ""
		for i, l := range labels(c[0], c[1]) {
			if i > 0 {
				got += " "
			}
			got += l
		}
		if got != want {
			t.Fatalf("page %d of %d: %q, want %q", c[0], c[1], got, want)
		}
	}
}
